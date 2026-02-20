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
from cli.commands.edit import cmd_edit
from cli.commands.cp import cmd_cp

COMMANDS = [
    ('setup',   cmd_setup,   'Configure host and log in'),
    ('login',   cmd_login,   'Log in (session saved — no repeated prompts)'),
    ('logout',  cmd_logout,  'Log out and clear saved session'),
    ('ping',    cmd_ping,    'Check connectivity to the drp server'),
    ('status',  cmd_status,  'Show config / view stats for a drop'),
    ('up',      cmd_up,      'Upload clipboard text or a file'),
    ('get',     cmd_get,     'Print clipboard or download file (no login needed)'),
    ('edit',    cmd_edit,    'Open a clipboard drop in $EDITOR and re-upload'),
    ('cp',      cmd_cp,      'Duplicate a drop under a new key'),
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
  echo "hello" | drp up -k hello        clipboard from stdin
  drp up report.pdf -k q3              file at /f/q3/
  drp up report.pdf --expires 30d       file with 30-day expiry
  drp get hello                         print clipboard to stdout
  drp get hello --url                   print URL without fetching content
  drp get -f q3 -o my-report.pdf        download file with custom name
  drp edit notes                        open clipboard in $EDITOR, re-upload on save
  drp cp notes notes-backup             duplicate clipboard drop
  drp cp -f q3 q3-backup               duplicate file drop (server-side, no re-upload)
  drp status notes                      view count and last seen for a drop
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
    try:
        from cli.completion import (
            key_completer, file_key_completer, clipboard_key_completer,
        )
        _completers = {
            'key':       key_completer,
            'file_key':  file_key_completer,
            'clip_key':  clipboard_key_completer,
        }
    except Exception:
        _completers = {}

    def _attach(arg, kind):
        if kind in _completers:
            arg.completer = _completers[kind]

    # ── up ────────────────────────────────────────────────────────────────────
    p_up = sub._name_parser_map['up']
    p_up.add_argument('target', nargs='?', default=None,
                      help='File path or text string to upload (omit to read from stdin)')
    p_up.add_argument('--key', '-k', default=None,
                      help='Custom key (e.g. -k q3 → /q3/ or /f/q3/)')
    p_up.add_argument('--expires', '-e', default=None, metavar='DURATION',
                      help='Expiry duration: 7d, 30d, 1y (paid accounts only)')

    # ── get ───────────────────────────────────────────────────────────────────
    p_get = sub._name_parser_map['get']
    p_get.add_argument('-f', '--file', action='store_true',
                       help='Key is a file drop')
    _attach(p_get.add_argument('key', help='Drop key'), 'key')
    p_get.add_argument('--output', '-o', default=None,
                       help='Save file as this name (default: original filename)')
    p_get.add_argument('--url', '-u', action='store_true',
                       help='Print the drop URL instead of fetching content')
    p_get.add_argument('--timing', action='store_true',
                       help='Print per-phase timing breakdown to stderr')

    # ── edit ──────────────────────────────────────────────────────────────────
    p_edit = sub._name_parser_map['edit']
    _attach(p_edit.add_argument('key', help='Clipboard drop key'), 'clip_key')

    # ── cp ────────────────────────────────────────────────────────────────────
    p_cp = sub._name_parser_map['cp']
    p_cp.add_argument('-f', '--file', action='store_true',
                      help='Key is a file drop')
    _attach(p_cp.add_argument('key', help='Source key'), 'key')
    p_cp.add_argument('new_key', help='Destination key')

    # ── rm ────────────────────────────────────────────────────────────────────
    p_rm = sub._name_parser_map['rm']
    p_rm.add_argument('-f', '--file', action='store_true')
    _attach(p_rm.add_argument('key', help='Drop key'), 'key')

    # ── mv ────────────────────────────────────────────────────────────────────
    p_mv = sub._name_parser_map['mv']
    p_mv.add_argument('-f', '--file', action='store_true')
    _attach(p_mv.add_argument('key', help='Current key'), 'key')
    p_mv.add_argument('new_key', help='New key')

    # ── renew ─────────────────────────────────────────────────────────────────
    p_renew = sub._name_parser_map['renew']
    p_renew.add_argument('-f', '--file', action='store_true')
    _attach(p_renew.add_argument('key', help='Drop key'), 'key')

    # ── save ──────────────────────────────────────────────────────────────────
    p_save = sub._name_parser_map['save']
    p_save.add_argument('-f', '--file', action='store_true')
    _attach(p_save.add_argument('key', help='Drop key'), 'key')

    # ── status ────────────────────────────────────────────────────────────────
    p_status = sub._name_parser_map['status']
    p_status.add_argument('key', nargs='?', default=None,
                          help='Drop key to inspect (omit for global status)')
    p_status.add_argument('-f', '--file', action='store_true',
                          help='Key is a file drop')

    # ── ls ────────────────────────────────────────────────────────────────────
    p_ls = sub._name_parser_map['ls']
    p_ls.add_argument('-l', '--long', action='store_true')
    p_ls.add_argument('--bytes', action='store_true')
    p_ls.add_argument('-t', '--type', choices=['c', 'f', 's'], default=None, metavar='TYPE')
    p_ls.add_argument('--sort', choices=['time', 'size', 'name'], default=None)
    p_ls.add_argument('-r', '--reverse', action='store_true')
    p_ls.add_argument('--export', action='store_true')

    # ── load ──────────────────────────────────────────────────────────────────
    p_load = sub._name_parser_map['load']
    p_load.add_argument('file', help='Path to a drp export JSON file')


_HANDLERS = {name: handler for name, handler, _ in COMMANDS}


def main():
    parser = build_parser()

    try:
        import argcomplete
        argcomplete.autocomplete(parser)
    except ImportError:
        pass

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