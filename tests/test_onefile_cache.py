"""The Linux onefile binary's unpack cache: one folder per version under
~/.cache/poise/onefile, older ones pruned at start (poise_tui.py)."""
import shutil
import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"),
                                reason="/proc and the onefile build: Linux")

import poise_tui  # noqa: E402


def versions(root):
    for name in ("1.4.0", "1.5.0", "1.6.0"):
        (root / name / "lib").mkdir(parents=True)
        (root / name / "lib" / "x.so").write_text("")
    return root


def test_other_versions_are_deleted_and_this_one_kept(tmp_path):
    root = versions(tmp_path / "onefile")
    poise_tui.prune_old_unpacks(str(root / "1.6.0"), str(root))
    assert sorted(p.name for p in root.iterdir()) == ["1.6.0"]


def test_nothing_is_deleted_outside_the_cache(tmp_path):
    root = versions(tmp_path / "onefile")
    poise_tui.prune_old_unpacks(str(tmp_path / "elsewhere" / "bin"), str(root))
    assert len(list(root.iterdir())) == 3


def test_a_version_still_running_is_kept(tmp_path):
    root = versions(tmp_path / "onefile")
    sleep = shutil.which("sleep")
    if sleep is None:
        pytest.skip("no sleep binary")
    shutil.copy(sleep, root / "1.4.0" / "sleep")
    proc = subprocess.Popen([str(root / "1.4.0" / "sleep"), "30"])
    try:
        poise_tui.prune_old_unpacks(str(root / "1.6.0"), str(root))
    finally:
        proc.kill()
        proc.wait()
    assert sorted(p.name for p in root.iterdir()) == ["1.4.0", "1.6.0"]
