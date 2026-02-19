#!/usr/bin/env python3
"""
drp — drop clipboards and files from the command line.

  drp up "text"          drop a clipboard  →  /key/
  drp up file.pdf        drop a file       →  /f/key/
  drp get key            clipboard → stdout
  drp get f/key          file → saved to disk
  drp ls -lh             list with sizes and times
  drp rm key             delete clipboard
  drp rm f/key           delete file
"""

import argparse
import sys

from cli import __version__
from cli.commands.setup import cmd_setup, cmd_login, cmd_logout
from cli.commands.upload import cmd_up
from cli.commands.get import cmd_get
from cli.commands.manage import cmd_rm, cmd_mv, cmd_renew
from cli.commands.ls import cmd_ls
from cli.commands.status import cmd_status, cmd_ping


def main():
    parser = argparse.ArgumentParser(
        prog='drp',
        description='Drop clipboards and files — get a link instantly.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
urls:
  /key/      clipboard — activity-based expiry
  /f/key/    file — expires 90 days after upload (anon)

key format for commands:
  key        clipboard (default)
  f/key      file

examples:
  drp up "hello world" -k hello    clipboard at /hello
  drp up report.pdf -k q3          file at /f/q3
  drp get hello                    print clipboard to stdout
  drp get f/q3 -o my-report.pdf    download file, save as different name
  drp get q3                       auto-detect: clipboard first, then file
  drp rm hello                     delete clipboard
  drp rm f/q3                      delete file
  drp mv q3 quarter3               rename key (blocked 24h after creation)
  drp ls -lh                       list with sizes and times
  drp ls -lh -t f                  list only files
  drp ls --export > backup.json    export as JSON (requires login)
""",
    )
    parser.add_argument('--version', '-V', action='version', version=f'%(prog)s {__version__}')

    sub = parser.add_subparsers(dest='command')

    sub.add_parser('setup', help='Configure host and log in')
    sub.add_parser('login', help='Log in (session saved — no repeated prompts)')
    sub.add_parser('logout', help='Log out and clear saved session')
    sub.add_parser('ping', help='Check connectivity to the drp server')
    sub.add_parser('status', help='Show config, account, and session info')

    p_up = sub.add_parser('up', help='Upload clipboard text or a file')
    p_up.add_argument('target', help='File path or text string to upload')
    p_up.add_argument('--key', '-k', default=None,
                      help='Custom key (e.g. -k q3 → /q3/ or /f/q3/)')

    p_get = sub.add_parser('get', help='Print clipboard or download file (no login needed)')
    p_get.add_argument('key',
                       help='Drop key — bare key tries clipboard then file; f/key forces file')
    p_get.add_argument('--output', '-o', default=None,
                       help='Save file as this name (default: original filename)')

    p_rm = sub.add_parser('rm', help='Delete a drop')
    p_rm.add_argument('key', help='Drop key (e.g. hello or f/report)')

    p_mv = sub.add_parser('mv', help='Rename a key (blocked 24h after creation)')
    p_mv.add_argument('key', help='Current key (e.g. q3 or f/q3)')
    p_mv.add_argument('new_key', help='New key')

    p_renew = sub.add_parser('renew', help='Renew expiry (paid accounts only)')
    p_renew.add_argument('key', help='Drop key (e.g. hello or f/report)')

    p_ls = sub.add_parser('ls', help='List your drops')
    p_ls.add_argument('-l', '--long', action='store_true',
                      help='Long format with size, time, and expiry (like ls -l)')
    p_ls.add_argument('-H', '--human', action='store_true',
                      help='Human-readable sizes (1.2M) — use with -l')
    p_ls.add_argument('-t', '--type', choices=['c', 'f'], default=None,
                      metavar='NS', help='Filter: c=clipboards, f=files')
    p_ls.add_argument('--sort', choices=['time', 'size', 'name'], default=None,
                      help='Sort by: time, size, or name')
    p_ls.add_argument('-r', '--reverse', action='store_true', help='Reverse sort order')
    p_ls.add_argument('--export', action='store_true',
                      help='Export as JSON (requires login). Pipe: drp ls --export > drops.json')

    commands = {
        'setup': cmd_setup,
        'login': cmd_login,
        'logout': cmd_logout,
        'ping': cmd_ping,
        'status': cmd_status,
        'up': cmd_up,
        'get': cmd_get,
        'rm': cmd_rm,
        'mv': cmd_mv,
        'renew': cmd_renew,
        'ls': cmd_ls,
    }

    args = parser.parse_args()

    if args.command in commands:
        try:
            commands[args.command](args)
        except KeyboardInterrupt:
            pass
        except SystemExit:
            raise
        except Exception as exc:
            from cli.crash_reporter import report
            report(args.command, exc)
            print(f'\n  ✗ Unexpected error: {type(exc).__name__}: {exc}')
            print('    This has been reported automatically.')
            sys.exit(1)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()