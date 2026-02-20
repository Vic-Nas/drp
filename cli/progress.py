"""
cli/progress.py

Terminal progress bar for upload/download.  No external dependencies.

Usage:
    bar = ProgressBar(total_bytes, label="uploading")
    bar.update(chunk_size)   # call as bytes flow
    bar.done()               # print newline + summary
"""

import sys
import time

_BAR_WIDTH = 30  # inner fill characters

# ANSI escape: carriage return + erase to end of line.
# Clears leftover bar characters before printing the summary line so the
# two don't collide when the summary is shorter than the bar was.
_CLEAR = '\r\033[K'


class ProgressBar:
    """
    Renders a progress bar to stderr like:
      uploading  [=============>        ]  62%  6.2M/10.0M  1.4 MB/s

    When stderr is not a tty (e.g. piped / redirected) all rendering is
    suppressed so no escape sequences or partial lines pollute the output.
    """

    def __init__(self, total: int, label: str = ""):
        self.total   = max(total, 1)
        self.label   = label
        self.done_   = 0
        self._start  = time.monotonic()
        self._tty    = sys.stderr.isatty()
        self._render()

    # ── Public ────────────────────────────────────────────────────────────────

    def update(self, n: int):
        self.done_ = min(self.done_ + n, self.total)
        self._render()

    def done(self, msg: str = ""):
        self.done_ = self.total
        elapsed = time.monotonic() - self._start
        speed   = self.total / elapsed if elapsed > 0 else 0

        if self._tty:
            # Erase the in-progress bar line completely before printing summary
            sys.stderr.write(
                f"{_CLEAR}  ✓ {self.label}  {_fmt(self.total)}  "
                f"({_fmt(speed)}/s  {elapsed:.1f}s)\n"
            )
        else:
            sys.stderr.write(
                f"  ✓ {self.label}  {_fmt(self.total)}  "
                f"({_fmt(speed)}/s  {elapsed:.1f}s)\n"
            )
        sys.stderr.flush()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _render(self):
        if not self._tty:
            return  # never write partial bar lines to non-interactive stderr

        pct     = self.done_ / self.total
        filled  = int(pct * _BAR_WIDTH)
        arrow   = ">" if filled < _BAR_WIDTH else ""
        bar     = "=" * filled + arrow + " " * (_BAR_WIDTH - filled - len(arrow))

        elapsed = time.monotonic() - self._start
        speed   = self.done_ / elapsed if elapsed > 0.1 else 0
        speed_s = f"  {_fmt(speed)}/s" if speed > 0 else ""

        line = (
            f"\r  {self.label:<12} [{bar}] "
            f"{int(pct * 100):>3}%  "
            f"{_fmt(self.done_)}/{_fmt(self.total)}"
            f"{speed_s}"
        )
        sys.stderr.write(line)
        sys.stderr.flush()


def _fmt(n: float) -> str:
    """Format bytes as human-readable string."""
    for unit in ("B", "K", "M", "G", "T"):
        if n < 1024:
            return f"{n:.1f}{unit}" if unit != "B" else f"{int(n)}B"
        n /= 1024
    return f"{n:.1f}P"