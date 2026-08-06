"""Welcome / goal-onboarding page — the first thing the user sees."""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QGridLayout
from qfluentwidgets import (
    SimpleCardWidget, LargeTitleLabel, SubtitleLabel, BodyLabel, StrongBodyLabel,
    PushButton, PrimaryPushButton,
)

from ui.theme import trust_bar, GOALS


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
