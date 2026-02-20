#!/usr/bin/env python3
"""drp — drop clipboards and files from the command line. Run `drp --help`."""

import argparse
import sys

from cli import __version__
from cli.commands.setup import cmd_setup, cmd_login, cmd_logout
from cli.commands.upload import cmd_up
from cli.commands.get import cmd_get
from cli.commands.manage import cmd_rm, cmd_mv, cmd_renew
from cli.commands.save import cmd_save
from cli.commands.ls import cmd_ls
from cli.commands.load import cmd_load
from cli.commands.status import cmd_status, cmd_ping

# ── Single source of truth ────────────────────────────────────────────────────
# (name, handler, help string)
# Order here is the order shown in --help and on the CLI docs page.

COMMANDS = [
    ('setup',   cmd_setup,   'Configure host and log in'),
    ('login',   cmd_login,   'Log in (session saved — no repeated prompts)'),
    ('logout',  cmd_logout,  'Log out and clear saved session'),
    ('ping',    cmd_ping,    'Check connectivity to the drp server'),
    ('status',  cmd_status,  'Show config, account, and session info'),
    ('up',      cmd_up,      'Upload clipboard text or a file'),
    ('get',     cmd_get,     'Print clipboard or download file (no login needed)'),
    ('save',    cmd_save,    'Bookmark a drop to your account (requires login)'),
    ('rm',      cmd_rm,      'Delete a drop'),
    ('mv',      cmd_mv,      'Rename a key (blocked 24h after creation)'),
    ('renew',   cmd_renew,   'Renew expiry (paid accounts only)'),
    ('ls',      cmd_ls,      'List your drops'),
    ('load',    cmd_load,    'Import a shared export as saved drops (requires login)'),
]

EPILOG = """
urls:
  /key/      clipboard — activity-based expiry
  /f/key/    file — expires 90 days after upload (anon)

key format:
  key        clipboard (default)
  -f key     file drop

examples:
  drp up "hello world" -k hello         clipboard at /hello/
  drp up report.pdf -k q3              file at /f/q3/
  drp get hello                         print clipboard to stdout
  drp get -f q3 -o my-report.pdf        download file with custom name
  drp save notes                        bookmark clipboard (appears in drp ls)
  drp save -f report                    bookmark file
  drp rm hello                          delete clipboard
  drp rm -f report                      delete file
  drp mv q3 quarter3                    rename clipboard key
  drp mv -f q3 quarter3                 rename file key
  drp ls -l                             list with sizes and times
  drp ls --export > backup.json         export as JSON
  drp load backup.json                  import shared export as saved drops
"""


# ── Parser ────────────────────────────────────────────────────────────────────

def build_parser():
    parser = argparse.ArgumentParser(
        prog='drp',
        description='Drop clipboards and files — get a link instantly.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=EPILOG,
    )
    parser.add_argument('--version', '-V', action='version', version=f'%(prog)s {__version__}')

    sub = parser.add_subparsers(dest='command')

    for name, _, help_str in COMMANDS:
        sub.add_parser(name, help=help_str)

    _configure_subparsers(sub)

    return parser


def _configure_subparsers(sub):
    """Add arguments to subparsers that need them."""
    p_up = sub._name_parser_map['up']
    p_up.add_argument('target', help='File path or text string to upload')
    p_up.add_argument('--key', '-k', default=None,
                      help='Custom key (e.g. -k q3 → /q3/ or /f/q3/)')

    p_get = sub._name_parser_map['get']
    p_get.add_argument('key', help='Drop key')
    p_get.add_argument('-f', '--file', action='store_true',
                       help='Key is a file drop (e.g. drp get -f q3)')
    p_get.add_argument('--output', '-o', default=None,
                       help='Save file as this name (default: original filename)')

    p_rm = sub._name_parser_map['rm']
    p_rm.add_argument('key', help='Drop key')
    p_rm.add_argument('-f', '--file', action='store_true',
                      help='Key is a file drop (e.g. drp rm -f report)')

    p_mv = sub._name_parser_map['mv']
    p_mv.add_argument('key', help='Current key')
    p_mv.add_argument('new_key', help='New key')
    p_mv.add_argument('-f', '--file', action='store_true',
                      help='Key is a file drop (e.g. drp mv -f q3 quarter3)')

    p_renew = sub._name_parser_map['renew']
    p_renew.add_argument('key', help='Drop key')
    p_renew.add_argument('-f', '--file', action='store_true',
                         help='Key is a file drop (e.g. drp renew -f report)')

    p_save = sub._name_parser_map['save']
    p_save.add_argument('key', help='Drop key')
    p_save.add_argument('-f', '--file', action='store_true',
                        help='Key is a file drop (e.g. drp save -f report)')

    p_ls = sub._name_parser_map['ls']
    p_ls.add_argument('-l', '--long', action='store_true',
                      help='Long format: kind, size, age, expiry')
    p_ls.add_argument('--bytes', action='store_true',
                      help='Show raw byte counts instead of human-readable sizes (use with -l)')
    p_ls.add_argument('-t', '--type', choices=['c', 'f', 's'], default=None,
                      metavar='TYPE', help='Filter: c=clipboards  f=files  s=saved')
    p_ls.add_argument('--sort', choices=['time', 'size', 'name'], default=None,
                      help='Sort by: time, size, or name (default: newest first)')
    p_ls.add_argument('-r', '--reverse', action='store_true', help='Reverse sort order')
    p_ls.add_argument('--export', action='store_true',
                      help='Dump drops as JSON: drp ls --export > backup.json')

    p_load = sub._name_parser_map['load']
    p_load.add_argument('file', help='Path to a drp export JSON file')


# ── Entry point ───────────────────────────────────────────────────────────────

_HANDLERS = {name: handler for name, handler, _ in COMMANDS}


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.command in _HANDLERS:
        try:
            _HANDLERS[args.command](args)
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