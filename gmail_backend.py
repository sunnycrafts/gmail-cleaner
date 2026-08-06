"""
Gmail Inbox Cleaner — backend engine
====================================
UI-agnostic IMAP core. No GUI imports here, so it can be unit-tested headlessly.

Public surface:
    connect(addr, pwd) -> IMAP4_SSL
    scan(addr, pwd, progress=None, should_stop=None) -> ScanResult
    do_action(addr, pwd, uids, mode, progress=None) -> int
    summarize(senders) -> dict
    human_size(n) -> str

A "sender" record is a dict:
    { name, email, count, unread, bytes, has_unsub, flagged, important, labeled,
      unsub_url, unsub_mailto, unsub_oneclick,
      first_date, last_date, subject, category, is_bulk, uids[],
      protected, stars, confidence, suggestion }
"""

import imaplib
import email
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime
import re
import datetime
import urllib.request

IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993
BATCH = 300
ACTION_BATCH = 200

# Header fields we pull (all cheap — no message bodies are ever downloaded).
# X-GM-LABELS is a Gmail IMAP extension giving \Important, \Starred, user labels.
# List-Unsubscribe(-Post) drive the v1.3 unsubscribe feature.
FETCH_ITEM = ("(FLAGS X-GM-LABELS RFC822.SIZE "
              "BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE "
              "LIST-UNSUBSCRIBE LIST-UNSUBSCRIBE-POST)])")

# ---- categorization -------------------------------------------------------
# Categories that are generally safe/expected to clear out in bulk.
BULK_CATEGORIES = {"Promotions", "Social", "Notifications", "Subscriptions"}

# Categories we never auto-select for deletion — the user's important mail.
PROTECTED_CATEGORIES = {"Finance", "Travel", "Personal"}

# Senders matching these are protected regardless of category (gov/health/etc).
PROTECTED_KEYWORDS = [
    ".gov", "irs", "tax", "court", "insurance", "hospital", "clinic",
    "doctor", "health", "medical", "medicare", "medicaid", "utility",
    "electric", "water", "gas", ".edu", "university", "college", "embassy",
    "immigration", "ssa", "benefits", "pension", "payroll", "hr@",
]

# Ordered rules: first matching category wins. Each rule = (label, keywords).
# Keywords are matched against the full lowercased "name <email>" + domain.
CATEGORY_RULES = [
    ("Finance", ["bank", "chase", "wellsfargo", "paypal", "visa", "mastercard",
                 "amex", "americanexpress", "invoice", "billing", "statement",
                 "tax", "irs", "insurance", "capitalone", "citi", "hdfc",
                 "icici", "sbi", "axis", "kotak", "razorpay", "stripe"]),
    ("Travel", ["flight", "airline", "airways", "booking", "hotel", "trip",
                "makemytrip", "expedia", "airbnb", "uber", "lyft", "ola",
                "irctc", "itinerary", "reservation", "indigo", "vistara",
                "delta", "united", "cleartrip", "goibibo"]),
    ("Shopping", ["amazon", "ebay", "walmart", "flipkart", "myntra", "etsy",
                  "target", "bestbuy", "order", "receipt", "shipment",
                  "shipped", "delivery", "tracking", "aliexpress", "shopify",
                  "ajio", "meesho", "nykaa"]),
    ("Social", ["facebook", "instagram", "twitter", "x.com", "linkedin",
                "reddit", "tiktok", "snapchat", "pinterest", "youtube",
                "quora", "discord", "meetup", "nextdoor", "threads"]),
    ("Subscriptions", ["newsletter", "digest", "substack", "medium", "weekly",
                       "subscribe", "mailchimp", "list-manage", "campaign",
                       "bulletin", "roundup"]),
    ("Promotions", ["deals", "deal", "offers", "offer", "sale", "promo",
                    "promotion", "save", "coupon", "discount", "% off",
                    "clearance", "marketing", "rewards"]),
    ("Notifications", ["noreply", "no-reply", "no_reply", "donotreply",
                       "notification", "notifications", "notify", "alerts",
                       "alert", "updates", "update", "security", "verify",
                       "account", "mailer", "automated", "system", "support"]),
]


def human_size(n):
    """Bytes -> friendly string."""
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024


def decode_mime(raw):
    """Decode an RFC 2047 header (=?UTF-8?...?= chunks) into clean text."""
    if not raw:
        return ""
    out = ""
    try:
        for text, enc in decode_header(raw):
            if isinstance(text, bytes):
                out += text.decode(enc or "utf-8", errors="replace")
            else:
                out += text
    except Exception:
        out = str(raw)
    return out.strip()


def parse_unsub(list_unsub, list_unsub_post):
    """From List-Unsubscribe(-Post) headers → (https_url, mailto, one_click)."""
    url, mailto = "", ""
    if list_unsub:
        targets = re.findall(r"<([^>]+)>", list_unsub) or [list_unsub.strip()]
        for t in targets:
            t = t.strip().strip("<>")
            low = t.lower()
            if low.startswith("http") and not url:
                url = t
            elif low.startswith("mailto:") and not mailto:
                mailto = t
    one_click = bool(url.lower().startswith("https") and list_unsub_post
                     and "one-click" in list_unsub_post.lower())
    return url, mailto, one_click


def one_click_unsubscribe(url, timeout=15):
    """RFC 8058 one-click POST. Returns True on a 2xx/3xx. https only."""
    if not url or not url.lower().startswith("https://"):
        return False
    req = urllib.request.Request(
        url, data=b"List-Unsubscribe=One-Click", method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "User-Agent": "GmailInboxCleaner/1.3"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= getattr(resp, "status", resp.getcode()) < 400
    except Exception:
        return False


def classify(sender_email, display_name, subject):
    """Return (category, is_bulk). Transparent, rule-based — a hint, not a verdict."""
    hay = f"{display_name} {sender_email} {subject}".lower()
    domain = sender_email.split("@")[1] if "@" in sender_email else ""
    for label, keywords in CATEGORY_RULES:
        for kw in keywords:
            if kw in hay or kw in domain:
                return label, (label in BULK_CATEGORIES)
    return "Personal", False


def _now_utc_naive():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def _months_since(dt):
    if not dt:
        return 0
    return (_now_utc_naive() - dt).days / 30.0


def assess(rec):
    """Derive (protected, stars, confidence, suggestion) from real IMAP signals.

    confidence = how SAFE this sender is to clear out (0..1). Built only from
    data IMAP actually gives us: category, unread ratio, age, volume, stars
    (\\Flagged/\\Starred), Gmail 'Important', labels, and List-Unsubscribe.
    ("last opened time" and "replies" are intentionally NOT used — IMAP can't
    provide them cheaply.)
    """
    hay = f"{rec['name']} {rec['email']}".lower()
    protected = (
        rec["category"] in PROTECTED_CATEGORIES
        or rec["important"] > 0
        or any(kw in hay for kw in PROTECTED_KEYWORDS)
    )

    count = max(rec["count"], 1)
    unread_ratio = rec["unread"] / count
    flagged_ratio = rec["flagged"] / count
    months = _months_since(rec["last_date"])

    c = 0.30
    if rec["category"] in BULK_CATEGORIES:
        c += 0.30
    if rec["has_unsub"]:
        c += 0.15
    c += 0.20 * unread_ratio            # never-read → safer to remove
    if months > 12:
        c += 0.10
    if months > 24:
        c += 0.10
    if rec["count"] >= 50:
        c += 0.05
    # pull back toward "keep"
    c -= 0.50 * flagged_ratio
    if rec["important"] > 0:
        c -= 0.30
    if rec["labeled"]:
        c -= 0.10
    if rec["category"] in PROTECTED_CATEGORIES:
        c -= 0.50
    confidence = max(0.0, min(1.0, c))

    stars = int(round(1 + 4 * confidence))
    if protected:
        suggestion = "Protected"
    elif confidence >= 0.60:
        suggestion = "Move to Trash"
    elif confidence >= 0.35:
        suggestion = "Archive"
    else:
        suggestion = "Keep"
    return protected, stars, round(confidence, 3), suggestion


def reasons(rec):
    """Human-readable 'why' behind a sender's rating (most telling first)."""
    out = []
    count = max(rec["count"], 1)
    months = _months_since(rec["last_date"])
    hay = f"{rec['name']} {rec['email']}".lower()

    if rec.get("protected"):
        if rec["important"] > 0:
            out.append("Marked important in Gmail")
        if rec["category"] in PROTECTED_CATEGORIES:
            out.append(f"{rec['category']} sender")
        if any(kw in hay for kw in PROTECTED_KEYWORDS):
            out.append("Looks official (gov / health / bills)")
        if rec["flagged"] > 0:
            out.append("You've starred some")
        return out or ["Protected to keep you safe"]

    if rec["category"] in BULK_CATEGORIES:
        out.append(f"{rec['category']} sender")
    if rec["has_unsub"]:
        out.append("Has an unsubscribe link")
    if rec["unread"] == rec["count"] and rec["count"] > 1:
        out.append("You've never opened these")
    elif rec["unread"] / count >= 0.8:
        out.append("You rarely open these")
    if months >= 24:
        out.append("Last received 2+ years ago")
    elif months >= 12:
        out.append("Last received over a year ago")
    if rec["count"] >= 100:
        out.append("High volume")
    if rec["flagged"] > 0:
        out.append("You've starred some — kept in mind")
    return out or ["No strong signals either way"]


def insights(senders, summary):
    """A few plain-English intelligence lines for the dashboard."""
    out = []
    recs = list(senders.values())
    removable = sorted(
        [r for r in recs if r["is_bulk"] and not r.get("protected")],
        key=lambda r: r["count"], reverse=True)
    total_removable = sum(r["count"] for r in removable)
    if total_removable:
        cum, n = 0, 0
        for r in removable:
            cum += r["count"]
            n += 1
            if cum >= 0.5 * total_removable:
                break
        pct = round(100 * cum / total_removable)
        out.append(f"Just {n} sender{'s' if n != 1 else ''} "
                   f"{'account' if n != 1 else 'accounts'} for "
                   f"{pct}% of your removable mail.")

    presets = summary.get("presets", {})
    if presets:
        cat, info = max(presets.items(), key=lambda kv: kv[1]["bytes"])
        out.append(f"Clearing {cat} first frees about {human_size(info['bytes'])}.")

    stale = [r for r in removable if _months_since(r["last_date"]) >= 24]
    if stale:
        out.append(f"{len(stale)} bulk senders haven't emailed you in over 2 years.")

    oneclick = [r for r in recs if r.get("unsub_oneclick")]
    if oneclick:
        out.append(f"{len(oneclick)} senders support a 1-click unsubscribe.")
    return out[:3]


ALL_CATEGORIES = [lbl for lbl, _ in CATEGORY_RULES] + ["Personal"]
_CAT_WORDS = {c.lower(): c for c in ALL_CATEGORIES}
_QUERY_STOP = {"than", "years", "year", "yr", "y", "months", "month", "mo", "m",
               "emails", "email", "mail", "from", "the", "with", "has", "and",
               "in", "over", "last", "received"}


def query_match(rec, query):
    """Keyword / natural-ish search. Supports phrases like:
       'older than 2 years newsletter', 'unread shopping', 'protected important',
       'government', 'large', plus plain name/email text.
    """
    q = (query or "").lower().strip()
    if not q:
        return True
    # age filters: 'older than N years/months', 'newer than N ...'
    for kind, older in (("older than", True), ("newer than", False)):
        m = re.search(kind + r"\s+(\d+)\s*(years?|yrs?|y|months?|mos?|m)\b", q)
        if m:
            n = int(m.group(1))
            months = n * 12 if m.group(2).startswith("y") else n
            age = _months_since(rec["last_date"])
            if older and age < months:
                return False
            if not older and age > months:
                return False
            q = (q[:m.start()] + " " + q[m.end():]).strip()

    text = f"{rec['name']} {rec['email']} {rec['category']}".lower()
    for w in [w for w in re.split(r"\s+", q) if w and w not in _QUERY_STOP]:
        if w in ("older", "newer"):
            continue
        elif w == "unread":
            if rec["unread"] == 0:
                return False
        elif w == "read":
            if rec["unread"] == rec["count"]:
                return False
        elif w == "protected":
            if not rec.get("protected"):
                return False
        elif w == "important":
            if rec["important"] == 0 and not rec.get("protected"):
                return False
        elif w in ("starred", "flagged"):
            if rec["flagged"] == 0:
                return False
        elif w in ("newsletter", "newsletters"):
            if rec["category"] != "Subscriptions":
                return False
        elif w == "unsubscribe":
            if not rec["has_unsub"]:
                return False
        elif w in ("government", "gov"):
            if not any(k in text for k in ("gov", "irs", "tax", "court", "embassy")):
                return False
        elif w in ("large", "big"):
            if rec["bytes"] / max(rec["count"], 1) < 100_000:
                return False
        elif w in _CAT_WORDS:
            if rec["category"].lower() != w:
                return False
        else:
            if w not in text:
                return False
    return True


def chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def connect(addr, pwd):
    M = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    M.login(addr, pwd.replace(" ", ""))
    return M


# ---- scanning -------------------------------------------------------------
def scan(addr, pwd, progress=None, should_stop=None):
    """Scan INBOX read-only and aggregate by sender.

    progress(stage:str, done:int, total:int) is called throughout.
    should_stop() -> bool lets the caller abort.
    Returns dict: { senders: {email: rec}, total: int }
    """
    def emit(stage, done=0, total=0):
        if progress:
            progress(stage, done, total)

    emit("Connecting to Gmail…")
    M = connect(addr, pwd)
    try:
        M.select("INBOX", readonly=True)
        emit("Reading your mailbox…")
        typ, data = M.uid("search", None, "ALL")
        uids = data[0].split() if data and data[0] else []
        total = len(uids)
        emit("Reading your mailbox…", 0, total)

        agg = {}
        done = 0
        for batch in chunks(uids, BATCH):
            if should_stop and should_stop():
                break
            uid_set = b",".join(batch).decode()
            typ, msgdata = M.uid("fetch", uid_set, FETCH_ITEM)
            _parse_batch(msgdata, agg)
            done += len(batch)
            emit("Grouping senders…", done, total)

        emit("Finding subscriptions…", total, total)
        for e, rec in agg.items():
            cat, bulk = classify(e, rec["name"], rec["subject"])
            rec["category"] = cat
            rec["is_bulk"] = bulk or rec["has_unsub"] and cat == "Personal"
            if rec["has_unsub"] and cat == "Personal":
                rec["category"] = "Subscriptions"
                rec["is_bulk"] = True

        emit("Scoring recommendations…", total, total)
        for rec in agg.values():
            rec["protected"], rec["stars"], rec["confidence"], rec["suggestion"] = assess(rec)

        emit("Preparing your summary…", total, total)
        return {"senders": agg, "total": total}
    finally:
        try:
            M.logout()
        except Exception:
            pass


def _parse_batch(msgdata, agg):
    for part in msgdata:
        if not isinstance(part, tuple):
            continue
        meta, header_bytes = part[0], part[1]
        m = re.search(rb"UID (\d+)", meta)
        uid = m.group(1).decode() if m else None
        fm = re.search(rb"FLAGS \(([^)]*)\)", meta)
        flags = fm.group(1) if fm else b""
        lm = re.search(rb"X-GM-LABELS \(([^)]*)\)", meta)
        labels = lm.group(1) if lm else b""
        sm = re.search(rb"RFC822\.SIZE (\d+)", meta)
        size = int(sm.group(1)) if sm else 0

        try:
            msg = email.message_from_bytes(header_bytes)
        except Exception:
            continue

        name, e = parseaddr(decode_mime(msg.get("From", "")))
        e = e.lower() or "(unknown sender)"
        name = name or e
        subject = decode_mime(msg.get("Subject", "")) or "(no subject)"
        unread = b"\\Seen" not in flags
        starred = b"\\Flagged" in flags or b"\\Starred" in labels
        important = b"\\Important" in labels
        # any label token that isn't a Gmail system \Label counts as a user label
        user_labeled = bool(re.search(rb'(^|\s)(?!\\)("?[^\\\s"][^\s"]*)', labels))
        lu = msg.get("List-Unsubscribe")
        has_unsub = lu is not None
        u_url, u_mailto, u_oneclick = parse_unsub(lu, msg.get("List-Unsubscribe-Post"))
        try:
            dt = parsedate_to_datetime(msg.get("Date"))
            if dt and dt.tzinfo:
                dt = dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        except Exception:
            dt = None

        rec = agg.get(e)
        if rec is None:
            rec = {"name": name, "email": e, "count": 0, "unread": 0,
                   "bytes": 0, "has_unsub": False, "flagged": 0, "important": 0,
                   "labeled": False, "unsub_url": "", "unsub_mailto": "",
                   "unsub_oneclick": False, "subject": subject,
                   "first_date": dt, "last_date": dt, "uids": [],
                   "category": "Personal", "is_bulk": False}
            agg[e] = rec
        rec["count"] += 1
        rec["bytes"] += size
        if unread:
            rec["unread"] += 1
        if has_unsub:
            rec["has_unsub"] = True
            # keep the most recent usable unsubscribe target
            if u_url:
                rec["unsub_url"] = u_url
            if u_mailto:
                rec["unsub_mailto"] = u_mailto
            if u_oneclick:
                rec["unsub_oneclick"] = True
        if starred:
            rec["flagged"] += 1
        if important:
            rec["important"] += 1
        if user_labeled:
            rec["labeled"] = True
        if uid:
            rec["uids"].append(uid)
        if dt:
            if rec["first_date"] is None or dt < rec["first_date"]:
                rec["first_date"] = dt
            if rec["last_date"] is None or dt > rec["last_date"]:
                rec["last_date"] = dt
                rec["subject"] = subject  # keep most-recent subject
                rec["name"] = name


# ---- summary --------------------------------------------------------------
def summarize(senders):
    """Compute dashboard stats from the sender dict."""
    recs = list(senders.values())
    total_mail = sum(r["count"] for r in recs)
    total_senders = len(recs)
    total_unread = sum(r["unread"] for r in recs)
    total_bytes = sum(r["bytes"] for r in recs)

    # smallest N senders covering >=80% of emails
    by_count = sorted(recs, key=lambda r: r["count"], reverse=True)
    cum, concentration_n = 0, 0
    for r in by_count:
        cum += r["count"]
        concentration_n += 1
        if total_mail and cum >= 0.8 * total_mail:
            break
    concentration_pct = round(100 * cum / total_mail) if total_mail else 0

    # category breakdown
    cats = {}
    for r in recs:
        c = cats.setdefault(r["category"], {"count": 0, "bytes": 0, "senders": 0})
        c["count"] += r["count"]
        c["bytes"] += r["bytes"]
        c["senders"] += 1

    bulk_recs = [r for r in recs if r["is_bulk"] and not r.get("protected")]
    reclaimable_bytes = sum(r["bytes"] for r in bulk_recs)
    reclaimable_mail = sum(r["count"] for r in bulk_recs)
    unsub_senders = [r for r in recs if r["has_unsub"]]
    protected_senders = [r for r in recs if r.get("protected")]

    # per-category preset info for one-click cleanup (protected excluded)
    presets = {}
    for cat in ("Promotions", "Social", "Notifications", "Subscriptions"):
        prs = [r for r in recs if r["category"] == cat and not r.get("protected")]
        if prs:
            presets[cat] = {
                "senders": len(prs),
                "mail": sum(r["count"] for r in prs),
                "bytes": sum(r["bytes"] for r in prs),
            }

    # Inbox Health 0..100 — higher is healthier. Bulk load and unread load hurt.
    bulk_frac = reclaimable_mail / total_mail if total_mail else 0
    unread_frac = total_unread / total_mail if total_mail else 0
    health = round(max(0, min(100, 100 - 62 * bulk_frac - 22 * unread_frac)))
    if health >= 80:
        health_label = "Healthy"
    elif health >= 55:
        health_label = "Getting there"
    else:
        health_label = "Needs attention"

    return {
        "total_mail": total_mail,
        "total_senders": total_senders,
        "total_unread": total_unread,
        "total_bytes": total_bytes,
        "concentration_n": concentration_n,
        "concentration_pct": concentration_pct,
        "categories": cats,
        "top_senders": by_count[:8],
        "reclaimable_bytes": reclaimable_bytes,
        "reclaimable_mail": reclaimable_mail,
        "reclaimable_senders": len(bulk_recs),
        "unsub_count": len(unsub_senders),
        "protected_count": len(protected_senders),
        "presets": presets,
        "health": health,
        "health_label": health_label,
    }


# ---- actions --------------------------------------------------------------
def do_action(addr, pwd, uids, mode, progress=None):
    """mode = 'trash' or 'archive'. Returns count processed."""
    M = connect(addr, pwd)
    try:
        M.select("INBOX")  # read-write
        done = 0
        total = len(uids)
        for batch in chunks(uids, ACTION_BATCH):
            uid_set = ",".join(batch)
            if mode == "trash":
                M.uid("STORE", uid_set, "+X-GM-LABELS", "\\Trash")
            else:  # archive: remove from inbox, keep in All Mail
                M.uid("STORE", uid_set, "-X-GM-LABELS", "\\Inbox")
            done += len(batch)
            if progress:
                progress(done, total)
        M.expunge()
        return done
    finally:
        try:
            M.logout()
        except Exception:
            pass


def undo_action(addr, pwd, uids, mode, progress=None):
    """Reverse the last do_action. Trash -> back to Inbox; Archive -> back to Inbox."""
    M = connect(addr, pwd)
    try:
        M.select("INBOX")  # read-write
        done = 0
        total = len(uids)
        for batch in chunks(uids, ACTION_BATCH):
            uid_set = ",".join(batch)
            if mode == "trash":
                M.uid("STORE", uid_set, "-X-GM-LABELS", "\\Trash")
            M.uid("STORE", uid_set, "+X-GM-LABELS", "\\Inbox")
            done += len(batch)
            if progress:
                progress(done, total)
        return done
    finally:
        try:
            M.logout()
        except Exception:
            pass
