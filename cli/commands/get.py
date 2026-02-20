"""
drp get — fetch a clipboard drop or download a file.

  drp get <key>              print clipboard to stdout
  drp get <key> --url        print the drop URL without fetching content
  drp get -f <key>           download file (saves to current directory)
  drp get -f <key> -o name   download with custom filename
  drp get -f <key> --url     print the file drop URL without downloading
  drp get <key> --timing     show per-phase timing breakdown
"""

import sys

import requests

from cli import config, api
from cli.session import auto_login
from cli.timing import Timer


def cmd_get(args):
    t = Timer(enabled=getattr(args, 'timing', False))

    cfg = config.load()
    host = cfg.get('host')
    if not host:
        print('  ✗ Not configured. Run: drp setup')
        sys.exit(1)

    t.checkpoint('load config')

    if getattr(args, 'url', False):
        if getattr(args, 'file', False):
            print(f'{host}/f/{args.key}/')
        else:
            print(f'{host}/{args.key}/')
        return

    session = requests.Session()
    t.instrument(session)
    auto_login(cfg, host, session)

    t.checkpoint('load session')

    if getattr(args, 'file', False):
        _get_file(args, host, session, t)
    else:
        _get_clipboard(args, host, session, t)


# ── Clipboard ─────────────────────────────────────────────────────────────────

def _get_clipboard(args, host, session, t):
    from cli.spinner import Spinner

    with Spinner('fetching'):
        kind, content = api.get_clipboard(host, session, args.key, timer=t)

    if kind == 'text':
        t.print()
        print(content)
        return

    if kind is None and content is None:
        try:
            with Spinner('checking'):
                res = session.get(
                    f'{host}/f/{args.key}/',
                    headers={'Accept': 'application/json'},
                    timeout=10,
                )
            if res.ok and res.json().get('kind') == 'file':
                t.print()
                print(f'  ↳ This is a file drop. Use: drp get -f {args.key}')
                return
        except Exception:
            pass

        t.print()
        sys.exit(1)


# ── File ──────────────────────────────────────────────────────────────────────

def _get_file(args, host, session, t):
    # Spinner covers the metadata fetch; the progress bar takes over once
    # bytes start flowing, so there's no overlap.
    from cli.spinner import Spinner

    with Spinner('fetching'):
        kind, result = api.get_file(host, session, args.key)

    if kind != 'file' or result is None:
        t.print()
        sys.exit(1)

    content, filename = result
    output_name = getattr(args, 'output', None) or filename or args.key

    t.checkpoint('download complete')

    try:
        with open(output_name, 'wb') as f:
            f.write(content)
    except OSError as e:
        print(f'  ✗ Could not write {output_name}: {e}', file=sys.stderr)
        t.print()
        sys.exit(1)

    t.print()
    print(f'  ✓ Saved {output_name}')