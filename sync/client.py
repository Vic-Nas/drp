#!/usr/bin/env python3
"""
drp sync client — lightweight OneDrive-style folder sync.

Watches a local folder and uploads every file under its own drp key.
Supports authenticated sessions so drops get plan-based expiry and locking.

Usage:
  python client.py --setup          # first-time config
  python client.py                  # start syncing
  python client.py --login          # (re)authenticate
  python client.py --status         # show config & tracked files
"""

import os
import sys
import json
import time
import getpass
import secrets
import argparse
import requests
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

CONFIG_FILE = Path.home() / '.drp_sync.json'


# ── Config ────────────────────────────────────────────────────────────────────

def load_config(path=None):
    p = Path(path) if path else CONFIG_FILE
    if p.exists():
        return json.loads(p.read_text())
    return {}


def save_config(cfg, path=None):
    p = Path(path) if path else CONFIG_FILE
    p.write_text(json.dumps(cfg, indent=2))


# ── API helpers ───────────────────────────────────────────────────────────────

def get_csrf(host, session):
    """Hit home page to obtain the csrftoken cookie."""
    session.get(f'{host}/', timeout=10)
    return session.cookies.get('csrftoken', '')


def api_login(host, session, email, password):
    """Authenticate with the drp server. Returns True on success."""
    csrf = get_csrf(host, session)
    res = session.post(
        f'{host}/auth/login/',
        data={'email': email, 'password': password, 'csrfmiddlewaretoken': csrf},
        timeout=10,
        allow_redirects=False,
    )
    # Django login redirects on success (302), returns 200 with form on failure
    return res.status_code in (302, 301)


def check_remote_key(host, session, key):
    """Return True if the key still exists on the server."""
    try:
        res = session.get(f'{host}/check-key/', params={'key': key}, timeout=10)
        if res.ok:
            return not res.json().get('available', True)  # available=False → exists
    except Exception:
        pass
    return False


def upload_file(host, session, filepath, key=None):
    """Upload a file as a Drop. Returns the key used, or None on failure."""
    csrf = get_csrf(host, session)
    try:
        with open(filepath, 'rb') as f:
            data = {'csrfmiddlewaretoken': csrf}
            if key:
                data['key'] = key
            res = session.post(
                f'{host}/save/',
                files={'file': (os.path.basename(filepath), f)},
                data=data,
                timeout=120,
            )
        if res.ok:
            result = res.json()
            print(f'  ↑ {os.path.basename(filepath)} → /{result["key"]}/')
            return result['key']
        else:
            print(f'  ✗ upload failed: {os.path.basename(filepath)} — {res.text[:200]}')
    except Exception as e:
        print(f'  ✗ upload error: {e}')
    return None


def delete_drop(host, session, key):
    """Delete a drop by key."""
    csrf = get_csrf(host, session)
    try:
        res = session.delete(
            f'{host}/{key}/delete/',
            headers={'X-CSRFToken': csrf},
            timeout=10,
        )
        if res.ok:
            print(f'  ✗ deleted remote: {key}')
        else:
            print(f'  ~ could not delete {key}: {res.status_code}')
    except Exception as e:
        print(f'  ✗ error deleting {key}: {e}')


# ── Key mapping ───────────────────────────────────────────────────────────────

def slug(name):
    """Turn a filename into a url-safe slug (max 40 chars)."""
    stem = Path(name).stem
    safe = ''.join(c if c.isalnum() or c in '-_' else '-' for c in stem).strip('-')
    return safe[:40] or secrets.token_urlsafe(6)


# ── Staleness check ──────────────────────────────────────────────────────────

def check_stale_keys(host, session, key_map):
    """
    Verify tracked keys still exist remotely.
    Returns (live, stale) where each is a dict {filename: key}.
    """
    live, stale = {}, {}
    for filename, key in key_map.items():
        if check_remote_key(host, session, key):
            live[filename] = key
        else:
            stale[filename] = key
    return live, stale


# ── Watchdog handler ──────────────────────────────────────────────────────────

class SyncHandler(FileSystemEventHandler):
    def __init__(self, host, folder, key_map, cfg):
        self.host = host
        self.folder = folder
        self.key_map = key_map  # filename → key
        self.cfg = cfg
        self.session = requests.Session()

    def _save(self):
        self.cfg['key_map'] = self.key_map
        save_config(self.cfg)

    def on_created(self, event):
        if event.is_directory:
            return
        name = os.path.basename(event.src_path)
        if name.startswith('.'):
            return
        print(f'[+] {name}')
        suggested_key = self.key_map.get(name) or slug(name)
        key = upload_file(self.host, self.session, event.src_path, key=suggested_key)
        if key:
            self.key_map[name] = key
            self._save()

    def on_modified(self, event):
        if event.is_directory:
            return
        name = os.path.basename(event.src_path)
        if name.startswith('.'):
            return
        print(f'[~] {name}')
        key = self.key_map.get(name)
        new_key = upload_file(self.host, self.session, event.src_path, key=key)
        if new_key:
            self.key_map[name] = new_key
            self._save()

    def on_deleted(self, event):
        if event.is_directory:
            return
        name = os.path.basename(event.src_path)
        key = self.key_map.pop(name, None)
        if key:
            print(f'[-] {name} (key: {key})')
            delete_drop(self.host, self.session, key)
            self._save()


# ── CLI ───────────────────────────────────────────────────────────────────────

def cmd_setup(cfg):
    """Interactive first-time setup."""
    print('drp sync setup')
    print('──────────────')
    default_host = cfg.get('host', 'https://drp.vic.so')
    cfg['host'] = input(f'  Host [{default_host}]: ').strip() or default_host
    default_folder = cfg.get('folder', str(Path.home() / 'drp-sync'))
    cfg['folder'] = input(f'  Sync folder [{default_folder}]: ').strip() or default_folder
    cfg.setdefault('key_map', {})

    # Offer login
    answer = input('  Log in now? (y/n) [y]: ').strip().lower()
    if answer != 'n':
        cmd_login(cfg)

    save_config(cfg)
    print(f'\n  Config saved to {CONFIG_FILE}')

    folder = Path(cfg['folder']).expanduser().resolve()
    if not folder.exists():
        folder.mkdir(parents=True)
        print(f'  Created sync folder: {folder}')

    print('\n  Run `make sync` or `python sync/client.py` to start syncing.')


def cmd_login(cfg):
    """Authenticate and store session cookies."""
    host = cfg.get('host', 'https://drp.vic.so')
    email = input('  Email: ').strip()
    password = getpass.getpass('  Password: ')
    session = requests.Session()
    if api_login(host, session, email, password):
        cfg['cookies'] = dict(session.cookies)
        cfg['email'] = email
        save_config(cfg)
        print('  ✓ Logged in — drops will be owned by your account.')
    else:
        print('  ✗ Login failed. Drops will be anonymous (24h/90d expiry).')


def cmd_status(cfg):
    """Show current config and tracked files."""
    print('drp sync status')
    print('────────────────')
    print(f'  Host:    {cfg.get("host", "(not set)")}')
    print(f'  Folder:  {cfg.get("folder", "(not set)")}')
    print(f'  Account: {cfg.get("email", "anonymous")}')
    key_map = cfg.get('key_map', {})
    print(f'  Tracked: {len(key_map)} file(s)')
    for filename, key in sorted(key_map.items()):
        print(f'    {filename} → /{key}/')


def cmd_sync(cfg, args):
    """Main sync loop."""
    host = args.host or cfg.get('host')
    folder_path = args.folder or cfg.get('folder')

    if not host or not folder_path:
        print('Not configured. Run: make sync-setup')
        sys.exit(1)

    folder = Path(folder_path).expanduser().resolve()
    if not folder.exists():
        folder.mkdir(parents=True)
        print(f'Created: {folder}')

    key_map = cfg.get('key_map', {})
    session = requests.Session()

    # Restore auth cookies if available
    cookies = cfg.get('cookies', {})
    for name, value in cookies.items():
        session.cookies.set(name, value)

    print(f'drp sync')
    print(f'  host:    {host}')
    print(f'  folder:  {folder}')
    print(f'  account: {cfg.get("email", "anonymous")}')
    print(f'  tracked: {len(key_map)} file(s)')

    # ── Staleness check ───────────────────────────────────────────────────
    if key_map:
        print('\nchecking remote keys…')
        live, stale = check_stale_keys(host, session, key_map)
        if stale:
            print(f'  {len(stale)} expired/missing — will re-upload if local file exists')
            for filename, key in stale.items():
                print(f'    ✗ {filename} (was /{key}/)')
            key_map = live
        else:
            print(f'  all {len(live)} keys alive')

    # ── Initial sync ──────────────────────────────────────────────────────
    print('\nsyncing local files…')
    local_files = {f.name for f in folder.iterdir() if f.is_file() and not f.name.startswith('.')}

    for name in sorted(local_files):
        filepath = folder / name
        existing_key = key_map.get(name)
        if existing_key:
            print(f'  ✓ {name} → /{existing_key}/ (already tracked)')
        else:
            print(f'  ↑ {name} (new)')
            key = upload_file(host, session, str(filepath), key=slug(name))
            if key:
                key_map[name] = key

    # Clean orphan entries (tracked files no longer on disk)
    orphans = set(key_map.keys()) - local_files
    for name in orphans:
        print(f'  ~ {name} removed locally, cleaning remote')
        delete_drop(host, session, key_map.pop(name))

    cfg['key_map'] = key_map
    save_config(cfg)

    # ── Watch for changes ─────────────────────────────────────────────────
    print('\nwatching for changes… (Ctrl+C to stop)\n')
    handler = SyncHandler(host, folder, key_map, cfg)
    handler.session = session
    observer = Observer()
    observer.schedule(handler, str(folder), recursive=False)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        print('\nSync stopped.')
    observer.join()


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='drp sync — folder sync for drp')
    parser.add_argument('--host', default=None, help='drp host URL')
    parser.add_argument('--folder', default=None, help='Local folder to watch')
    parser.add_argument('--setup', action='store_true', help='Run setup wizard')
    parser.add_argument('--login', action='store_true', help='Log in to drp')
    parser.add_argument('--status', action='store_true', help='Show config & tracked files')
    args = parser.parse_args()

    cfg = load_config()

    if args.setup:
        cmd_setup(cfg)
    elif args.login:
        cmd_login(cfg)
    elif args.status:
        cmd_status(cfg)
    else:
        cmd_sync(cfg, args)


if __name__ == '__main__':
    main()
