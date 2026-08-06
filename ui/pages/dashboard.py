"""Dashboard page — Inbox Health hero, trust chips, goal-tailored recommended
actions, smart insights, and analytics collapsed behind progressive
disclosure ("Show inbox details").
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QGridLayout
from qfluentwidgets import (
    SingleDirectionScrollArea, TitleLabel, StrongBodyLabel, BodyLabel,
    CaptionLabel, SimpleCardWidget, PushButton, PrimaryPushButton,
    TransparentPushButton, ProgressBar, DisplayLabel, FluentIcon as FIF,
)

import gmail_backend as gb
from ui.theme import health_color, color_for, elide, CATEGORY_ORDER, trust_bar
from ui.utils import clear_layout
from ui.widgets import stat_card


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
