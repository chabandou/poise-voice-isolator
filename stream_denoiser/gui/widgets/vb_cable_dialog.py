"""
Poise Voice Isolator - VB-Cable routing error dialog.

Shown when automatic switching to VB-Cable fails. Processing does NOT
start in this case — the user must fix routing manually and retry.
A themed dialog (numbered steps, copyable PowerShell fix) rather than a
plain message box, so a long recovery guide stays readable.
"""

from PyQt6.QtWidgets import (
    QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QVBoxLayout,
)
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices

from .phosphor import PhosphorIcon
from ..scaling import sp
from ..themes import current as current_theme

VB_CABLE_URL = "https://vb-audio.com/Cable/index.htm"

MANUAL_PS_FIX = (
    "Install-PackageProvider -Name NuGet -MinimumVersion 2.8.5.201 "
    "-Scope CurrentUser -Force; "
    "Set-PSRepository -Name PSGallery -InstallationPolicy Trusted; "
    "Install-Module -Name AudioDeviceCmdlets -Scope CurrentUser "
    "-Force -AllowClobber -SkipPublisherCheck"
)

INTRO = ("Poise captures system audio through VB-Cable automatically, "
         "but the automatic switch failed.")

STEPS = (
    "Install VB-Cable from vb-audio.com/Cable and reboot if needed.",
    "Open Windows Sound settings (button below).",
    "In Playback, set “CABLE Input (VB-Audio Virtual Cable)” as "
    "Default Device (and Default Communications Device).",
    "In Recording, make sure “CABLE Output” is present — "
    "Poise captures from there automatically.",
    "In Properties > Advanced for both, use the same format "
    "(e.g. 48000 Hz) and turn OFF “Listen to this device”.",
    "Press the power button again to retry.",
)

PS_NOTE = ("If the switch keeps failing (fresh Windows asks about the NuGet "
           "provider with no console to answer in), run this once in "
           "PowerShell and retry:")

MANUAL_STEPS = (
    INTRO + "\n\nTo fix it manually:\n"
    + "\n".join(f"{n}. {t}" for n, t in enumerate(STEPS, 1))
    + "\n\n" + PS_NOTE
)


class VbCableDialog(QDialog):
    """Modal recovery guide for a failed VB-Cable switch."""

    def __init__(self, parent, error_message: str = ""):
        super().__init__(parent)
        self.setObjectName("vb-dialog")
        self.setWindowTitle("Could not route audio through VB-Cable")
        self.setModal(True)
        self.setMinimumWidth(sp(680))

        root = QVBoxLayout(self)
        root.setContentsMargins(sp(28), sp(24), sp(28), sp(20))
        root.setSpacing(sp(10))

        head = QHBoxLayout()
        head.setSpacing(sp(16))
        chip = QFrame()
        chip.setObjectName("err-chip")
        chip.setFixedSize(sp(44), sp(44))
        chip_layout = QHBoxLayout(chip)
        chip_layout.setContentsMargins(0, 0, 0, 0)
        chip_layout.addWidget(
            PhosphorIcon("info", color=current_theme()["error"], size=22),
            alignment=Qt.AlignmentFlag.AlignCenter)
        head.addWidget(chip, alignment=Qt.AlignmentFlag.AlignTop)
        titles = QVBoxLayout()
        titles.setSpacing(sp(4))
        title = QLabel(error_message or "Automatic VB-Cable switch failed.")
        title.setObjectName("card-title")
        title.setWordWrap(True)
        titles.addWidget(title)
        intro = QLabel(INTRO)
        intro.setObjectName("row-sub")
        intro.setWordWrap(True)
        titles.addWidget(intro)
        head.addLayout(titles, stretch=1)
        root.addLayout(head)

        heading = QLabel("To fix it manually")
        heading.setObjectName("row-title")
        root.addSpacing(sp(6))
        root.addWidget(heading)
        for n, text in enumerate(STEPS, 1):
            row = QHBoxLayout()
            row.setSpacing(sp(12))
            num = QLabel(str(n))
            num.setObjectName("step-num")
            num.setAlignment(Qt.AlignmentFlag.AlignCenter)
            row.addWidget(num, alignment=Qt.AlignmentFlag.AlignTop)
            body = QLabel(text)
            body.setWordWrap(True)
            row.addWidget(body, stretch=1)
            root.addLayout(row)

        note = QLabel(PS_NOTE)
        note.setObjectName("row-sub")
        note.setWordWrap(True)
        root.addSpacing(sp(6))
        root.addWidget(note)

        code_row = QHBoxLayout()
        code_row.setSpacing(sp(10))
        code = QLabel(MANUAL_PS_FIX)
        code.setObjectName("code-box")
        code.setWordWrap(True)
        code.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        # Word-wrapped labels under-report their height once QSS padding
        # is added; reserve the three wrapped lines explicitly.
        code.setMinimumHeight(sp(88))
        code_row.addWidget(code, stretch=1)
        copy_btn = QPushButton("Copy")
        copy_btn.setObjectName("ghost")
        copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        copy_btn.clicked.connect(
            lambda: QApplication.clipboard().setText(MANUAL_PS_FIX))
        code_row.addWidget(copy_btn, alignment=Qt.AlignmentFlag.AlignTop)
        root.addLayout(code_row)

        root.addSpacing(sp(10))
        foot = QHBoxLayout()
        foot.setSpacing(sp(10))
        sound_btn = QPushButton("Open Sound Settings")
        sound_btn.setObjectName("ghost")
        sound_btn.clicked.connect(lambda: _open_sound_settings())
        foot.addWidget(sound_btn)
        cable_btn = QPushButton("Install VB-Cable")
        cable_btn.setObjectName("primary")
        cable_btn.clicked.connect(
            lambda: _on_install_vb_cable(self, cable_btn))
        foot.addWidget(cable_btn)
        foot.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.setObjectName("ghost")
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.accept)
        foot.addWidget(close_btn)
        root.addLayout(foot)
        self.cable_btn = cable_btn


def show_vb_cable_error(parent, error_message: str) -> None:
    """Show a blocking modal with manual routing steps.

    Always modal (even when a tray icon exists) because processing
    cannot start without VB-Cable routing.
    """
    VbCableDialog(parent, error_message).exec()


def _on_install_vb_cable(parent, button) -> None:
    """Install the vendored VB-Cable driver, or fall back to the website."""
    try:
        from ...backends.platform.windows import (
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
