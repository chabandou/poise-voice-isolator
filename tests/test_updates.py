"""In-app update core (stream_denoiser/updates.py; no Qt needed).

Downloads run against a local HTTP server standing in for GitHub.
"""
import hashlib
import http.server
import json
import os
import threading

import pytest

from stream_denoiser import updates

PAYLOAD = os.urandom(300_000)
SHA = hashlib.sha256(PAYLOAD).hexdigest()


@pytest.fixture()
def server():
    """A local server: path -> bytes, with request counts."""
    routes, hits = {}, {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 (http.server API)
            hits[self.path] = hits.get(self.path, 0) + 1
            body = routes.get(self.path)
            if body is None:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    yield base, routes, hits
    httpd.shutdown()
    httpd.server_close()


def _release_json(base, tag="v9.0.0", digest=True, checksum=False, **extra):
    asset = {"name": updates.CORE_ASSET, "size": len(PAYLOAD),
             "browser_download_url": f"{base}/core"}
    if digest:
        asset["digest"] = f"sha256:{SHA}"
    assets = [{"name": "Poise_Setup.exe", "size": 1,
               "browser_download_url": f"{base}/setup"}, asset]
    if checksum:
        assets.append({"name": updates.CHECKSUM_ASSET, "size": 80,
                       "browser_download_url": f"{base}/core.sha256"})
    data = {"tag_name": tag, "html_url": f"{base}/page", "draft": False,
            "prerelease": False, "assets": assets}
    data.update(extra)
    return data


# -- versions -------------------------------------------------------------------
@pytest.mark.parametrize("text, expected", [
    ("v1.6.0", (1, 6, 0)), ("1.6.0", (1, 6, 0)), ("v2.0", (2, 0, 0)),
    ("1.6.0+local", (1, 6, 0)), ("v1.6.0-rc1", None), ("launch", None),
    ("", None),
])
def test_parse_version(text, expected):
    assert updates.parse_version(text) == expected


def test_is_newer_compares_numerically():
    assert updates.is_newer("v1.10.0", "1.9.3")
    assert not updates.is_newer("v1.9.3", "1.9.3")
    assert not updates.is_newer("v1.2.0", "1.10.0")
    assert not updates.is_newer("garbage", "1.0.0")
    assert not updates.is_newer("v2.0.0", "0+unknown")


# -- release JSON -----------------------------------------------------------------
def test_parse_release_picks_the_core_and_its_digest():
    release = updates.parse_release(_release_json("http://x"))
    assert release.version == "9.0.0"
    assert release.asset_url == "http://x/core"
    assert release.asset_size == len(PAYLOAD)
    assert release.sha256 == SHA
    assert release.page_url == "http://x/page"


def test_parse_release_skips_drafts_prereleases_and_odd_tags():
    assert updates.parse_release(_release_json("x", draft=True)) is None
    assert updates.parse_release(_release_json("x", prerelease=True)) is None
    assert updates.parse_release(_release_json("x", tag="nightly")) is None


def test_parse_release_without_core_still_offers_the_page():
    data = _release_json("http://x")
    data["assets"] = data["assets"][:1]   # an old release: setup only
    release = updates.parse_release(data)
    assert release.version == "9.0.0" and release.asset_url == ""


def test_fetch_latest(server, monkeypatch):
    base, routes, _ = server
    routes["/latest"] = json.dumps(_release_json(base)).encode()
    monkeypatch.setattr(updates, "LATEST_API", f"{base}/latest")
    assert updates.fetch_latest().version == "9.0.0"


def test_fetch_latest_without_releases(server, monkeypatch):
    base, _, _ = server
    monkeypatch.setattr(updates, "LATEST_API", f"{base}/missing")
    assert updates.fetch_latest() is None


def test_fetch_latest_unreachable(monkeypatch):
    monkeypatch.setattr(updates, "LATEST_API", "http://127.0.0.1:9/latest")
    with pytest.raises(updates.UpdateError):
        updates.fetch_latest(timeout=2)


# -- download ---------------------------------------------------------------------
def test_download_verifies_and_reports_progress(server, tmp_path):
    base, routes, _ = server
    routes["/core"] = PAYLOAD
    release = updates.parse_release(_release_json(base))
    seen = []
    path = updates.download(release, str(tmp_path),
                            progress=lambda d, t: seen.append((d, t)))
    assert open(path, "rb").read() == PAYLOAD
    assert seen[-1] == (len(PAYLOAD), len(PAYLOAD))
    assert not any(name.endswith(".part") for name in os.listdir(tmp_path))


def test_download_uses_the_checksum_file_without_a_digest(server, tmp_path):
    base, routes, _ = server
    routes["/core"] = PAYLOAD
    routes["/core.sha256"] = f"{SHA}  PoiseCore.exe".encode()
    release = updates.parse_release(
        _release_json(base, digest=False, checksum=True))
    assert release.sha256 == ""
    assert open(updates.download(release, str(tmp_path)), "rb").read() \
        == PAYLOAD


def test_download_rejects_a_mismatch(server, tmp_path):
    base, routes, _ = server
    routes["/core"] = PAYLOAD[:-1] + bytes([PAYLOAD[-1] ^ 1])
    release = updates.parse_release(_release_json(base))
    with pytest.raises(updates.UpdateError, match="checksum"):
        updates.download(release, str(tmp_path))
    assert os.listdir(tmp_path) == []


def test_download_rejects_a_short_file(server, tmp_path):
    base, routes, _ = server
    routes["/core"] = PAYLOAD[:1000]
    release = updates.parse_release(_release_json(base))
    with pytest.raises(updates.UpdateError, match="incomplete"):
        updates.download(release, str(tmp_path))
    assert os.listdir(tmp_path) == []


def test_download_needs_something_to_verify_against(server, tmp_path):
    base, routes, hits = server
    routes["/core"] = PAYLOAD
    release = updates.parse_release(_release_json(base, digest=False))
    with pytest.raises(updates.UpdateError, match="checksum"):
        updates.download(release, str(tmp_path))
    assert "/core" not in hits   # refused before downloading anything


def test_download_can_be_cancelled(server, tmp_path):
    base, routes, _ = server
    routes["/core"] = PAYLOAD
    release = updates.parse_release(_release_json(base))
    with pytest.raises(updates.UpdateError, match="cancelled"):
        updates.download(release, str(tmp_path), cancelled=lambda: True)
    assert os.listdir(tmp_path) == []


# -- installing -------------------------------------------------------------------
def test_source_checkout_cannot_update_itself():
    assert updates.install_dir() is None
    assert not updates.can_self_update()


def test_installed_build_is_found_by_its_uninstaller(tmp_path, monkeypatch):
    exe = tmp_path / "Poise.exe"
    exe.write_bytes(b"")
    monkeypatch.setattr(updates.sys, "platform", "win32")
    monkeypatch.setattr(updates.sys, "frozen", True, raising=False)
    monkeypatch.setattr(updates.sys, "executable", str(exe))
    assert updates.install_dir() is None          # portable copy
    (tmp_path / updates.UNINSTALLER).write_bytes(b"")
    assert updates.install_dir() == str(tmp_path)


def test_installer_args_are_silent_and_mark_an_update():
    args = updates.installer_args(r"C:\t\started", r"C:\t\install.log")
    assert "/VERYSILENT" in args and "/SUPPRESSMSGBOXES" in args
    assert "/CLOSEAPPLICATIONS" in args and "/NORESTART" in args
    assert r"/POISEUPDATE=C:\t\started" in args
    assert r"/LOG=C:\t\install.log" in args
    assert f"/POISEPID={os.getpid()}" in args
    assert "/POISEPID=42" in updates.installer_args("s", "l", pid=42)


def test_setup_script_honours_the_update_contract():
    """setup.iss must read the switches and mutex this module uses."""
    path = os.path.join(os.path.dirname(__file__), "..", "setup.iss")
    with open(path, encoding="utf-8") as f:
        script = f.read()
    assert "{param:POISEUPDATE|}" in script
    assert "{param:POISEPID|}" in script      # a Poise that won't quit
    assert f"'{updates.RUNNING_MUTEX}'" in script
    # Poise starts again however the update ends, as the user.
    assert "procedure DeinitializeSetup" in script
    assert "ExecAsOriginalUser" in script
