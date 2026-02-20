"""
Formatting helpers: human-readable sizes, times, and minimal ANSI color.

Color is gated on the 'ansi' key in config (set by drp setup) and
sys.stdout.isatty() / sys.stderr.isatty() so nothing leaks into pipes or logs.

Override with FORCE_COLOR=1 env var for terminals that don't report isatty()
correctly (some tmux, screen, VS Code, SSH setups).
"""

import math
import os
import sys
from datetime import datetime, timezone as tz


# ── Human-readable sizes and times ────────────────────────────────────────────

def human_size(n):
    """1234567 → '1.2 M'  (like ls -lh)"""
    if not n:
        return '-'
    units = ['B', 'K', 'M', 'G', 'T']
    i = int(math.log(max(n, 1), 1024))
    i = min(i, len(units) - 1)
    val = n / (1024 ** i)
    if i == 0:
        return f'{n}B'
    return f'{val:.1f}{units[i]}'


def human_time(iso_str):
    """ISO datetime → human-friendly relative or absolute."""
    if not iso_str:
        return '-'
    try:
        dt = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
        now = datetime.now(tz.utc)
        secs = (now - dt).total_seconds()
        if secs < 60:
            return 'just now'
        if secs < 3600:
            return f'{int(secs / 60)}m ago'
        if secs < 86400:
            return f'{int(secs / 3600)}h ago'
        if secs < 86400 * 7:
            return f'{int(secs / 86400)}d ago'
        return dt.strftime('%Y-%m-%d')
    except Exception:
        return iso_str[:10]


# ── ANSI color ─────────────────────────────────────────────────────────────────
#
# Emits escape codes when ANY of these are true:
#   1. FORCE_COLOR env var is set (user override for broken TTY detection)
#
# And NONE of these are true:
#   1. NO_COLOR env var is set  (no-color.org)
#   2. config has ansi=false
#
# Without FORCE_COLOR, also requires the target stream to be a real TTY.
#
# Use the stream= kwarg to check stderr instead of stdout (e.g. progress bar).

def _ansi_on(stream=None) -> bool:
    # NO_COLOR always wins
    if os.environ.get('NO_COLOR'):
        return False
    # FORCE_COLOR overrides TTY detection (but still respects NO_COLOR and config)
    if os.environ.get('FORCE_COLOR'):
        try:
            from cli import config as _cfg
            return bool(_cfg.load().get('ansi', False))
        except Exception:
            return True
    # Normal path: check config then TTY
    try:
        from cli import config as _cfg
        if not _cfg.load().get('ansi', False):
            return False
    except Exception:
        return False
    target = stream if stream is not None else sys.stdout
    return getattr(target, 'isatty', lambda: False)()


def _c(code: str, text: str, stream=None) -> str:
    if _ansi_on(stream):
        return f'\033[{code}m{text}\033[0m'
    return text


# Public helpers — import these wherever you want color.

def green(text, stream=None):  return _c('32', text, stream)
def red(text, stream=None):    return _c('31', text, stream)
def dim(text, stream=None):    return _c('2',  text, stream)
def bold(text, stream=None):   return _c('1',  text, stream)
def cyan(text, stream=None):   return _c('36', text, stream)