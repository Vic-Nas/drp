#!/usr/bin/env python3
"""
drp — drop files and text from the command line, get a link instantly.

Quick start:
  drp setup                        configure host & log in
  drp up report.pdf -k q3          upload with a memorable key → drp.vicnas.me/q3/
  drp up "some text"               upload text → auto key
  drp get q3                       download to disk (files) or print (text)
  drp ls                           list your drops
  drp rm q3                        delete a drop

Keys are the address of your drop. Pick something memorable with -k,
or get an auto-generated one. Keys can't be changed within 24h of creation.
"""

import sys
import os
import json
import getpass
import argparse
import requests

from cli import config, api


# ── Session persistence ───────────────────────────────────────────────────────

SESSION_FILE = config.CONFIG_DIR / 'session.json'


def _load_session(session):
    """Load saved cookies into a requests session."""
    if SESSION_FILE.exists():
        try:
            cookies = json.loads(SESSION_FILE.read_text())
            session.cookies.update(cookies)
        except Exception:
            pass


def _save_session(session):
    """Persist current cookies to disk."""
    config.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_FILE.write_text(json.dumps(dict(session.cookies)) + '\n')


def _clear_session():
    """Delete saved session cookies."""
    if SESSION_FILE.exists():
        SESSION_FILE.unlink()


def _auto_login(cfg, host, session, required=False):
    """
    Try to reuse saved session first. If expired, prompt for password.
    Returns True if authenticated, False if anonymous.
    """
    email = cfg.get('email')
    if not email:
        return False

    # Try saved session first — no password prompt
    _load_session(session)
    try:
        res = session.get(
            f'{host}/auth/account/',
            headers={'Accept': 'application/json'},
            timeout=10,
            allow_redirects=False,
        )
        if res.status_code == 200:
            return True  # session still valid
    except Exception:
        pass

    # Session expired — re-authenticate
    password = getpass.getpass(f'  Session expired. Password for {email}: ')
    if api.login(host, session, email, password):
        _save_session(session)
        return True

    print('  ⚠ Login failed, continuing as anonymous.')
    if required:
        sys.exit(1)
    return False


# ── PATH check (Windows) ──────────────────────────────────────────────────────

def _check_scripts_in_path():
    import sysconfig
    scripts_dir = sysconfig.get_path('scripts')
    if not scripts_dir:
        return
    path_dirs = os.environ.get('PATH', '').split(os.pathsep)
    if scripts_dir in path_dirs:
        return

    print(f'\n  ⚠ {scripts_dir} is not in your PATH.')
    print('    The `drp` command may not work in new terminals.\n')

    if sys.platform == 'win32':
        answer = input('  Add it to your user PATH now? (y/n) [y]: ').strip().lower()
        if answer != 'n':
            _add_to_user_path_windows(scripts_dir)
    else:
        print('  Add this to your shell profile (~/.bashrc, ~/.zshrc, etc.):')
        print(f'    export PATH="{scripts_dir}:$PATH"\n')


def _add_to_user_path_windows(scripts_dir):
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, r'Environment', 0,
            winreg.KEY_READ | winreg.KEY_WRITE,
        )
        try:
            current, _ = winreg.QueryValueEx(key, 'PATH')
        except FileNotFoundError:
            current = ''
        if scripts_dir.lower() not in current.lower():
            new_path = f'{current};{scripts_dir}' if current else scripts_dir
            winreg.SetValueEx(key, 'PATH', 0, winreg.REG_EXPAND_SZ, new_path)
            winreg.CloseKey(key)
            try:
                import ctypes
                ctypes.windll.user32.SendMessageTimeoutW(
                    0xFFFF, 0x001A, 0, 'Environment', 2, 5000, None
                )
            except Exception:
                pass
            print('  ✓ Added to PATH. Restart your terminal for it to take effect.')
        else:
            print('  ✓ Already in PATH (may need a terminal restart).')
    except Exception as e:
        print(f'  ✗ Could not update PATH automatically: {e}')
        print(f'    Add manually: {scripts_dir}')


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_setup(args):
    cfg = config.load()
    print('drp setup')
    print('─────────')
    default = cfg.get('host', 'https://drp.vicnas.me')
    cfg['host'] = input(f'  Host [{default}]: ').strip() or default
    config.save(cfg)

    answer = input('  Log in now? (y/n) [y]: ').strip().lower()
    if answer != 'n':
        cmd_login(args)
    else:
        config.save(cfg)

    _check_scripts_in_path()
    print(f'\n  ✓ Saved to {config.CONFIG_FILE}')


def cmd_login(args):
    cfg = config.load()
    host = cfg.get('host', 'https://drp.vicnas.me')
    email = input('  Email: ').strip()
    password = getpass.getpass('  Password: ')
    session = requests.Session()
    if api.login(host, session, email, password):
        cfg['email'] = email
        config.save(cfg)
        _save_session(session)
        print(f'  ✓ Logged in as {email}')
    else:
        print('  ✗ Login failed.')
        sys.exit(1)


def cmd_logout(args):
    cfg = config.load()
    email = cfg.pop('email', None)
    config.save(cfg)
    _clear_session()
    if email:
        print(f'  ✓ Logged out ({email})')
    else:
        print('  (already anonymous)')


def cmd_up(args):
    cfg = config.load()
    host = cfg.get('host')
    if not host:
        print('Not configured. Run: drp setup')
        sys.exit(1)

    session = requests.Session()
    _auto_login(cfg, host, session)

    target = args.target
    key = args.key

    if os.path.isfile(target):
        if not key:
            key = api.slug(os.path.basename(target))
        result_key = api.upload_file(host, session, target, key=key)
        if result_key:
            print(f'{host}/{result_key}/')
            config.record_drop(result_key, 'file', filename=os.path.basename(target), host=host)
        else:
            sys.exit(1)
    else:
        result_key = api.upload_text(host, session, target, key=key)
        if result_key:
            print(f'{host}/{result_key}/')
            config.record_drop(result_key, 'text', host=host)
        else:
            sys.exit(1)


def cmd_get(args):
    cfg = config.load()
    host = cfg.get('host')
    if not host:
        print('Not configured. Run: drp setup')
        sys.exit(1)

    # get never prompts for password — drops are public
    session = requests.Session()
    _load_session(session)  # silently reuse session if available

    key = args.key
    kind, content = api.get_drop(host, session, key)

    if kind == 'text':
        print(content)
    elif kind == 'file':
        data, filename = content
        out = args.output or filename
        with open(out, 'wb') as f:
            f.write(data)
        print(f'  ✓ {out} ({len(data):,} bytes)')
    else:
        sys.exit(1)


def cmd_rm(args):
    cfg = config.load()
    host = cfg.get('host')
    if not host:
        print('Not configured. Run: drp setup')
        sys.exit(1)

    session = requests.Session()
    _auto_login(cfg, host, session)

    if api.delete(host, session, args.key):
        print(f'  ✓ deleted /{args.key}/')
        config.remove_local_drop(args.key)
    else:
        print(f'  ✗ could not delete /{args.key}/')
        sys.exit(1)


def cmd_mv(args):
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
        config.rename_local_drop(args.key, new_key)
    else:
        print(f'  ✗ could not rename /{args.key}/')
        sys.exit(1)


def cmd_renew(args):
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
    cfg = config.load()
    host = cfg.get('host')
    if not host:
        print('Not configured. Run: drp setup')
        sys.exit(1)

    email = cfg.get('email')

    if email:
        session = requests.Session()
        authed = _auto_login(cfg, host, session)

        if authed and getattr(args, 'export', False):
            try:
                res = session.get(f'{host}/auth/account/export/', timeout=15)
                if res.ok:
                    print(res.text)
                    return
                print('  ✗ Export failed.')
            except Exception as e:
                print(f'  ✗ Export error: {e}')
            sys.exit(1)

        if authed:
            drops = api.list_drops(host, session)
            if drops is not None:
                _print_drops(drops, host, source='server')
                return

    # Local list (anonymous or login failed)
    local = config.load_local_drops()
    if not local:
        print('  (no drops — drops you upload will appear here)')
        return

    # Reconcile: remove drops that no longer exist on the server
    anon_session = requests.Session()
    alive = [d for d in local if api.key_exists(host, anon_session, d['key'])]
    if len(alive) != len(local):
        config.save_local_drops(alive)
        local = alive

    if not local:
        print('  (no drops — drops you upload will appear here)')
        return
    _print_drops(local, host, source='local')


def _print_drops(drops, host, source='server'):
    if not drops:
        print('  (no drops)')
        return

    if source == 'local':
        print('  (local cache)')

    for d in drops:
        kind = d.get('kind', '?')
        key = d.get('key', '?')
        name = d.get('filename') or ''
        drop_host = d.get('host', host) or host
        url = f'{drop_host}/{key}/'
        if kind == 'file' and name:
            print(f'  {key:30s}  {kind:4s}  {name:30s}  {url}')
        else:
            print(f'  {key:30s}  {kind:4s}  {url}')


def cmd_status(args):
    cfg = config.load()
    local_count = len(config.load_local_drops())
    session_active = SESSION_FILE.exists()
    print('drp status')
    print('──────────')
    print(f'  Host:        {cfg.get("host", "(not set)")}')
    print(f'  Account:     {cfg.get("email", "anonymous")}')
    print(f'  Session:     {"active" if session_active else "none (will prompt on next command)"}')
    print(f'  Local drops: {local_count}')
    print(f'  Config:      {config.CONFIG_FILE}')
    print(f'  Drop cache:  {config.DROPS_FILE}')


def main():
    from cli import __version__

    parser = argparse.ArgumentParser(
        prog='drp',
        description='Drop files and text from the command line — get a link instantly.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  drp up report.pdf -k q3       upload with a memorable key → drp.vicnas.me/q3/
  drp up "hello world"          upload text, get an auto key
  drp get q3                    download to disk (files) or print (text)
  drp get q3 -o my-report.pdf   download and save as a different name
  drp rm q3                     delete a drop
  drp mv q3 quarter3            rename a drop's key
  drp ls                        list your drops
  drp ls --export > backup.json export drops as JSON

keys:
  Pick a memorable key with -k, or get a random one automatically.
  Keys are locked for 24h after creation — use -k on upload to set it right.
  Anonymous drops expire after 24h (text) or 90 days (files).
  Paid accounts get longer expiry, locked drops, and renewals.
""",
    )
    parser.add_argument('--version', '-V', action='version', version=f'%(prog)s {__version__}')
    sub = parser.add_subparsers(dest='command')

    sub.add_parser('setup', help='Configure host & log in')
    sub.add_parser('login', help='Log in to drp')
    sub.add_parser('logout', help='Log out and clear saved session')

    p_up = sub.add_parser('up', help='Upload a file or text')
    p_up.add_argument('target', help='File path or text string to upload')
    p_up.add_argument('--key', '-k', default=None,
                      help='Custom key (e.g. -k q3 → drp.vicnas.me/q3/). Default: auto from filename')

    p_get = sub.add_parser('get', help='Download or print a drop (no login needed)')
    p_get.add_argument('key', help='Drop key')
    p_get.add_argument('--output', '-o', default=None,
                       help='Save file as this name (default: original filename)')

    p_rm = sub.add_parser('rm', help='Delete a drop')
    p_rm.add_argument('key', help='Drop key')

    p_mv = sub.add_parser('mv', help="Rename a drop's key (blocked for 24h after creation)")
    p_mv.add_argument('key', help='Current key')
    p_mv.add_argument('new_key', help='New key')

    p_renew = sub.add_parser('renew', help="Renew a drop's expiry (paid accounts only)")
    p_renew.add_argument('key', help='Drop key')

    p_ls = sub.add_parser('ls', help='List your drops')
    p_ls.add_argument('--export', action='store_true',
                      help='Export as JSON (requires login). Pipe with: drp ls --export > backup.json')

    sub.add_parser('status', help='Show config and session info')

    args = parser.parse_args()

    commands = {
        'setup':  cmd_setup,
        'login':  cmd_login,
        'logout': cmd_logout,
        'up':     cmd_up,
        'get':    cmd_get,
        'rm':     cmd_rm,
        'mv':     cmd_mv,
        'renew':  cmd_renew,
        'ls':     cmd_ls,
        'status': cmd_status,
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()