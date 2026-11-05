"""
Check the poise_* exports of a built libpoise_coreaudio.dylib.

    python tools/check_dylib_exports.py stream_denoiser/native/libpoise_coreaudio.dylib

The macOS counterpart of tools/check_dll_exports.py (that one reads a PE
export table). libpoise_coreaudio.dylib is built, never committed
(native/poise_coreaudio/Makefile), so there is no stale-build comparison
here: the check is against the two places the names come from.

  - every poise_core_* name stream_denoiser/backends/delay_core.py binds
    (core_signatures()) must be exported: it is compiled in from
    native/core and the node's inference thread calls it through ctypes;
  - every poise_ca_* name declared in
    native/poise_coreaudio/poise_coreaudio.h must be exported: that is the
    node's API (backends/coreaudio_node.py binds it).

poise_core.h is read too, as the list of core exports the library may
carry: input(), output() and count_trigger_fail() are the realtime leg,
called by the node in C, and must be exported but not bound by Python.

It also fails when the library exports main (the CLI target's
-DPOISE_CA_CLI leaking into the dylib) and when it exports a poise_* name
no header declares, so a C API change cannot land without the Python side
still binding cleanly.

nm does the Mach-O reading (`nm -gU`, Darwin's leading underscore
accepted), so this runs anywhere nm can read the file; where it cannot, it
says why and exits 2 rather than raising a traceback.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_HEADER = REPO / "native" / "poise_coreaudio" / "poise_coreaudio.h"
DEFAULT_CORE_HEADER = REPO / "native" / "core" / "poise_core.h"

# Mach-O magic, thin and fat: nm reads every architecture of a fat file.
MACHO_MAGIC = frozenset({
    b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf",  # 64-bit
    b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xce",  # 32-bit
    b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca",  # fat
    b"\xca\xfe\xba\xbf",                          # fat, 64-bit offsets
})

# nm flags that mean "defined, externally visible symbols only": -U is
# "defined only" on Darwin and in GNU binutils alike.
NM_FLAGS = (("-g", "-U"), ("-g", "--defined-only"))

# <address> <type> <name>, address optional (undefined lines have none).
NM_LINE = re.compile(r"^(?:[0-9a-fA-F]+\s+)?([A-Za-z?])\s+(\S+)$")

# A declaration: the name followed by its parameter list.
DECLARATION = r"\b({prefix}_\w+)\s*\("

GUARD_DEFINE = re.compile(r"#\s*ifndef\s+(\w+)[ \t]*\n\s*#\s*define\s+\1\b")
DIRECTIVE = re.compile(r"#\s*(if|ifdef|ifndef|else|elif|endif)\b")


class CheckError(Exception):
    """The check could not be run (as opposed to: it found a mismatch)."""


def check_macho(path):
    """CheckError saying what ``path`` is, unless it is a Mach-O file."""
    try:
        with open(path, "rb") as f:
            head = f.read(4)
    except OSError as e:
        raise CheckError(f"{path}: {e.strerror or e}")
    if head == b"\x7fELF":
        raise CheckError(
            f"{path}: ELF, not a Mach-O file: this checks the macOS dylib "
            "only (the Linux nodes are built and tested by pulse-ci's "
            "pipewire job)")
    if head == b"MZ":
        raise CheckError(
            f"{path}: PE, not a Mach-O file: use tools/check_dll_exports.py")
    if head not in MACHO_MAGIC:
        raise CheckError(f"{path}: not a Mach-O file")


def nm_exports(path, nm="nm"):
    """Defined, externally visible symbol names in a Mach-O file."""
    failure = None
    for flags in NM_FLAGS:
        try:
            proc = subprocess.run([nm, *flags, str(path)],
                                  capture_output=True, text=True)
        except FileNotFoundError:
            raise CheckError(
                f"{nm}: not found (on macOS it comes with the Xcode command "
                "line tools)")
        except OSError as e:
            raise CheckError(f"{nm}: {e}")
        if proc.returncode == 0:
            return parse_nm(proc.stdout)
        failure = proc.stderr.strip() or f"exit status {proc.returncode}"
    raise CheckError(f"{nm} could not read {path}: {failure}")


def parse_nm(output):
    """Symbol names from nm's output, without Darwin's leading underscore."""
    names = set()
    for line in output.splitlines():
        m = NM_LINE.match(line.strip())
        if not m:
            continue  # "(for architecture arm64):" and other headers
        kind, name = m.groups()
        if kind in ("U", "u"):
            continue  # undefined: imported, not exported
        names.add(name[1:] if name.startswith("_") else name)
    return names


def strip_comments(text):
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", " ", text)


def strip_conditionals(text):
    """The header's text outside every #if/#ifdef block.

    A declaration behind a feature macro is not part of the library: the
    CLI's poise_ca_list_devices sits behind POISE_CA_CLI, which the dylib's
    compile line does not define. The include guard is not such a block.
    """
    guard = GUARD_DEFINE.search(text)
    guard_macro = guard.group(1) if guard else None
    kept, depth = [], 0
    for line in text.splitlines():
        stripped = line.strip()
        directive = DIRECTIVE.match(stripped)
        if directive:
            kind = directive.group(1)
            if kind == "ifndef" and guard_macro and re.match(
                    rf"#\s*ifndef\s+{guard_macro}\b", stripped):
                continue  # the include guard: its body is the file
            if kind == "endif":
                depth = max(depth - 1, 0)
            elif kind not in ("else", "elif"):
                depth += 1
            # #else/#elif keep the depth: both branches are conditional
            continue
        if not depth:
            kept.append(line)
    return "\n".join(kept)


def header_exports(path, prefix):
    """The <prefix>_* names a header declares (unconditional code only)."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as e:
        raise CheckError(f"{path}: {e.strerror or e}")
    pattern = re.compile(DECLARATION.format(prefix=prefix))
    names = set(pattern.findall(strip_conditionals(strip_comments(text))))
    if not names:
        raise CheckError(f"{path}: no {prefix}_* declarations found: "
                         "wrong header, or the declarations moved")
    return names


def bound_node_exports():
    """The poise_ca_* names coreaudio_node._bind() binds, without a dlopen.

    The header check alone cannot catch a rename on the Python side: the
    declaration would still be in poise_coreaudio.h and the export would
    still be in the library, while coreaudio_node._bind asked for a name that
    no longer exists. Instead of loading the library (which needs macOS),
    call _bind with a stub binder and record the names it asks for.
    """
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    try:
        from stream_denoiser.backends import coreaudio_node
    except ImportError as e:
        raise CheckError(f"cannot import coreaudio_node._bind(): {e}")
    names = set()
    real = coreaudio_node.bind
    coreaudio_node.bind = lambda lib, sigs: names.update(sigs)
    try:
        coreaudio_node._bind(None)
    finally:
        coreaudio_node.bind = real
    if not names:
        raise CheckError("coreaudio_node._bind() asked for no names")
    return names


def bound_exports():
    """The poise_core_* names delay_core.core_signatures() binds."""
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    try:
        from stream_denoiser.backends.delay_core import core_signatures
    except ImportError as e:
        raise CheckError(f"cannot import delay_core.core_signatures(): {e}")
    return set(core_signatures())


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dylib", help="libpoise_coreaudio.dylib just built")
    ap.add_argument("--header", default=str(DEFAULT_HEADER),
                    help="poise_coreaudio.h (default: %(default)s)")
    ap.add_argument("--core-header", default=str(DEFAULT_CORE_HEADER),
                    help="poise_core.h (default: %(default)s)")
    ap.add_argument("--nm", default="nm",
                    help="nm to run (default: %(default)s)")
    args = ap.parse_args(argv)
    node_header = Path(args.header).name
    try:
        check_macho(args.dylib)
        exported = nm_exports(args.dylib, args.nm)
        core = bound_exports()
        node_bound = bound_node_exports()
        declared = header_exports(args.header, "poise_ca")
        core_api = header_exports(args.core_header, "poise_core")
    except CheckError as e:
        print(f"check_dylib_exports: {e}", file=sys.stderr)
        return 2

    if not exported & (core | declared):
        print(f"check_dylib_exports: {args.dylib}: none of the "
              f"{len(core | declared)} expected poise_* names is exported "
              "(wrong file, or nm lists only what is left of a stripped "
              "library)", file=sys.stderr)
        return 1

    problems = []
    for name in sorted(core - exported):
        problems.append(f"missing export: {name} "
                        "(delay_core.core_signatures() binds it)")
    for name in sorted(declared - exported):
        problems.append(f"missing export: {name} "
                        f"(declared in {node_header})")
    for name in sorted(node_bound - exported):
        problems.append(f"missing export: {name} "
                        "(coreaudio_node._bind() binds it)")
    for name in sorted(node_bound - declared - core_api):
        problems.append(f"bound but undeclared: {name} "
                        "(coreaudio_node._bind() binds it; neither "
                        f"{node_header} nor {Path(args.core_header).name} "
                        "declares it)")
    for name in sorted(core - core_api):
        problems.append(f"bound but undeclared: {name} "
                        "(delay_core.core_signatures() binds it, "
                        f"{Path(args.core_header).name} does not declare it)")
    expected = core | declared | node_bound
    known = expected | core_api
    for name in sorted({n for n in exported
                        if n.startswith(("poise_core_", "poise_ca_"))
                        and n not in known}):
        problems.append(f"unexpected export: {name} (not declared "
                        f"unconditionally in {node_header} or "
                        f"{Path(args.core_header).name})")
    if "main" in exported:
        problems.append("this library exports main: it was built with "
                        "-DPOISE_CA_CLI, the CLI target's flag "
                        "(make -C native/poise_coreaudio dylib)")
    if problems:
        for line in problems:
            print(line, file=sys.stderr)
        print(f"{args.dylib}: {len(problems)} export problem(s); the dylib "
              "and the Python side have drifted apart", file=sys.stderr)
        return 1

    print(f"{args.dylib}: {len(expected)} required poise_* names verified "
          f"({len(exported)} exported, all declared: {len(core)} bound by "
          f"delay_core, {len(declared)} declared in {node_header}), no main")
    return 0


if __name__ == "__main__":
    sys.exit(main())
