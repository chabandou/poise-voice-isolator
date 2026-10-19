"""
Import the setup package from the source tree, without installing it.

`installer/` is build tooling: pyproject ships only stream_denoiser, so
there is no installed `installer` package to import in CI. These helpers
load the modules by path, the way test_themes.py loads gui/themes.py.
"""
import importlib.util
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE_DIR = os.path.join(ROOT, "installer", "bootstrapper")
GUI_DIR = os.path.join(ROOT, "stream_denoiser", "gui")

_PACKAGE = "poise_setup_test"


def _ensure_package():
    package = sys.modules.get(_PACKAGE)
    if package is None:
        package = types.ModuleType(_PACKAGE)
        package.__path__ = [PACKAGE_DIR]
        sys.modules[_PACKAGE] = package
    return package


def load(name):
    """Import installer/bootstrapper/<name>.py as poise_setup_test.<name>."""
    _ensure_package()
    fullname = f"{_PACKAGE}.{name}"
    if fullname in sys.modules:
        return sys.modules[fullname]
    spec = importlib.util.spec_from_file_location(
        fullname, os.path.join(PACKAGE_DIR, name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[fullname] = module
    spec.loader.exec_module(module)
    return module


def load_gui(name):
    """Import stream_denoiser/gui/<name>.py without its package __init__."""
    package_name = "poise_gui_for_setup"
    package = sys.modules.get(package_name)
    if package is None:
        package = types.ModuleType(package_name)
        package.__path__ = [GUI_DIR]
        sys.modules[package_name] = package
    fullname = f"{package_name}.{name}"
    if fullname in sys.modules:
        return sys.modules[fullname]
    spec = importlib.util.spec_from_file_location(
        fullname, os.path.join(GUI_DIR, name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[fullname] = module
    spec.loader.exec_module(module)
    return module
