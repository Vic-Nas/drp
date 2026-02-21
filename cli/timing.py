"""
cli/timing.py

Lightweight timing utility for drp commands.

Usage:
    from cli.timing import Timer

    t = Timer(enabled=args.timing)
    t.checkpoint('config load')
    t.instrument(session)
    t.checkpoint('parse response')
    t.print()
"""

import time
import sys


class Timer:
    """
    Collects named checkpoints and optionally HTTP timing splits.
    When enabled=False every method is a no-op.

    instrument() accumulates elapsed time across ALL responses on the session
    so that auto_login's network round-trip is included in the total, not
    silently dropped.
    """

    def __init__(self, enabled: bool = False):
        self.enabled = enabled
        self._start = time.perf_counter()
        self._last  = self._start
        self._steps: list[tuple[str, float]] = []
        self._total_rtt_ms: float = 0.0
        self._rtt_count: int = 0

    # ── Checkpoints ──────────────────────────────────────────────────────────

    def checkpoint(self, label: str) -> None:
        if not self.enabled:
            return
        now = time.perf_counter()
        self._steps.append((label, (now - self._last) * 1000))
        self._last = now

    # ── HTTP instrumentation ─────────────────────────────────────────────────

    def instrument(self, session) -> None:
        """
        Hook all responses on this session.  Accumulates elapsed time so
        that multiple round-trips (e.g. auto_login + the real request) are
        all visible in the timing output.
        """
        if not self.enabled:
            return

        timer = self

        def on_response(res, *args, **kwargs):
            ms = res.elapsed.total_seconds() * 1000
            timer._total_rtt_ms += ms
            timer._rtt_count += 1

        session.hooks['response'].append(on_response)

    # ── Output ───────────────────────────────────────────────────────────────

    def print(self) -> None:
        if not self.enabled:
            return

        from cli.format import dim

        total_ms = (time.perf_counter() - self._start) * 1000

        rows: list[tuple[str, float]] = list(self._steps)

        if self._rtt_count == 1:
            rows.append(('server (TTFB)', self._total_rtt_ms))
        elif self._rtt_count > 1:
            rows.append((f'server ({self._rtt_count} RTTs)', self._total_rtt_ms))

        rows.append(('total', total_ms))

        col_w = max(len(r[0]) for r in rows) + 2
        val_w = max(len(f'{r[1]:.0f}ms') for r in rows)
        sep   = '─' * (col_w + val_w + 2)

        lines = ['', f'  {dim("timing")}', f'  {dim(sep)}']
        for i, (label, ms) in enumerate(rows):
            if i == len(rows) - 1:
                lines.append(f'  {dim(sep)}')
            val = f'{ms:.0f}ms'.rjust(val_w)
            lines.append(f'  {label:<{col_w}}{val}')

        print('\n'.join(lines), file=sys.stderr)