"""
drp get — retrieve a clipboard or file drop.

  drp get key          clipboard → stdout
  drp get -f key       file drop → saved to disk
  drp get -f key -o out save with custom filename
"""

import sys

import requests

from cli import config, api
from cli.session import load_session
from cli.format import human_size


def cmd_get(args):
    cfg = config.load()
    host = cfg.get('host')
    if not host:
        print('  ✗ Not configured. Run: drp setup')
        sys.exit(1)

    session = requests.Session()
    load_session(session)  # silent — never prompts for password

    key = args.key

    if args.file:
        _get_file(host, session, key, args)
        return

    kind, content = api.get_clipboard(host, session, key)
    if kind == 'text':
        print(content)
        return

    print(f'  ✗ No clipboard drop found for /{key}/')
    print(f'  → If this is a file, try: drp get -f {key}')
    sys.exit(1)


def _get_file(host, session, key, args):
    kind, content = api.get_file(host, session, key)
    if kind != 'file':
        print(f'  ✗ File drop /f/{key}/ not found.')
        sys.exit(1)
    _save_file(content, key, args)


def _save_file(content, key, args):
    data, filename = content
    out = args.output or filename
    with open(out, 'wb') as f:
        f.write(data)
    print(f'  ✓ Saved {out} ({human_size(len(data))})')