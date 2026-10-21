"""
Bake the pen for the About emblem's seal (gui/widgets/emblem.py).

    python tools/bake_seal_pen.py            # opens the page in a browser
    python tools/bake_seal_pen.py --no-browser

The easter egg writes تَمَّ بِحَمْدِ اللَّهِ in Aref Ruqaa the way the site's
colophon does (docs/src/colophon.ts): the letters are thinned to centre
lines that a pen follows. Qt can read neither the site's woff2 font nor
run that tracing cheaply (and the UI process stays free of numpy), so a
browser does it once: this serves tools/seal_pen.html, which shapes and
traces the text and posts back the result, and writes, under
stream_denoiser/gui/assets/seal:

- pen.json: every pen point (x, y, radius, the time it is reached) in
  writing order, and where each letter group's shape sits in parts.png;
- text.png: the lettering's coverage (white on transparent), drawn at
  twice the text space for a crisp fill;
- parts.png: each letter group's own shape, slightly dilated, packed
  into one atlas; it settles in when the pen leaves the group.

All three are committed; run this after changing the lines, their
layout or the pen's pace in seal_pen.html. Stdlib only.
"""
import argparse
import base64
import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "tools" / "seal_pen.html"
FONT = ROOT / "docs" / "src" / "fonts" / "aref-ruqaa-arabic-700.woff2"
OUT = ROOT / "stream_denoiser" / "gui" / "assets" / "seal"


def _png(data_url: str) -> bytes:
    head, _, body = data_url.partition(",")
    if head != "data:image/png;base64":
        raise ValueError("expected a PNG data URL")
    return base64.b64decode(body)


def write_result(payload: dict) -> str:
    pen = payload["pen"]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "pen.json").write_text(
        json.dumps(pen, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8")
    (OUT / "text.png").write_bytes(_png(payload["text"]))
    (OUT / "parts.png").write_bytes(_png(payload["parts"]))
    points = sum(len(item["pts"]) for item in pen["items"])
    return (f"{len(pen['items'])} strokes, {points} pen points, "
            f"{len(pen['parts'])} parts, {pen['duration'] / 1000:.2f} s")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--port", type=int, default=8763)
    parser.add_argument("--no-browser", action="store_true",
                        help="only print the URL to open")
    args = parser.parse_args()
    done = threading.Event()
    outcome = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def _send(self, code: int, body: bytes, kind: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802 (http.server API)
            if self.path in ("/", "/index.html"):
                self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            elif self.path == "/font.woff2":
                self._send(200, FONT.read_bytes(), "font/woff2")
            else:
                self._send(404, b"not found", "text/plain")

        def do_POST(self):  # noqa: N802 (http.server API)
            if self.path != "/result":
                self._send(404, b"not found", "text/plain")
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                outcome["summary"] = write_result(json.loads(self.rfile.read(size)))
                self._send(200, b"ok", "text/plain")
            except Exception as e:  # report to the page and the console
                outcome["error"] = repr(e)
                self._send(500, repr(e).encode(), "text/plain")
            done.set()

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Open {url} to bake (waiting for the page to post its result)")
    if not args.no_browser:
        webbrowser.open(url)
    done.wait()
    server.shutdown()
    if "error" in outcome:
        print("Failed:", outcome["error"])
        return 1
    print(f"Wrote {OUT.relative_to(ROOT)}: {outcome['summary']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
