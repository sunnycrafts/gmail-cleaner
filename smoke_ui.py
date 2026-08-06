"""Headless smoke test: build every page with fake senders, render, screenshot."""
import sys, datetime, random
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QTimer
from qfluentwidgets import setTheme, Theme, setThemeColor
import gmail_backend as gb
from ui.app import GmailCleaner

def fake_senders(n=60):
    names = [("Amazon","deals@amazon.com","order shipped"),
             ("Facebook","notify@facebookmail.com","5 notifications"),
             ("LinkedIn","news@linkedin.com","jobs for you"),
             ("Chase Bank","alerts@chase.com","your statement"),
             ("MakeMyTrip","offers@makemytrip.com","flight deal"),
             ("Weekly Digest","hello@substack.com","this week"),
             ("Jane Doe","jane@gmail.com","lunch tomorrow?"),
             ("Reddit","noreply@reddit.com","top posts"),
             ("Nykaa","promo@nykaa.com","50% off sale"),
             ("PayPal","service@paypal.com","receipt")]
    senders = {}
    for i in range(n):
        nm, em, subj = names[i % len(names)]
        em = f"{i}_{em}"
        cnt = random.randint(1, 300)
        cat, bulk = gb.classify(em, nm, subj)
        last = gb._now_utc_naive() - datetime.timedelta(days=random.randint(10, 900))
        rec = {
            "name": nm, "email": em, "count": cnt,
            "unread": random.randint(0, cnt), "bytes": cnt * random.randint(20000, 200000),
            "has_unsub": bulk, "flagged": random.choice([0, 0, 0, 1]),
            "important": random.choice([0, 0, 0, cnt]), "labeled": False,
            "unsub_url": ("https://ex.com/u/%d" % i) if bulk else "",
            "unsub_mailto": "", "unsub_oneclick": bool(bulk and i % 2 == 0),
            "subject": subj, "first_date": last, "last_date": last,
            "uids": [str(x) for x in range(cnt)],
            "category": cat, "is_bulk": bulk,
        }
        rec["protected"], rec["stars"], rec["confidence"], rec["suggestion"] = gb.assess(rec)
        senders[em] = rec
    return senders

def run():
    theme = Theme.DARK if "--dark" in sys.argv else Theme.LIGHT
    tag = "dark" if theme == Theme.DARK else "light"
    app = QApplication(sys.argv)
    setTheme(theme)
    setThemeColor("#0067C0")
    win = GmailCleaner()
    win.senders = fake_senders(80)
    win.summary = gb.summarize(win.senders)

    # exercise each page
    win.goal = "storage"
    win.original_total = win.summary["total_mail"]
    win.connect_page._reveal()
    win.dash_page.populate(win.summary)
    win.dash_page._toggle_details()          # progressive disclosure
    win.senders_page.populate(win.senders)
    win.senders_page._select_bulk()
    assert win.senders_page.unsub_btn.isEnabled(), "unsub button should enable on bulk selection"
    # natural-language search + lazy paging
    win.senders_page.search.setText("older than 1 year unread")
    win.senders_page.search.setText("")
    win.senders_page._set_cat("Social")
    win.senders_page._set_cat("All")
    win.senders_page._load_more()
    # finish page (5-tuple with % reduction)
    win.finish_page.populate((1234, 456_000_000, 42, win.summary["protected_count"], 18))
    print("health:", win.summary["health"], win.summary["health_label"],
          "| protected:", win.summary["protected_count"],
          "| presets:", list(win.summary["presets"].keys()),
          "| insights:", len(gb.insights(win.senders, win.summary)))

    # show dashboard and screenshot
    win.stack.setCurrentWidget(win.dash_page)
    win.show()

    def shoot():
        win.stack.setCurrentWidget(win.connect_page)
        win.connect_page._reveal()
        win.grab().save(f"smoke_connect_{tag}.png")
        win.stack.setCurrentWidget(win.welcome_page)
        win.grab().save(f"smoke_welcome_{tag}.png")
        win.stack.setCurrentWidget(win.dash_page)
        def d():
            win.grab().save(f"smoke_dashboard_{tag}.png")
            win.stack.setCurrentWidget(win.senders_page)
            def s():
                win.grab().save(f"smoke_senders_{tag}.png")
                win.stack.setCurrentWidget(win.finish_page)
                QTimer.singleShot(200, lambda: (win.grab().save(f"smoke_finish_{tag}.png"), app.quit()))
            QTimer.singleShot(200, s)
        QTimer.singleShot(200, d)
    QTimer.singleShot(400, shoot)
    app.exec()
    print("smoke UI OK — screenshots saved")

if __name__ == "__main__":
    run()
