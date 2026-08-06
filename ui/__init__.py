"""Gmail Inbox Cleaner — Fluent UI package.

Split out of a single 1,400+ line gmail_cleaner_fluent.py (see CHANGELOG.md,
v1.4.0) so each page/concern is independently readable. gmail_backend.py is
untouched by this split — it has no dependency on this package, only the
reverse (ui -> gmail_backend), same as before.
"""
