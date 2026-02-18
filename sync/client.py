#!/usr/bin/env python3
"""
drp sync client
Watches a local folder and syncs files to a drp key per file.

Each file gets its own key: filename (without extension) by default.
Keys are stored in drp_sync.json so you know which key = which file.

Usage:
  python client.py --setup
  python client.py
"""

import os
import sys
import json
import time
import secrets
import argparse
import requests
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

CONFIG_FILE = Path.home() / '.drp_sync.json'


# ── Config ────────────────────────────────────────────────────────────────────

def load_config():
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    return {}

def save_config(cfg):
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))
    print(f'Config saved to {CONFIG_FILE}')


# ── API ───────────────────────────────────────────────────────────────────────

def get_csrf(host, session):
    """Hit home page to get CSRF cookie."""
    session.get(f'{host}/', timeout=10)
    return session.cookies.get('csrftoken', '')

def upload_file(host, session, filepath, key=None):
    """Upload a file as a Drop. Returns the key used."""
    csrf = get_csrf(host, session)
    with open(filepath, 'rb') as f:
        data = {'csrfmiddlewaretoken': csrf}
        if key:
            data['key'] = key
        try:
            res = session.post(
                f'{host}/save/',
                files={'file': (os.path.basename(filepath), f)},
                data=data,
                timeout=60
            )
            if res.ok:
                result = res.json()
                print(f'  ↑ {os.path.basename(filepath)} → {host}/{result["key"]}/')
                return result['key']
            else:
                print(f'  ✗ failed: {os.path.basename(filepath)} — {res.text}')
        except Exception as e:
            print(f'  ✗ error: {e}')
    return key

def delete_drop(host, session, key):
    """Delete a drop by key."""
    csrf = get_csrf(host, session)
    try:
        res = session.delete(
            f'{host}/{key}/delete/',
            headers={'X-CSRFToken': csrf},
            timeout=10
        )
        if res.ok:
            print(f'  ✗ deleted: {key}')
        else:
            print(f'  ~ could not delete {key}: {res.status_code}')
    except Exception as e:
        print(f'  ✗ error deleting {key}: {e}')


# ── Key mapping ───────────────────────────────────────────────────────────────

def key_for_file(filename, key_map):
    """Get existing key for a filename or None."""
    return key_map.get(filename)

def slug(name):
    """Turn a filename into a url-safe slug."""
    stem = Path(name).stem
    safe = ''.join(c if c.isalnum() or c in '-_' else '-' for c in stem).strip('-')
    return safe[:40] or secrets.token_urlsafe(6)


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
        if event.is_directory: return
        name = os.path.basename(event.src_path)
        print(f'[+] {name}')
        suggested_key = self.key_map.get(name) or slug(name)
        key = upload_file(self.host, self.session, event.src_path, key=suggested_key)
        if key:
            self.key_map[name] = key
            self._save()

    def on_modified(self, event):
        if event.is_directory: return
        name = os.path.basename(event.src_path)
        print(f'[~] {name}')
        key = self.key_map.get(name)
        new_key = upload_file(self.host, self.session, event.src_path, key=key)
        if new_key:
            self.key_map[name] = new_key
            self._save()

    def on_deleted(self, event):
        if event.is_directory: return
        name = os.path.basename(event.src_path)
        key = self.key_map.pop(name, None)
        if key:
            print(f'[-] {name} (key: {key})')
            delete_drop(self.host, self.session, key)
            self._save()
        else:
            print(f'[-] {name} (no key tracked, skipping)')


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='drp sync client')
    parser.add_argument('--host', default=None, help='drp host (e.g. https://drp.yourdomain.com)')
    parser.add_argument('--folder', default=None, help='Local folder to watch')
    parser.add_argument('--setup', action='store_true', help='Run setup wizard')
    args = parser.parse_args()

    cfg = load_config()

    if args.setup or not cfg.get('host') or not cfg.get('folder'):
        print('drp sync setup')
        print('──────────────')
        default_host = cfg.get('host', 'http://localhost:8000')
        cfg['host'] = input(f'Host [{default_host}]: ').strip() or default_host
        default_folder = cfg.get('folder', str(Path.home() / 'drp-sync'))
        cfg['folder'] = input(f'Folder [{default_folder}]: ').strip() or default_folder
        cfg.setdefault('key_map', {})
        save_config(cfg)

    host = args.host or cfg['host']
    folder = Path(args.folder or cfg['folder']).expanduser().resolve()
    key_map = cfg.get('key_map', {})

    if not folder.exists():
        folder.mkdir(parents=True)
        print(f'Created: {folder}')

    print(f'\ndrp sync')
    print(f'  host:   {host}')
    print(f'  folder: {folder}')
    print(f'  tracking {len(key_map)} file(s)\n')

    session = requests.Session()

    # Initial sync
    for f in sorted(folder.iterdir()):
        if f.is_file():
            existing_key = key_map.get(f.name)
            print(f'[init] {f.name}')
            key = upload_file(host, session, str(f), key=existing_key or slug(f.name))
            if key:
                key_map[f.name] = key

    cfg['key_map'] = key_map
    save_config(cfg)

    print('\nwatching for changes… (Ctrl+C to stop)\n')

    handler = SyncHandler(host, folder, key_map, cfg)
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


if __name__ == '__main__':
    main()