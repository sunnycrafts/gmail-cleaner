"""Small reusable widgets: category pill, a stat tile, and the sender card
used throughout the Senders page.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout
from qfluentwidgets import (
    CaptionLabel, StrongBodyLabel, DisplayLabel, SimpleCardWidget,
    CardWidget, CheckBox,
)

import gmail_backend as gb
from ui.theme import color_for, rgba, elide, fmt_date, text_color, stars_str, SUGGESTION_COLORS


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
