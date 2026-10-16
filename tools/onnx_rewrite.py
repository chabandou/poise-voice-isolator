"""
Graph surgery shared by tools/optimize_gtcrn.py and tools/optimize_df3.py.

A Graph holds a model's nodes and constants, editable, with every tensor's
(static) shape; the rewrites here are model-agnostic and exact up to float
rounding. Needs the onnx package (a dev tool; Poise itself only needs
onnxruntime).
"""
import hashlib
import os
import sys
import tempfile
from pathlib import Path

import numpy as np
import onnx
import onnxruntime as ort
from onnx import helper, numpy_helper


def session(model, level=ort.GraphOptimizationLevel.ORT_ENABLE_ALL, save_to=None):
    so = ort.SessionOptions()
    so.graph_optimization_level = level
    so.intra_op_num_threads = 1
    so.log_severity_level = 3
    if save_to:
        so.optimized_model_filepath = save_to
    if isinstance(model, onnx.ModelProto):
        model = model.SerializeToString()
    return ort.InferenceSession(model, so, providers=["CPUExecutionProvider"])


def attr(node, name, default=None):
    for a in node.attribute:
        if a.name == name:
            return helper.get_attribute_value(a)
    return default


def i64(*values):
    return np.array(values, np.int64)


class Graph:
    """A model's nodes and constants, editable, with every tensor's shape
    (all static here: taken from one ORT run with every tensor exposed)."""

    def __init__(self, model):
        self.model = model
        self.inputs = [i.name for i in model.graph.input]
        self.outputs = [o.name for o in model.graph.output]
        self.consts = {t.name: numpy_helper.to_array(t) for t in model.graph.initializer}
        self.nodes = list(model.graph.node)
        self._uid = 0
        self._taken = set(self.consts) | set(self.inputs) | {n.name for n in self.nodes} | \
            {o for n in self.nodes for o in n.output}
        probe = onnx.ModelProto()
        probe.CopyFrom(model)
        seen = set(self.outputs)
        for n in probe.graph.node:
            for o in n.output:
                if o and o not in seen:
                    probe.graph.output.append(helper.make_empty_tensor_value_info(o))
                    seen.add(o)
        s = session(probe, ort.GraphOptimizationLevel.ORT_DISABLE_ALL)
        feeds = {i.name: np.zeros(i.shape, np.float32) for i in s.get_inputs()}
        self.shape = {o.name: v.shape for o, v in zip(s.get_outputs(), s.run(None, feeds))}
        self.shape.update({k: v.shape for k, v in {**self.consts, **feeds}.items()})

    # -- building blocks --------------------------------------------------------
    def name(self, base):
        while True:
            self._uid += 1
            n = f"opt_{base}_{self._uid}"
            if n not in self._taken:
                self._taken.add(n)
                return n

    def const(self, value, base="c"):
        n = self.name(base)
        self.consts[n] = np.asarray(value)
        self.shape[n] = self.consts[n].shape
        return n

    def add(self, op, inputs, shape, **attrs):
        out = self.name(op.lower())
        self.nodes.append(helper.make_node(op, inputs, [out], name=out, **attrs))
        self.shape[out] = tuple(shape)
        return out

    def slice(self, x, axis, start, end):
        shape = list(self.shape[x])
        shape[axis] = end - start
        return self.add("Slice", [x, self.const(i64(start)), self.const(i64(end)),
                                  self.const(i64(axis))], shape)

    def concat(self, xs, axis):
        if len(xs) == 1:
            return xs[0]
        shape = list(self.shape[xs[0]])
        shape[axis] = sum(self.shape[x][axis] for x in xs)
        return self.add("Concat", xs, shape, axis=axis)

    def reshape(self, x, shape):
        return self.add("Reshape", [x, self.const(i64(*shape))], shape)

    # -- graph queries / edits --------------------------------------------------
    def producers(self):
        return {o: n for n in self.nodes for o in n.output}

    def consumers(self):
        c = {}
        for n in self.nodes:
            for i in n.input:
                c.setdefault(i, []).append(n)
        return c

    def replace(self, old, new):
        """Point every reader of tensor `old` at `new` (graph outputs keep their name)."""
        for n in self.nodes:
            for k, i in enumerate(n.input):
                if i == old:
                    n.input[k] = new
        if old in self.outputs:
            for n in self.nodes:                # an old producer still in place goes dead
                for k, o in enumerate(n.output):
                    if o == old:
                        n.output[k] = self.name("dead")
            self.nodes.append(helper.make_node("Identity", [new], [old], name=self.name("id")))

    def prune(self):
        """Drop nodes and constants nothing reaches the outputs through."""
        prod = self.producers()
        live, todo = set(), list(self.outputs)
        while todo:
            t = todo.pop()
            if t in live:
                continue
            live.add(t)
            if t in prod:
                todo.extend(i for i in prod[t].input if i)
        self.nodes = [n for n in self.nodes if any(o in live for o in n.output)]
        self.consts = {k: v for k, v in self.consts.items() if k in live}

    def sorted_nodes(self):
        ready = set(self.inputs) | set(self.consts) | {""}
        order, pending = [], list(self.nodes)
        while pending:
            rest = [n for n in pending if not all(i in ready for i in n.input)]
            for n in pending:
                if n not in rest:
                    order.append(n)
                    ready.update(n.output)
            if len(rest) == len(pending):
                raise RuntimeError(f"unresolvable inputs at {rest[0].name}")
            pending = rest
        return order

    def to_model(self):
        self.prune()
        g = self.model.graph
        del g.node[:]
        g.node.extend(self.sorted_nodes())
        del g.initializer[:]
        g.initializer.extend(numpy_helper.from_array(v, k) for k, v in self.consts.items())
        del g.value_info[:]
        onnx.checker.check_model(self.model)
        return self.model


def slice_params(G, n):
    """(axis, start, end) of a one-axis, step-1 Slice with constant bounds, else None."""
    ins = list(n.input) + [""] * (5 - len(n.input))
    starts, ends, axes, steps = (G.consts.get(i) if i else None for i in ins[1:5])
    if starts is None or ends is None or starts.size != 1:
        return None
    if (ins[3] and axes is None) or (ins[4] and (steps is None or int(steps[0]) != 1)):
        return None
    rank = len(G.shape[ins[0]])
    axis = (int(axes[0]) if axes is not None else 0) % rank
    dim = G.shape[ins[0]][axis]
    s, e = (int(v) + dim if int(v) < 0 else int(v) for v in (starts[0], ends[0]))
    return axis, min(max(s, 0), dim), min(max(e, 0), dim)


def concat_axis(G, n):
    return attr(n, "axis") % len(G.shape[n.output[0]])



# ------------------------------------------------------------------ rewrites
def scatter_to_concat(G):
    """ScatterND writing a dense box of `data` (the cache updates) -> slices
    of `data` around `updates`, concatenated."""
    def box(indices, shape):
        k = indices.shape[-1]
        flat = np.where(indices < 0, indices + np.array(shape[:k]), indices).reshape(-1, k)
        ranges = [(int(flat[:, j].min()), int(flat[:, j].max()) + 1) for j in range(k)]
        grid = np.stack(np.meshgrid(*[np.arange(a, b) for a, b in ranges], indexing="ij"), -1)
        if grid.shape[:-1] != indices.shape[:-1] or not np.array_equal(grid.reshape(-1, k), flat):
            return None
        return ranges

    def rebuild(data, upd, ranges, axis=0):
        if axis == len(ranges):
            return upd
        a, b = ranges[axis]
        dim = G.shape[data][axis]
        if (a, b) == (0, dim):
            return rebuild(data, upd, ranges, axis + 1)
        pieces = [G.slice(data, axis, 0, a)] if a > 0 else []
        pieces.append(rebuild(G.slice(data, axis, a, b), upd, ranges, axis + 1))
        if b < dim:
            pieces.append(G.slice(data, axis, b, dim))
        return G.concat(pieces, axis)

    count = 0
    for n in [n for n in G.nodes if n.op_type == "ScatterND"]:
        data, idx, upd = n.input
        indices = G.consts.get(idx)
        ranges = box(indices, G.shape[data]) if indices is not None else None
        if ranges is None:
            continue
        G.nodes.remove(n)
        G.replace(n.output[0], rebuild(data, upd, ranges))
        count += 1
    return count



def simplify(G):
    """Resolve slices of slices/concats and gathers from them, flatten
    nested concats, drop no-op slices and concats. Repeats to a fixpoint."""
    def step():
        prod = G.producers()
        for n in G.nodes:
            if n.op_type == "Slice" and (p := slice_params(G, n)):
                axis, s, e = p
                x = n.input[0]
                src = prod.get(x)
                if (s, e) == (0, G.shape[x][axis]):
                    new = x
                elif src is not None and src.op_type == "Slice" and \
                        (q := slice_params(G, src)) and q[0] == axis:
                    new = G.slice(src.input[0], axis, q[1] + s, q[1] + e)
                elif src is not None and src.op_type == "Concat" and concat_axis(G, src) == axis:
                    pieces, off = [], 0
                    for inp in src.input:
                        size = G.shape[inp][axis]
                        lo, hi = max(s, off) - off, min(e, off + size) - off
                        if lo < hi:
                            pieces.append(inp if (lo, hi) == (0, size) else G.slice(inp, axis, lo, hi))
                        off += size
                    new = G.concat(pieces, axis)
                else:
                    continue
                G.nodes.remove(n)
                G.replace(n.output[0], new)
                return True
            if n.op_type == "Gather":
                idx = G.consts.get(n.input[1])
                if idx is None or idx.ndim != 0:
                    continue
                x = n.input[0]
                axis = attr(n, "axis", 0) % len(G.shape[x])
                i = int(idx) % G.shape[x][axis]
                src = prod.get(x)
                if src is not None and src.op_type == "Concat" and concat_axis(G, src) == axis:
                    for inp in src.input:
                        if i < G.shape[inp][axis]:
                            break
                        i -= G.shape[inp][axis]
                elif src is not None and src.op_type == "Slice" and \
                        (q := slice_params(G, src)) and q[0] == axis:
                    inp, i = src.input[0], q[1] + i
                else:
                    continue
                n.input[0], n.input[1] = inp, G.const(np.array(i, np.int64))
                return True
            if n.op_type == "Concat":
                axis = concat_axis(G, n)
                flat = []
                for inp in n.input:
                    src = prod.get(inp)
                    if src is not None and src.op_type == "Concat" and concat_axis(G, src) == axis:
                        flat.extend(src.input)
                    else:
                        flat.append(inp)
                merged = []
                for inp in flat:          # neighbouring slices of one tensor -> one slice
                    a, b = (prod.get(merged[-1]) if merged else None), prod.get(inp)
                    if a is not None and b is not None and a.op_type == b.op_type == "Slice" \
                            and a.input[0] == b.input[0]:
                        pa, pb = slice_params(G, a), slice_params(G, b)
                        if pa and pb and pa[0] == pb[0] == axis and pa[2] == pb[1]:
                            merged[-1] = G.slice(a.input[0], axis, pa[1], pb[2])
                            prod = G.producers()
                            continue
                    merged.append(inp)
                if merged == list(n.input) and len(merged) > 1:
                    continue
                G.nodes.remove(n)
                if len(merged) == 1:
                    G.replace(n.output[0], merged[0])
                else:
                    G.nodes.append(helper.make_node("Concat", merged, list(n.output), name=n.name, axis=axis))
                return True
        return False

    count = 0
    while step():
        count += 1
        G.prune()
    return count



def convtranspose_to_conv(G):
    """Stride-1 ConvTranspose == Conv with the kernel flipped and its
    in/out channels swapped (per group)."""
    count = 0
    for n in [n for n in G.nodes if n.op_type == "ConvTranspose"]:
        if any(s != 1 for s in attr(n, "strides", [1, 1])) or attr(n, "output_padding") or \
                attr(n, "output_shape") or attr(n, "auto_pad", b"NOTSET") != b"NOTSET":
            continue
        g, dil, pads = attr(n, "group", 1), attr(n, "dilations", [1, 1]), attr(n, "pads", [0, 0, 0, 0])
        W = G.consts[n.input[1]]
        cin, cog, kh, kw = W.shape
        new_pads = [(k - 1) * d - p for k, d, p in zip((kh, kw, kh, kw), dil * 2, pads)]
        if min(new_pads) < 0:
            continue
        cig = cin // g
        V = np.concatenate([W[i * cig:(i + 1) * cig].transpose(1, 0, 2, 3)[:, :, ::-1, ::-1]
                            for i in range(g)])
        G.nodes.remove(n)
        G.nodes.append(helper.make_node(
            "Conv", [n.input[0], G.const(np.ascontiguousarray(V))] + list(n.input[2:3]), list(n.output),
            name=n.name, group=g, kernel_shape=[kh, kw], dilations=list(dil), pads=new_pads, strides=[1, 1]))
        count += 1
    return count



def fold_batchnorm(G):
    count = 0
    prod, cons = G.producers(), G.consumers()
    for bn in [n for n in G.nodes if n.op_type == "BatchNormalization"]:
        c = prod.get(bn.input[0])
        if c is None or c.op_type not in ("Conv", "ConvTranspose") or len(cons[c.output[0]]) != 1:
            continue
        gamma, beta, mean, var = (G.consts[i] for i in bn.input[1:5])
        s = gamma / np.sqrt(var + attr(bn, "epsilon", 1e-5))
        W = G.consts[c.input[1]].copy()
        b = G.consts[c.input[2]] if len(c.input) > 2 and c.input[2] else np.zeros_like(s)
        if c.op_type == "Conv":
            W *= s[:, None, None, None]
        else:                                   # out channel o = group * cog + j
            g = attr(c, "group", 1)
            cig, cog = W.shape[0] // g, W.shape[1]
            for i in range(g):
                W[i * cig:(i + 1) * cig] *= s[i * cog:(i + 1) * cog][None, :, None, None]
        c.input[1] = G.const(W.astype(np.float32))
        b = G.const(((b - mean) * s + beta).astype(np.float32))
        if len(c.input) > 2:
            c.input[2] = b
        else:
            c.input.append(b)
        G.nodes.remove(bn)
        G.replace(bn.output[0], c.output[0])
        count += 1
    return count



def reshape_likes(G):
    """Squeeze, Unsqueeze and Transposes that keep the order of the axes
    longer than 1 -> Reshape; then collapse reshape chains, drop no-ops."""
    count = 0
    for n in list(G.nodes):
        if n.op_type == "Transpose":
            shape = G.shape[n.input[0]]
            moved = [p for p in attr(n, "perm") if shape[p] != 1]
            if moved != sorted(moved):
                continue
        elif n.op_type not in ("Squeeze", "Unsqueeze"):
            continue
        G.nodes.remove(n)
        G.nodes.append(helper.make_node("Reshape", [n.input[0], G.const(i64(*G.shape[n.output[0]]))],
                                        list(n.output[:1]), name=n.name))
        count += 1
    changed = True
    while changed:
        changed = False
        prod = G.producers()
        for n in G.nodes:
            if n.op_type != "Reshape":
                continue
            x, out = n.input[0], n.output[0]
            if G.shape[x] == G.shape[out]:
                G.nodes.remove(n)
                G.replace(out, x)
            elif (p := prod.get(x)) is not None and p.op_type == "Reshape":
                n.input[0], n.input[1] = p.input[0], G.const(i64(*G.shape[out]))
            else:
                continue
            count += 1
            changed = True
            G.prune()
            break
    return count



def layernorm(G):
    """ReduceMean, Sub, Pow 2, ReduceMean, Add eps, Sqrt, Div, Mul gamma,
    Add beta over trailing axes -> LayerNormalization (needs opset 17)."""
    count = 0
    for rm in [n for n in G.nodes if n.op_type == "ReduceMean"]:
        if rm not in G.nodes or attr(rm, "keepdims", 1) != 1:
            continue
        cons = G.consumers()
        x = rm.input[0]
        shape = G.shape[x]
        axes = sorted(a % len(shape) for a in attr(rm, "axes"))
        k = axes[0]
        if any(shape[a] != 1 for a in range(k, len(shape)) if a not in axes):
            continue

        def only(t, op):
            cs = cons.get(t, [])
            return cs[0] if len(cs) == 1 and cs[0].op_type == op else None

        def other(n, t):
            return G.consts.get(n.input[1] if n.input[0] == t else n.input[0])

        sub = only(rm.output[0], "Sub")
        d = sub.output[0] if sub is not None and list(sub.input) == [x, rm.output[0]] else None
        readers = cons.get(d, [])
        if d is None or sorted(c.op_type for c in readers) != ["Div", "Pow"]:
            continue
        pw, dv = sorted(readers, key=lambda c: c.op_type != "Pow")
        rm2 = only(pw.output[0], "ReduceMean")
        if G.consts.get(pw.input[1]) is None or float(G.consts[pw.input[1]]) != 2.0 or rm2 is None or \
                sorted(a % len(shape) for a in attr(rm2, "axes")) != axes:
            continue
        add = only(rm2.output[0], "Add")
        sq = only(add.output[0], "Sqrt") if add is not None else None
        eps = other(add, rm2.output[0]) if add is not None else None
        if sq is None or eps is None or eps.size != 1 or list(dv.input) != [d, sq.output[0]] or \
                len(cons[sq.output[0]]) != 1:
            continue
        mul = only(dv.output[0], "Mul")
        bias = only(mul.output[0], "Add") if mul is not None else None
        if bias is None:
            continue
        gamma, beta = other(mul, dv.output[0]), other(bias, mul.output[0])
        if gamma is None or beta is None:
            continue
        lead = (0,) * k
        gamma = np.broadcast_to(gamma, shape)[lead].astype(np.float32)
        beta = np.broadcast_to(beta, shape)[lead].astype(np.float32)
        for n in (rm, sub, pw, rm2, add, sq, dv, mul, bias):
            G.nodes.remove(n)
        G.nodes.append(helper.make_node(
            "LayerNormalization", [x, G.const(gamma), G.const(beta)], list(bias.output), name=G.name("ln"),
            axis=k, epsilon=float(eps), stash_type=1))
        count += 1
    if count:
        for o in G.model.opset_import:
            if o.domain in ("", "ai.onnx"):
                o.version = max(o.version, 17)
        G.model.ir_version = max(G.model.ir_version, 8)
    return count



def name_outputs(G):
    """Identity feeding a graph output: let its producer write the output."""
    prod, cons = G.producers(), G.consumers()
    for n in [n for n in G.nodes if n.op_type == "Identity" and n.output[0] in G.outputs]:
        src = n.input[0]
        p = prod.get(src)
        if p is None or len(cons[src]) != 1 or src in G.outputs:
            continue
        p.output[list(p.output).index(src)] = n.output[0]
        G.nodes.remove(n)
    return 0



# ------------------------------------------------------------------ driver
def read_source(path, sha256):
    """The bytes of the model at path; exits unless it is the expected file."""
    raw = Path(path).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != sha256:
        sys.exit(f"{path}: sha256 {digest}, expected {sha256}")
    return raw


def ort_folded(raw):
    """Graph of the model after ONNX Runtime's basic optimizations (constant
    folding, no hardware-specific layouts)."""
    with tempfile.TemporaryDirectory() as tmp:
        folded = os.path.join(tmp, "folded.onnx")
        session(raw, ort.GraphOptimizationLevel.ORT_ENABLE_BASIC, save_to=folded)
        return Graph(onnx.load(folded))


def max_differences(a, b, frames, state_map):
    """Run both models over `frames` (values of the first input), each fed
    back its own state outputs (state_map: output name -> input name), all
    states starting at zero unless `frames` yields (value, states) pairs;
    the largest |difference| per output."""
    sa, sb = session(a), session(b)
    ins = sa.get_inputs()
    assert [(i.name, i.shape) for i in ins] == [(i.name, i.shape) for i in sb.get_inputs()]
    outs = [o.name for o in sa.get_outputs()]
    assert outs == [o.name for o in sb.get_outputs()]
    worst = dict.fromkeys(outs, 0.0)
    ca = cb = None
    for frame in frames:
        frame, init = frame if isinstance(frame, tuple) else (frame, None)
        if ca is None:
            ca = init or {i.name: np.zeros(i.shape, np.float32) for i in ins[1:]}
            cb = dict(ca)
        ra = sa.run(outs, {ins[0].name: frame, **ca})
        rb = sb.run(outs, {ins[0].name: frame, **cb})
        for name, va, vb in zip(outs, ra, rb):
            worst[name] = max(worst[name], float(np.abs(va - vb).max()))
        ca = {state_map[o]: v for o, v in zip(outs, ra) if o in state_map}
        cb = {state_map[o]: v for o, v in zip(outs, rb) if o in state_map}
    return worst


def rewrite_and_save(G, raw, rewrites, out, tool, source, source_sha256, frames, state_map, tolerance):
    """Apply `rewrites` in order, check the result against the source model
    (max_differences) and write it only if every output stays within
    `tolerance`."""
    original = onnx.load_from_string(raw)
    print(f"onnxruntime {ort.__version__}: {len(original.graph.node)} nodes, {len(G.nodes)} after its folding")
    for rewrite in rewrites:
        count = rewrite(G)
        G.prune()
        print(f"  {rewrite.__name__:26s} {count:3d} -> {len(G.nodes)} nodes")
    model = G.to_model()
    model.producer_name, model.producer_version = f"poise {tool}", ""
    del model.metadata_props[:]
    helper.set_model_props(model, {"source": source, "source_sha256": source_sha256})

    worst = max_differences(original, model, frames, state_map)
    print("  max |difference| per output:", ", ".join(f"{k} {v:.2g}" for k, v in worst.items()))
    if max(worst.values()) > tolerance:
        sys.exit(f"outputs differ by more than {tolerance}; not writing {out}")
    onnx.save(model, out)
    print(f"wrote {out} ({os.path.getsize(out)} bytes)")
