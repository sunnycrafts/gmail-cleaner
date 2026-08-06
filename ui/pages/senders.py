"""Senders page — the card list: search/filter, lazy paging, selection, and
the Undo / Unsubscribe / Archive / Trash action bar.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QButtonGroup
from qfluentwidgets import (
    TitleLabel, BodyLabel, SearchLineEdit, PushButton, PrimaryPushButton,
    TransparentPushButton, TransparentToolButton, PillPushButton, FlowLayout,
    SingleDirectionScrollArea, MessageBox, FluentIcon as FIF,
)

import gmail_backend as gb
from ui.theme import CATEGORY_ORDER
from ui.utils import clear_layout
from ui.widgets import SenderCard


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
