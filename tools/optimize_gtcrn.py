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
Shared machinery: tools/onnx_rewrite.py.
"""
import argparse
import sys
from pathlib import Path

import numpy as np
from onnx import helper

sys.path.insert(0, str(Path(__file__).resolve().parent))
from onnx_rewrite import (  # noqa: E402
    attr, convtranspose_to_conv, fold_batchnorm, i64, layernorm, name_outputs, ort_folded,
    read_source, reshape_likes, rewrite_and_save, scatter_to_concat, simplify, slice_params)

UPSTREAM_SHA256 = "f648b02f2d7ff96ebcb0eec2219688a08ed12fe7e3d50f248605a90eba8cad17"
DEFAULT_OUT = Path(__file__).resolve().parent.parent / "stream_denoiser" / "models" / "gtcrn.onnx"
#: Largest |difference| allowed on any raw output (spectrum, caches) in the check.
TOLERANCE = 1e-4
NO_END = -2 ** 62     # Slice end for "through the start" with step -1


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


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("src", help="upstream stream/onnx_models/gtcrn.onnx")
    ap.add_argument("out", nargs="?", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    raw = read_source(args.src, UPSTREAM_SHA256)
    # ORT's own constant folding first: the export computes most shapes and
    # indices at run time.
    G = ort_folded(raw)
    caches = G.inputs[1:]
    rewrite_and_save(
        G, raw, REWRITES, args.out, tool="tools/optimize_gtcrn.py",
        source="github.com/Xiaobin-Rong/gtcrn stream/onnx_models/gtcrn.onnx (MIT)",
        source_sha256=UPSTREAM_SHA256, frames=test_frames(),
        state_map=dict(zip(G.outputs[1:], caches)), tolerance=TOLERANCE)


if __name__ == "__main__":
    main()
