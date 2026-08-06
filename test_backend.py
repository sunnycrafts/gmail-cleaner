"""Offline tests for gmail_backend — no network required."""
import datetime
import time
import urllib.error
from unittest.mock import patch
import gmail_backend as gb


def make_rec(email, name, count, bytes_, cat_subject="", unsub=False, unread=0,
             flagged=0, important=0, labeled=False, months_old=6):
    cat, bulk = gb.classify(email, name, cat_subject)
    if unsub and cat == "Personal":
        cat, bulk = "Subscriptions", True
    last = gb._now_utc_naive() - datetime.timedelta(days=int(months_old * 30))
    rec = {
        "name": name, "email": email, "count": count, "unread": unread,
        "bytes": bytes_, "has_unsub": unsub, "flagged": flagged,
        "important": important, "labeled": labeled, "subject": cat_subject,
        "first_date": last, "last_date": last,
        "uids": [str(i) for i in range(count)],
        "category": cat, "is_bulk": bulk,
    }
    rec["protected"], rec["stars"], rec["confidence"], rec["suggestion"] = gb.assess(rec)
    return rec


def test_human_size():
    assert gb.human_size(0) == "0 B"
    assert gb.human_size(1500) == "1 KB"
    assert gb.human_size(5 * 1024 * 1024) == "5.0 MB"
    assert gb.human_size(2 * 1024**3) == "2.0 GB"
    print("human_size OK")


def test_decode_mime():
    assert gb.decode_mime("=?UTF-8?B?SGVsbG8=?=") == "Hello"
    assert gb.decode_mime("Plain Name") == "Plain Name"
    assert gb.decode_mime("") == ""
    print("decode_mime OK")


def test_classify():
    assert gb.classify("deals@amazon.com", "Amazon", "50% off")[0] == "Shopping"
    assert gb.classify("noreply@bank.com", "My Bank", "statement")[0] == "Finance"
    assert gb.classify("info@newsletter.co", "Weekly Digest", "")[0] == "Subscriptions"
    assert gb.classify("notify@facebook.com", "Facebook", "")[0] == "Social"
    assert gb.classify("jane@gmail.com", "Jane Doe", "lunch?")[0] == "Personal"
    print("classify OK")


def test_assess_protected():
    # Finance is always protected
    bank = make_rec("alerts@chase.com", "Chase", 20, 5_000_000, "statement")
    assert bank["protected"] is True
    assert bank["suggestion"] == "Protected"
    # a .gov sender is protected even if it looks like a notification
    gov = make_rec("noreply@irs.gov", "IRS", 5, 1_000_000, "notice")
    assert gov["protected"] is True
    # Gmail 'Important' protects
    imp = make_rec("promo@store.com", "Store", 40, 8_000_000, "sale", important=3)
    assert imp["protected"] is True
    print("assess_protected OK")


def test_assess_confidence():
    # heavy promo, all unread, old -> high confidence, 5 stars, Trash
    junk = make_rec("deals@promo-store.com", "Deals", 200, 50_000_000, "big sale",
                    unsub=True, unread=200, months_old=20)
    assert junk["suggestion"] == "Move to Trash", junk["suggestion"]
    assert junk["stars"] >= 4, junk["stars"]
    # personal, read, recent -> low confidence, not for trash
    friend = make_rec("bob@gmail.com", "Bob", 30, 6_000_000, "hey", unread=0, months_old=1)
    assert friend["protected"] is True  # Personal is protected
    print("assess_confidence OK  (junk stars=%d, junk conf=%.2f)"
          % (junk["stars"], junk["confidence"]))


def test_summarize():
    senders = {
        "a@amazon.com": make_rec("a@amazon.com", "Amazon", 200, 200_000_000, "order"),
        "b@facebook.com": make_rec("b@facebook.com", "Facebook", 150, 50_000_000, unread=150),
        "c@news.com": make_rec("c@news.com", "News", 100, 30_000_000, "", unsub=True, unread=80),
        "d@bank.com": make_rec("d@bank.com", "Bank", 20, 5_000_000, "statement"),
        "e@gmail.com": make_rec("e@gmail.com", "Jane", 5, 1_000_000, "hi"),
    }
    s = gb.summarize(senders)
    assert s["total_mail"] == 475
    assert s["concentration_n"] == 3, s["concentration_n"]
    # reclaimable = bulk & not protected: Facebook(social)+News(subs) = 250
    assert s["reclaimable_mail"] == 250, s["reclaimable_mail"]
    # Bank(Finance) + Jane(Personal) protected
    assert s["protected_count"] == 2, s["protected_count"]
    assert "Social" in s["presets"]
    assert 0 <= s["health"] <= 100
    print("summarize OK")
    print("  health:", s["health"], s["health_label"],
          "| protected:", s["protected_count"],
          "| presets:", {k: v["mail"] for k, v in s["presets"].items()})


def test_reasons():
    junk = make_rec("deals@promo-store.com", "Deals", 200, 50_000_000, "sale",
                    unsub=True, unread=200, months_old=30)
    rs = gb.reasons(junk)
    assert any("unsubscribe" in r.lower() for r in rs), rs
    assert any("2+ years" in r for r in rs), rs
    bank = make_rec("alerts@chase.com", "Chase", 20, 5_000_000, "statement")
    assert any("Finance" in r or "important" in r.lower() or "official" in r.lower()
               for r in gb.reasons(bank)), gb.reasons(bank)
    print("reasons OK  e.g.", rs[:2])


def test_query_match():
    junk = make_rec("deals@promo-store.com", "Deals", 200, 50_000_000, "sale",
                    unsub=True, unread=200, months_old=30)
    news = make_rec("hi@substack.com", "Weekly Digest", 40, 8_000_000, "", unsub=True,
                    unread=0, months_old=2)
    bank = make_rec("alerts@chase.com", "Chase", 20, 5_000_000, "statement")
    assert gb.query_match(junk, "older than 2 years") is True
    assert gb.query_match(news, "older than 2 years") is False
    assert gb.query_match(junk, "unread") is True
    assert gb.query_match(news, "unread") is False
    assert gb.query_match(news, "newsletter") is True
    assert gb.query_match(bank, "protected") is True
    assert gb.query_match(junk, "protected") is False
    assert gb.query_match(junk, "deals") is True
    assert gb.query_match(junk, "unsubscribe promotions") is True
    print("query_match OK")


def test_insights():
    senders = {
        "a@amazon.com": make_rec("a@amazon.com", "Amazon", 200, 200_000_000, "order"),
        "b@facebook.com": make_rec("b@facebook.com", "Facebook", 150, 50_000_000, unread=150, months_old=30),
        "c@news.com": make_rec("c@news.com", "News", 100, 30_000_000, "", unsub=True, unread=80, months_old=30),
    }
    s = gb.summarize(senders)
    ins = gb.insights(senders, s)
    assert ins and any("%" in i for i in ins), ins
    print("insights OK:", ins)


def test_parse_unsub():
    url, mailto, oc = gb.parse_unsub(
        "<https://ex.com/u?x=1>, <mailto:u@ex.com?subject=unsub>",
        "List-Unsubscribe=One-Click")
    assert url == "https://ex.com/u?x=1", url
    assert mailto == "mailto:u@ex.com?subject=unsub", mailto
    assert oc is True
    # mailto only, no one-click
    u2, m2, oc2 = gb.parse_unsub("<mailto:u@ex.com>", None)
    assert u2 == "" and m2 == "mailto:u@ex.com" and oc2 is False
    # http (not https) must not be one-click eligible
    u3, m3, oc3 = gb.parse_unsub("<http://ex.com/u>", "List-Unsubscribe=One-Click")
    assert oc3 is False
    # none
    assert gb.parse_unsub(None, None) == ("", "", False)
    # one-click POST rejects non-https target
    assert gb.one_click_unsubscribe("http://ex.com/u") is False
    assert gb.one_click_unsubscribe("") is False
    print("parse_unsub / one_click guard OK")


def test_one_click_retry_behavior():
    # 4xx must fail fast: no sleep, no retries beyond the first attempt.
    calls = []
    with patch("gmail_backend.urllib.request.urlopen",
               side_effect=urllib.error.HTTPError("https://x", 404, "Not Found", {}, None)), \
         patch("gmail_backend.time.sleep", side_effect=lambda s: calls.append(s)):
        ok = gb.one_click_unsubscribe("https://ex.com/u")
    assert ok is False
    assert calls == [], "4xx must not trigger a retry sleep"

    # Transient failure must retry NETWORK_RETRIES times with backoff, then fail.
    calls.clear()
    with patch("gmail_backend.urllib.request.urlopen", side_effect=TimeoutError("timed out")), \
         patch("gmail_backend.time.sleep", side_effect=lambda s: calls.append(s)):
        ok = gb.one_click_unsubscribe("https://ex.com/u", retries=3)
    assert ok is False
    assert calls == [gb.NETWORK_RETRY_BASE_DELAY, gb.NETWORK_RETRY_BASE_DELAY * 2], calls

    # Non-https is rejected before any network attempt (no retries needed).
    calls.clear()
    with patch("gmail_backend.time.sleep", side_effect=lambda s: calls.append(s)):
        assert gb.one_click_unsubscribe("http://ex.com/u") is False
    assert calls == []
    print("one_click retry/backoff behavior OK")


if __name__ == "__main__":
    test_human_size()
    test_decode_mime()
    test_classify()
    test_assess_protected()
    test_assess_confidence()
    test_summarize()
    test_reasons()
    test_query_match()
    test_insights()
    test_parse_unsub()
    test_one_click_retry_behavior()
    print("\nAll backend tests passed ✅")
