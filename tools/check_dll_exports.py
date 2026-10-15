"""
Compare the poise_* exports of a freshly built DLL with the committed one.

    python tools/check_dll_exports.py BUILT.dll stream_denoiser/native/poise_wasapi.dll

The committed stream_denoiser/native/poise_wasapi.dll is built by hand
(native/poise_wasapi/Makefile). CI rebuilds it from the sources and runs
this: a function added to or dropped from the C API without a rebuild of
the committed DLL fails here instead of as a missing symbol in ctypes.
Only names with the prefix count; toolchains differ in what else they
export. Reads the PE export table directly, so it runs anywhere.
"""
import argparse
import struct
import sys
from pathlib import Path


def pe_exports(path):
    """Names in a PE file's export table."""
    data = Path(path).read_bytes()
    if data[:2] != b"MZ":
        raise ValueError(f"{path}: not a PE file")
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe:pe + 4] != b"PE\0\0":
        raise ValueError(f"{path}: no PE signature")
    n_sections, = struct.unpack_from("<H", data, pe + 6)
    opt_size, = struct.unpack_from("<H", data, pe + 20)
    opt = pe + 24
    magic, = struct.unpack_from("<H", data, opt)
    dirs = opt + {0x10B: 96, 0x20B: 112}[magic]
    export_rva, export_size = struct.unpack_from("<II", data, dirs)
    if not export_size:
        return set()
    sections = []
    for i in range(n_sections):
        vsize, va, raw_size, raw_ptr = struct.unpack_from(
            "<IIII", data, opt + opt_size + 40 * i + 8)
        sections.append((va, max(vsize, raw_size), raw_ptr))

    def offset(rva):
        for va, size, raw_ptr in sections:
            if va <= rva < va + size:
                return rva - va + raw_ptr
        raise ValueError(f"{path}: RVA {rva:#x} outside every section")

    exp = offset(export_rva)
    n_names, = struct.unpack_from("<I", data, exp + 24)
    names_rva, = struct.unpack_from("<I", data, exp + 32)
    names = set()
    for i in range(n_names):
        name_rva, = struct.unpack_from("<I", data, offset(names_rva) + 4 * i)
        start = offset(name_rva)
        names.add(data[start:data.index(b"\0", start)].decode("ascii"))
    return names


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("built", help="DLL just built from the sources")
    ap.add_argument("committed", help="DLL committed to the repo")
    ap.add_argument("--prefix", default="poise_",
                    help="compare only exports with this prefix (default: %(default)s)")
    args = ap.parse_args()
    built = {n for n in pe_exports(args.built) if n.startswith(args.prefix)}
    committed = {n for n in pe_exports(args.committed) if n.startswith(args.prefix)}
    if not built:
        print(f"{args.built}: no {args.prefix}* exports", file=sys.stderr)
        return 1
    if built == committed:
        print(f"{len(built)} {args.prefix}* exports match")
        return 0
    for name in sorted(built - committed):
        print(f"missing from {args.committed}: {name}", file=sys.stderr)
    for name in sorted(committed - built):
        print(f"no longer in the sources: {name}", file=sys.stderr)
    print(f"{args.committed} is stale: rebuild it "
          "(see native/poise_wasapi/Makefile)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
