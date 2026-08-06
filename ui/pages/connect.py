"""Connect page — progressive disclosure (Connect button first, then
credentials), the App Password help dialog, Remember me, and the opt-in
diagnostics-logging toggle.
"""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout
from qfluentwidgets import (
    SimpleCardWidget, LargeTitleLabel, SubtitleLabel, BodyLabel,
    PrimaryPushButton, LineEdit, PasswordLineEdit, CheckBox, HyperlinkButton,
    MessageBox, InfoBar, InfoBarPosition, FluentIcon as FIF,
)

import gmail_backend as gb


class ConnectPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        outer = QVBoxLayout(self)
        outer.addStretch(1)

        card = SimpleCardWidget()
        card.setMaximumWidth(560)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(44, 40, 44, 40)
        cl.setSpacing(10)

        title = LargeTitleLabel("Gmail Inbox Cleaner")
        subtitle = SubtitleLabel("Let's tidy up your inbox — together.")
        subtitle.setStyleSheet("color: #888;")
        note = BodyLabel(
            "This app only looks at who emailed you — never the contents of your "
            "messages. Your password is only stored on this computer if you "
            "choose \"Remember me\" below — and even then, in Windows' own "
            "encrypted credential store, never as plain text.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #999;")
        cl.addWidget(title)
        cl.addWidget(subtitle)
        cl.addSpacing(6)
        cl.addWidget(note)
        cl.addSpacing(14)

        # progressive disclosure: big Connect button first
        self.connect_btn = PrimaryPushButton("Connect Gmail")
        self.connect_btn.setIcon(FIF.MAIL)
        self.connect_btn.setFixedHeight(40)
        self.connect_btn.clicked.connect(self._reveal)
        cl.addWidget(self.connect_btn)

        # hidden credentials group
        self.creds = QWidget()
        cg = QVBoxLayout(self.creds)
        cg.setContentsMargins(0, 0, 0, 0)
        cg.setSpacing(10)
        self.email = LineEdit()
        self.email.setPlaceholderText("your.name@gmail.com")
        self.email.setClearButtonEnabled(True)
        self.pwd = PasswordLineEdit()
        self.pwd.setPlaceholderText("16-character App Password")
        cg.addWidget(BodyLabel("Gmail address"))
        cg.addWidget(self.email)
        cg.addWidget(BodyLabel("App Password"))
        cg.addWidget(self.pwd)

        self.remember_check = CheckBox("Remember me on this computer")
        self.remember_check.setToolTip(
            "Stores your App Password in Windows' own encrypted credential "
            "store (Credential Manager) — the same place Windows keeps saved "
            "network and website passwords. Never written as plain text.")
        self.remember_check.setAccessibleName(
            "Remember me on this computer, stores password in Windows Credential Manager")
        cg.addWidget(self.remember_check)

        # prefill from a prior session, if any (email is non-secret; password
        # only comes back if it was actually remembered last time)
        last_addr = gb.load_last_address()
        if last_addr:
            self.email.setText(last_addr)
            saved_pwd = gb.recall_password(last_addr)
            if saved_pwd:
                self.pwd.setText(saved_pwd)
                self.remember_check.setChecked(True)

        self.diag_check = CheckBox("Save diagnostic logs (advanced)")
        self.diag_check.setToolTip(
            "Off by default. When on, writes a technical log to help diagnose "
            "problems if something goes wrong — never your password, and never "
            "email contents. File: %LOCALAPPDATA%\\GmailCleaner\\logs\\")
        self.diag_check.setAccessibleName(
            "Save diagnostic logs, advanced option, off by default")
        cg.addWidget(self.diag_check)

        row = QHBoxLayout()
        help_btn = HyperlinkButton("", "What's an App Password?")
        help_btn.clicked.connect(self._help)
        row.addWidget(help_btn)
        row.addStretch(1)
        self.scan_btn = PrimaryPushButton("Scan my inbox")
        self.scan_btn.setIcon(FIF.SEARCH)
        self.scan_btn.setFixedHeight(38)
        self.scan_btn.clicked.connect(self._go)
        row.addWidget(self.scan_btn)
        cg.addSpacing(4)
        cg.addLayout(row)
        self.creds.setVisible(False)
        cl.addWidget(self.creds)

        hbox = QHBoxLayout()
        hbox.addStretch(1)
        hbox.addWidget(card)
        hbox.addStretch(1)
        outer.addLayout(hbox)
        outer.addStretch(1)

    def _reveal(self):
        self.connect_btn.setVisible(False)
        self.creds.setVisible(True)
        self.email.setFocus()

    def _help(self):
        MessageBox(
            "How to get a Gmail App Password",
            "An App Password is a 16-character code that lets this app read your "
            "inbox without your real password.\n\n"
            "1.  Turn ON 2-Step Verification:\n"
            "     myaccount.google.com  ›  Security  ›  2-Step Verification\n\n"
            "2.  Go to:  myaccount.google.com/apppasswords\n\n"
            "3.  Name it \"Inbox Cleaner\" and click Create.\n\n"
            "4.  Copy the 16-letter code and paste it here. Spaces don't matter.\n\n"
            "You can delete this code anytime from the same page.",
            self.window()).exec()

    def _go(self):
        addr = self.email.text().strip()
        pwd = self.pwd.text().strip()
        if not addr or not pwd:
            InfoBar.warning("Missing info", "Enter your Gmail address and App Password.",
                            parent=self.window(), position=InfoBarPosition.TOP, duration=3000)
            return
        log_path = gb.enable_diagnostics(self.diag_check.isChecked())
        if self.diag_check.isChecked():
            InfoBar.info("Diagnostics on", f"Logging to {log_path}",
                         parent=self.window(), position=InfoBarPosition.TOP, duration=4000)
        # Only actually persist/forget the credential once the connection is
        # confirmed to work (see GmailCleaner._scan_done) — never on a typo.
        self.main.remember_choice = self.remember_check.isChecked()
        self.main.start_scan(addr, pwd)
