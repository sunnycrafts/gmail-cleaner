"""
Gmail Inbox Cleaner
===================
A friendly desktop app that scans your Gmail inbox, groups every email by who
sent it, ranks the biggest senders, flags likely junk, and lets you move all
emails from chosen senders to Trash (or Archive them) in one click.

Connection uses Gmail IMAP with an App Password (no Google Cloud setup needed).
Trash is recoverable for 30 days, so nothing here is permanent right away.
"""

import imaplib
import email
from email.header import decode_header
from email.utils import parseaddr
import threading
import queue
import re
import csv
import datetime

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993
BATCH = 300  # how many message headers to fetch per round-trip

# Words that strongly suggest an automated / marketing / bulk sender.
JUNK_KEYWORDS = [
    "noreply", "no-reply", "no_reply", "donotreply", "do-not-reply",
    "newsletter", "marketing", "notification", "notifications", "notify",
    "mailer", "mailing", "bounce", "news", "info", "updates", "update",
    "deals", "offers", "offer", "promo", "promotions", "promotion",
    "alerts", "alert", "support", "team", "hello", "campaign", "email",
    "e-mail", "automated", "auto", "system", "billing", "receipt", "order",
]
JUNK_DOMAINS = [
    "mailchimp", "sendgrid", "sparkpostmail", "mcsv", "rsgsv", "list-manage",
    "amazonses", "mandrillapp", "constantcontact", "sendinblue", "klaviyo",
    "hubspot", "mailgun", "postmarkapp", "salesforce", "marketo", "exacttarget",
]


def decode_mime(raw):
    """Decode an RFC2047-encoded header (handles =?UTF-8?...?= chunks)."""
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


def junk_score(sender_email, display_name, subject):
    """Heuristic 0-3+ score; higher = more likely bulk/junk."""
    score = 0
    e = (sender_email or "").lower()
    local = e.split("@")[0] if "@" in e else e
    domain = e.split("@")[1] if "@" in e else ""

    for kw in JUNK_KEYWORDS:
        if kw in local:
            score += 1
            break
    for d in JUNK_DOMAINS:
        if d in domain:
            score += 2
            break
    # bulk-looking subjects
    subj = (subject or "").lower()
    if any(w in subj for w in ["unsubscribe", "% off", "sale", "newsletter",
                               "deal", "coupon", "limited time", "act now"]):
        score += 1
    # a name that is just the brand / no human name pattern
    if not display_name or "@" in display_name:
        score += 0
    return score


def chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


class GmailCleaner(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Gmail Inbox Cleaner")
        self.geometry("1040x680")
        self.minsize(900, 560)

        self.queue = queue.Queue()
        self.senders = {}          # email -> dict(name, count, unread, subject, score, uids[])
        self.checked = set()       # set of tree item ids that are checked
        self.worker = None
        self.creds = ("", "")

        self._build_login()
        self._build_results()
        self._build_statusbar()

        self.after(100, self._pump_queue)

    # ---------------- UI construction ----------------
    def _build_login(self):
        f = ttk.LabelFrame(self, text="  Step 1 · Connect to Gmail  ")
        f.pack(fill="x", padx=12, pady=(12, 6))

        ttk.Label(f, text="Gmail address:").grid(row=0, column=0, sticky="e", padx=6, pady=6)
        self.email_var = tk.StringVar()
        ttk.Entry(f, textvariable=self.email_var, width=34).grid(row=0, column=1, sticky="w", pady=6)

        ttk.Label(f, text="App Password:").grid(row=0, column=2, sticky="e", padx=6, pady=6)
        self.pwd_var = tk.StringVar()
        self.pwd_entry = ttk.Entry(f, textvariable=self.pwd_var, width=22, show="•")
        self.pwd_entry.grid(row=0, column=3, sticky="w", pady=6)

        self.show_pwd = tk.BooleanVar(value=False)
        ttk.Checkbutton(f, text="show", variable=self.show_pwd,
                        command=self._toggle_pwd).grid(row=0, column=4, padx=4)

        ttk.Button(f, text="What's an App Password?",
                   command=self._show_help).grid(row=0, column=5, padx=8)

        self.scan_btn = ttk.Button(f, text="🔍  Scan my inbox", command=self.start_scan)
        self.scan_btn.grid(row=0, column=6, padx=10)

        f.columnconfigure(1, weight=1)

    def _build_results(self):
        f = ttk.LabelFrame(self, text="  Step 2 · Your senders (biggest first) — tick the ones to clean out  ")
        f.pack(fill="both", expand=True, padx=12, pady=6)

        # filter row
        top = ttk.Frame(f)
        top.pack(fill="x", padx=6, pady=(6, 0))
        ttk.Label(top, text="Filter:").pack(side="left")
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *_: self._apply_filter())
        ttk.Entry(top, textvariable=self.filter_var, width=30).pack(side="left", padx=6)
        ttk.Button(top, text="Tick all visible", command=lambda: self._bulk_check(True)).pack(side="left", padx=4)
        ttk.Button(top, text="Untick all", command=lambda: self._bulk_check(False)).pack(side="left", padx=4)
        ttk.Button(top, text="Tick likely-junk", command=self._check_junk).pack(side="left", padx=4)

        cols = ("chk", "name", "email", "count", "unread", "kind", "subject")
        self.tree = ttk.Treeview(f, columns=cols, show="headings", selectmode="none")
        headings = {
            "chk": ("✓", 36),
            "name": ("Sender name", 200),
            "email": ("Email address", 240),
            "count": ("Emails", 70),
            "unread": ("Unread", 70),
            "kind": ("Type", 110),
            "subject": ("Most recent subject", 300),
        }
        for c, (text, w) in headings.items():
            self.tree.heading(c, text=text,
                              command=(lambda col=c: self._sort_by(col)) if c != "chk" else self._toggle_all_header)
            anchor = "center" if c in ("chk", "count", "unread", "kind") else "w"
            self.tree.column(c, width=w, anchor=anchor, stretch=(c in ("name", "email", "subject")))

        vs = ttk.Scrollbar(f, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        vs.pack(side="right", fill="y", pady=6)

        self.tree.tag_configure("junk", foreground="#b00020")
        self.tree.bind("<Button-1>", self._on_tree_click)

        # action row
        act = ttk.Frame(self)
        act.pack(fill="x", padx=12, pady=(0, 6))
        self.sel_label = ttk.Label(act, text="Selected: 0 senders · 0 emails")
        self.sel_label.pack(side="left")
        ttk.Button(act, text="Export list to CSV", command=self.export_csv).pack(side="right", padx=4)
        self.archive_btn = ttk.Button(act, text="📦  Archive selected (out of inbox)",
                                      command=lambda: self.start_action("archive"))
        self.archive_btn.pack(side="right", padx=4)
        self.trash_btn = ttk.Button(act, text="🗑  Move selected to Trash",
                                    command=lambda: self.start_action("trash"))
        self.trash_btn.pack(side="right", padx=4)

    def _build_statusbar(self):
        bar = ttk.Frame(self)
        bar.pack(fill="x", side="bottom")
        self.status = tk.StringVar(value="Ready. Enter your Gmail + App Password, then click Scan.")
        ttk.Label(bar, textvariable=self.status, anchor="w").pack(side="left", fill="x", expand=True, padx=8, pady=4)
        self.progress = ttk.Progressbar(bar, mode="determinate", length=240)
        self.progress.pack(side="right", padx=8, pady=4)

    # ---------------- small UI helpers ----------------
    def _toggle_pwd(self):
        self.pwd_entry.config(show="" if self.show_pwd.get() else "•")

    def _show_help(self):
        messagebox.showinfo(
            "How to get a Gmail App Password",
            "An App Password is a 16-character code that lets this app read your "
            "inbox without your real password.\n\n"
            "1. Your Google account must have 2-Step Verification turned ON.\n"
            "   (myaccount.google.com  ›  Security  ›  2-Step Verification)\n\n"
            "2. Then go to:  myaccount.google.com/apppasswords\n\n"
            "3. Type a name like 'Inbox Cleaner' and click Create.\n\n"
            "4. Google shows a 16-letter code (4 groups of 4). Copy it and paste "
            "it into the App Password box here. Spaces don't matter.\n\n"
            "This code only works for mail, and you can delete it anytime from the "
            "same page."
        )

    def set_busy(self, busy, msg=None):
        state = "disabled" if busy else "normal"
        for b in (self.scan_btn, self.trash_btn, self.archive_btn):
            b.config(state=state)
        if msg:
            self.status.set(msg)

    # ---------------- scanning ----------------
    def start_scan(self):
        addr = self.email_var.get().strip()
        pwd = self.pwd_var.get().replace(" ", "")
        if not addr or not pwd:
            messagebox.showwarning("Missing info", "Please enter both your Gmail address and App Password.")
            return
        self.creds = (addr, pwd)
        self.senders.clear()
        self.checked.clear()
        self.tree.delete(*self.tree.get_children())
        self.set_busy(True, "Connecting to Gmail…")
        self.progress.config(mode="indeterminate")
        self.progress.start(12)
        self.worker = threading.Thread(target=self._scan_worker, daemon=True)
        self.worker.start()

    def _scan_worker(self):
        addr, pwd = self.creds
        try:
            M = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
            M.login(addr, pwd)
            M.select("INBOX", readonly=True)
            typ, data = M.uid("search", None, "ALL")
            uids = data[0].split()
            total = len(uids)
            self.queue.put(("status", f"Found {total} emails. Reading senders…"))
            self.queue.put(("progress_mode", ("determinate", total)))

            done = 0
            agg = {}
            for batch in chunks(uids, BATCH):
                uid_set = b",".join(batch).decode()
                typ, msgdata = M.uid(
                    "fetch", uid_set,
                    "(FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
                self._parse_batch(msgdata, agg)
                done += len(batch)
                self.queue.put(("progress", done))
                self.queue.put(("status", f"Reading senders… {done}/{total}"))

            M.logout()
            self.queue.put(("scan_done", (agg, total)))
        except imaplib.IMAP4.error as e:
            self.queue.put(("error", "Login failed. Double-check your address and App Password.\n\n"
                                     "Remember: App Passwords need 2-Step Verification ON.\n\n"
                                     f"Details: {e}"))
        except Exception as e:
            self.queue.put(("error", f"Something went wrong:\n\n{e}"))

    def _parse_batch(self, msgdata, agg):
        cur_uid = None
        cur_flags = b""
        for part in msgdata:
            if isinstance(part, tuple):
                meta, header_bytes = part[0], part[1]
                m = re.search(rb"UID (\d+)", meta)
                cur_uid = m.group(1).decode() if m else None
                fm = re.search(rb"FLAGS \(([^)]*)\)", meta)
                cur_flags = fm.group(1) if fm else b""
                try:
                    msg = email.message_from_bytes(header_bytes)
                except Exception:
                    continue
                name, addr = parseaddr(decode_mime(msg.get("From", "")))
                addr = addr.lower()
                if not addr:
                    addr = "(unknown sender)"
                name = name or addr
                subject = decode_mime(msg.get("Subject", "")) or "(no subject)"
                unread = b"\\Seen" not in cur_flags

                rec = agg.get(addr)
                if rec is None:
                    rec = {"name": name, "count": 0, "unread": 0,
                           "subject": subject, "uids": [], "score": 0}
                    agg[addr] = rec
                rec["count"] += 1
                if unread:
                    rec["unread"] += 1
                if cur_uid:
                    rec["uids"].append(cur_uid)
                # keep the most recent subject (last seen, since UIDs ascend)
                rec["subject"] = subject
                rec["name"] = name

    def _finish_scan(self, agg, total):
        for addr, rec in agg.items():
            rec["score"] = junk_score(addr, rec["name"], rec["subject"])
        self.senders = agg
        self._populate(sort_col="count")
        junk_n = sum(1 for r in agg.values() if r["score"] >= 2)
        self.status.set(
            f"Done! {total} emails from {len(agg)} senders. "
            f"~{junk_n} senders look like bulk/junk. "
            f"Tick the ones to clean, then choose Trash or Archive."
        )

    # ---------------- table population ----------------
    def _populate(self, sort_col="count", reverse=True):
        self.tree.delete(*self.tree.get_children())
        flt = self.filter_var.get().lower().strip()
        items = list(self.senders.items())

        def key(kv):
            addr, rec = kv
            if sort_col == "name":
                return rec["name"].lower()
            if sort_col == "email":
                return addr
            if sort_col == "subject":
                return rec["subject"].lower()
            if sort_col == "unread":
                return rec["unread"]
            if sort_col == "kind":
                return rec["score"]
            return rec["count"]

        items.sort(key=key, reverse=reverse)
        for addr, rec in items:
            if flt and flt not in addr and flt not in rec["name"].lower():
                continue
            kind = "Likely junk" if rec["score"] >= 2 else ("Maybe bulk" if rec["score"] == 1 else "Personal")
            iid = addr  # use the email as the stable item id
            mark = "☑" if iid in self.checked else "☐"
            tags = ("junk",) if rec["score"] >= 2 else ()
            self.tree.insert("", "end", iid=iid,
                             values=(mark, rec["name"], addr, rec["count"],
                                     rec["unread"], kind, rec["subject"]),
                             tags=tags)
        self._update_selcount()

    def _apply_filter(self):
        self._populate(sort_col=getattr(self, "_last_sort", "count"),
                       reverse=getattr(self, "_last_rev", True))

    def _sort_by(self, col):
        rev = not getattr(self, "_last_rev", True) if getattr(self, "_last_sort", None) == col else True
        self._last_sort, self._last_rev = col, rev
        self._populate(sort_col=col, reverse=rev)

    # ---------------- checkbox handling ----------------
    def _on_tree_click(self, event):
        if self.tree.identify("region", event.x, event.y) != "cell":
            return
        col = self.tree.identify_column(event.x)
        row = self.tree.identify_row(event.y)
        if not row:
            return
        if col == "#1":   # the checkbox column
            self._toggle_row(row)

    def _toggle_row(self, iid):
        if iid in self.checked:
            self.checked.discard(iid)
            self.tree.set(iid, "chk", "☐")
        else:
            self.checked.add(iid)
            self.tree.set(iid, "chk", "☑")
        self._update_selcount()

    def _toggle_all_header(self):
        self._bulk_check(not self._all_visible_checked())

    def _all_visible_checked(self):
        vis = self.tree.get_children()
        return bool(vis) and all(v in self.checked for v in vis)

    def _bulk_check(self, on):
        for iid in self.tree.get_children():
            if on:
                self.checked.add(iid)
                self.tree.set(iid, "chk", "☑")
            else:
                self.checked.discard(iid)
                self.tree.set(iid, "chk", "☐")
        self._update_selcount()

    def _check_junk(self):
        for iid in self.tree.get_children():
            rec = self.senders.get(iid)
            if rec and rec["score"] >= 2:
                self.checked.add(iid)
                self.tree.set(iid, "chk", "☑")
        self._update_selcount()

    def _update_selcount(self):
        n_send = len(self.checked)
        n_mail = sum(self.senders[a]["count"] for a in self.checked if a in self.senders)
        self.sel_label.config(text=f"Selected: {n_send} senders · {n_mail} emails")

    # ---------------- actions (trash / archive) ----------------
    def start_action(self, mode):
        if not self.checked:
            messagebox.showinfo("Nothing selected", "Tick at least one sender first.")
            return
        targets = [a for a in self.checked if a in self.senders]
        n_mail = sum(self.senders[a]["count"] for a in targets)
        verb = "move to Trash" if mode == "trash" else "Archive (remove from inbox)"
        note = ("They go to Trash and auto-delete after 30 days — fully recoverable until then."
                if mode == "trash" else
                "They leave your inbox but stay searchable in 'All Mail' — nothing is deleted.")
        if not messagebox.askyesno(
                "Please confirm",
                f"{verb}:\n\n{len(targets)} senders\n{n_mail} emails\n\n{note}\n\nProceed?"):
            return
        self.set_busy(True, f"Working… {verb} {n_mail} emails")
        self.progress.config(mode="indeterminate")
        self.progress.start(12)
        all_uids = []
        for a in targets:
            all_uids.extend(self.senders[a]["uids"])
        self.worker = threading.Thread(
            target=self._action_worker, args=(mode, all_uids, targets), daemon=True)
        self.worker.start()

    def _action_worker(self, mode, uids, targets):
        addr, pwd = self.creds
        try:
            M = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
            M.login(addr, pwd)
            M.select("INBOX")  # read-write
            done = 0
            for batch in chunks(uids, 200):
                uid_set = ",".join(batch)
                if mode == "trash":
                    M.uid("STORE", uid_set, "+X-GM-LABELS", "\\Trash")
                else:  # archive = remove the Inbox label
                    M.uid("STORE", uid_set, "-X-GM-LABELS", "\\Inbox")
                done += len(batch)
                self.queue.put(("status", f"Working… {done}/{len(uids)} emails"))
            M.expunge()
            M.logout()
            self.queue.put(("action_done", (mode, targets, len(uids))))
        except Exception as e:
            self.queue.put(("error", f"Action failed:\n\n{e}"))

    def _finish_action(self, mode, targets, n):
        for a in targets:
            self.senders.pop(a, None)
            self.checked.discard(a)
        self._populate(sort_col=getattr(self, "_last_sort", "count"),
                       reverse=getattr(self, "_last_rev", True))
        word = "moved to Trash" if mode == "trash" else "archived"
        self.status.set(f"✅ {n} emails {word}. {len(self.senders)} senders left in your inbox.")

    # ---------------- export ----------------
    def export_csv(self):
        if not self.senders:
            messagebox.showinfo("Nothing to export", "Scan your inbox first.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            initialfile=f"gmail_senders_{datetime.date.today()}.csv",
            filetypes=[("CSV files", "*.csv")])
        if not path:
            return
        rows = sorted(self.senders.items(), key=lambda kv: kv[1]["count"], reverse=True)
        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["Sender name", "Email", "Emails", "Unread", "Type", "Most recent subject"])
            for addr, rec in rows:
                kind = "Likely junk" if rec["score"] >= 2 else ("Maybe bulk" if rec["score"] == 1 else "Personal")
                w.writerow([rec["name"], addr, rec["count"], rec["unread"], kind, rec["subject"]])
        messagebox.showinfo("Exported", f"Saved to:\n{path}")

    # ---------------- queue pump (thread -> GUI) ----------------
    def _pump_queue(self):
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "status":
                    self.status.set(payload)
                elif kind == "progress_mode":
                    mode, total = payload
                    self.progress.stop()
                    self.progress.config(mode=mode, maximum=max(total, 1), value=0)
                elif kind == "progress":
                    self.progress.config(value=payload)
                elif kind == "scan_done":
                    self.progress.stop()
                    self.progress.config(mode="determinate", value=0)
                    self.set_busy(False)
                    self._finish_scan(*payload)
                elif kind == "action_done":
                    self.progress.stop()
                    self.progress.config(mode="determinate", value=0)
                    self.set_busy(False)
                    self._finish_action(*payload)
                elif kind == "error":
                    self.progress.stop()
                    self.progress.config(mode="determinate", value=0)
                    self.set_busy(False)
                    self.status.set("Stopped — see the message.")
                    messagebox.showerror("Error", payload)
        except queue.Empty:
            pass
        self.after(120, self._pump_queue)


if __name__ == "__main__":
    app = GmailCleaner()
    app.mainloop()
