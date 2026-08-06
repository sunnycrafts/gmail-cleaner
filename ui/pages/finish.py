"""Finish page — celebration screen with session stats and an undo reminder."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout
from qfluentwidgets import (
    LargeTitleLabel, TitleLabel, CaptionLabel, SimpleCardWidget,
    PrimaryPushButton, FluentIcon as FIF,
)

import gmail_backend as gb
from ui.utils import clear_layout


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
