# Changelog — Gmail Inbox Cleaner

All notable changes to this project are documented here.
This project follows semantic versioning.

## [1.4.0] — 2026-08-06

Remediation release — implements the technical-debt findings from the
code-backed engineering review, in priority order (High → Low).

### Added
- **Git version control** for the project (was previously untracked). Baseline
  commit captures the working v1.3.0 state before this release's changes.
- **`run_checks.py`** — a CI-lite gate wrapping the backend test suite and the
  UI smoke test into one pass/fail command; now the mandatory pre-build step.
- **`SenderRecord` TypedDict** documenting the sender-record schema for static
  type checking / IDE autocomplete (no runtime behavior change — still a plain
  dict everywhere).
- **Retry with exponential backoff** for `connect()` (transient network errors
  only — never a bad password, to avoid triggering Gmail's suspicious-login
  flagging) and `one_click_unsubscribe()` (transient/5xx only — 4xx fails fast
  since retrying a rejected request won't help).
- **Opt-in diagnostics logging** — off by default; a "Save diagnostic logs
  (advanced)" checkbox on Connect turns on a rotating log file at
  `%LOCALAPPDATA%\GmailCleaner\logs\`. Never logs passwords or email content.
- **"Remember me" credential storage** — opt-in, stores the App Password in
  Windows Credential Manager via `keyring` (never plaintext on disk), and only
  after a *confirmed-working* connection, never on a typo. Email address is
  cached separately (non-secret) to prefill the field next time.
- **UI split into a package** — `gmail_cleaner_fluent.py` (1,432 lines, 12
  classes) is now a 14-line entry-point shim over a new `ui/` package
  (`theme.py`, `utils.py`, `workers.py`, `widgets.py`, `pages/*.py`, `app.py`).
  No behavior change — verified via `run_checks.py` and a live app launch
  through the new entry point.

### Fixed
- Removed a redundant `PROTECTED_CATEGORIES` confidence penalty in `assess()`
  that only affected an already-unused numeric value for protected senders.

### Notes
- Both distributables (`--collect-all keyring` added to the PyInstaller
  command, alongside the existing `--collect-all qfluentwidgets`) were
  rebuilt and verified to launch — portable and the *installed* copy after a
  silent install. The build log showed no keyring-related warnings, consistent
  with the metadata being bundled correctly; a full credential-manager
  write/read round-trip from inside the frozen EXE itself was not separately
  exercised beyond the app launching without error.
- Deferred (not in this release): a real MailProvider abstraction (Outlook/
  other-provider support), memory/perf work (measured as a non-issue at
  current scale), verified screen-reader support, Mica/acrylic visual polish.

## [1.3.0] — 2026-07-31

Unsubscribe release.

### Added
- **Unsubscribe** action on the senders page (bulk, on the current selection):
  - Senders that support **RFC 8058 one-click** are unsubscribed automatically via
    a background POST (https only).
  - The rest **open in your browser** (one tab each) to finish.
  - A confirmation dialog shows the split (auto vs browser) and a privacy caveat
    (unsubscribing confirms a live address; only do it for senders you recognize).
  - The button enables only when the selection includes senders that offer it.
- Scan now also reads `List-Unsubscribe` / `List-Unsubscribe-Post` (still headers
  only) and stores the unsubscribe URL, mailto, and one-click capability per sender.
- Dashboard insight: "N senders support a 1-click unsubscribe."

### Notes
- The `mailto:`-only unsubscribe path opens the user's mail client but is not
  auto-sent. SMTP-based unsubscribe remains out of scope.
- Unsubscribing does not delete existing mail — Trash separately if desired.

## [1.2.0] — 2026-07-31

Craftsmanship release — refinement, discoverability, and trust (per product review v2).

### Added
- **Goal-based onboarding** — a welcome screen picks a goal (Just tidy up / Free up
  storage / Remove newsletters / Archive old mail) before credentials; the goal
  reorders the dashboard's recommended actions.
- **Reorganized dashboard** — a single Inbox Health hero, a trust-chip row, **three
  goal-tailored recommended actions**, and a "What we noticed" insights card above the
  fold; all analytics moved behind a **Show inbox details** toggle (progressive disclosure).
- **Explained recommendations** — each sender card now shows the *reasons* behind its
  rating ("Has an unsubscribe link", "Marked important in Gmail", "Last received over a
  year ago", …), with the full list on hover.
- **Smart insights** — e.g. "Just 8 senders account for 55% of your removable mail",
  "Clearing Social first frees ~201 MB".
- **Natural-language-ish search** — queries like `older than 2 years newsletter unread`,
  `protected`, `important`, `government`, `large` (a keyword parser, not an LLM).
- **Archive old mail** one-click action (bulk senders inactive 2+ years).
- **Trust chips** throughout (Headers only · Recoverable 30 days · Undo anytime · Nothing
  permanent).
- **Expanded finish screen** — now leads with **% inbox reduction** and an undo reminder.
- **Fade page transitions**; keyboard/focus **accessible names** and larger touch targets.

### Notes
- Deferred to a later release: Mica/acrylic, skeleton loading, and verified
  screen-reader/high-contrast support (best-effort a11y only for now). Reply-based
  confidence scoring still omitted — not available cheaply over IMAP.

## [1.1.0] — 2026-07-31

Confidence & trust release — reduce decisions, increase user confidence.

### Added
- **Protected senders** — Finance, Travel, Personal, and gov/health/utility senders
  (plus anything Gmail marks Important) are auto-protected: badged "🔒 Protected"
  and never selectable for deletion.
- **Confidence stars + suggested action** on every sender card (★1–5 with
  "Move to Trash" / "Archive" / "Keep"), derived only from real IMAP signals:
  category, unread ratio, age, volume, stars (\Flagged/\Starred), Gmail Important,
  labels, and List-Unsubscribe. (Deliberately NOT "last opened" or "replies" —
  IMAP can't provide those cheaply.)
- **Inbox Health score** (0–100) on the dashboard, with a hero card and a single
  "Start cleaning" call to action.
- **Quick Cleanup presets** — one-click "Clean Promotions / Social / Notifications /
  Subscriptions" with a preview of emails + storage, protected senders excluded.
- **Undo** the last Trash/Archive (restores mail to the inbox).
- **Celebration finish screen** — emails cleared, storage recovered, senders handled,
  protected count.
- **Lazy sender list** — renders 20 at a time with "Load more" (replaces the old
  500-card cap); filtering and selection persist across pages.

### Changed
- Scan now also fetches `X-GM-LABELS` (stars/important/labels) — still headers only.
- Dashboard reorganized around Health + next-best-action instead of raw stats.

### Fixed
- Stat-card numbers were near-invisible in light theme (a stylesheet cleared the
  themed text color) — now given an explicit theme-aware color.

## [1.0.2] — 2026-07-29

### Changed
- **Installer** now packages a folder-based (PyInstaller onedir) build instead of
  wrapping the single-file EXE. The installed app launches instantly (no per-launch
  unpacking), and the setup is smaller (~73 MB vs ~108 MB) thanks to real compression.
- Portable `GmailCleaner.exe` remains single-file/onefile, unchanged.

## [1.0.1] — 2026-07-29

### Changed
- App now uses a fixed **light** design (was auto light/dark following the OS).

## [1.0.0] — 2026-07-27

First packaged release. Portable EXE + installer.

### Added
- **Fluent (Windows 11) UI** rebuilt in PySide6 + qfluentwidgets:
  - Progressive-disclosure connect screen (one "Connect Gmail" button first).
  - Staged scan progress ("Reading mailbox… Grouping senders…").
  - **Summary dashboard**: totals, "X% from Y senders" concentration insight,
    biggest-senders bar chart, category breakdown, promotional/bulk reclaim card.
  - **Sender card list** with colored category pills, per-category filter chips,
    text filter, and "Select likely junk".
  - Actions: Move to Trash / Archive, with confirmation showing exact counts.
- **Backend engine** (`gmail_backend.py`), UI-agnostic and unit-tested:
  - Header-only IMAP scan (adds RFC822.SIZE, Date, List-Unsubscribe).
  - Rule-based categorization (Promotions/Shopping/Social/Finance/Travel/
    Subscriptions/Notifications/Personal).
  - `summarize()` for dashboard stats (80% concentration, reclaimable size, etc.).
- **Distribution**: portable `GmailCleaner.exe` (PyInstaller onefile) and
  `GmailCleaner-Setup.exe` (Inno Setup, Start-menu + optional desktop shortcut,
  uninstaller). Custom app icon.

### Notes
- Predecessor: `gmail_cleaner.py`, a zero-dependency Tkinter version (retained).
- Fixes during build: transparent scroll backgrounds (OS-palette bleed-through),
  `rgba()` pill colors (Qt reads 8-digit hex alpha-first), and ampersand-as-
  accelerator in button labels.
