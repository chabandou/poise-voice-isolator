"""
Poise Voice Isolator - VB-Cable routing error dialog.

Shown when automatic switching to VB-Cable fails. Processing does NOT
start in this case — the user must fix routing manually and retry.
"""

from PyQt6.QtWidgets import QMessageBox, QPushButton
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices

VB_CABLE_URL = "https://vb-audio.com/Cable/index.htm"

MANUAL_PS_FIX = (
    "Install-PackageProvider -Name NuGet -MinimumVersion 2.8.5.201 "
    "-Scope CurrentUser -Force; "
    "Set-PSRepository -Name PSGallery -InstallationPolicy Trusted; "
    "Install-Module -Name AudioDeviceCmdlets -Scope CurrentUser "
    "-Force -AllowClobber -SkipPublisherCheck"
)

MANUAL_STEPS = (
    "Poise captures system audio through VB-Cable automatically, "
    "but the automatic switch failed.\n\n"
    "To fix it manually:\n"
    "1. Install VB-Cable from vb-audio.com/Cable and reboot if needed.\n"
    "2. Open Windows Sound settings (button below).\n"
    "3. In Playback, set “CABLE Input (VB-Audio Virtual Cable)” as "
    "Default Device (and Default Communications Device).\n"
    "4. In Recording, make sure “CABLE Output” is present — "
    "Poise captures from there automatically.\n"
    "5. In Properties > Advanced for both, use the same format "
    "(e.g. 48000 Hz) and turn OFF “Listen to this device”.\n"
    "6. Press the power button again to retry.\n\n"
    "If the switch keeps failing (fresh Windows asks about the NuGet "
    "provider with no console to answer in), run this once in PowerShell "
    "and retry — the Copy button copies it:"
)


def show_vb_cable_error(parent, error_message: str) -> None:
    """Show a blocking modal with manual routing steps.

    Always modal (even when a tray icon exists) because processing
    cannot start without VB-Cable routing.
    """
    from PyQt6.QtWidgets import QApplication

    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Critical)
    box.setWindowTitle("Could not route audio through VB-Cable")
    box.setText(error_message or "Automatic VB-Cable switch failed.")
    box.setInformativeText(MANUAL_STEPS + "\n" + MANUAL_PS_FIX)
    box.setStandardButtons(QMessageBox.StandardButton.Close)

    sound_btn = QPushButton("Open Sound Settings")
    sound_btn.clicked.connect(lambda: _open_sound_settings())
    box.addButton(sound_btn, QMessageBox.ButtonRole.ActionRole)

    cable_btn = QPushButton("Install VB-Cable")
    cable_btn.clicked.connect(
        lambda: _on_install_vb_cable(parent, cable_btn))
    box.addButton(cable_btn, QMessageBox.ButtonRole.ActionRole)

    copy_btn = QPushButton("Copy PowerShell fix")
    copy_btn.clicked.connect(
        lambda: QApplication.clipboard().setText(MANUAL_PS_FIX))
    box.addButton(copy_btn, QMessageBox.ButtonRole.ActionRole)

    box.exec()


def _on_install_vb_cable(parent, button) -> None:
    """Install the vendored VB-Cable driver, or fall back to the website."""
    from PyQt6.QtWidgets import QApplication, QMessageBox

    try:
        from ..platform.windows import (
            find_bundled_vbcable_setup,
            install_vbcable_driver,
            interpret_setup_exit_code,
            is_vbcable_installed,
        )
    except ImportError:
        _open_cable_website()
        return

    if is_vbcable_installed():
        QMessageBox.information(
            parent, "VB-Cable already installed",
            "CABLE Input/Output are present. If routing still fails, "
            "reboot Windows once and press the power button again.")
        return

    if find_bundled_vbcable_setup() is None:
        _open_cable_website()
        return

    button.setEnabled(False)
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        code = install_vbcable_driver()
    except RuntimeError as e:
        QMessageBox.warning(parent, "VB-Cable install failed", str(e))
        return
    finally:
        QApplication.restoreOverrideCursor()
        button.setEnabled(True)

    outcome = interpret_setup_exit_code(code)
    if is_vbcable_installed():
        QMessageBox.information(
            parent, "VB-Cable installed",
            "CABLE Input/Output are ready. Press the power button "
            "again to start.")
    elif outcome == "reboot-required":
        QMessageBox.information(
            parent, "Reboot required",
            "VB-Cable installed — reboot Windows to activate the driver, "
            "then press the power button again.")
    else:
        QMessageBox.warning(
            parent, "VB-Cable install failed",
            f"The driver setup exited with code {code}. "
            "Try installing manually from vb-audio.com/Cable.")


def _open_cable_website() -> None:
    """Fallback when no vendored setup is available."""
    QDesktopServices.openUrl(QUrl(VB_CABLE_URL))


def _open_sound_settings() -> None:
    """Open Windows Sound settings, with Control Panel fallback."""
    try:
        QDesktopServices.openUrl(QUrl("ms-settings:sound"))
    except Exception:
        pass
    # Fallback for VMs / stripped Windows where ms-settings: is blocked.
    try:
        import subprocess
        subprocess.Popen(
            ["control", "mmsys.cpl"],
            shell=True,
        )
    except Exception:
        pass
