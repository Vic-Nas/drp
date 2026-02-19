"""
Formatting helpers: human-readable sizes and times.
"""

import math
from datetime import datetime, timezone as tz


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