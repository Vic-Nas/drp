"""
cli/completion.py

Shell tab-completion for drp.

Command completion:    handled by argcomplete from the parser itself.
Key completion:        reads the local drop cache (~/.config/drp/drops.json)
                       immediately (so the shell sees results in <1ms), then
                       fires a background thread to refresh the cache from the
                       server so the *next* completion is up to date.

Background refresh rules:
  - Only runs if a session file exists (avoids prompting for a password mid-tab)
  - Skips refresh if the cache was written within the last REFRESH_INTERVAL_SECS
  - One process at a time (lock file prevents pile-up on repeated tabs)
  - Silent — any error is swallowed; completions must never break the shell
  - Prunes local-only entries whose host matches the server but are no longer
    returned by the server (expired/deleted drops)

Usage (in drp.py):
    import argcomplete
    from cli.completion import key_completer, file_key_completer
    ...
    p_get.add_argument('key').completer = key_completer
    argcomplete.autocomplete(parser)
"""

import os
import sys
import time
import threading
from pathlib import Path

# How stale the cache can be before a background refresh is triggered (seconds).
REFRESH_INTERVAL_SECS = 30


# ── Completers ────────────────────────────────────────────────────────────────

def key_completer(prefix, parsed_args, **kwargs):
    """
    Complete clipboard keys by default; file keys when -f is set.
    """
    is_file = getattr(parsed_args, 'file', False)
    ns = 'f' if is_file else 'c'
    return _complete(prefix, ns)


def file_key_completer(prefix, parsed_args, **kwargs):
    """Complete file-drop keys only."""
    return _complete(prefix, 'f')


def clipboard_key_completer(prefix, parsed_args, **kwargs):
    """Complete clipboard keys only."""
    return _complete(prefix, 'c')


def any_key_completer(prefix, parsed_args, **kwargs):
    """Complete keys from both namespaces."""
    return _complete(prefix, ns=None)


# ── Core ──────────────────────────────────────────────────────────────────────

def _complete(prefix: str, ns: str | None) -> list[str]:
    keys = _read_cache(ns, prefix)
    _trigger_background_refresh()
    return keys


def _read_cache(ns: str | None, prefix: str) -> list[str]:
    """Read drops.json and return matching keys. Never raises."""
    try:
        from cli import config
        drops = config.load_local_drops()
        results = []
        for d in drops:
            if ns is not None and d.get('ns') != ns:
                continue
            key = d.get('key', '')
            if key.startswith(prefix):
                results.append(key)
        return results
    except Exception:
        return []


# ── Background refresh ────────────────────────────────────────────────────────

def _trigger_background_refresh() -> None:
    try:
        from cli import config
        from cli.session import SESSION_FILE

        if not SESSION_FILE.exists():
            return

        drops_file = config.DROPS_FILE
        if drops_file.exists():
            age = time.time() - drops_file.stat().st_mtime
            if age < REFRESH_INTERVAL_SECS:
                return

        t = threading.Thread(target=_refresh_worker, daemon=True)
        t.start()
        t.join(timeout=0.05)
    except Exception:
        pass


def _refresh_worker() -> None:
    try:
        from cli import config
        from cli.session import SESSION_FILE

        lock_path = config.CONFIG_DIR / '.refresh.lock'

        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
        except FileExistsError:
            return
        except Exception:
            return

        try:
            _do_refresh(config, SESSION_FILE)
        finally:
            try:
                lock_path.unlink(missing_ok=True)
            except Exception:
                pass

    except Exception:
        pass


def _do_refresh(config, SESSION_FILE) -> None:
    """Fetch server drop list, merge into local cache, and prune dead entries."""
    import requests as req_lib
    from cli.session import load_session

    cfg = config.load()
    host = cfg.get('host')
    if not host:
        return

    session = req_lib.Session()
    load_session(session)

    try:
        res = session.get(
            f'{host}/auth/account/',
            headers={'Accept': 'application/json'},
            timeout=8,
        )
    except Exception:
        return

    if not res.ok:
        return

    try:
        data = res.json()
    except Exception:
        return

    server_drops = data.get('drops', [])
    saved_drops  = data.get('saved', [])

    # Build a set of (ns, key) pairs the server currently knows about.
    server_keys = set()
    for d in server_drops:
        ns  = d.get('ns', 'c')
        key = d.get('key', '')
        if key:
            server_keys.add((ns, key))
    for s in saved_drops:
        ns  = s.get('ns', 'c')
        key = s.get('key', '')
        if key:
            server_keys.add((ns, key))

    existing = config.load_local_drops()
    existing_by_key = {}
    for d in existing:
        ns  = d.get('ns', 'c')
        key = d.get('key', '')
        if not key:
            continue
        drop_host = d.get('host', '')

        # Prune: drop is from this host, logged-in session is active,
        # but the server no longer lists it → expired or deleted.
        if drop_host == host and (ns, key) not in server_keys:
            continue  # omit — drop is gone from server

        existing_by_key[(ns, key)] = d

    # Merge server drops in (server is authoritative for fields it returns).
    for d in server_drops:
        ns  = d.get('ns', 'c')
        key = d.get('key', '')
        if not key:
            continue
        existing_by_key[(ns, key)] = {
            'key':        key,
            'ns':         ns,
            'kind':       d.get('kind', 'text'),
            'created_at': d.get('created_at', ''),
            'host':       host,
            'filename':   d.get('filename') or None,
        }

    for s in saved_drops:
        ns  = s.get('ns', 'c')
        key = s.get('key', '')
        if not key:
            continue
        if (ns, key) not in existing_by_key:
            existing_by_key[(ns, key)] = {
                'key':        key,
                'ns':         ns,
                'kind':       'text' if ns == 'c' else 'file',
                'created_at': s.get('saved_at', ''),
                'host':       host,
            }

    merged = sorted(
        existing_by_key.values(),
        key=lambda d: d.get('created_at', ''),
        reverse=True,
    )
    config.save_local_drops(merged)