"""Scan page — staged progress while the inbox is being read."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout
from qfluentwidgets import TitleLabel, BodyLabel, IndeterminateProgressRing


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
