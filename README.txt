GMAIL INBOX CLEANER  —  quick start
====================================

WHAT IT DOES
  Scans your Gmail inbox, groups every email by who sent it, and opens on a
  SUMMARY DASHBOARD: total emails, how few senders make up most of your inbox,
  biggest senders, a category breakdown, and how much promotional/bulk mail you
  can clear. Then you drill into a card list of senders, tick the ones you want
  gone, and move them to Trash (recoverable 30 days) or Archive them.

HOW TO RUN
  Double-click "Gmail Cleaner.bat" (in the Desktop\claude code folder).

REQUIREMENTS
  Python 3 with PySide6 and qfluentwidgets (already installed on this PC).
  If ever needed:  pip install PySide6 qfluentwidgets

ONE-TIME SETUP: get a Gmail App Password
  1. Turn on 2-Step Verification for your Google account:
       myaccount.google.com  >  Security  >  2-Step Verification
  2. Go to:  myaccount.google.com/apppasswords
  3. Name it "Inbox Cleaner" and click Create.
  4. Copy the 16-letter code it shows you.

USING IT
  1. Pick a goal on the welcome screen (Just tidy up / Free up storage /
     Remove newsletters / Archive old mail).
  2. Click "Connect Gmail", enter your address + paste the App Password.
     - "Remember me on this computer" (optional): saves the password in
       Windows' own encrypted Credential Manager, never as plain text, and
       only after a real successful connection.
     - "Save diagnostic logs (advanced)" (optional, off by default): writes a
       technical log to %LOCALAPPDATA%\GmailCleaner\logs\ if you ever need to
       troubleshoot a problem. Never logs your password or email content.
  3. Click "Scan my inbox" (a 7,000-email inbox takes a couple of minutes).
  4. Read the dashboard: your Inbox Health score, three recommended next steps,
     and "What we noticed" insights. Click "Show inbox details" for the full stats.
  4. Or click "Start cleaning" / "Review senders" to see every sender as a card,
     each with a confidence rating (stars) and a suggested action.
       - 🔒 Protected senders (banks, family, travel, gov...) can't be deleted.
       - "Select likely junk" ticks the safe-to-clear senders for you.
       - Filter by the category chips or the search box.
  5. Click "Move to Trash" OR "Archive".
     - Trash  = goes to Trash, auto-deletes after 30 days (recoverable).
     - Archive = leaves inbox, stays in "All Mail" (nothing deleted).
  6. "Unsubscribe" (on selected senders that offer it): one-click senders are
     unsubscribed automatically; the rest open in your browser to finish. Only
     unsubscribe from senders you recognize. This does NOT delete existing mail.
  7. Made a mistake? Click "Undo" to put those emails right back.
  8. Click "Finish" any time to see what you accomplished.

FILES
  gmail_cleaner_fluent.py .. entry point (thin shim into the ui/ package)
  ui/ ....................... the Fluent UI, split by page/concern
  gmail_backend.py .......... the IMAP engine (no GUI; unit-tested)
  test_backend.py ........... offline tests for the engine
  run_checks.py .............. runs test_backend.py + smoke_ui.py as one gate
  gmail_cleaner.py ........... older zero-dependency Tkinter version (still works)

SAFE BY DESIGN
  - Scanning only READS your inbox (opened read-only); it changes nothing.
  - Only email HEADERS are read (who/subject/date/size) - never message bodies.
  - Trash is recoverable for 30 days inside Gmail. Archive deletes nothing.
  - Every action shows a confirmation with exact counts first.
  - The App Password is only used to log in and is never saved to disk.
