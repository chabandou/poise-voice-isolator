"""
Rewrite the vendored DeepFilterNet3 streaming model into an equivalent,
faster graph.

    git show 05c081a:stream_denoiser/models/denoiser_model_df3.onnx > df3_orig.onnx
    python tools/optimize_df3.py df3_orig.onnx [OUT.onnx]

stream_denoiser/models/denoiser_model_df3.onnx is this script's output for
the DF3 export the repo vendored in 9e7c2c1 (sha256 below). Inputs,
outputs and states keep their names and shapes, so the two files are
interchangeable, and denoiser_model_df3_states.npz is unchanged.

Why: the export does its inverse FFT as an Einsum with a 513 x 2 x 1024
float32 matrix: 4.2 MB of weights read every frame, over a tenth of the
frame time, and cache space the GRUs (memory-bound, ~8 MB of weights)
then lack.
The rewrites, each exact up to float rounding:

- inverse real FFT (Einsum with the irfft basis, then constant scalings)
  -> two-stage 32 x 32 FFT from small MatMuls, with the scalings and the
  synthesis window folded into its weights (more accurate than the
  Einsum, too)
- deep filtering's complex multiply-accumulate over taps (Split, Transpose,
  four Muls, Sub, Add, Concat, ReduceSum) -> one outer-product Mul,
  ReduceSum and a 4 x 2 MatMul
- ScatterND writing a box -> Slice + Concat; reshape-like ops and slices of
  concats simplified (tools/onnx_rewrite.py)

The forward FFT stays ORT's DFT on purpose. The same MatMul FFT there is
more accurate than the DFT, yet the log-ERB features amplify any change in
near-empty bins: a full-scale DC input moved the output by 4e-5.

Before writing, both models run the same few hundred frames (states fed
back, starting from the .npz) and the largest output difference must stay
under TOLERANCE.

Needs the onnx package (a dev tool; Poise itself only needs onnxruntime).
"""
import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from onnx_rewrite import (  # noqa: E402
    attr, i64, name_outputs, ort_folded, read_source, reshape_likes, rewrite_and_save,
    scatter_to_concat, simplify)

SOURCE_SHA256 = "b758c49d6708a5b7979e3de185705a8a4915076c862fb17b1b304d9a72b75cdc"
MODELS = Path(__file__).resolve().parent.parent / "stream_denoiser" / "models"
DEFAULT_OUT = MODELS / "denoiser_model_df3.onnx"
STATES = MODELS / "denoiser_model_df3_states.npz"
#: Largest |difference| allowed on any raw output (audio, states) in the check.
TOLERANCE = 1e-4


def _cis(j, n):
    """cos and sin of 2*pi*j/n for integer j, exact at multiples of n/4."""
    j = np.mod(j, n)
    c, s = np.cos(2 * np.pi * j / n), np.sin(2 * np.pi * j / n)
    c[np.abs(c) < 1e-12] = 0.0
    s[np.abs(s) < 1e-12] = 0.0
    return c, s


def _factor(n):
    """n = p * q with p, q as close as possible (powers of two here)."""
    p = 1 << (int(np.log2(n)) // 2)
    if p * (n // p) != n:
        raise ValueError(f"no two-stage split for n={n}")
    return p, n // p


def _scale_chain(G, t):
    """Constant elementwise Muls after tensor t (scalars, or vectors over
    t's last axis) with nothing else reading t: (combined factor, last
    tensor of the chain)."""
    cons = G.consumers()
    factor = np.ones(G.shape[t][-1], np.float64)
    while len(cs := cons.get(t, [])) == 1 and cs[0].op_type == "Mul" and t not in G.outputs:
        m = cs[0]
        k = G.consts.get(m.input[1] if m.input[0] == t else m.input[0])
        if k is None or k.size not in (1, factor.size) or G.shape[m.output[0]] != G.shape[t]:
            break
        factor = factor * k.astype(np.float64).reshape(-1)
        t = m.output[0]
    return factor, t


def irfft_to_matmuls(G):
    """Einsum('fi,fij->j', spectrum [f, 2], irfft basis [f, 2, n]) ->
    [scalings] becomes, with n = L*m + l (m < R, l < L) and k = a + R*b:
      step 1  Y[l, a] = sum_b S'[a + R*b] e^(2 pi i l b / L)    (one MatMul)
      step 2  x[L*m + l] = Re sum_a Y[l, a] e^(2 pi i a (L*m + l) / n)
              (one MatMul batched over l; twiddles, scalings, window inside)
    where S' is the spectrum with the inner bins doubled, over n (irfft)."""
    count = 0
    for ein in [n for n in G.nodes if n.op_type == "Einsum"]:
        M = G.consts.get(ein.input[1])
        if attr(ein, "equation") not in (b"fi,fij->j", "fi,fij->j") or M is None or M.ndim != 3:
            continue
        f, two, n = M.shape
        if two != 2 or f != n // 2 + 1:
            continue
        if np.abs(M[:, 0] - np.fft.irfft(np.eye(f), n)).max() > 1e-6 or \
                np.abs(M[:, 1] - np.fft.irfft(1j * np.eye(f), n)).max() > 1e-6:
            continue                                      # not the irfft basis
        scale, out = _scale_chain(G, ein.output[0])    # per output sample
        R, L = _factor(n)
        nb = -(-f // R)
        weight = np.full(f, 2.0 / n)
        weight[0] = weight[-1] = 1.0 / n
        s = G.add("Mul", [ein.input[0], G.const(weight[:, None].astype(np.float32))], (f, 2))
        s = G.add("Pad", [s, G.const(i64(0, 0, nb * R - f, 0))], (nb * R, 2), mode="constant")
        s = G.add("Transpose", [s], (2, nb * R), perm=[1, 0])
        s = G.reshape(s, (2 * nb, R))                     # [(part, b), a]
        a, m, l, b = np.arange(R), np.arange(R), np.arange(L), np.arange(nb)
        c, sn = _cis(np.outer(l, b), L)                   # [l, b]
        F = np.block([[c, -sn], [sn, c]])                 # Y = (S_r + i S_i) e^(i theta)
        y = G.add("MatMul", [G.const(F.astype(np.float32)), s], (2 * L, R))     # [(part, l), a]
        y = G.add("Transpose", [G.reshape(y, (2, L, R))], (L, 2, R), perm=[1, 0, 2])
        y = G.reshape(y, (L, 1, 2 * R))
        # x = Re(Y e^(i phi)) = Y_r cos phi - Y_i sin phi
        cp, sp = _cis(a[None, :, None] * (L * m[None, None, :] + l[:, None, None]), n)   # [l, a, m]
        W = np.stack([cp, -sp], 1)                        # [l, part, a, m]
        W *= scale.reshape(R, L).T[:, None, None, :]      # x[L*m + l] scaled at [l, m]
        x = G.add("MatMul", [y, G.const(W.reshape(L, 2 * R, R).astype(np.float32))], (L, 1, R))
        x = G.add("Transpose", [G.reshape(x, (L, R))], (R, L), perm=[1, 0])
        G.replace(out, G.reshape(x, (n,)))
        count += 1
    return count


def complex_mac(G):
    """Deep filtering's sum over taps of complex products, written as
    Split/Transpose/Squeeze of both operands, four Muls, Sub, Add,
    Unsqueezes, Concat and ReduceSum over taps -> one outer-product Mul
    of the [taps, bins, 2] operands, ReduceSum over taps, and a 4 x 2
    MatMul that combines (re, im) x (re, im) into the complex result."""
    prod = G.producers()

    def part(t):
        """t = Reshape(Transpose?(output p of Split(axis -1) of B[.., .., 2])) -> (B, p, perm)."""
        n = prod.get(t)
        if n is None or n.op_type != "Reshape" or len(G.shape[t]) != 2:
            return None
        x = n.input[0]
        n, perm = prod.get(x), None
        if n is not None and n.op_type == "Transpose":
            perm, x = tuple(attr(n, "perm")), n.input[0]
            n = prod.get(x)
        if n is None or n.op_type != "Split" or len(n.output) != 2 or len(n.input) > 1:
            return None
        base = n.input[0]
        if len(G.shape[base]) != 3 or G.shape[base][2] != 2 or attr(n, "axis") % 3 != 2 or \
                (perm is not None and perm[2] != 2):
            return None
        return base, list(n.output).index(x), perm

    count = 0
    for r in [n for n in G.nodes if n.op_type == "ReduceSum"]:
        axes = G.consts.get(r.input[1]) if len(r.input) > 1 else None
        cat = prod.get(r.input[0])
        if axes is None or axes.tolist() != [0] or attr(r, "keepdims", 1) != 0 or cat is None or \
                cat.op_type != "Concat" or len(cat.input) != 2 or attr(cat, "axis") % 3 != 2:
            continue
        re, im = (prod.get(prod[i].input[0]) if prod.get(i) is not None and prod[i].op_type == "Reshape" else None
                  for i in cat.input)
        if re is None or im is None or re.op_type != "Sub" or im.op_type != "Add":
            continue
        muls = [prod.get(i) for i in list(re.input) + list(im.input)]
        if any(m is None or m.op_type != "Mul" for m in muls):
            continue
        parts = [[part(i) for i in m.input] for m in muls]
        if any(p is None for ps in parts for p in ps):
            continue
        s_base = {p[0] for ps in parts for p in ps if p[2] is None}
        c_base = {(p[0], p[2]) for ps in parts for p in ps if p[2] is not None}
        if len(s_base) != 1 or len(c_base) != 1:
            continue
        # each product: (S part, C part); re = SrCr - SiCi, im = SrCi + SiCr
        pairs = [tuple(sorted(((p[1], "S") if p[2] is None else (p[1], "C")) for p in ps)) for ps in parts]
        want = [((0, "C"), (0, "S")), ((1, "C"), (1, "S"))]
        if pairs[:2] != want or \
                sorted(pairs[2:]) != sorted([((0, "S"), (1, "C")), ((0, "C"), (1, "S"))]):
            continue
        S = s_base.pop()
        C, perm = c_base.pop()
        T, Fb, _ = G.shape[S]
        s4 = G.reshape(S, (T, Fb, 2, 1))
        d0, d1, _ = G.shape[C]
        c4 = G.add("Transpose", [G.reshape(C, (d0, d1, 1, 2))], (T, Fb, 1, 2), perm=[perm[0], perm[1], 2, 3])
        outer = G.add("Mul", [s4, c4], (T, Fb, 2, 2))
        summed = G.add("ReduceSum", [outer, G.const(i64(0))], (Fb, 2, 2), keepdims=0)
        M = np.array([[1, 0], [0, 1], [0, 1], [-1, 0]], np.float32)     # rows (S part, C part)
        out = G.add("MatMul", [G.reshape(summed, (Fb, 4)), G.const(M)], (Fb, 2))
        G.replace(r.output[0], out)
        count += 1
    return count


REWRITES = [irfft_to_matmuls, scatter_to_concat, simplify, reshape_likes, complex_mac,
            reshape_likes, simplify, name_outputs]


def test_frames(n=400, seed=0):
    """(input_frame, start states), then input frames: noisy harmonic audio
    at 48 kHz, its last quarter full-scale DC (the touchiest input found)."""
    rng = np.random.default_rng(seed)
    t = np.arange(n * 512) / 48000.0
    f0 = 150 + 40 * np.sin(2 * np.pi * 0.5 * t)
    voice = sum(np.sin(k * 2 * np.pi * np.cumsum(f0) / 48000) / k for k in range(1, 40))
    x = 0.2 * voice * np.clip(np.sin(2 * np.pi * 3 * t), 0, None) + 0.05 * rng.standard_normal(len(t))
    x[len(x) * 3 // 4:] = 0.95 + 1e-3 * rng.standard_normal(len(x) - len(x) * 3 // 4)
    x = x.astype(np.float32)
    with np.load(STATES) as z:
        states = {k: z[k].astype(np.float32) for k in z.files}
    yield x[:512], states
    for i in range(1, n):
        yield x[i * 512:(i + 1) * 512]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("src", help="the DF3 model as vendored in 9e7c2c1")
    ap.add_argument("out", nargs="?", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    raw = read_source(args.src, SOURCE_SHA256)
    # ORT's own folding first (the export already contains ORT's FusedConv,
    # so the file is ORT-only either way).
    G = ort_folded(raw)
    rewrite_and_save(
        G, raw, REWRITES, args.out, tool="tools/optimize_df3.py",
        source="denoiser_model_df3.onnx as vendored in 9e7c2c1", source_sha256=SOURCE_SHA256,
        frames=test_frames(), state_map={o: o[4:] for o in G.outputs if o.startswith("new_")},
        tolerance=TOLERANCE)


if __name__ == "__main__":
    main()
