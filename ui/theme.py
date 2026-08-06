"""Visual constants and small style/format helpers shared across pages.

Nothing here touches gmail_backend or holds any state — pure presentation.
"""

from PySide6.QtWidgets import QWidget, QHBoxLayout
from qfluentwidgets import CaptionLabel, FlowLayout, isDarkTheme, FluentIcon as FIF

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


def text_color():
    return "#f0f0f0" if isDarkTheme() else "#1c1c1c"


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


# -------------------------------------------------------- onboarding goals
GOALS = [
    ("tidy",        "Just tidy up",        "Clear the clutter, keep what matters",     FIF.BROOM),
    ("storage",     "Free up storage",     "Target the biggest, heaviest senders",     FIF.CLOUD),
    ("newsletters", "Remove newsletters",  "Subscriptions and marketing mail",          FIF.MAIL),
    ("archive",     "Archive old mail",    "Move old messages out without deleting",    FIF.FOLDER),
]
