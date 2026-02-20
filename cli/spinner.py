"""
cli/spinner.py

Lightweight terminal spinner. Runs in a background thread — the calling
thread is never blocked. Safe to use anywhere.

Usage:
    with Spinner("fetching"):
        result = slow_network_call()

    # or manually:
    s = Spinner("loading")
    s.start()
    result = slow_call()
    s.stop()

The spinner is suppressed automatically when stderr is not a TTY or when
ANSI color is disabled, so it never pollutes pipes or logs.
"""

import sys
import threading
import time

_FRAMES = ['⣾', '⣽', '⣻', '⢿', '⡿', '⣟', '⣯', '⣷']
_INTERVAL = 0.08  # seconds per frame

# Carriage return + erase to end of line
_CLEAR = '\r\033[K'


def _tty_ok() -> bool:
    """Only spin when stderr is an interactive terminal."""
    return sys.stderr.isatty()


class Spinner:
    """
    Context-manager spinner that runs on a daemon thread.

    On stop/exit it erases itself completely — the caller prints whatever
    the real output is on a clean line.
    """

    def __init__(self, label: str = ''):
        self._label    = label
        self._thread   = None
        self._stop_evt = threading.Event()

    # ── Context manager ───────────────────────────────────────────────────────

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_):
        self.stop()

    # ── Manual control ────────────────────────────────────────────────────────

    def start(self):
        if not _tty_ok():
            return
        self._stop_evt.clear()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()

    def stop(self):
        if self._thread is None:
            return
        self._stop_evt.set()
        self._thread.join()
        self._thread = None
        if _tty_ok():
            # Erase the spinner line so the caller prints on a clean line
            sys.stderr.write(_CLEAR)
            sys.stderr.flush()

    # ── Worker ────────────────────────────────────────────────────────────────

    def _spin(self):
        i = 0
        while not self._stop_evt.wait(timeout=_INTERVAL):
            frame = _frames()[i % len(_frames())]
            label = f'  {frame}  {self._label}' if self._label else f'  {frame}'
            sys.stderr.write(f'\r{label}')
            sys.stderr.flush()
            i += 1
        # Final erase happens in stop() on the main thread


def _frames():
    """Return colored frames if ANSI is on, plain otherwise."""
    try:
        from cli.format import dim
        return [dim(f) for f in _FRAMES]
    except Exception:
        return _FRAMES