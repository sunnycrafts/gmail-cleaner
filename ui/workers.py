"""Background QThread workers. None of these touch widgets directly — they
only emit Qt signals, which the GUI thread receives via queued connections.
This is what keeps the window responsive during multi-minute IMAP scans.
"""

from PySide6.QtCore import QThread, Signal

import gmail_backend as gb


class ScanWorker(QThread):
    progress = Signal(str, int, int)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, addr, pwd):
        super().__init__()
        self.addr, self.pwd = addr, pwd
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            res = gb.scan(self.addr, self.pwd,
                          progress=lambda s, d, t: self.progress.emit(s, d, t),
                          should_stop=lambda: self._stop)
            self.done.emit(res)
        except Exception as e:
            self.failed.emit(str(e))


class ActionWorker(QThread):
    progress = Signal(int, int)
    done = Signal(int)
    failed = Signal(str)

    def __init__(self, addr, pwd, uids, mode, undo=False):
        super().__init__()
        self.addr, self.pwd, self.uids, self.mode = addr, pwd, uids, mode
        self.undo = undo

    def run(self):
        try:
            fn = gb.undo_action if self.undo else gb.do_action
            n = fn(self.addr, self.pwd, self.uids, self.mode,
                   progress=lambda d, t: self.progress.emit(d, t))
            self.done.emit(n)
        except Exception as e:
            self.failed.emit(str(e))


class UnsubscribeWorker(QThread):
    """Fires RFC 8058 one-click POSTs for senders that support them."""
    done = Signal(int, int)   # succeeded, attempted
    failed = Signal(str)

    def __init__(self, urls):
        super().__init__()
        self.urls = urls

    def run(self):
        try:
            ok = sum(1 for u in self.urls if gb.one_click_unsubscribe(u))
            self.done.emit(ok, len(self.urls))
        except Exception as e:
            self.failed.emit(str(e))


class LabelWorker(QThread):
    """Applies one or more (label, uids) groups. Additive-only — never moves
    or deletes anything, so a failure partway through just leaves fewer
    labels applied than intended, not a broken inbox."""
    progress = Signal(int, int)   # groups done, groups total
    done = Signal(int, int)       # total emails tagged, groups done
    failed = Signal(str)

    def __init__(self, addr, pwd, groups):
        super().__init__()
        self.addr, self.pwd, self.groups = addr, pwd, groups

    def run(self):
        try:
            total_tagged = 0
            for i, (label, uids) in enumerate(self.groups, start=1):
                total_tagged += gb.apply_label(self.addr, self.pwd, uids, label)
                self.progress.emit(i, len(self.groups))
            self.done.emit(total_tagged, len(self.groups))
        except Exception as e:
            self.failed.emit(str(e))
