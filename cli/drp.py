#!/usr/bin/env python3
"""
drp — drop clipboards and files from the command line.

  drp up "text"          drop a clipboard  →  /c/key/
  drp up file.pdf        drop a file       →  /f/key/
  drp get key            print or download
  drp ls -lh             list with sizes and times
  drp rm key             delete
"""

import sys
import os
import json
import getpass
import argparse
import math
from datetime import datetime, timezone as tz
from pathlib import Path

import requests

from cli import config, api


# ── Session persistence ───────────────────────────────────────────────────────

SESSION_FILE = config.CONFIG_DIR / 'session.json'


def _load_session(session):
    if SESSION_FILE.exists():
        try:
            session.cookies.update(json.loads(SESSION_FILE.read_text()))
        except Exception:
            pass


def _save_session(session):
    config.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_FILE.write_text(json.dumps(dict(session.cookies)) + '\n')


def _clear_session():
    if SESSION_FILE.exists():
        SESSION_FILE.unlink()


def _auto_login(cfg, host, session, required=False):
    """Reuse saved session. Only re-prompt if expired or missing."""
    email = cfg.get('email')
    if not email:
        return False

    _load_session(session)
    try:
        res = session.get(
            f'{host}/auth/account/',
            headers={'Accept': 'application/json'},
            timeout=10,
            allow_redirects=False,
        )
        if res.status_code == 200:
            return True
    except Exception:
        pass

    password = getpass.getpass(f'  Session expired. Password for {email}: ')
    if api.login(host, session, email, password):
        _save_session(session)
        return True

    print('  ⚠ Login failed, continuing as anonymous.')
    if required:
        sys.exit(1)
    return False


# ── Formatting helpers ────────────────────────────────────────────────────────

def _human_size(n):
    """1234567 → '1.2M'  (like ls -lh)"""
    if n is None or n == 0:
        return '-'
    units = ['', 'K', 'M', 'G', 'T']
    i = int(math.log(max(n, 1), 1024))
    i = min(i, len(units) - 1)
    val = n / (1024 ** i)
    if i == 0:
        return f'{n}B'
    return f'{val:.1f}{units[i]}'


def _human_time(iso_str):
    """ISO datetime → human-friendly relative or absolute."""
    if not iso_str:
        return '-'
    try:
        dt = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
        now = datetime.now(tz.utc)
        delta = now - dt
        secs = delta.total_seconds()
        if secs < 60:
            return 'just now'
        if secs < 3600:
            return f'{int(secs/60)}m ago'
        if secs < 86400:
            return f'{int(secs/3600)}h ago'
        if secs < 86400 * 7:
            return f'{int(secs/86400)}d ago'
        return dt.strftime('%Y-%m-%d')
    except Exception:
        return iso_str[:10]


def _expiry_str(drop):
    """Return a human expiry string for a drop dict."""
    expires_at = drop.get('expires_at')
    if expires_at:
        return _human_time(expires_at)
    ns = drop.get('ns', 'c')
    if ns == 'c':
        last = drop.get('last_accessed_at') or drop.get('created_at')
        return f'idle+24h (last: {_human_time(last)})'
    return '90d from create'


def _ns_label(ns):
    return 'clip' if ns == 'c' else 'file'


# ── PATH check (Windows) ──────────────────────────────────────────────────────

def _check_scripts_in_path():
    import sysconfig
    scripts_dir = sysconfig.get_path('scripts')
    if not scripts_dir:
        return
    if scripts_dir in os.environ.get('PATH', '').split(os.pathsep):
        return

    print(f'\n  ⚠ {scripts_dir} is not in your PATH.')
    if sys.platform == 'win32':
        answer = input('  Add it to your user PATH now? (y/n) [y]: ').strip().lower()
        if answer != 'n':
            _add_to_user_path_windows(scripts_dir)
    else:
        print(f'  Add to your shell profile:\n    export PATH="{scripts_dir}:$PATH"\n')


def _add_to_user_path_windows(scripts_dir):
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Environment', 0,
                             winreg.KEY_READ | winreg.KEY_WRITE)
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
                    0xFFFF, 0x001A, 0, 'Environment', 2, 5000, None)
            except Exception:
                pass
            print('  ✓ Added. Restart your terminal for it to take effect.')
    except Exception as e:
        print(f'  ✗ Could not update PATH: {e}\n    Add manually: {scripts_dir}')


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
    _check_scripts_in_path()
    print(f'\n  ✓ Config saved to {config.CONFIG_FILE}')


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
    print(f'  ✓ Logged out ({email})' if email else '  (already anonymous)')


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
        result = api.upload_file(host, session, target, key=key)
        if result:
            result_key, ns = result if isinstance(result, tuple) else (result, 'f')
            url = f'{host}/{result_key}/'
            print(url)
            config.record_drop(result_key, 'file', ns=ns,
                               filename=os.path.basename(target), host=host)
        else:
            sys.exit(1)
    else:
        result = api.upload_text(host, session, target, key=key)
        if result:
            result_key, ns = result if isinstance(result, tuple) else (result, 'c')
            url = f'{host}/{result_key}/'
            print(url)
            config.record_drop(result_key, 'text', ns=ns, host=host)
        else:
            sys.exit(1)


def cmd_get(args):
    cfg = config.load()
    host = cfg.get('host')
    if not host:
        print('Not configured. Run: drp setup')
        sys.exit(1)

    session = requests.Session()
    _load_session(session)  # silent — never prompts

    key = args.key
    kind, content = api.get_drop(host, session, key)

    if kind == 'text':
        print(content)
    elif kind == 'file':
        data, filename = content
        out = args.output or filename
        with open(out, 'wb') as f:
            f.write(data)
        size = _human_size(len(data))
        print(f'  ✓ {out} ({size})')
    else:
        print(f'  ✗ /{key}/ not found')
        sys.exit(1)


def cmd_rm(args):
    cfg = config.load()
    host = cfg.get('host')
    if not host:
        print('Not configured. Run: drp setup')
        sys.exit(1)

    session = requests.Session()
    _auto_login(cfg, host, session)

    # Support both bare key and ns-prefixed key (c/notes or f/report)
    key = args.key
    ns = None
    if '/' in key:
        ns, key = key.split('/', 1)

    if api.delete(host, session, key, ns=ns):
        print(f'  ✓ deleted /{key}/')
        config.remove_local_drop(key)
    else:
        print(f'  ✗ could not delete /{key}/')
        sys.exit(1)


def cmd_mv(args):
    cfg = config.load()
    host = cfg.get('host')
    if not host:
        print('Not configured. Run: drp setup')
        sys.exit(1)

    session = requests.Session()
    _auto_login(cfg, host, session)

    key = args.key
    ns = None
    if '/' in key:
        ns, key = key.split('/', 1)

    new_key = api.rename(host, session, key, args.new_key, ns=ns)
    if new_key:
        prefix = f'{ns}/' if ns else ''
        print(f'  ✓ /{prefix}{key}/ → /{prefix}{new_key}/')
        config.rename_local_drop(key, new_key)
    else:
        print(f'  ✗ could not rename /{key}/')
        sys.exit(1)


def cmd_renew(args):
    cfg = config.load()
    host = cfg.get('host')
    if not host:
        print('Not configured. Run: drp setup')
        sys.exit(1)

    session = requests.Session()
    _auto_login(cfg, host, session)

    key = args.key
    ns = None
    if '/' in key:
        ns, key = key.split('/', 1)

    expires_at, renewals = api.renew(host, session, key, ns=ns)
    if expires_at:
        print(f'  ✓ /{key}/ renewed → expires {_human_time(expires_at)} (renewal #{renewals})')
    else:
        print(f'  ✗ could not renew /{key}/')
        sys.exit(1)


def cmd_ls(args):
    cfg = config.load()
    host = cfg.get('host')
    if not host:
        print('Not configured. Run: drp setup')
        sys.exit(1)

    email = cfg.get('email')
    long_fmt = getattr(args, 'long', False)
    human = getattr(args, 'human', False)
    sort_key = getattr(args, 'sort', None)
    reverse = getattr(args, 'reverse', False)
    ns_filter = getattr(args, 'type', None)  # 'c', 'f', or None

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
                _print_drops(drops, host, long_fmt=long_fmt, human=human,
                             sort_key=sort_key, reverse=reverse, ns_filter=ns_filter,
                             source='server')
                return

    # Local list
    local = config.load_local_drops()
    if not local:
        print('  (no drops)')
        return

    anon_session = requests.Session()
    alive = []
    stale = []
    for d in local:
        if api.key_exists(host, anon_session, d['key']):
            alive.append(d)
        else:
            stale.append(d)

    if stale:
        config.save_local_drops(alive)
        if long_fmt:
            for d in stale:
                print(f"  {d['key']:30s}  (gone — renamed or expired)")

    if not alive:
        print('  (no drops)')
        return

    _print_drops(alive, host, long_fmt=long_fmt, human=human,
                 sort_key=sort_key, reverse=reverse, ns_filter=ns_filter,
                 source='local')


def _print_drops(drops, host, long_fmt=False, human=False, sort_key=None,
                 reverse=False, ns_filter=None, source='server'):

    if ns_filter:
        drops = [d for d in drops if d.get('ns', 'c') == ns_filter]

    if not drops:
        print('  (no drops)')
        return

    # Sorting
    if sort_key == 'time':
        drops = sorted(drops, key=lambda d: d.get('created_at', ''), reverse=not reverse)
    elif sort_key == 'size':
        drops = sorted(drops, key=lambda d: d.get('filesize') or 0, reverse=not reverse)
    elif sort_key == 'name':
        drops = sorted(drops, key=lambda d: d.get('key', ''), reverse=reverse)
    elif reverse:
        drops = list(reversed(drops))

    if source == 'local':
        print('  (local cache)\n')

    if long_fmt:
        # ls -l style: type  size  modified  key  url  [expiry]
        print(f"  {'TYPE':<6}  {'SIZE':>7}  {'MODIFIED':<12}  {'KEY':<25}  URL")
        print(f"  {'─'*6}  {'─'*7}  {'─'*12}  {'─'*25}  {'─'*30}")
        for d in drops:
            ns = d.get('ns', 'c')
            kind_label = _ns_label(ns)
            key = d.get('key', '?')
            drop_host = d.get('host', host) or host
            url = f'{drop_host}/{key}/'

            if human:
                size = _human_size(d.get('filesize'))
            else:
                size_raw = d.get('filesize')
                size = str(size_raw) if size_raw else '-'

            modified = _human_time(d.get('last_accessed_at') or d.get('created_at'))
            expiry = _expiry_str(d)
            name = d.get('filename', '')
            display_key = f'{key}' + (f'  ({name})' if name else '')

            print(f"  {kind_label:<6}  {size:>7}  {modified:<12}  {display_key:<25}  {url}")
            if long_fmt:
                print(f"  {'':6}  {'':>7}  {'expires:':12}  {expiry}")
    else:
        # Short format: key  type  url
        for d in drops:
            ns = d.get('ns', 'c')
            key = d.get('key', '?')
            drop_host = d.get('host', host) or host
            url = f'{drop_host}/{key}/'
            kind_label = _ns_label(ns)
            name = d.get('filename', '')
            suffix = f'  {name}' if name else ''
            print(f'  {key:<30}  {kind_label:<4}{suffix}  {url}')


def cmd_status(args):
    cfg = config.load()
    local_count = len(config.load_local_drops())
    session_active = SESSION_FILE.exists()
    print('drp status')
    print('──────────')
    print(f'  Host:        {cfg.get("host", "(not set)")}')
    print(f'  Account:     {cfg.get("email", "anonymous")}')
    print(f'  Session:     {"active" if session_active else "none (will prompt next command)"}')
    print(f'  Local drops: {local_count}')
    print(f'  Config:      {config.CONFIG_FILE}')
    print(f'  Cache:       {config.DROPS_FILE}')


def cmd_ping(args):
    """Quick connectivity check."""
    cfg = config.load()
    host = cfg.get('host')
    if not host:
        print('Not configured. Run: drp setup')
        sys.exit(1)
    try:
        res = requests.get(f'{host}/', timeout=5)
        print(f'  ✓ {host} reachable ({res.status_code})')
    except Exception as e:
        print(f'  ✗ {host} unreachable: {e}')
        sys.exit(1)


def main():
    from cli import __version__

    parser = argparse.ArgumentParser(
        prog='drp',
        description='Drop clipboards and files — get a link instantly.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
namespaces:
  /c/key   clipboard (text) — activity-based expiry: resets on each access
  /f/key   file — expires 90 days after upload
  /key     short alias → resolves to whichever exists (clipboard preferred)

examples:
  drp up "hello world" -k hello    clipboard at /c/hello  →  share as /hello
  drp up report.pdf -k q3          file at /f/q3          →  share as /q3
  drp get hello                    print clipboard content
  drp get q3 -o my-report.pdf      download and save as different name
  drp rm c/hello                   delete by namespace (or just: drp rm hello)
  drp mv q3 quarter3               rename key (blocked 24h after creation)
  drp ls                           list drops
  drp ls -lh                       list with sizes and times (like ls -lh)
  drp ls -lh -t c                  list only clipboards
  drp ls -lh --sort time           sort by modified time
  drp ls --export > backup.json    export as JSON

clipboard expiry (activity-based):
  anonymous   24h idle timeout, 7 days max lifetime
  free        48h idle timeout, 30 days max lifetime
  paid        explicit date you choose, renewable

keys:
  Set once with -k on upload — locked for 24h after creation.
  After 24h, rename with: drp mv old new
""",
    )
    parser.add_argument('--version', '-V', action='version', version=f'%(prog)s {__version__}')

    sub = parser.add_subparsers(dest='command')

    sub.add_parser('setup', help='Configure host & log in')
    sub.add_parser('login', help='Log in (session saved — no repeated prompts)')
    sub.add_parser('logout', help='Log out and clear saved session')
    sub.add_parser('ping', help='Check connectivity to the drp server')
    sub.add_parser('status', help='Show config, account, and session info')

    p_up = sub.add_parser('up', help='Upload clipboard text or file')
    p_up.add_argument('target', help='File path or text to upload')
    p_up.add_argument('--key', '-k', default=None,
                      help='Custom key (e.g. -k q3 → /q3/). Default: auto from filename')

    p_get = sub.add_parser('get', help='Print clipboard or download file (no login needed)')
    p_get.add_argument('key', help='Drop key (e.g. q3, c/notes, f/report)')
    p_get.add_argument('--output', '-o', default=None,
                       help='Save file as this name (default: original filename)')

    p_rm = sub.add_parser('rm', help='Delete a drop')
    p_rm.add_argument('key', help='Drop key (e.g. q3 or c/notes)')

    p_mv = sub.add_parser('mv', help="Rename a key (blocked 24h after creation)")
    p_mv.add_argument('key', help='Current key')
    p_mv.add_argument('new_key', help='New key')

    p_renew = sub.add_parser('renew', help="Renew expiry (paid accounts only)")
    p_renew.add_argument('key', help='Drop key')

    p_ls = sub.add_parser('ls', help='List your drops')
    p_ls.add_argument('-l', '--long', action='store_true',
                      help='Long format with size, time, and expiry (like ls -l)')
    p_ls.add_argument('-h', '--human', action='store_true',
                      help='Human-readable sizes (1.2M instead of 1234567) — use with -l')
    p_ls.add_argument('-t', '--type', choices=['c', 'f'], default=None,
                      metavar='NS',
                      help='Filter by type: c=clipboards, f=files')
    p_ls.add_argument('--sort', choices=['time', 'size', 'name'], default=None,
                      help='Sort by: time, size, or name')
    p_ls.add_argument('-r', '--reverse', action='store_true',
                      help='Reverse sort order')
    p_ls.add_argument('--export', action='store_true',
                      help='Export as JSON (requires login). Pipe: drp ls --export > drops.json')

    args = parser.parse_args()

    # Allow combined flags: drp ls -lh
    # argparse handles -l and -h separately, but -lh needs manual combination
    # This is handled automatically since both are store_true with short flags

    commands = {
        'setup':  cmd_setup,
        'login':  cmd_login,
        'logout': cmd_logout,
        'ping':   cmd_ping,
        'status': cmd_status,
        'up':     cmd_up,
        'get':    cmd_get,
        'rm':     cmd_rm,
        'mv':     cmd_mv,
        'renew':  cmd_renew,
        'ls':     cmd_ls,
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()