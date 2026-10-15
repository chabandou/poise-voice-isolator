"""
Rewrite upstream's streaming GTCRN export into an equivalent, faster graph.

    python tools/optimize_gtcrn.py UPSTREAM_GTCRN.onnx [OUT.onnx]

stream_denoiser/models/gtcrn.onnx is this script's output for the
streaming export in github.com/Xiaobin-Rong/gtcrn (stream/onnx_models/
gtcrn.onnx, MIT licensed; the file Poise for Android ships, sha256 below).
Inputs and outputs keep their names, shapes and cache layout, so the two
files are interchangeable.

Why: ONNX Runtime folds the 1786-node export to ~430 nodes, nearly all of
them tiny, and per-node cost rather than arithmetic set the frame time
(1.2 ms per 16 ms frame on a Ryzen 5 4500U, one thread). The rewrites,
each exact up to float rounding:

- cache updates: per-element ScatterND (one 4-number index per float)
  -> Slice + Concat, then slices of concats and gathers from them resolved
- grouped GRUs (two half-width GRUs on channels 0:8 and 8:16)
  -> one GRU with block-diagonal weights
- bidirectional GRUs -> one forward GRU over [x_t, x_(T-1-t)] with
  block-diagonal weights: both directions advance in the same step
- stride-1 ConvTranspose -> Conv; BatchNormalization folded into the conv
- subband unfold (Pad, Gather, Gather, Transpose, Reshape, Reshape) merged
  into the 1x1 conv after it as a 1x3 conv (or a one-hot grouped conv)
- mean/variance normalization chains -> LayerNormalization (opset 17)
- Transposes that only move size-1 axes, Squeeze, Unsqueeze -> Reshape;
  reshape chains collapsed

Before writing, both models run the same few hundred frames (caches fed
back) and the largest output difference must stay under TOLERANCE.

Needs the onnx package (a dev tool; Poise itself only needs onnxruntime).
"""
import argparse
import hashlib
import os
import sys
import tempfile
from pathlib import Path

import numpy as np
import onnx
import onnxruntime as ort
from onnx import helper, numpy_helper

UPSTREAM_SHA256 = "f648b02f2d7ff96ebcb0eec2219688a08ed12fe7e3d50f248605a90eba8cad17"
DEFAULT_OUT = Path(__file__).resolve().parent.parent / "stream_denoiser" / "models" / "gtcrn.onnx"
#: Largest |difference| allowed on any raw output (spectrum, caches) in the check.
TOLERANCE = 1e-4
NO_END = -2 ** 62     # Slice end for "through the start" with step -1


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


def _blockdiag(a, b, h, gates=3):
    """Per gate, [a_g 0; 0 b_g]: [D, gates*h, k_a], [D, gates*h, k_b] -> [D, gates*2h, k_a+k_b]."""
    ka = a.shape[2]
    out = np.zeros((a.shape[0], gates * 2 * h, ka + b.shape[2]), a.dtype)
    for g in range(gates):
        out[:, 2 * g * h:(2 * g + 1) * h, :ka] = a[:, g * h:(g + 1) * h]
        out[:, (2 * g + 1) * h:(2 * g + 2) * h, ka:] = b[:, g * h:(g + 1) * h]
    return out


def _interleave(a, b, h, parts=6):
    """Per part, [a_p, b_p]: [D, parts*h] x2 -> [D, parts*2h] (GRU bias layout)."""
    out = np.zeros((a.shape[0], parts * 2 * h), a.dtype)
    for p in range(parts):
        out[:, 2 * p * h:(2 * p + 1) * h] = a[:, p * h:(p + 1) * h]
        out[:, (2 * p + 1) * h:(2 * p + 2) * h] = b[:, p * h:(p + 1) * h]
    return out


def merge_grouped_grus(G):
    """Two GRUs on channel halves [0:k] and [k:2k] of one tensor, outputs
    joined by a Concat -> one GRU with block-diagonal weights (hidden units
    of the first, then of the second: the Concat's order)."""
    def half_of(x, prod):
        n, perm = prod.get(x), None
        if n is not None and n.op_type == "Transpose":
            perm, n = tuple(attr(n, "perm")), prod.get(n.input[0])
        p = slice_params(G, n) if n is not None and n.op_type == "Slice" else None
        if not p or p[0] != len(G.shape[n.input[0]]) - 1:
            return None
        return n.input[0], perm, p[1], p[2]

    def joined(t, cons):
        """Follow single-reader reshape-like ops from t to a Concat:
        (the Concat, the ops passed, the tensor it reads), else None."""
        ops = []
        while len(cs := cons.get(t, [])) == 1:
            if cs[0].op_type == "Concat":
                return cs[0], ops, t
            if cs[0].op_type not in ("Squeeze", "Unsqueeze", "Transpose", "Reshape"):
                break
            ops.append(cs[0].op_type)
            t = cs[0].output[0]
        return None

    def match(a, b, prod, cons):
        """(x source, perm, initial state, [(output of a, joining Concat)]) if
        a and b are the two halves of one grouped GRU, else None."""
        ha, hb = half_of(a.input[0], prod), half_of(b.input[0], prod)
        if not ha or not hb or ha[:2] != hb[:2] or (ha[2], ha[3], hb[3]) != (0, hb[2], G.shape[ha[0]][-1]):
            return None
        if any(attr(a, k) != attr(b, k) for k in ("hidden_size", "direction", "linear_before_reset")) or \
                len(a.input) < 6 or len(b.input) < 6 or a.input[4] or b.input[4]:
            return None
        h = attr(a, "hidden_size")
        joins = []
        for oa, ob in zip(a.output, b.output):
            if not cons.get(oa) and not cons.get(ob):
                continue
            ja, jb = joined(oa, cons), joined(ob, cons)
            # one Concat of exactly the two, a's half first, reached the same way
            if not ja or not jb or ja[0] is not jb[0] or list(ja[0].input) != [ja[2], jb[2]] or ja[1] != jb[1]:
                return None
            joins.append((oa, ja[0]))
        za, zb = G.consts.get(a.input[5]), G.consts.get(b.input[5])
        if za is not None and zb is not None and not za.any() and not zb.any():
            return ha[0], ha[1], G.const(np.zeros(za.shape[:-1] + (2 * h,), np.float32)), joins
        sa, sb = prod.get(a.input[5]), prod.get(b.input[5])
        pa = slice_params(G, sa) if sa is not None and sa.op_type == "Slice" else None
        pb = slice_params(G, sb) if sb is not None and sb.op_type == "Slice" else None
        if pa and pb and sa.input[0] == sb.input[0] and pa[0] == pb[0] == len(G.shape[sa.input[0]]) - 1 \
                and pa[1:] == (0, h) and pb[1:] == (h, 2 * h):
            return ha[0], ha[1], sa.input[0], joins
        return None

    count = 0
    while True:
        prod, cons = G.producers(), G.consumers()
        grus = [n for n in G.nodes if n.op_type == "GRU"]
        found = next(((a, b, m) for a in grus for b in grus
                      if a is not b and (m := match(a, b, prod, cons))), None)
        if found is None:
            return count
        a, b, (src, perm, h0, joins) = found
        h = attr(a, "hidden_size")
        x = src if perm is None else G.add("Transpose", [src], [G.shape[src][p] for p in perm], perm=list(perm))
        W = _blockdiag(G.consts[a.input[1]], G.consts[b.input[1]], h)
        R = _blockdiag(G.consts[a.input[2]], G.consts[b.input[2]], h)
        B = _interleave(G.consts[a.input[3]], G.consts[b.input[3]], h)
        seq, dirs, batch, _ = G.shape[a.output[0]]
        y, yh = G.name("gru_y"), G.name("gru_yh")
        G.nodes.append(helper.make_node(
            "GRU", [x, G.const(W), G.const(R), G.const(B), "", h0], [y, yh], name=G.name("gru"),
            hidden_size=2 * h, direction=attr(a, "direction"), linear_before_reset=attr(a, "linear_before_reset")))
        G.shape[y], G.shape[yh] = (seq, dirs, batch, 2 * h), (dirs, batch, 2 * h)
        for out, join in joins:
            shape = G.shape[join.output[0]]
            if out == a.output[1] or dirs == 1:
                # [..., A units, B units] on the last axis already
                new = G.reshape(yh if out == a.output[1] else y, shape)
            else:
                # [seq, dir, batch, (A, B), unit] -> [seq, batch, A_f A_b B_f B_b]
                r = G.reshape(y, (seq, 2, batch, 2, h))
                t = G.add("Transpose", [r], (seq, batch, 2, 2, h), perm=[0, 2, 3, 1, 4])
                new = G.reshape(t, shape)
            G.replace(join.output[0], new)
        G.nodes.remove(a)
        G.nodes.remove(b)
        G.prune()
        count += 1


def bidirectional_to_forward(G):
    """Bidirectional GRU (batch 1, zero initial state, Y_h unread) -> one
    forward GRU over [x_t, x_(T-1-t)] with block-diagonal weights; the
    backward half of its output is flipped back in time."""
    cons = G.consumers()
    count = 0
    for n in [n for n in G.nodes if n.op_type == "GRU" and attr(n, "direction") == b"bidirectional"]:
        x = n.input[0]
        T, batch, I = G.shape[x]
        h = attr(n, "hidden_size")
        h0 = G.consts.get(n.input[5]) if len(n.input) > 5 and n.input[5] else np.zeros(1)
        if batch != 1 or h0 is None or h0.any() or (len(n.input) > 4 and n.input[4]) or \
                (len(n.output) > 1 and cons.get(n.output[1])):
            continue
        W, R, B = (G.consts[i] for i in n.input[1:4])
        rev = G.add("Slice", [x, G.const(i64(-1)), G.const(i64(NO_END)), G.const(i64(0)), G.const(i64(-1))],
                    (T, 1, I))
        xx = G.concat([x, rev], 2)
        y = G.name("gru_y")
        G.nodes.append(helper.make_node(
            "GRU", [xx, G.const(_blockdiag(W[:1], W[1:], h)), G.const(_blockdiag(R[:1], R[1:], h)),
                    G.const(_interleave(B[:1], B[1:], h))], [y],
            name=G.name("gru"), hidden_size=2 * h, direction="forward",
            linear_before_reset=attr(n, "linear_before_reset")))
        G.shape[y] = (T, 1, 1, 2 * h)
        fwd = G.slice(y, 3, 0, h)
        bwd = G.add("Slice", [y, G.const(i64(-1, h)), G.const(i64(NO_END, 2 * h)), G.const(i64(0, 3)),
                              G.const(i64(-1, 1))], (T, 1, 1, h))
        G.nodes.remove(n)
        G.replace(n.output[0], G.reshape(G.concat([fwd, bwd], 3), (T, 2, 1, h)))
        count += 1
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


def unfold_to_conv(G):
    """Subband feature extraction: Pad (freq 1, 1), Gather(axis 2, [[0]]),
    Gather(axis 4, f + k), Transpose, Reshape, Reshape = unfold over
    frequency, channel c*3+k = x[c, f+k-1]. Folded into the 1x1 conv that
    reads it (as a 1x3 conv), else a grouped conv with one-hot kernels."""
    count = 0
    for pad in [n for n in G.nodes if n.op_type == "Pad"]:
        cons = G.consumers()
        pads = G.consts.get(pad.input[1]) if len(pad.input) > 1 else None
        if pads is None or pads.tolist() != [0, 0, 0, 1, 0, 0, 0, 1] or \
                attr(pad, "mode", b"constant") != b"constant" or \
                (len(pad.input) > 2 and pad.input[2] and G.consts[pad.input[2]].any()):
            continue
        chain, t = [pad], pad.output[0]
        for op in ("Gather", "Gather", "Transpose", "Reshape", "Reshape"):
            cs = cons.get(t, [])
            if len(cs) != 1 or cs[0].op_type != op:
                break
            chain.append(cs[0])
            t = cs[0].output[0]
        if len(chain) != 6:
            continue
        x = pad.input[0]
        B, C, T, F = G.shape[x]
        _, g1, g2, tr = chain[:4]
        idx = G.consts.get(g2.input[1])
        if T != 1 or attr(g1, "axis") != 2 or G.consts[g1.input[1]].tolist() != [[0]] or \
                attr(g2, "axis") != 4 or idx is None or \
                not np.array_equal(idx, np.arange(F)[None, :] + np.arange(3)[:, None]) or \
                attr(tr, "perm") != [0, 1, 2, 4, 3, 5] or G.shape[t] != (B, 3 * C, 1, F):
            continue
        readers = cons.get(t, [])
        conv = readers[0] if len(readers) == 1 else None
        if conv is not None and conv.op_type == "Conv" and attr(conv, "kernel_shape") == [1, 1] \
                and attr(conv, "group", 1) == 1 and t not in G.outputs:
            W = G.consts[conv.input[1]]
            conv.input[0] = x
            conv.input[1] = G.const(W.reshape(W.shape[0], C, 1, 3))
            for a in [a for a in conv.attribute if a.name in ("kernel_shape", "pads")]:
                conv.attribute.remove(a)
            conv.attribute.extend([helper.make_attribute("kernel_shape", [1, 3]),
                                   helper.make_attribute("pads", [0, 1, 0, 1])])
        else:
            E = np.zeros((C, 3, 1, 1, 3), np.float32)
            E[:, np.arange(3), 0, 0, np.arange(3)] = 1.0
            G.nodes.append(helper.make_node(
                "Conv", [x, G.const(E.reshape(3 * C, 1, 1, 3))], [t], name=G.name("unfold"),
                group=C, kernel_shape=[1, 3], pads=[0, 1, 0, 1], strides=[1, 1]))
        for n in chain:
            G.nodes.remove(n)
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


REWRITES = [scatter_to_concat, simplify, merge_grouped_grus, bidirectional_to_forward,
            convtranspose_to_conv, fold_batchnorm, unfold_to_conv, reshape_likes, simplify,
            layernorm, name_outputs]


# ------------------------------------------------------------------ check
def test_frames(n=400, seed=0):
    """The model's input for n hops of noisy harmonic audio at 16 kHz."""
    rng = np.random.default_rng(seed)
    t = np.arange((n + 1) * 256) / 16000.0
    f0 = 150 + 40 * np.sin(2 * np.pi * 0.5 * t)
    voice = sum(np.sin(k * 2 * np.pi * np.cumsum(f0) / 16000) / k for k in range(1, 20))
    x = 0.2 * voice * np.clip(np.sin(2 * np.pi * 3 * t), 0, None) + 0.05 * rng.standard_normal(len(t))
    win = np.sqrt(0.5 - 0.5 * np.cos(2 * np.pi * np.arange(512) / 512))
    for i in range(n):
        spec = np.fft.rfft(x[i * 256:i * 256 + 512] * win)
        yield np.stack([spec.real, spec.imag], -1)[None, :, None, :].astype(np.float32)


def max_differences(a, b):
    sa, sb = session(a), session(b)
    ins = [i for i in sa.get_inputs()]
    assert [(i.name, i.shape) for i in ins] == [(i.name, i.shape) for i in sb.get_inputs()]
    outs = [o.name for o in sa.get_outputs()]
    assert outs == [o.name for o in sb.get_outputs()]
    ca = {i.name: np.zeros(i.shape, np.float32) for i in ins[1:]}
    cb = dict(ca)
    worst = dict.fromkeys(outs, 0.0)
    for mix in test_frames():
        ra = sa.run(outs, {ins[0].name: mix, **ca})
        rb = sb.run(outs, {ins[0].name: mix, **cb})
        for name, va, vb in zip(outs, ra, rb):
            worst[name] = max(worst[name], float(np.abs(va - vb).max()))
        ca = dict(zip([i.name for i in ins[1:]], ra[1:]))
        cb = dict(zip([i.name for i in ins[1:]], rb[1:]))
    return worst


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("src", help="upstream stream/onnx_models/gtcrn.onnx")
    ap.add_argument("out", nargs="?", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    raw = Path(args.src).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != UPSTREAM_SHA256:
        sys.exit(f"{args.src}: sha256 {digest}, expected upstream's {UPSTREAM_SHA256}")
    source = onnx.load_from_string(raw)

    # ORT's own constant folding first (the export computes most shapes and
    # indices at run time), saved without its hardware-specific layouts.
    with tempfile.TemporaryDirectory() as tmp:
        folded = os.path.join(tmp, "folded.onnx")
        session(raw, ort.GraphOptimizationLevel.ORT_ENABLE_BASIC, save_to=folded)
        G = Graph(onnx.load(folded))
    print(f"onnxruntime {ort.__version__}: {len(source.graph.node)} nodes, {len(G.nodes)} after its folding")
    for rewrite in REWRITES:
        count = rewrite(G)
        G.prune()
        print(f"  {rewrite.__name__:26s} {count:3d} -> {len(G.nodes)} nodes")
    model = G.to_model()
    model.producer_name, model.producer_version = "poise tools/optimize_gtcrn.py", ""
    del model.metadata_props[:]
    onnx.helper.set_model_props(model, {
        "source": "github.com/Xiaobin-Rong/gtcrn stream/onnx_models/gtcrn.onnx (MIT)",
        "source_sha256": UPSTREAM_SHA256,
    })

    worst = max_differences(source, model)
    print("  max |difference| per output:", ", ".join(f"{k} {v:.2g}" for k, v in worst.items()))
    if max(worst.values()) > TOLERANCE:
        sys.exit(f"outputs differ by more than {TOLERANCE}; not writing {args.out}")
    onnx.save(model, args.out)
    print(f"wrote {args.out} ({os.path.getsize(args.out)} bytes)")


if __name__ == "__main__":
    main()
