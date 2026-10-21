"""
Poise Setup - the four screens.

Each page is self-contained: it paints its own header, body and action
row, and reports intent through signals. Nothing here runs an installer;
window.py owns the state machine.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QSizePolicy,
    QVBoxLayout, QWidget,
)

from . import brand, core
from .widgets import (
    Badge, Check, ElidedLabel, Progress, StepRow, heading_font, ui_font,
)


def _label(text: str, font: QFont, name: str = "", wrap: bool = False) -> QLabel:
    label = QLabel(text)
    if name:
        label.setObjectName(name)
    label.setFont(font)
    if wrap:
        label.setWordWrap(True)
        label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
    return label


def _chip(text: str, foreground: str, background: str) -> QLabel:
    chip = QLabel(text)
    chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
    chip.setFixedHeight(20)
    chip.setStyleSheet(
        "QLabel {"
        f" color: {foreground};"
        f" background-color: {background};"
        " border-radius: 4px;"
        " padding: 0 8px;"
        " font-size: 9px;"
        " font-weight: 700;"
        "}")
    return chip


class Page(QWidget):
    """Common rhythm: header, body, stretch, action row.

    Pages reach GUTTER px past the text column on the top and left (the
    window's margins are smaller by as much), so an outcome badge's halo
    has room to glow without pushing the text column out of line.
    """

    GUTTER = Badge.BLEED

    def __init__(self, parent=None):
        super().__init__(parent)
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._outer.setSpacing(0)
        self.body = QVBoxLayout()
        self.body.setContentsMargins(self.GUTTER, self.GUTTER, 0, 0)
        self.body.setSpacing(0)
        self._outer.addLayout(self.body, 1)

    def hero(self, widget: QWidget) -> None:
        """Place a badge in the gutter, above the text column."""
        self.body.setContentsMargins(self.GUTTER, 0, 0, 0)
        self._outer.insertWidget(0, widget, 0, Qt.AlignmentFlag.AlignLeft)
        self._outer.insertSpacing(1, 4)

    def header(self, eyebrow: str, title: str, subtitle: str):
        self.body.addWidget(_label(eyebrow, ui_font(10, QFont.Weight.DemiBold,
                                                    spacing=2.2), "eyebrow"))
        self.body.addSpacing(9)
        title_label = _label(title, heading_font(30), "display")
        self.body.addWidget(title_label)
        self.body.addSpacing(7)
        subtitle_label = _label(subtitle, ui_font(13), "sub", wrap=True)
        self.body.addWidget(subtitle_label)
        self.body.addSpacing(24)
        return title_label, subtitle_label

    def actions(self, *buttons, note: QLabel = None):
        self.body.addStretch(1)
        row = QHBoxLayout()
        row.setSpacing(10)
        if note is not None:
            row.addWidget(note, 1)
            row.addStretch(1)
        else:
            row.addStretch(1)
        for button in buttons:
            row.addWidget(button)
        self.body.addLayout(row)

    def focus_primary(self) -> None:
        """Give the page's main action the keyboard when it appears."""


def _button(text: str, kind: str = "ghost") -> QPushButton:
    button = QPushButton(text)
    button.setObjectName(kind)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


#: Status chips: the app's colour-at-14% chips (QFrame#err-chip).
VB_AUDIO_URL = "https://vb-audio.com/Cable/"


def open_url(url: str) -> None:
    """Open a link in the user's browser.

    Setup runs elevated, and a browser started from it would run as
    administrator too. On Windows the link goes through explorer.exe,
    which hands it to the user's own (unelevated) shell instead.
    """
    import subprocess
    import sys
    if sys.platform == "win32":
        try:
            subprocess.Popen(["explorer.exe", url])
            return
        except OSError:
            pass
    from PyQt6.QtCore import QUrl
    from PyQt6.QtGui import QDesktopServices
    QDesktopServices.openUrl(QUrl(url))


READY_FG = brand.PALETTE["success"]
READY_BG = brand.SUCCESS_CHIP


class WelcomePage(Page):
    """Where to install, what will be installed, and the two ways out."""

    browse_clicked = pyqtSignal()
    install_clicked = pyqtSignal()
    cancel_clicked = pyqtSignal()

    def __init__(self, target_dir: str, existing: core.Existing | None = None,
                 cable: bool | None = None, parent=None):
        super().__init__(parent)

        if existing:
            title = "Update Poise"
            installed = (f"Poise {existing.version}" if existing.version
                         else "Poise")
            subtitle = (f"{installed} is already installed. "
                        "Setup replaces its files in place.")
        else:
            title = "Install Poise"
            subtitle = ("Real-time voice isolation for everything your PC "
                        "plays, with no audio ever leaving it.")
        self.heading, self.subtitle = self.header("POISE SETUP", title, subtitle)

        self.body.addWidget(self._location_card(target_dir))
        self.body.addSpacing(14)

        self.shortcut = Check("Create a desktop shortcut")
        self.shortcut.setChecked(True)
        self.shortcut.setFont(ui_font(12.5))
        self.body.addWidget(self.shortcut)

        self.body.addSpacing(16)
        self.body.addWidget(self._driver_card(cable))

        self.note = _label("", ui_font(11), "warning", wrap=True)
        self.note.hide()

        self.install_button = _button("Install" if not existing else "Update",
                                      "primary")
        self.install_button.setDefault(True)
        self.install_button.setMinimumWidth(128)
        self.install_button.clicked.connect(self.install_clicked)

        cancel = _button("Cancel")
        cancel.clicked.connect(self.cancel_clicked)

        self.actions(cancel, self.install_button, note=self.note)

    # -- body pieces -------------------------------------------------------

    def _location_card(self, target_dir: str) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        box = QVBoxLayout(card)
        box.setContentsMargins(18, 14, 14, 15)
        box.setSpacing(7)

        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(_label("Install location", ui_font(12.5, QFont.Weight.DemiBold),
                             "card-title"))
        top.addStretch(1)
        change = QPushButton("Change...")
        change.setObjectName("tool")
        change.setCursor(Qt.CursorShape.PointingHandCursor)
        change.clicked.connect(self.browse_clicked)
        top.addWidget(change)
        box.addLayout(top)

        self.dir_label = ElidedLabel(target_dir)
        box.addWidget(self.dir_label)

        box.addWidget(_label("Installed for all users of this PC.",
                             ui_font(11), "small"))
        return card

    def _driver_card(self, cable: bool | None) -> QFrame:
        card = QFrame()
        card.setObjectName("notice")
        box = QHBoxLayout(card)
        box.setContentsMargins(16, 13, 16, 13)
        box.setSpacing(13)

        # The app's icon chip: the secondary colour on its 16% tint.
        dot = QLabel("i")
        dot.setObjectName("chip")
        dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dot.setFixedSize(22, 22)
        box.addWidget(dot, 0, Qt.AlignmentFlag.AlignTop)

        texts = QVBoxLayout()
        texts.setSpacing(4)
        texts.addWidget(_label("VB-Cable audio driver",
                               ui_font(12, QFont.Weight.DemiBold), "notice-title"))
        if cable is True:
            detail = ("CABLE Input was found on this PC. Setup reuses the "
                      "existing driver.")
            state = ("READY", READY_FG, READY_BG)
        elif cable is False:
            detail = ("Poise captures system audio through this virtual cable. "
                      "Setup installs it quietly - a reboot may be needed.")
            state = ("BUNDLED", READY_FG, READY_BG)
        else:
            detail = ("Poise captures system audio through this virtual cable. "
                      "Setup checks for it and installs it only when missing.")
            state = ("AUTOMATIC", brand.PALETTE["badge_fg"], brand.PALETTE["badge_bg"])
        self.driver_detail = _label(detail, ui_font(11.5), "notice-sub", wrap=True)
        texts.addWidget(self.driver_detail)

        # VB-Audio's terms ask for this credit; the same text is in
        # installer/windows/vbcable-notice.txt.
        accent = brand.PALETTE["accent"]
        self.driver_credit = _label(
            "Donationware by VB-Audio Software · donations welcome at "
            # nowrap: the link moves to the next line whole, never split.
            '<span style="white-space: nowrap;">'
            f'<a href="{VB_AUDIO_URL}" style="color: {accent};'
            ' text-decoration: none;">vb-audio.com/Cable</a></span>',
            ui_font(11), "small", wrap=True)
        self.driver_credit.setTextFormat(Qt.TextFormat.RichText)
        self.driver_credit.setTextInteractionFlags(
            Qt.TextInteractionFlag.LinksAccessibleByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByKeyboard)
        self.driver_credit.linkActivated.connect(open_url)
        texts.addSpacing(2)
        texts.addWidget(self.driver_credit)
        box.addLayout(texts, 1)
        box.addWidget(_chip(*state), 0, Qt.AlignmentFlag.AlignTop)
        return card

    # -- state -------------------------------------------------------------

    def target_dir(self) -> str:
        return self.dir_label.text()

    def set_target_dir(self, path: str) -> None:
        self.dir_label.setText(path)

    def desktop_icon(self) -> bool:
        return self.shortcut.isChecked()

    def set_note(self, text: str) -> None:
        self.note.setText(text)
        self.note.setVisible(bool(text))

    def set_installing(self, installing: bool) -> None:
        self.install_button.setEnabled(not installing)

    def focus_primary(self) -> None:
        self.install_button.setFocus()


class ProgressPage(Page):
    """The run itself: four phases, one bar, no cancel while copying."""

    STEPS = (
        ("prepare", "Preparing setup"),
        ("files", "Copying program files"),
        ("driver", "Configuring audio"),
        ("finish", "Finishing up"),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.header("INSTALLING", "Installing Poise",
                    "This usually takes less than a minute.")

        self.rows = {}
        for key, text in self.STEPS:
            row = StepRow(text)
            self.rows[key] = row
            self.body.addWidget(row)

        self.body.addSpacing(20)
        self.bar = Progress()
        self.body.addWidget(self.bar)
        self.body.addSpacing(10)
        self.detail = _label("Starting setup...", ui_font(11.5), "card-sub", wrap=True)
        self.body.addWidget(self.detail)

        self.note = _label("Please keep this window open.",
                           ui_font(11), "small", wrap=True)
        self.body.addStretch(1)
        self.body.addWidget(self.note)

    def reset(self) -> None:
        for key, _ in self.STEPS:
            self.rows[key].set_state(StepRow.PENDING)
        self.bar.set_value(0)
        self.detail.setText("Starting setup...")
        self.note.setText("Please keep this window open.")

    def set_phase(self, name: str) -> None:
        if name not in self.rows:
            return
        index = [key for key, _ in self.STEPS].index(name)
        for position, (key, _) in enumerate(self.STEPS):
            row = self.rows[key]
            if position < index:
                # Keep what the row already learned ("already present", ...).
                row.set_state(StepRow.DONE, row.detail())
            elif position == index:
                row.set_state(StepRow.ACTIVE)
            else:
                row.set_state(StepRow.PENDING)
        self.detail.setText({
            "prepare": "Preparing setup...",
            "files": "Copying Poise into place...",
            "driver": "Configuring audio...",
            "finish": "Finishing up...",
        }.get(name, ""))

    def set_driver(self, event: str) -> None:
        text = core.driver_text(event)
        if text:
            self.detail.setText(text)
        if event == "skip":
            self.rows["driver"].set_state(StepRow.DONE, "already present")
        elif event == "failed":
            self.rows["driver"].set_state(StepRow.DONE, "not installed")
        elif event in ("done", "reboot"):
            self.rows["driver"].set_state(
                StepRow.DONE, "reboot needed" if event == "reboot" else "")
            for key in ("prepare", "files"):
                self.rows[key].set_state(StepRow.DONE)

    def set_value(self, value: float) -> None:
        self.bar.set_value(value)

    def complete(self) -> None:
        for key, _ in self.STEPS:
            self.rows[key].set_state(StepRow.DONE)
        self.bar.set_value(100)
        self.detail.setText("Done.")

    def set_note(self, text: str) -> None:
        self.note.setText(text)


class FinishPage(Page):
    """Success: launch, and restart when the driver asked for one."""

    done_clicked = pyqtSignal(bool, bool)   # launch, restart

    def __init__(self, parent=None):
        super().__init__(parent)

        self.badge = Badge("success")
        self.hero(self.badge)

        self.heading, self.subtitle = self.header(
            "COMPLETE", "Poise is installed",
            "Everything is in place.")

        self.path = _label("", ui_font(11.5), "small", wrap=True)
        self.body.addWidget(self.path)
        self.body.addSpacing(20)

        self.launch = Check("Launch Poise now")
        self.launch.setChecked(True)
        self.launch.setFont(ui_font(12.5))
        self.body.addWidget(self.launch)

        self.reboot_frame = QFrame()
        self.reboot_frame.setObjectName("warn")
        box = QVBoxLayout(self.reboot_frame)
        box.setContentsMargins(16, 13, 16, 13)
        box.setSpacing(6)
        box.addWidget(_label("A restart is needed to activate the audio driver.",
                             ui_font(12, QFont.Weight.DemiBold), "warn-title",
                             wrap=True))
        box.addWidget(_label(
            "VB-Cable only appears after Windows restarts. Poise can be "
            "launched afterwards.", ui_font(11.5), "card-sub", wrap=True))
        self.restart = Check("Restart Windows now")
        self.restart.setChecked(True)
        self.restart.setFont(ui_font(12.5))
        box.addWidget(self.restart)
        self.reboot_frame.hide()
        self.body.addSpacing(14)
        self.body.addWidget(self.reboot_frame)

        hint = _label("Start Poise from the Start menu or the desktop "
                      "shortcut, then press the power button when you want "
                      "isolation.", ui_font(11.5), "small", wrap=True)
        self.body.addSpacing(18)
        self.body.addWidget(hint)

        self.finish_button = _button("Finish", "primary")
        self.finish_button.setMinimumWidth(128)
        self.finish_button.setDefault(True)
        self.finish_button.clicked.connect(self._emit)
        self.actions(self.finish_button)

    def focus_primary(self) -> None:
        self.finish_button.setFocus()

    def configure(self, target_dir: str, reboot: bool = False) -> None:
        self.path.setText(f"Installed in {target_dir}")
        self.reboot_frame.setVisible(reboot)
        self.restart.setChecked(reboot)
        self.launch.setChecked(not reboot)
        self.launch.setEnabled(not reboot)

    def _emit(self) -> None:
        self.done_clicked.emit(self.launch.isChecked(), self.restart.isChecked())


class ErrorPage(Page):
    """Failure: what happened, the end of the log, and a way to retry."""

    retry_clicked = pyqtSignal()
    close_clicked = pyqtSignal()
    open_log_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.badge = Badge("error")
        self.hero(self.badge)

        self.heading, self.subtitle = self.header(
            "SETUP FAILED", "Setup could not finish",
            "No changes were made to your system.")

        self.log = QPlainTextEdit()
        self.log.setObjectName("log")
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(220)
        self.log.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.body.addWidget(self.log)
        self.body.addSpacing(8)

        self.show_log = QPushButton("Show log file")
        self.show_log.setObjectName("tool")
        self.show_log.setCursor(Qt.CursorShape.PointingHandCursor)
        self.show_log.clicked.connect(self.open_log_clicked)
        self.body.addWidget(self.show_log, 0, Qt.AlignmentFlag.AlignLeft)

        self.retry_button = _button("Try again", "primary")
        self.retry_button.setMinimumWidth(128)
        self.retry_button.setDefault(True)
        self.retry_button.clicked.connect(self.retry_clicked)
        close = _button("Close")
        close.clicked.connect(self.close_clicked)
        self.actions(close, self.retry_button)

    def focus_primary(self) -> None:
        self.retry_button.setFocus()

    def set_error(self, message: str, log_text: str) -> None:
        self.subtitle.setText(message or "The installer reported an error.")
        self.log.setPlainText(log_text or "(the log is empty)")
        self.show_log.setVisible(bool(log_text))
