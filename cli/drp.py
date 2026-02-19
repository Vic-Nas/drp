#!/usr/bin/env python3
"""
drp — command-line tool for dropping text and files.

Usage:
  drp setup                     # configure host & login
  drp login                     # (re)authenticate
  drp up <file>                 # upload a file
  drp up <file> --key myname    # upload with a custom key
  drp up "some text"            # upload text
  drp get <key>                 # download a drop
  drp rm <key>                  # delete a drop
  drp mv <key> <new-key>        # rename a drop
  drp renew <key>               # renew a drop's expiry
  drp ls                        # list your drops (requires login)
  drp status                    # show config
"""

import sys
import os
import getpass
import argparse
import requests

from cli import config, api


def cmd_setup(args):
    """Interactive first-time setup."""
    cfg = config.load()
    print('drp setup')
    print('─────────')
    default = cfg.get('host', 'https://drp.vic.so')
    cfg['host'] = input(f'  Host [{default}]: ').strip() or default
    config.save(cfg)

    answer = input('  Log in now? (y/n) [y]: ').strip().lower()
    if answer != 'n':
        cmd_login(args)
    else:
        config.save(cfg)

    print(f'\n  ✓ Saved to {config.CONFIG_FILE}')


def cmd_login(args):
    """Log in to drp."""
    cfg = config.load()
    host = cfg.get('host', 'https://drp.vic.so')
    email = input('  Email: ').strip()
    password = getpass.getpass('  Password: ')
    session = requests.Session()
    if api.login(host, session, email, password):
        cfg['email'] = email
        config.save(cfg)
        print(f'  ✓ Logged in as {email}')
    else:
        print('  ✗ Login failed.')
        sys.exit(1)


def cmd_up(args):
    """Upload a file or text."""
    cfg = config.load()
    host = cfg.get('host')
    if not host:
        print('Not configured. Run: drp setup')
        sys.exit(1)

    session = requests.Session()
    _auto_login(cfg, host, session)

    target = args.target
    key = args.key

    # If target is a file path that exists, upload as file
    if os.path.isfile(target):
        if not key:
            key = api.slug(os.path.basename(target))
        result_key = api.upload_file(host, session, target, key=key)
        if result_key:
            url = f'{host}/{result_key}/'
            print(f'{url}')
        else:
            sys.exit(1)
    else:
        # Treat as text content
        result_key = api.upload_text(host, session, target, key=key)
        if result_key:
            url = f'{host}/{result_key}/'
            print(f'{url}')
        else:
            sys.exit(1)


def cmd_get(args):
    """Download a drop."""
    cfg = config.load()
    host = cfg.get('host')
    if not host:
        print('Not configured. Run: drp setup')
        sys.exit(1)

    session = requests.Session()
    _auto_login(cfg, host, session)

    key = args.key
    kind, content = api.get_drop(host, session, key)

    if kind == 'text':
        print(content)
    elif kind == 'file':
        data, filename = content
        out = args.output or filename
        with open(out, 'wb') as f:
            f.write(data)
        print(f'  ✓ {out} ({len(data)} bytes)')
    else:
        print(f'  ✗ drop not found: {key}')
        sys.exit(1)


def cmd_rm(args):
    """Delete a drop."""
    cfg = config.load()
    host = cfg.get('host')
    if not host:
        print('Not configured. Run: drp setup')
        sys.exit(1)

    session = requests.Session()
    _auto_login(cfg, host, session)

    if api.delete(host, session, args.key):
        print(f'  ✓ deleted /{args.key}/')
    else:
        print(f'  ✗ could not delete /{args.key}/')
        sys.exit(1)


def cmd_mv(args):
    """Rename a drop's key."""
    cfg = config.load()
    host = cfg.get('host')
    if not host:
        print('Not configured. Run: drp setup')
        sys.exit(1)

    session = requests.Session()
    _auto_login(cfg, host, session)

    new_key = api.rename(host, session, args.key, args.new_key)
    if new_key:
        print(f'  ✓ /{args.key}/ → /{new_key}/')
    else:
        print(f'  ✗ could not rename /{args.key}/')
        sys.exit(1)


def cmd_renew(args):
    """Renew a drop's expiry."""
    cfg = config.load()
    host = cfg.get('host')
    if not host:
        print('Not configured. Run: drp setup')
        sys.exit(1)

    session = requests.Session()
    _auto_login(cfg, host, session)

    expires_at, renewals = api.renew(host, session, args.key)
    if expires_at:
        print(f'  ✓ /{args.key}/ renewed (expires {expires_at}, #{renewals})')
    else:
        print(f'  ✗ could not renew /{args.key}/')
        sys.exit(1)


def cmd_ls(args):
    """List your drops."""
    cfg = config.load()
    host = cfg.get('host')
    if not host:
        print('Not configured. Run: drp setup')
        sys.exit(1)

    session = requests.Session()
    _auto_login(cfg, host, session)

    drops = api.list_drops(host, session)
    if drops is None:
        print('  ✗ could not list drops (are you logged in?)')
        sys.exit(1)

    if not drops:
        print('  (no drops)')
        return

    for d in drops:
        kind = d['kind']
        key = d['key']
        name = d.get('filename') or ''
        if kind == 'file' and name:
            print(f'  {key:30s}  {kind:4s}  {name}')
        else:
            print(f'  {key:30s}  {kind:4s}')


def cmd_status(args):
    """Show current config."""
    cfg = config.load()
    print('drp status')
    print('──────────')
    print(f'  Host:    {cfg.get("host", "(not set)")}')
    print(f'  Account: {cfg.get("email", "anonymous")}')
    print(f'  Config:  {config.CONFIG_FILE}')


def _auto_login(cfg, host, session):
    """Silently log in if email is saved. Continues anonymously on failure."""
    email = cfg.get('email')
    if email:
        password = getpass.getpass(f'  Password for {email}: ')
        if not api.login(host, session, email, password):
            print('  ⚠ Login failed, continuing as anonymous.')


def main():
    from cli import __version__

    parser = argparse.ArgumentParser(
        prog='drp',
        description='Drop text and files from the command line.',
    )
    parser.add_argument('--version', '-V', action='version', version=f'%(prog)s {__version__}')
    sub = parser.add_subparsers(dest='command')

    # setup
    sub.add_parser('setup', help='Configure host & login')

    # login
    sub.add_parser('login', help='Log in to drp')

    # up
    p_up = sub.add_parser('up', help='Upload a file or text')
    p_up.add_argument('target', help='File path or text string to upload')
    p_up.add_argument('--key', '-k', default=None, help='Custom key (default: auto from filename)')

    # get
    p_get = sub.add_parser('get', help='Download a drop')
    p_get.add_argument('key', help='Drop key to download')
    p_get.add_argument('--output', '-o', default=None, help='Output filename (files only)')

    # rm
    p_rm = sub.add_parser('rm', help='Delete a drop')
    p_rm.add_argument('key', help='Drop key to delete')

    # mv (rename)
    p_mv = sub.add_parser('mv', help='Rename a drop key')
    p_mv.add_argument('key', help='Current drop key')
    p_mv.add_argument('new_key', help='New key')

    # renew
    p_renew = sub.add_parser('renew', help='Renew a drop expiry')
    p_renew.add_argument('key', help='Drop key to renew')

    # ls
    sub.add_parser('ls', help='List your drops (requires login)')

    # status
    sub.add_parser('status', help='Show config')

    args = parser.parse_args()

    commands = {
        'setup': cmd_setup,
        'login': cmd_login,
        'up': cmd_up,
        'get': cmd_get,
        'rm': cmd_rm,
        'mv': cmd_mv,
        'renew': cmd_renew,
        'ls': cmd_ls,
        'status': cmd_status,
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
