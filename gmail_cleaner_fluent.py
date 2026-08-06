"""
Gmail Inbox Cleaner — Fluent edition
====================================
A Windows-11-styled desktop app (PySide6 + QFluentWidgets) built on top of the
gmail_backend engine. Flow: Connect -> Scan -> Summary dashboard -> Sender cards.

The backend (IMAP scanning, safety model, actions) is unchanged; this file is
purely the experience layer: progressive disclosure, a summary-first dashboard,
sender cards, staged progress, friendly copy.
"""

import sys
import datetime

from PySide6.QtCore import Qt, QThread, Signal, QPropertyAnimation, QEasingCurve, QUrl
from PySide6.QtGui import QFont, QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QWidget, QStackedWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QSpacerItem, QSizePolicy, QFrame, QButtonGroup,
    QGraphicsOpacityEffect,
)
from qfluentwidgets import (
    setTheme, Theme, setThemeColor, isDarkTheme,
    DisplayLabel, LargeTitleLabel, TitleLabel, SubtitleLabel, StrongBodyLabel,
    BodyLabel, CaptionLabel, PrimaryPushButton, PushButton, TransparentPushButton,
    HyperlinkButton, LineEdit, PasswordLineEdit, SearchLineEdit, CheckBox,
    SimpleCardWidget, CardWidget, ProgressBar, IndeterminateProgressRing,
    InfoBar, InfoBarPosition, MessageBox, PillPushButton, FlowLayout,
    SingleDirectionScrollArea, FluentIcon as FIF, TransparentToolButton,
)

import gmail_backend as gb

# ---------------------------------------------------------------- categories
CATEGORY_COLORS = {
    "Promotions":    "#C77700",
    "Shopping":      "#0E7C7B",
    "Social":        "#8764B8",
    "Finance":       "#107C10",
    "Travel":        "#0F6CBD",
    "Subscriptions": "#B146C2",
    "Notifications": "#6B6B6B",
    "Personal":      "#3A6EA5",
}
CATEGORY_ORDER = ["Promotions", "Subscriptions", "Social", "Notifications",
                  "Shopping", "Travel", "Finance", "Personal"]


def color_for(cat):
    return CATEGORY_COLORS.get(cat, "#6B6B6B")


def rgba(hex_color, alpha):
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"


def elide(text, n=44):
    return text if len(text) <= n else text[: n - 1] + "…"


def fmt_date(dt):
    if not dt:
        return "—"
    return dt.strftime("%b %Y")


# ------------------------------------------------------------------- workers
class ScanWorker(QThread):
    progress = Signal(str, int, int)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, addr, pwd):
        super().__init__()
        self.addr, self.pwd = addr, pwd
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            res = gb.scan(self.addr, self.pwd,
                          progress=lambda s, d, t: self.progress.emit(s, d, t),
                          should_stop=lambda: self._stop)
            self.done.emit(res)
        except Exception as e:
            self.failed.emit(str(e))


class ActionWorker(QThread):
    progress = Signal(int, int)
    done = Signal(int)
    failed = Signal(str)

    def __init__(self, addr, pwd, uids, mode, undo=False):
        super().__init__()
        self.addr, self.pwd, self.uids, self.mode = addr, pwd, uids, mode
        self.undo = undo

    def run(self):
        try:
            fn = gb.undo_action if self.undo else gb.do_action
            n = fn(self.addr, self.pwd, self.uids, self.mode,
                   progress=lambda d, t: self.progress.emit(d, t))
            self.done.emit(n)
        except Exception as e:
            self.failed.emit(str(e))


class UnsubscribeWorker(QThread):
    """Fires RFC 8058 one-click POSTs for senders that support them."""
    done = Signal(int, int)   # succeeded, attempted
    failed = Signal(str)

    def __init__(self, urls):
        super().__init__()
        self.urls = urls

    def run(self):
        try:
            ok = sum(1 for u in self.urls if gb.one_click_unsubscribe(u))
            self.done.emit(ok, len(self.urls))
        except Exception as e:
            self.failed.emit(str(e))


# ---------------------------------------------------------------- small bits
class Pill(QFrame):
    """Small rounded category tag."""
    def __init__(self, category, parent=None):
        super().__init__(parent)
        c = color_for(category)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lbl = CaptionLabel(category)
        lbl.setStyleSheet(
            f"background: {rgba(c, 0.16)}; color: {c}; border-radius: 9px; "
            f"padding: 2px 10px; font-weight: 600;")
        lay.addWidget(lbl)


def text_color():
    return "#f0f0f0" if isDarkTheme() else "#1c1c1c"


def stat_card(number, label, accent=None):
    card = SimpleCardWidget()
    card.setMinimumHeight(104)
    lay = QVBoxLayout(card)
    lay.setContentsMargins(20, 16, 20, 16)
    lay.setSpacing(2)
    num = DisplayLabel(str(number))
    num.setStyleSheet(f"font-size: 34px; font-weight: 700; "
                      f"color: {accent or text_color()};")
    cap = CaptionLabel(label)
    cap.setStyleSheet("color: #888;")
    lay.addWidget(num)
    lay.addWidget(cap)
    return card


def clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w:
            w.setParent(None)
            w.deleteLater()


# ---------------------------------------------------------- recommendations
SUGGESTION_COLORS = {
    "Move to Trash": "#C42B1C",
    "Archive":       "#9A6700",
    "Keep":          "#6B6B6B",
    "Protected":     "#107C10",
}


def stars_str(n):
    n = max(0, min(5, n))
    return "★" * n + "☆" * (5 - n)


def health_color(h):
    if h >= 80:
        return "#107C10"   # green
    if h >= 55:
        return "#9A6700"   # amber
    return "#C42B1C"       # red


# --------------------------------------------------------------- sender card
class SenderCard(CardWidget):
    def __init__(self, rec, on_toggle, parent=None):
        super().__init__(parent)
        self.email = rec["email"]
        self.rec = rec
        self.on_toggle = on_toggle
        self.protected = rec.get("protected", False)
        self.setMinimumHeight(74)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 10, 18, 10)
        lay.setSpacing(14)

        self.check = CheckBox()
        self.check.setEnabled(not self.protected)
        self.check.stateChanged.connect(self._changed)
        lay.addWidget(self.check, 0, Qt.AlignVCenter)

        mid = QVBoxLayout()
        mid.setSpacing(1)
        name = StrongBodyLabel(elide(rec["name"], 34))
        sub = CaptionLabel(elide(rec["email"], 40))
        sub.setStyleSheet("color: #8a8a8a;")
        rs = gb.reasons(rec)
        why = CaptionLabel(elide(" · ".join(rs[:2]), 52))
        why.setStyleSheet("color: #9a9a9a;")
        mid.addWidget(name)
        mid.addWidget(sub)
        mid.addWidget(why)
        lay.addLayout(mid)
        lay.addStretch(1)
        self.setToolTip("Why this rating: " + "; ".join(rs))
        self.setAccessibleName(
            f"{rec['name']}, {rec['count']} emails, {rec.get('suggestion','')}. "
            + ("Protected. " if self.protected else "")
            + "; ".join(rs))

        # recommendation block: stars + suggested action (or a protected lock)
        sugg = rec.get("suggestion", "Keep")
        col = SUGGESTION_COLORS.get(sugg, "#6B6B6B")
        rec_box = QVBoxLayout()
        rec_box.setSpacing(1)
        if self.protected:
            top = CaptionLabel("🔒 Protected")
            bottom = CaptionLabel("kept safe")
        else:
            top = CaptionLabel(stars_str(rec.get("stars", 1)))
            top.setStyleSheet(f"color: {col}; font-weight: 700; letter-spacing: 1px;")
            bottom = CaptionLabel(sugg)
        top.setAlignment(Qt.AlignRight)
        bottom.setAlignment(Qt.AlignRight)
        if self.protected:
            top.setStyleSheet(f"color: {col}; font-weight: 600;")
        bottom.setStyleSheet(f"color: {col};")
        rec_box.addWidget(top)
        rec_box.addWidget(bottom)
        lay.addLayout(rec_box)

        lay.addWidget(Pill(rec["category"]), 0, Qt.AlignVCenter)

        right = QVBoxLayout()
        right.setSpacing(1)
        cnt = StrongBodyLabel(f"{rec['count']} emails")
        cnt.setAlignment(Qt.AlignRight)
        meta = CaptionLabel(f"{gb.human_size(rec['bytes'])} · {fmt_date(rec['last_date'])}")
        meta.setAlignment(Qt.AlignRight)
        meta.setStyleSheet("color: #8a8a8a;")
        right.addWidget(cnt)
        right.addWidget(meta)
        lay.addLayout(right)

    def _changed(self):
        self.on_toggle(self.email, self.check.isChecked())

    def set_checked(self, on):
        if self.protected:
            return
        self.check.setChecked(on)

    def mousePressEvent(self, e):
        # click anywhere on the card toggles it (protected cards can't be picked)
        if not self.protected and not self.check.underMouse():
            self.check.toggle()
        super().mousePressEvent(e)


# ---------------------------------------------------------------- trust bar
TRUST_ITEMS = ["Headers only", "Recoverable 30 days",
               "Undo anytime", "Nothing permanent"]


def trust_bar():
    w = QWidget()
    w.setStyleSheet("background: transparent;")
    flow = FlowLayout(w, needAni=False)
    flow.setContentsMargins(0, 0, 0, 0)
    flow.setHorizontalSpacing(8)
    flow.setVerticalSpacing(8)
    for t in TRUST_ITEMS:
        c = CaptionLabel("✓ " + t)
        c.setStyleSheet("background: rgba(16,124,16,0.10); color: #107C10; "
                        "border-radius: 9px; padding: 3px 10px; font-weight: 600;")
        flow.addWidget(c)
    return w


GOALS = [
    ("tidy",        "Just tidy up",        "Clear the clutter, keep what matters",     FIF.BROOM),
    ("storage",     "Free up storage",     "Target the biggest, heaviest senders",     FIF.CLOUD),
    ("newsletters", "Remove newsletters",  "Subscriptions and marketing mail",          FIF.MAIL),
    ("archive",     "Archive old mail",    "Move old messages out without deleting",    FIF.FOLDER),
]


# ------------------------------------------------------------------- pages
class WelcomePage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        outer = QVBoxLayout(self)
        outer.addStretch(1)

        card = SimpleCardWidget()
        card.setMaximumWidth(620)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(48, 40, 48, 40)
        cl.setSpacing(10)

        cl.addWidget(LargeTitleLabel("Gmail Inbox Cleaner"))
        sub = SubtitleLabel("Let's make your inbox feel calm again.")
        sub.setStyleSheet("color: #888;")
        cl.addWidget(sub)
        note = BodyLabel("This app only looks at who emailed you — never the contents "
                         "of your messages. Your password stays on this computer.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #999;")
        cl.addWidget(note)
        cl.addSpacing(4)
        cl.addWidget(trust_bar())
        cl.addSpacing(14)

        cl.addWidget(StrongBodyLabel("What would you like to do?"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        for i, (key, title, desc, icon) in enumerate(GOALS):
            grid.addWidget(self._goal_card(key, title, desc, icon), i // 2, i % 2)
        cl.addLayout(grid)

        hbox = QHBoxLayout()
        hbox.addStretch(1)
        hbox.addWidget(card)
        hbox.addStretch(1)
        outer.addLayout(hbox)
        outer.addStretch(1)

    def _goal_card(self, key, title, desc, icon):
        btn = PushButton(f"  {title}")
        btn.setIcon(icon)
        btn.setMinimumHeight(58)
        btn.setToolTip(desc)
        btn.setAccessibleName(f"{title}. {desc}")
        if key == "tidy":
            btn = PrimaryPushButton(f"  {title}")
            btn.setIcon(icon)
            btn.setMinimumHeight(58)
            btn.setToolTip(desc)
            btn.setAccessibleName(f"{title} (recommended). {desc}")
        btn.clicked.connect(lambda _=False, k=key: self.main.begin(k))
        return btn


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
            "messages. Your password stays on this computer and is never saved.")
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
        self.main.start_scan(addr, pwd)


class ScanPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        lay = QVBoxLayout(self)
        lay.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        self.ring = IndeterminateProgressRing()
        self.ring.setFixedSize(64, 64)
        row.addWidget(self.ring)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addSpacing(18)
        self.stage = TitleLabel("Connecting to Gmail…")
        self.stage.setAlignment(Qt.AlignCenter)
        self.count = BodyLabel("")
        self.count.setAlignment(Qt.AlignCenter)
        self.count.setStyleSheet("color: #888;")
        lay.addWidget(self.stage)
        lay.addWidget(self.count)
        lay.addStretch(1)

    def update_progress(self, stage, done, total):
        self.stage.setText(stage)
        self.count.setText(f"{done:,} / {total:,} emails" if total else "")


class DashboardPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.scroll = SingleDirectionScrollArea(orient=Qt.Vertical)
        self.scroll.setWidgetResizable(True)
        self.scroll.enableTransparentBackground()
        self.body = QWidget()
        self.body.setStyleSheet("background: transparent;")
        self.v = QVBoxLayout(self.body)
        self.v.setContentsMargins(28, 24, 28, 24)
        self.v.setSpacing(16)
        self.scroll.setWidget(self.body)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.scroll)

    def populate(self, summary):
        clear_layout(self.v)
        s = summary

        head = QHBoxLayout()
        head.addWidget(TitleLabel("Your inbox at a glance"))
        head.addStretch(1)
        review = PushButton("See all senders")
        review.setIcon(FIF.PEOPLE)
        review.clicked.connect(lambda: self.main.goto_senders())
        head.addWidget(review)
        self.v.addLayout(head)

        # 1) Health hero (single hero card, above the fold)
        self.v.addWidget(self._health_hero(s))

        # 2) Trust reassurance
        self.v.addWidget(trust_bar())

        # 3) Three recommended actions (goal-tailored)
        self.v.addWidget(self._recommended_card(s))

        # 4) Smart insights
        ins = self._insights_card(s)
        if ins:
            self.v.addWidget(ins)

        # 5) Progressive disclosure — analytics hidden until asked for
        self.details = self._details_panel(s)
        self.details.setVisible(False)
        self.toggle_btn = TransparentPushButton("Show inbox details  ▾")
        self.toggle_btn.clicked.connect(self._toggle_details)
        trow = QHBoxLayout()
        trow.addWidget(self.toggle_btn)
        trow.addStretch(1)
        self.v.addLayout(trow)
        self.v.addWidget(self.details)
        self.v.addStretch(1)

    def _toggle_details(self):
        shown = not self.details.isVisible()
        self.details.setVisible(shown)
        self.toggle_btn.setText("Hide inbox details  ▴" if shown else "Show inbox details  ▾")

    def _recommended_card(self, s):
        card = SimpleCardWidget()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(10)
        lay.addWidget(StrongBodyLabel("Recommended next steps"))
        grid = QHBoxLayout()
        grid.setSpacing(12)
        for label, subtitle, cb in self._recommended(s):
            b = PushButton(f"{label}\n{subtitle}")
            b.setIcon(FIF.BROOM)
            b.setMinimumHeight(58)
            b.setAccessibleName(f"{label}. {subtitle}")
            b.clicked.connect(cb)
            grid.addWidget(b, 1)
        lay.addLayout(grid)
        return card

    def _recommended(self, s):
        presets = s.get("presets", {})
        order = list(presets.keys())
        goal = self.main.goal
        if goal == "storage":
            order.sort(key=lambda c: presets[c]["bytes"], reverse=True)
        elif goal == "newsletters":
            order.sort(key=lambda c: (c not in ("Subscriptions", "Promotions"),
                                      -presets[c]["mail"]))
        else:
            order.sort(key=lambda c: presets[c]["mail"], reverse=True)
        acts = [(f"Clean {c}", f"{presets[c]['mail']:,} emails · {gb.human_size(presets[c]['bytes'])}",
                 (lambda _=False, cat=c: self.main.run_preset(cat))) for c in order]

        old_n = sum(1 for r in self.main.senders.values()
                    if r["is_bulk"] and not r.get("protected")
                    and gb._months_since(r["last_date"]) >= 24)
        if old_n:
            act = ("Archive old mail", f"{old_n} senders inactive 2+ years",
                   (lambda _=False: self.main.run_archive_old()))
            acts.insert(0 if goal == "archive" else len(acts), act)

        if not acts:
            acts.append(("Review all senders", f"{s['total_senders']:,} senders",
                         (lambda _=False: self.main.goto_senders())))
        return acts[:3]

    def _insights_card(self, s):
        lines = gb.insights(self.main.senders, s)
        if not lines:
            return None
        card = SimpleCardWidget()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(6)
        lay.addWidget(StrongBodyLabel("What we noticed"))
        for ln in lines:
            row = BodyLabel("•  " + ln)
            row.setWordWrap(True)
            row.setStyleSheet("color: #666;")
            lay.addWidget(row)
        return card

    def _details_panel(self, s):
        panel = QWidget()
        panel.setStyleSheet("background: transparent;")
        v = QVBoxLayout(panel)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(16)

        stats = QHBoxLayout()
        stats.setSpacing(14)
        stats.addWidget(stat_card(f"{s['total_mail']:,}", "Emails in inbox"))
        stats.addWidget(stat_card(f"{s['total_senders']:,}", "Different senders"))
        stats.addWidget(stat_card(f"{s['total_unread']:,}", "Unread", accent="#C77700"))
        stats.addWidget(stat_card(gb.human_size(s['total_bytes']), "Total size"))
        v.addLayout(stats)

        hi = SimpleCardWidget()
        hl = QVBoxLayout(hi)
        hl.setContentsMargins(22, 18, 22, 18)
        big = TitleLabel(f"{s['concentration_pct']}% of your inbox comes from just "
                         f"{s['concentration_n']} senders")
        big.setWordWrap(True)
        sub = BodyLabel("Clear out the biggest ones and your inbox shrinks fast.")
        sub.setStyleSheet("color: #888;")
        hl.addWidget(big)
        hl.addWidget(sub)
        v.addWidget(hi)

        if s.get("presets"):
            v.addWidget(self._presets_card(s))

        cols = QHBoxLayout()
        cols.setSpacing(14)
        cols.addWidget(self._top_senders_card(s), 1)
        cols.addWidget(self._categories_card(s), 1)
        v.addLayout(cols)
        return panel

    def _health_hero(self, s):
        card = SimpleCardWidget()
        row = QHBoxLayout(card)
        row.setContentsMargins(26, 22, 26, 22)
        row.setSpacing(24)

        hc = health_color(s["health"])
        score_box = QVBoxLayout()
        score_box.setSpacing(0)
        score = DisplayLabel(str(s["health"]))
        score.setStyleSheet(f"font-size: 52px; font-weight: 800; color: {hc};")
        score.setAlignment(Qt.AlignCenter)
        cap = CaptionLabel("Inbox Health")
        cap.setAlignment(Qt.AlignCenter)
        cap.setStyleSheet("color: #888;")
        score_box.addWidget(score)
        score_box.addWidget(cap)
        row.addLayout(score_box)

        mid = QVBoxLayout()
        mid.setSpacing(3)
        mid.addWidget(TitleLabel(s["health_label"]))
        det = BodyLabel(
            f"About {s['reclaimable_mail']:,} emails "
            f"({gb.human_size(s['reclaimable_bytes'])}) can be cleared, "
            f"and {s['protected_count']} important senders are protected.")
        det.setWordWrap(True)
        det.setStyleSheet("color: #888;")
        mid.addWidget(det)
        row.addLayout(mid, 1)

        cta = PrimaryPushButton("Start cleaning")
        cta.setIcon(FIF.BROOM)
        cta.clicked.connect(lambda: self.main.goto_senders(check_bulk=True))
        row.addWidget(cta, 0, Qt.AlignVCenter)
        return card

    def _presets_card(self, s):
        card = SimpleCardWidget()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(10)
        lay.addWidget(StrongBodyLabel("Quick cleanup"))
        grid = QHBoxLayout()
        grid.setSpacing(12)
        for cat, info in s["presets"].items():
            b = self._preset_button(cat, info)
            grid.addWidget(b, 1)
        lay.addLayout(grid)
        return card

    def _preset_button(self, cat, info):
        btn = PushButton(f"Clean {cat}")
        btn.setIcon(FIF.BROOM)
        btn.setMinimumHeight(56)
        btn.setToolTip(f"{info['mail']:,} emails · {gb.human_size(info['bytes'])} · "
                       f"recoverable for 30 days")
        btn.setText(f"Clean {cat}\n{info['mail']:,} emails · {gb.human_size(info['bytes'])}")
        btn.clicked.connect(lambda _=False, c=cat: self.main.run_preset(c))
        return btn

    def _top_senders_card(self, s):
        card = SimpleCardWidget()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(8)
        lay.addWidget(StrongBodyLabel("Biggest senders"))
        top = s["top_senders"]
        mx = top[0]["count"] if top else 1
        for r in top:
            row = QGridLayout()
            row.setHorizontalSpacing(10)
            name = BodyLabel(elide(r["name"], 22))
            name.setMinimumWidth(150)
            bar = ProgressBar()
            bar.setTextVisible(False)
            bar.setValue(int(100 * r["count"] / mx))
            bar.setFixedHeight(6)
            cnt = CaptionLabel(f"{r['count']:,}")
            cnt.setStyleSheet("color: #888;")
            cnt.setMinimumWidth(44)
            cnt.setAlignment(Qt.AlignRight)
            row.addWidget(name, 0, 0)
            row.addWidget(bar, 0, 1)
            row.addWidget(cnt, 0, 2)
            row.setColumnStretch(1, 1)
            lay.addLayout(row)
        return card

    def _categories_card(self, s):
        card = SimpleCardWidget()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(8)
        lay.addWidget(StrongBodyLabel("By category"))
        cats = s["categories"]
        total = s["total_mail"] or 1
        for cat in CATEGORY_ORDER:
            if cat not in cats:
                continue
            info = cats[cat]
            row = QGridLayout()
            row.setHorizontalSpacing(10)
            dot = CaptionLabel("●")
            dot.setStyleSheet(f"color: {color_for(cat)};")
            name = BodyLabel(cat)
            name.setMinimumWidth(120)
            bar = ProgressBar()
            bar.setTextVisible(False)
            bar.setValue(int(100 * info["count"] / total))
            bar.setFixedHeight(6)
            cnt = CaptionLabel(f"{info['count']:,}")
            cnt.setStyleSheet("color: #888;")
            cnt.setMinimumWidth(44)
            cnt.setAlignment(Qt.AlignRight)
            row.addWidget(dot, 0, 0)
            row.addWidget(name, 0, 1)
            row.addWidget(bar, 0, 2)
            row.addWidget(cnt, 0, 3)
            row.setColumnStretch(2, 1)
            lay.addLayout(row)
        return card


class SendersPage(QWidget):
    PAGE = 20

    def __init__(self, main):
        super().__init__()
        self.main = main
        self.selected = set()
        self.cards = []
        self.all_recs = []
        self.filtered = []
        self.shown = 0
        self.more_btn = None
        self.active_cat = "All"

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 12)
        root.setSpacing(12)

        # header
        head = QHBoxLayout()
        back = TransparentToolButton(FIF.RETURN)
        back.clicked.connect(self.main.goto_dashboard)
        head.addWidget(back)
        head.addWidget(TitleLabel("Senders"))
        head.addStretch(1)
        self.search = SearchLineEdit()
        self.search.setPlaceholderText("Try: older than 2 years newsletter unread")
        self.search.setFixedWidth(300)
        self.search.setToolTip("Search by name/email or words like: older than 5 years, "
                               "unread, protected, important, newsletter, government, large")
        self.search.setAccessibleName("Search senders")
        self.search.textChanged.connect(self._refresh)
        head.addWidget(self.search)
        self.finish_btn = PushButton("Finish")
        self.finish_btn.setIcon(FIF.ACCEPT)
        self.finish_btn.clicked.connect(self.main.goto_finish)
        head.addWidget(self.finish_btn)
        root.addLayout(head)

        # category chips
        self.chips_wrap = QWidget()
        self.chips = FlowLayout(self.chips_wrap, needAni=False)
        self.chips.setContentsMargins(0, 0, 0, 0)
        self.chip_group = QButtonGroup(self)
        self.chip_group.setExclusive(True)
        root.addWidget(self.chips_wrap)

        # scroll of cards
        self.scroll = SingleDirectionScrollArea(orient=Qt.Vertical)
        self.scroll.setWidgetResizable(True)
        self.scroll.enableTransparentBackground()
        self.listbody = QWidget()
        self.listbody.setStyleSheet("background: transparent;")
        self.lv = QVBoxLayout(self.listbody)
        self.lv.setContentsMargins(2, 2, 8, 2)
        self.lv.setSpacing(8)
        self.scroll.setWidget(self.listbody)
        root.addWidget(self.scroll, 1)

        # quick-select + action bar
        bar = QHBoxLayout()
        self.undo_btn = TransparentPushButton("Undo")
        self.undo_btn.setIcon(FIF.HISTORY)
        self.undo_btn.setEnabled(False)
        self.undo_btn.clicked.connect(self.main.run_undo)
        junk_btn = PushButton("Select likely junk")
        junk_btn.setIcon(FIF.BROOM)
        junk_btn.clicked.connect(self._select_bulk)
        clear_btn = TransparentPushButton("Clear")
        clear_btn.clicked.connect(self._clear_sel)
        bar.addWidget(self.undo_btn)
        bar.addWidget(junk_btn)
        bar.addWidget(clear_btn)
        bar.addStretch(1)
        self.sel_label = BodyLabel("Nothing selected")
        self.sel_label.setStyleSheet("color: #888;")
        bar.addWidget(self.sel_label)
        self.unsub_btn = PushButton("Unsubscribe")
        self.unsub_btn.setIcon(FIF.CANCEL)
        self.unsub_btn.setToolTip("Unsubscribe from the selected senders that offer it")
        self.unsub_btn.setEnabled(False)
        self.unsub_btn.clicked.connect(self._unsubscribe)
        self.archive_btn = PushButton("Archive")
        self.archive_btn.setIcon(FIF.FOLDER)
        self.archive_btn.clicked.connect(lambda: self._act("archive"))
        self.trash_btn = PrimaryPushButton("Move to Trash")
        self.trash_btn.setIcon(FIF.DELETE)
        self.trash_btn.clicked.connect(lambda: self._act("trash"))
        bar.addWidget(self.unsub_btn)
        bar.addWidget(self.archive_btn)
        bar.addWidget(self.trash_btn)
        root.addLayout(bar)

    # -------- build
    def populate(self, senders):
        self.selected.clear()
        self.all_recs = sorted(senders.values(), key=lambda r: r["count"], reverse=True)
        self._build_chips(senders)
        self._refresh()

    def _build_chips(self, senders):
        while self.chips.count():
            item = self.chips.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        for b in list(self.chip_group.buttons()):
            self.chip_group.removeButton(b)
        present = {r["category"] for r in senders.values()}
        cats = ["All"] + [c for c in CATEGORY_ORDER if c in present]
        for cat in cats:
            chip = PillPushButton(cat)
            chip.setCheckable(True)
            if cat == self.active_cat:
                chip.setChecked(True)
            chip.clicked.connect(lambda _=False, c=cat: self._set_cat(c))
            self.chip_group.addButton(chip)
            self.chips.addWidget(chip)

    # -------- filtering + lazy paging
    def _set_cat(self, cat):
        self.active_cat = cat
        self._refresh()

    def _refresh(self):
        q = self.search.text().strip()
        self.filtered = [
            r for r in self.all_recs
            if (self.active_cat == "All" or r["category"] == self.active_cat)
            and gb.query_match(r, q)
        ]
        clear_layout(self.lv)
        self.cards = []
        self.more_btn = None
        self.shown = 0
        self._load_more()

    def _load_more(self):
        self._drop_footer()
        for r in self.filtered[self.shown:self.shown + self.PAGE]:
            c = SenderCard(r, self._toggle)
            if r["email"] in self.selected:
                c.set_checked(True)
            self.lv.addWidget(c)
            self.cards.append(c)
        self.shown += min(self.PAGE, len(self.filtered) - self.shown)
        self._add_footer()

    def _drop_footer(self):
        if self.more_btn is not None:
            self.lv.removeWidget(self.more_btn)
            self.more_btn.deleteLater()
            self.more_btn = None
        cnt = self.lv.count()
        if cnt and self.lv.itemAt(cnt - 1).spacerItem():
            self.lv.takeAt(cnt - 1)

    def _add_footer(self):
        remaining = len(self.filtered) - self.shown
        if remaining > 0:
            self.more_btn = PushButton(f"Load more  ({remaining:,} more)")
            self.more_btn.clicked.connect(self._load_more)
            self.lv.addWidget(self.more_btn, 0, Qt.AlignHCenter)
        elif not self.filtered:
            empty = BodyLabel("No senders match this filter.")
            empty.setStyleSheet("color: #999;")
            empty.setAlignment(Qt.AlignCenter)
            self.lv.addWidget(empty)
        self.lv.addStretch(1)

    # -------- selection
    def _toggle(self, email, on):
        if on:
            self.selected.add(email)
        else:
            self.selected.discard(email)
        self._update_sel()

    def _select_bulk(self):
        for r in self.all_recs:
            if r["is_bulk"] and not r.get("protected"):
                self.selected.add(r["email"])
        for c in self.cards:
            if c.email in self.selected:
                c.set_checked(True)
        self._update_sel()

    def _clear_sel(self):
        self.selected.clear()
        for c in self.cards:
            c.set_checked(False)
        self._update_sel()

    def _update_sel(self):
        n = len(self.selected)
        mails = sum(self.main.senders[e]["count"] for e in self.selected if e in self.main.senders)
        self.sel_label.setText("Nothing selected" if not n
                               else f"{n} senders · {mails:,} emails selected")
        self.archive_btn.setEnabled(n > 0)
        self.trash_btn.setEnabled(n > 0)
        can_unsub = any(self.main.senders.get(e, {}).get("unsub_url")
                        or self.main.senders.get(e, {}).get("unsub_mailto")
                        for e in self.selected)
        self.unsub_btn.setEnabled(can_unsub)

    def _unsubscribe(self):
        targets = [e for e in self.selected if e in self.main.senders]
        if targets:
            self.main.run_unsubscribe(targets)

    def set_undo_enabled(self, on):
        self.undo_btn.setEnabled(on)

    # -------- actions
    def _act(self, mode):
        targets = [e for e in self.selected if e in self.main.senders]
        if not targets:
            return
        mails = sum(self.main.senders[e]["count"] for e in targets)
        verb = "Move to Trash" if mode == "trash" else "Archive"
        note = ("They go to Trash and auto-delete after 30 days — fully recoverable "
                "until then." if mode == "trash" else
                "They leave your inbox but stay in All Mail — nothing is deleted.")
        box = MessageBox(f"{verb} {mails:,} emails?",
                         f"From {len(targets)} senders.\n\n{note}", self.window())
        box.yesButton.setText(verb)
        if not box.exec():
            return
        uids = []
        for e in targets:
            uids.extend(self.main.senders[e]["uids"])
        self._set_busy(True)
        self.main.run_action(mode, uids, targets)

    def _set_busy(self, busy):
        self.archive_btn.setEnabled(not busy)
        self.trash_btn.setEnabled(not busy)

    def remove_senders(self, emails):
        emset = set(emails)
        self.all_recs = [r for r in self.all_recs if r["email"] not in emset]
        self.selected -= emset
        self._refresh()


class FinishPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        outer = QVBoxLayout(self)
        outer.addStretch(1)
        self.card = SimpleCardWidget()
        self.card.setMaximumWidth(560)
        self.cl = QVBoxLayout(self.card)
        self.cl.setContentsMargins(48, 44, 48, 44)
        self.cl.setSpacing(10)
        hbox = QHBoxLayout()
        hbox.addStretch(1)
        hbox.addWidget(self.card)
        hbox.addStretch(1)
        outer.addLayout(hbox)
        outer.addStretch(1)

    def populate(self, stats):
        clear_layout(self.cl)
        emoji = LargeTitleLabel("🎉")
        emoji.setAlignment(Qt.AlignCenter)
        title = LargeTitleLabel("Nice work!")
        title.setAlignment(Qt.AlignCenter)
        self.cl.addWidget(emoji)
        self.cl.addWidget(title)
        self.cl.addSpacing(8)

        def line(big, small, color=None):
            box = QVBoxLayout()
            box.setSpacing(0)
            n = TitleLabel(big)
            n.setAlignment(Qt.AlignCenter)
            if color:
                n.setStyleSheet(f"color: {color};")
            c = CaptionLabel(small)
            c.setAlignment(Qt.AlignCenter)
            c.setStyleSheet("color: #888;")
            box.addWidget(n)
            box.addWidget(c)
            self.cl.addLayout(box)
            self.cl.addSpacing(6)

        removed, freed, senders, protected, pct = stats
        if pct > 0:
            line(f"{pct}%", "smaller inbox", "#107C10")
        line(f"{removed:,}", "emails cleared", "#107C10")
        line(gb.human_size(freed), "storage recoverable")
        line(f"{senders:,}", "senders handled")
        line(f"{protected:,}", "important senders protected")

        self.cl.addSpacing(10)
        row = QHBoxLayout()
        more = PrimaryPushButton("Keep cleaning")
        more.setIcon(FIF.BROOM)
        more.clicked.connect(self.main.goto_dashboard)
        row.addStretch(1)
        row.addWidget(more)
        row.addStretch(1)
        self.cl.addLayout(row)
        note = CaptionLabel("↩ Changed your mind? Trashed mail sits in Gmail's Trash, "
                            "recoverable for 30 days.")
        note.setWordWrap(True)
        note.setAlignment(Qt.AlignCenter)
        note.setStyleSheet("color: #999;")
        self.cl.addWidget(note)


# ------------------------------------------------------------------- window
class GmailCleaner(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("Root")
        self.setWindowTitle("Gmail Inbox Cleaner")
        self.resize(1020, 700)
        self.setMinimumSize(900, 600)

        self.addr = self.pwd = ""
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


if __name__ == "__main__":
    main()
