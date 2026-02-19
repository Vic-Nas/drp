"""
drp ls — list drops.

  drp ls             list keys (clipboards + files + saved)
  drp ls -l          long format with size, time, expiry (human-readable sizes)
  drp ls -l --bytes  long format with raw byte counts
  drp ls -t c        only clipboards
  drp ls -t f        only files
  drp ls -t s        only saved (bookmarked) drops
  drp ls --export    export as JSON (includes saved)
"""

import json
import sys
from datetime import datetime, timezone

import requests

from cli import config
from cli.session import auto_login


# ── Formatting helpers ────────────────────────────────────────────────────────

def _human(n):
    for unit in ('B', 'K', 'M', 'G', 'T'):
        if n < 1024:
            return f'{n:.0f}{unit}' if unit == 'B' else f'{n:.1f}{unit}'
        n /= 1024
    return f'{n:.1f}P'


def _since(iso):
    if not iso:
        return '—'
    try:
        dt = datetime.fromisoformat(iso.replace('Z', '+00:00'))
        diff = datetime.now(timezone.utc) - dt
        s = int(diff.total_seconds())
        if s < 60:      return f'{s}s ago'
        if s < 3600:    return f'{s//60}m ago'
        if s < 86400:   return f'{s//3600}h ago'
        return f'{s//86400}d ago'
    except Exception:
        return iso[:10]


def _until(iso):
    if not iso:
        return 'no expiry'
    try:
        dt = datetime.fromisoformat(iso.replace('Z', '+00:00'))
        diff = dt - datetime.now(timezone.utc)
        s = int(diff.total_seconds())
        if s < 0:        return 'expired'
        if s < 3600:     return f'{s//60}m left'
        if s < 86400:    return f'{s//3600}h left'
        return f'{s//86400}d left'
    except Exception:
        return iso[:10]


# ── Main ──────────────────────────────────────────────────────────────────────

def cmd_ls(args):
    cfg = config.load()
    host = cfg.get('host')
    if not host:
        print('  ✗ Not configured. Run: drp setup')
        sys.exit(1)

    if not cfg.get('email'):
        print('  ✗ drp ls requires a logged-in account. Run: drp login')
        sys.exit(1)

    session = requests.Session()
    authed = auto_login(cfg, host, session)
    if not authed:
        print('  ✗ Not logged in. Run: drp login')
        sys.exit(1)

    try:
        res = session.get(
            f'{host}/auth/account/',
            headers={'Accept': 'application/json'},
            timeout=15,
        )
        res.raise_for_status()
        data = res.json()
    except Exception as e:
        print(f'  ✗ Could not fetch drops: {e}')
        sys.exit(1)

    drops = data.get('drops', [])
    saved = data.get('saved', [])

    # ── Filter ────────────────────────────────────────────────────────────────
    ns_filter = getattr(args, 'type', None)
    if ns_filter == 'c':
        drops = [d for d in drops if d['ns'] == 'c']
        saved = []
    elif ns_filter == 'f':
        drops = [d for d in drops if d['ns'] == 'f']
        saved = []
    elif ns_filter == 's':
        drops = []
        # saved stays as-is

    # ── Sort ──────────────────────────────────────────────────────────────────
    sort_by = getattr(args, 'sort', None)
    reverse = getattr(args, 'reverse', False)

    if sort_by == 'name':
        drops.sort(key=lambda d: d['key'], reverse=reverse)
    elif sort_by == 'size':
        drops.sort(key=lambda d: d.get('filesize', 0), reverse=not reverse)
    elif sort_by == 'time':
        drops.sort(key=lambda d: d.get('created_at', ''), reverse=not reverse)
    else:
        # Default: newest first
        drops.sort(key=lambda d: d.get('created_at', ''), reverse=True)
        saved.sort(key=lambda s: s.get('saved_at', ''), reverse=True)

    # ── Export ────────────────────────────────────────────────────────────────
    if getattr(args, 'export', False):
        out = {'drops': drops, 'saved': saved}
        json.dump(out, sys.stdout, indent=2)
        print()
        return

    long_fmt = getattr(args, 'long', False)
    raw_bytes = getattr(args, 'bytes', False)

    # ── Print ─────────────────────────────────────────────────────────────────
    all_empty = not drops and not saved
    if all_empty:
        print('  (no drops)')
        return

    if not long_fmt:
        # Short: just keys
        for d in drops:
            prefix = 'f/' if d['ns'] == 'f' else ''
            print(f'{prefix}{d["key"]}')
        for s in saved:
            prefix = 'f/' if s['ns'] == 'f' else ''
            print(f'{prefix}{s["key"]}  [saved]')
        return

    # Long format — human-readable sizes by default, raw with --bytes
    def fmt_size(n):
        if n == 0:
            return '—'
        return str(n) if raw_bytes else _human(n)

    rows = []

    # Owned drops
    for d in drops:
        prefix = 'f/' if d['ns'] == 'f' else ''
        key = f'{prefix}{d["key"]}'
        kind = '📎' if d['kind'] == 'file' else '📋'
        size = fmt_size(d['filesize']) if d['kind'] == 'file' else '—'
        created = _since(d.get('created_at'))
        expires = _until(d.get('expires_at')) if d.get('expires_at') else 'idle-based'
        locked = '🔒' if d.get('locked') else '  '
        rows.append((kind, locked, key, size, created, expires, ''))

    # Saved drops (separator if both)
    if drops and saved:
        rows.append(('', '', '', '', '', '', ''))  # blank separator

    for s in saved:
        prefix = 'f/' if s['ns'] == 'f' else ''
        key = f'{prefix}{s["key"]}'
        saved_at = _since(s.get('saved_at'))
        rows.append(('🔖', '  ', key, '—', saved_at, '—', '[saved]'))

    if not rows:
        print('  (no drops)')
        return

    # Column widths
    key_w     = max((len(r[2]) for r in rows if r[2]), default=4)
    size_w    = max((len(r[3]) for r in rows if r[3]), default=4)
    created_w = max((len(r[4]) for r in rows if r[4]), default=7)
    exp_w     = max((len(r[5]) for r in rows if r[5]), default=10)

    for kind, lock, key, size, created, exp, tag in rows:
        if not key:
            print()
            continue
        print(
            f'{kind} {lock}  '
            f'{key:<{key_w}}  '
            f'{size:>{size_w}}  '
            f'{created:>{created_w}}  '
            f'{exp:<{exp_w}}'
            + (f'  {tag}' if tag else '')
        )