"""Setup engine: plan, command line, exit codes, log parsing (no Qt).

The window's decisions are all made here, so these tests run on the
Qt-free CI too.
"""
import importlib.util
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import installer_harness  # noqa: E402

core = installer_harness.load("core")
brand = installer_harness.load("brand")

SETUP_ISS = os.path.join(installer_harness.ROOT, "setup.iss")


# -- the command line handed to the core -----------------------------------

def test_silent_run_arguments():
    plan = core.InstallPlan(
        target_dir=r"C:\Program Files\Poise Voice Isolator",
        desktop_icon=True,
        log_path=r"C:\Temp\poise.log",
    )
    args = core.build_args(plan)
    assert "/VERYSILENT" in args          # no second UI on screen
    assert "/SUPPRESSMSGBOXES" in args    # dialogs become exit codes
    assert "/NORESTART" in args           # the window asks about rebooting
    assert r"/LOG=C:\Temp\poise.log" in args
    assert r"/DIR=C:\Program Files\Poise Voice Isolator" in args
    assert "/TASKS=desktopicon" in args


def test_no_desktop_icon_means_no_task():
    args = core.build_args(core.InstallPlan("C:\\Poise", desktop_icon=False))
    assert not any(arg.startswith("/TASKS") for arg in args)


def test_default_dir_matches_the_32_bit_core():
    # setup.iss is 32-bit Inno: {autopf} is Program Files (x86) there.
    assert core.default_dir().endswith(core.APP_NAME)
    assert core.default_dir().startswith(
        os.environ.get("ProgramFiles(x86)")
        or os.environ.get("ProgramFiles") or "C:\\Program Files")


def test_log_path_is_unique_and_in_temp():
    first, second = core.default_log_path(), core.default_log_path()
    assert first != second
    assert first.endswith(".log")


# -- exit codes ------------------------------------------------------------

def test_success_and_reboot_codes():
    assert core.exit_status(0) == core.OK
    assert core.exit_status(3010) == core.REBOOT
    assert core.exit_status(1641) == core.REBOOT


def test_cancelled_codes():
    for code in (2, 5, 6):
        assert core.exit_status(code) == core.CANCELLED


def test_everything_else_fails():
    for code in (1, 3, 4, 7, 8, 9, 99, -1):
        assert core.exit_status(code) == core.FAILED


# -- the log contract with setup.iss ---------------------------------------

def test_parse_marker():
    line = "2026-10-19 14:32:08.203   POISE:phase=files"
    assert core.parse_marker(line) == ("phase", "files")
    assert core.parse_marker("POISE:driver=skip") == ("driver", "skip")
    assert core.parse_marker("Dest filename: C:\\x\\Poise.exe") is None
    assert core.parse_marker("POISE:without-a-value") is None


def test_setup_iss_only_emits_known_markers():
    """Guards the setup.iss <-> core.py contract against drift."""
    with open(SETUP_ISS, encoding="utf-8") as fh:
        script = fh.read()
    markers = re.findall(r"Log\('POISE:([a-z]+)=([a-z]+)'\)", script)
    assert markers, "setup.iss no longer logs any progress markers"
    for key, value in markers:
        if key == "phase":
            assert value in core.PHASES, value
        elif key == "driver":
            assert value in core.DRIVER_EVENTS, value
        else:
            pytest.fail(f"unknown marker kind: {key}")


def test_every_driver_event_has_a_caption():
    for event in core.DRIVER_EVENTS:
        assert core.driver_text(event), event


def test_phases_are_ordered():
    assert list(core.PHASES) == ["prepare", "files", "driver", "finish"]
    assert core.PHASE_ORDER["files"] < core.PHASE_ORDER["driver"]


# -- incremental log reading ----------------------------------------------

def test_log_tail_reads_only_new_complete_lines(tmp_path):
    log = tmp_path / "setup.log"
    log.write_text("one\ntwo\n", encoding="utf-8")
    tail = core.LogTail(str(log))
    assert tail.read() == ["one", "two"]

    with open(log, "a", encoding="utf-8") as fh:
        fh.write("POISE:phase=driver\nhalf a line")
    assert tail.read() == ["POISE:phase=driver"]

    with open(log, "a", encoding="utf-8") as fh:
        fh.write(" completed\n")
    assert tail.read() == ["half a line completed"]


def test_log_tail_survives_a_missing_file(tmp_path):
    assert core.LogTail(str(tmp_path / "absent.log")).read() == []


def test_log_tail_reads_utf16_logs(tmp_path):
    """Inno writes UTF-16 on some systems; the BOM decides."""
    log = tmp_path / "utf16.log"
    log.write_bytes("POISE:phase=files\r\n".encode("utf-16"))
    assert core.LogTail(str(log)).read() == ["POISE:phase=files"]


# -- discovery and probes --------------------------------------------------

def test_resolve_core_honours_an_explicit_path(tmp_path):
    core_exe = tmp_path / "PoiseCore.exe"
    core_exe.write_bytes(b"MZ")
    assert core.resolve_core(str(core_exe)) == str(core_exe)
    assert core.resolve_core(str(tmp_path / "missing.exe")) is None


def test_core_is_looked_for_beside_the_installer_sources():
    expected = os.path.join(installer_harness.ROOT, "installer", core.CORE_NAME)
    assert expected in core.core_candidates()


def test_vbcable_probe_answers_without_raising():
    assert core.vbcable_present() in (True, False, None)


def test_existing_install_is_optional():
    found = core.existing_install()
    assert found is None or isinstance(found, core.Existing)


def test_tail_of_a_missing_log_is_empty(tmp_path):
    assert core.tail(str(tmp_path / "nope.log")) == ""


def test_tail_returns_the_last_lines_only(tmp_path):
    log = tmp_path / "setup.log"
    log.write_text("\n".join(f"line {n}" for n in range(100)), encoding="utf-8")
    text = core.tail(str(log), lines=3)
    assert text.splitlines() == ["line 97", "line 98", "line 99"]


def test_tail_reads_a_utf16_log(tmp_path):
    log = tmp_path / "utf16.log"
    log.write_bytes("Log opened.\r\nPOISE:driver=failed\r\n".encode("utf-16"))
    assert "POISE:driver=failed" in core.tail(str(log))


# -- brand parity ----------------------------------------------------------

def test_palette_matches_the_application_theme():
    """The setup window must not drift from the app's signature palette."""
    themes = installer_harness.load_gui("themes")
    assert brand.PALETTE == themes.THEMES["halcyon"]


def test_stylesheet_has_no_unresolved_tokens():
    css = brand.stylesheet()
    assert not re.search(r"@[a-z_]+@", css)
    assert brand.PALETTE["accent"] in css


def test_version_is_read_from_pyproject():
    assert re.match(r"^\d+\.\d+", brand.version())


def test_version_is_read_from_the_bundled_file(tmp_path, monkeypatch):
    """The frozen build ships a bare-number version.txt, not pyproject."""
    (tmp_path / "version.txt").write_text("9.9.9\n", encoding="utf-8")
    monkeypatch.setattr(brand.sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(brand, "_version", None)
    assert brand.version() == "9.9.9"
