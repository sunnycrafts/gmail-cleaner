"""
Gmail Inbox Cleaner — Fluent edition, entry point.

The application itself lives in the ui/ package (see ui/app.py and the
pages/workers/widgets modules alongside it) — this file is kept as a thin,
stably-named shim so existing build tooling (GmailCleaner.iss,
GmailCleaner.spec, PyInstaller commands) can keep targeting this exact
filename unchanged. Before v1.4.0 this file held all ~1,400 lines of the UI
in one module; see CHANGELOG.md for why it was split.
"""
from ui.app import main

if __name__ == "__main__":
    main()
