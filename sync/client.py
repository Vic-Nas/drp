#!/usr/bin/env python3
"""
drp sync client
Watches a local folder and syncs it to a drp bin.

Usage:
  python client.py --bin mykey --folder ~/Documents/drp --host https://yoursite.com

Config is saved to drp_sync.json after first run.
"""

import os
import sys
import json
import time
import hashlib
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


# ── API helpers ───────────────────────────────────────────────────────────────

def upload_file(host, bin_key, filepath):
    url = f'{host}/b/{bin_key}/upload/'
    with open(filepath, 'rb') as f:
        try:
            res = requests.post(url, files={'files': (os.path.basename(filepath), f)}, timeout=30)
            if res.ok:
                print(f'  ↑ uploaded: {os.path.basename(filepath)}')
            else:
                print(f'  ✗ failed: {os.path.basename(filepath)} — {res.text}')
        except Exception as e:
            print(f'  ✗ error uploading {os.path.basename(filepath)}: {e}')


def delete_file_by_name(host, bin_key, filename):
    # Fetch file list to find ID
    try:
        res = requests.get(f'{host}/b/{bin_key}/', timeout=10)
        # Simple parse — in prod you'd have a /api/bin/<key>/files/ endpoint
        print(f'  ~ delete not yet implemented via API for: {filename}')
    except Exception as e:
        print(f'  ✗ error: {e}')


# ── Watchdog handler ──────────────────────────────────────────────────────────

class SyncHandler(FileSystemEventHandler):
    def __init__(self, host, bin_key, folder):
        self.host = host
        self.bin_key = bin_key
        self.folder = folder

    def on_created(self, event):
        if event.is_directory: return
        print(f'[+] new file: {event.src_path}')
        upload_file(self.host, self.bin_key, event.src_path)

    def on_modified(self, event):
        if event.is_directory: return
        print(f'[~] modified: {event.src_path}')
        upload_file(self.host, self.bin_key, event.src_path)

    def on_deleted(self, event):
        if event.is_directory: return
        filename = os.path.basename(event.src_path)
        print(f'[-] deleted: {filename}')
        delete_file_by_name(self.host, self.bin_key, filename)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='drp sync client')
    parser.add_argument('--bin', help='Bin key to sync to')
    parser.add_argument('--folder', help='Local folder to watch')
    parser.add_argument('--host', default='http://localhost:8000', help='drp host URL')
    parser.add_argument('--setup', action='store_true', help='Run setup wizard')
    args = parser.parse_args()

    cfg = load_config()

    # Setup wizard
    if args.setup or not cfg:
        print('drp sync setup')
        print('──────────────')
        cfg['host'] = input(f'Host [{args.host}]: ').strip() or args.host
        cfg['bin_key'] = input('Bin key: ').strip()
        cfg['folder'] = input('Local folder to sync: ').strip()
        save_config(cfg)

    # CLI args override config
    host = args.host if args.host != 'http://localhost:8000' else cfg.get('host', args.host)
    bin_key = args.bin or cfg.get('bin_key')
    folder = args.folder or cfg.get('folder')

    if not bin_key or not folder:
        print('Error: bin key and folder required. Run with --setup')
        sys.exit(1)

    folder = Path(folder).expanduser().resolve()
    if not folder.exists():
        folder.mkdir(parents=True)
        print(f'Created folder: {folder}')

    print(f'\ndrp sync started')
    print(f'  bin:    {host}/b/{bin_key}/')
    print(f'  folder: {folder}')
    print(f'  watching for changes...\n')

    # Initial sync — upload everything in folder
    for f in folder.iterdir():
        if f.is_file():
            print(f'[initial] uploading {f.name}')
            upload_file(host, bin_key, str(f))

    # Watch
    handler = SyncHandler(host, bin_key, folder)
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