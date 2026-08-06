"""Main window: page stack, navigation, and the flows that coordinate
workers with pages (scan, actions, undo, unsubscribe). This is the
composition root — it imports every page and worker, but no page imports it
back (they only call methods on `self.main`, passed in at construction), so
there's no import cycle.
"""

import sys

from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QWidget, QStackedWidget, QVBoxLayout, QGraphicsOpacityEffect,
)
from qfluentwidgets import (
    setTheme, Theme, setThemeColor, isDarkTheme,
    InfoBar, InfoBarPosition, MessageBox,
)

import gmail_backend as gb
from ui.workers import ScanWorker, ActionWorker, UnsubscribeWorker
from ui.pages.welcome import WelcomePage
from ui.pages.connect import ConnectPage
from ui.pages.scan import ScanPage
from ui.pages.dashboard import DashboardPage
from ui.pages.senders import SendersPage
from ui.pages.finish import FinishPage


class GmailCleaner(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("Root")
        self.setWindowTitle("Gmail Inbox Cleaner")
        self.resize(1020, 700)
        self.setMinimumSize(900, 600)

        self.addr = self.pwd = ""
        self.remember_choice = False
        self.goal = "tidy"
        self.original_total = 0
        self.senders = {}
        self.summary = {}
        self.scan_worker = None
        self.action_worker = None
        self.session = {"removed": 0, "freed": 0, "senders": 0}
        self.last_action = None
        self._anim = None

        self.stack = QStackedWidget()
        self.welcome_page = WelcomePage(self)
        self.connect_page = ConnectPage(self)
        self.scan_page = ScanPage(self)
        self.dash_page = DashboardPage(self)
        self.senders_page = SendersPage(self)
        self.finish_page = FinishPage(self)
        for p in (self.welcome_page, self.connect_page, self.scan_page,
                  self.dash_page, self.senders_page, self.finish_page):
            self.stack.addWidget(p)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.stack)
        self._apply_bg()

    def _apply_bg(self):
        bg = "#1f1f1f" if isDarkTheme() else "#f4f5f7"
        self.setStyleSheet(f"#Root {{ background: {bg}; }}")

    def _switch(self, page):
        """Switch stacked page with a short fade-in."""
        self.stack.setCurrentWidget(page)
        eff = QGraphicsOpacityEffect(page)
        page.setGraphicsEffect(eff)
        anim = QPropertyAnimation(eff, b"opacity", self)
        anim.setDuration(180)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.finished.connect(lambda: page.setGraphicsEffect(None))
        anim.start()
        self._anim = anim

    def begin(self, goal):
        """Called from the Welcome page after the user picks a goal."""
        self.goal = goal
        self._switch(self.connect_page)

    # -------- scan flow
    def start_scan(self, addr, pwd):
        self.addr, self.pwd = addr, pwd
        self._switch(self.scan_page)
        self.scan_page.update_progress("Connecting to Gmail…", 0, 0)
        self.scan_worker = ScanWorker(addr, pwd)
        self.scan_worker.progress.connect(self.scan_page.update_progress)
        self.scan_worker.done.connect(self._scan_done)
        self.scan_worker.failed.connect(self._scan_failed)
        self.scan_worker.start()

    def _scan_done(self, res):
        # Only now, with a confirmed-working connection, act on the
        # remember-me choice — never persist (or wipe) a credential we
        # haven't actually verified works.
        gb.save_last_address(self.addr)
        if self.remember_choice:
            gb.remember_password(self.addr, self.pwd)
        else:
            gb.forget_password(self.addr)

        self.senders = res["senders"]
        self.summary = gb.summarize(self.senders)
        self.original_total = self.summary["total_mail"]
        self.session = {"removed": 0, "freed": 0, "senders": 0}
        self.last_action = None
        self.senders_page.set_undo_enabled(False)
        self.dash_page.populate(self.summary)
        self._switch(self.dash_page)
        InfoBar.success(
            "Scan complete",
            f"Found {self.summary['total_mail']:,} emails from "
            f"{self.summary['total_senders']:,} senders.",
            parent=self, position=InfoBarPosition.TOP, duration=4000)

    def _scan_failed(self, msg):
        self._switch(self.connect_page)
        InfoBar.error(
            "Couldn't connect",
            "Check your address and App Password. App Passwords need 2-Step "
            "Verification turned on.\n\n" + msg,
            parent=self, position=InfoBarPosition.TOP, duration=8000)

    # -------- navigation
    def goto_senders(self, check_bulk=False):
        self.senders_page.populate(self.senders)
        if check_bulk:
            self.senders_page._select_bulk()
        self._switch(self.senders_page)

    def goto_dashboard(self):
        self.summary = gb.summarize(self.senders)
        self.dash_page.populate(self.summary)
        self._switch(self.dash_page)

    def goto_finish(self):
        pct = round(100 * self.session["removed"] / self.original_total) if self.original_total else 0
        stats = (self.session["removed"], self.session["freed"],
                 self.session["senders"], self.summary.get("protected_count", 0), pct)
        self.finish_page.populate(stats)
        self._switch(self.finish_page)

    # -------- one-click preset (from dashboard)
    def run_preset(self, cat):
        prs = [r for r in self.senders.values()
               if r["category"] == cat and not r.get("protected")]
        if not prs:
            return
        targets = [r["email"] for r in prs]
        mails = sum(r["count"] for r in prs)
        size = gb.human_size(sum(r["bytes"] for r in prs))
        box = MessageBox(
            f"Clean {cat}?",
            f"{mails:,} emails from {len(prs)} senders ({size}) will move to Trash.\n\n"
            "They're recoverable in Gmail for 30 days.", self)
        box.yesButton.setText("Clean")
        if not box.exec():
            return
        uids = [u for r in prs for u in r["uids"]]
        self.run_action("trash", uids, targets)

    def run_archive_old(self):
        old = [r for r in self.senders.values()
               if r["is_bulk"] and not r.get("protected")
               and gb._months_since(r["last_date"]) >= 24]
        if not old:
            return
        targets = [r["email"] for r in old]
        mails = sum(r["count"] for r in old)
        box = MessageBox(
            "Archive old mail?",
            f"{mails:,} emails from {len(old)} senders inactive for 2+ years will "
            "leave your inbox (kept in All Mail — nothing deleted).", self)
        box.yesButton.setText("Archive")
        if not box.exec():
            return
        uids = [u for r in old for u in r["uids"]]
        self.run_action("archive", uids, targets)

    # -------- unsubscribe (v1.3)
    def run_unsubscribe(self, targets):
        recs = [self.senders[e] for e in targets if e in self.senders]
        oneclick = [r for r in recs if r.get("unsub_oneclick") and r.get("unsub_url")]
        browser = [r for r in recs
                   if r not in oneclick and (r.get("unsub_url") or r.get("unsub_mailto"))]
        if not oneclick and not browser:
            InfoBar.warning("No unsubscribe link",
                            "None of the selected senders offer an unsubscribe option.",
                            parent=self, position=InfoBarPosition.TOP, duration=4000)
            return

        parts = []
        if oneclick:
            parts.append(f"• {len(oneclick)} will unsubscribe automatically (1-click)")
        if browser:
            parts.append(f"• {len(browser)} will open in your browser "
                         f"({len(browser)} tab{'s' if len(browser) != 1 else ''}) to finish")
        detail = "\n".join(parts)
        if len(browser) > 12:
            detail += "\n\n⚠ That's a lot of browser tabs to open at once."
        box = MessageBox(
            f"Unsubscribe from {len(oneclick) + len(browser)} senders?",
            detail + "\n\nTip: only unsubscribe from senders you recognize — for spam, "
            "clicking unsubscribe can confirm your address. This doesn't delete existing "
            "emails; Trash them separately if you like.", self)
        box.yesButton.setText("Unsubscribe")
        if not box.exec():
            return

        for r in browser:
            QDesktopServices.openUrl(QUrl(r.get("unsub_url") or r.get("unsub_mailto")))

        if oneclick:
            urls = [r["unsub_url"] for r in oneclick]
            self.unsub_worker = UnsubscribeWorker(urls)
            self.unsub_worker.done.connect(self._unsub_done)
            self.unsub_worker.failed.connect(
                lambda m: InfoBar.error("Unsubscribe error", m, parent=self,
                                        position=InfoBarPosition.TOP, duration=6000))
            self.unsub_worker.start()
            InfoBar.info("Unsubscribing…",
                         f"Sending {len(urls)} one-click unsubscribe request"
                         f"{'s' if len(urls) != 1 else ''}.",
                         parent=self, position=InfoBarPosition.TOP, duration=2500)
        elif browser:
            InfoBar.success("Opened in browser",
                            f"Finish unsubscribing in the {len(browser)} tab"
                            f"{'s' if len(browser) != 1 else ''} that opened.",
                            parent=self, position=InfoBarPosition.TOP, duration=5000)

    def _unsub_done(self, ok, attempted):
        InfoBar.success("Unsubscribed",
                        f"{ok} of {attempted} one-click unsubscribes succeeded."
                        + (" Some may take a day or two to take effect." if ok else ""),
                        parent=self, position=InfoBarPosition.TOP, duration=6000)

    # -------- action flow
    def run_action(self, mode, uids, targets):
        self._pending = {
            "mode": mode, "targets": targets, "uids": uids,
            "records": {e: self.senders[e] for e in targets if e in self.senders},
        }
        self.action_worker = ActionWorker(self.addr, self.pwd, uids, mode)
        self.action_worker.done.connect(self._action_done)
        self.action_worker.failed.connect(self._action_failed)
        self.action_worker.start()
        InfoBar.info("Working…", f"{'Trashing' if mode=='trash' else 'Archiving'} "
                     f"{len(uids):,} emails.", parent=self,
                     position=InfoBarPosition.TOP, duration=2000)

    def _action_done(self, n):
        p = self._pending
        mode, targets, records = p["mode"], p["targets"], p["records"]
        freed = sum(r["bytes"] for r in records.values())
        self.session["removed"] += n
        self.session["freed"] += freed
        self.session["senders"] += len(targets)
        self.last_action = {"mode": mode, "uids": p["uids"], "records": records}
        self.senders_page.set_undo_enabled(True)

        for e in targets:
            self.senders.pop(e, None)
        self.senders_page.remove_senders(targets)
        self.senders_page._set_busy(False)
        self.summary = gb.summarize(self.senders)
        self.dash_page.populate(self.summary)

        word = "moved to Trash" if mode == "trash" else "archived"
        InfoBar.success("Done", f"{n:,} emails {word}. "
                        f"{len(self.senders):,} senders left in your inbox.",
                        parent=self, position=InfoBarPosition.TOP, duration=5000)

    def _action_failed(self, msg):
        self.senders_page._set_busy(False)
        InfoBar.error("Action failed", msg, parent=self,
                      position=InfoBarPosition.TOP, duration=8000)

    # -------- undo
    def run_undo(self):
        if not self.last_action:
            return
        self.senders_page.set_undo_enabled(False)
        la = self.last_action
        self.action_worker = ActionWorker(self.addr, self.pwd, la["uids"],
                                          la["mode"], undo=True)
        self.action_worker.done.connect(self._undo_done)
        self.action_worker.failed.connect(self._undo_failed)
        self.action_worker.start()
        InfoBar.info("Undoing…", "Restoring those emails to your inbox.",
                     parent=self, position=InfoBarPosition.TOP, duration=2000)

    def _undo_done(self, n):
        la = self.last_action
        records = la["records"]
        for e, rec in records.items():
            self.senders[e] = rec
        self.session["removed"] = max(0, self.session["removed"] - n)
        self.session["freed"] = max(0, self.session["freed"] - sum(r["bytes"] for r in records.values()))
        self.session["senders"] = max(0, self.session["senders"] - len(records))
        self.last_action = None
        self.summary = gb.summarize(self.senders)
        self.dash_page.populate(self.summary)
        self.senders_page.populate(self.senders)
        InfoBar.success("Undone", f"{n:,} emails restored to your inbox.",
                        parent=self, position=InfoBarPosition.TOP, duration=4000)

    def _undo_failed(self, msg):
        self.senders_page.set_undo_enabled(True)
        InfoBar.error("Undo failed", msg, parent=self,
                      position=InfoBarPosition.TOP, duration=8000)


def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    setTheme(Theme.LIGHT)
    setThemeColor("#0067C0")
    win = GmailCleaner()
    win.show()
    sys.exit(app.exec())
