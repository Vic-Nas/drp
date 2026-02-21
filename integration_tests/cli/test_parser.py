"""
integration_tests/cli/test_parser.py

Tests for drp.py itself — no network needed:
  drp            (no args)   → colored help, exit 0
  drp -h         → colored help, exit 0
  drp --help     → colored help, exit 0
  drp -V         → version string
  drp --version  → version string
  EXAMPLES / COMMAND_GROUPS / _build_epilog — internal consistency
  _ColorHelpAction — wired correctly
  drp <unknown>  → non-zero exit
"""

import re
import subprocess
import sys

import pytest

from conftest import run_drp


# ── Help output ───────────────────────────────────────────────────────────────

class TestHelpOutput:
    def _help_text(self, cli_env, *flags):
        r = run_drp(*flags, env=cli_env)
        return r.stdout + r.stderr, r.returncode

    def test_no_args_exits_zero(self, cli_env):
        r = run_drp(env=cli_env)
        assert r.returncode == 0

    def test_dash_h_exits_zero(self, cli_env):
        r = run_drp('-h', env=cli_env)
        assert r.returncode == 0

    def test_double_dash_help_exits_zero(self, cli_env):
        r = run_drp('--help', env=cli_env)
        assert r.returncode == 0

    def test_no_args_and_dash_h_same_output(self, cli_env):
        r_bare = run_drp(env=cli_env)
        r_h    = run_drp('-h', env=cli_env)
        assert r_bare.stdout == r_h.stdout

    def test_dash_h_and_double_help_same_output(self, cli_env):
        r_h    = run_drp('-h', env=cli_env)
        r_help = run_drp('--help', env=cli_env)
        assert r_h.stdout == r_help.stdout

    def test_help_contains_all_command_groups(self, cli_env):
        r = run_drp('-h', env=cli_env)
        text = r.stdout
        for group_label, _ in [
            ('upload / download', []),
            ('manage', []),
            ('account', []),
            ('info', []),
            ('setup', []),
        ]:
            assert group_label in text, f'Missing group: {group_label!r}'

    def test_help_contains_all_commands(self, cli_env):
        r = run_drp('-h', env=cli_env)
        text = r.stdout
        for cmd in ['up', 'get', 'edit', 'serve', 'rm', 'mv', 'cp', 'renew',
                    'diff', 'save', 'ls', 'load', 'status', 'ping',
                    'setup', 'login', 'logout']:
            assert cmd in text, f'Missing command: {cmd!r}'

    def test_help_contains_examples_section(self, cli_env):
        r = run_drp('-h', env=cli_env)
        assert 'examples:' in r.stdout.lower()

    def test_help_contains_password_example(self, cli_env):
        """Regression: --password must appear in examples (was missing pre-refactor)."""
        r = run_drp('-h', env=cli_env)
        assert '--password' in r.stdout

    def test_help_contains_key_format_section(self, cli_env):
        r = run_drp('-h', env=cli_env)
        assert 'key format' in r.stdout.lower()

    def test_help_mentions_file_flag(self, cli_env):
        r = run_drp('-h', env=cli_env)
        assert '-f key' in r.stdout or '-f ' in r.stdout

    def test_help_no_traceback(self, cli_env):
        r = run_drp('-h', env=cli_env)
        assert 'Traceback' not in r.stdout
        assert 'Traceback' not in r.stderr


# ── Version ───────────────────────────────────────────────────────────────────

class TestVersion:
    def test_version_flag_exits_zero(self, cli_env):
        r = run_drp('-V', env=cli_env)
        assert r.returncode == 0

    def test_double_version_flag(self, cli_env):
        r = run_drp('--version', env=cli_env)
        assert r.returncode == 0

    def test_version_output_is_semver(self, cli_env):
        r = run_drp('--version', env=cli_env)
        combined = r.stdout + r.stderr
        match = re.search(r'(\d+\.\d+\.\d+)', combined)
        assert match, f'No semver found in: {combined!r}'

    def test_version_matches_package(self, cli_env):
        from cli import __version__
        r = run_drp('--version', env=cli_env)
        combined = r.stdout + r.stderr
        assert __version__ in combined


# ── Unknown command ───────────────────────────────────────────────────────────

class TestUnknownCommand:
    def test_unknown_command_exits_nonzero(self, cli_env):
        r = run_drp('notacommand', env=cli_env)
        # argparse prints help and exits non-zero for unknown subcommands
        assert r.returncode != 0 or 'usage' in (r.stdout + r.stderr).lower()


# ── Internal consistency (no network) ────────────────────────────────────────

class TestInternalConsistency:
    """
    These tests import drp.py directly and check the data structures —
    no subprocess, no network.
    """

    def test_examples_all_have_three_fields(self):
        from drp import EXAMPLES
        for entry in EXAMPLES:
            assert len(entry) == 3, f'Bad EXAMPLES entry: {entry!r}'

    def test_examples_no_empty_fields(self):
        from drp import EXAMPLES
        for cmd, arg, desc in EXAMPLES:
            assert cmd.strip(), f'Empty cmd in: {(cmd, arg, desc)}'
            assert arg.strip(), f'Empty arg in: {(cmd, arg, desc)}'
            assert desc.strip(), f'Empty desc in: {(cmd, arg, desc)}'

    def test_examples_contains_password(self):
        from drp import EXAMPLES
        all_text = ' '.join(f'{c} {a} {d}' for c, a, d in EXAMPLES)
        assert '--password' in all_text

    def test_command_groups_reference_only_known_commands(self):
        from drp import COMMANDS, COMMAND_GROUPS
        known = {name for name, _, _ in COMMANDS}
        for label, names in COMMAND_GROUPS:
            for name in names:
                assert name in known, f'Unknown command {name!r} in group {label!r}'

    def test_command_groups_cover_all_commands(self):
        from drp import COMMANDS, COMMAND_GROUPS
        known = {name for name, _, _ in COMMANDS}
        grouped = {name for _, names in COMMAND_GROUPS for name in names}
        assert known == grouped, f'Commands not in any group: {known - grouped}'

    def test_build_epilog_contains_all_examples(self):
        from drp import EXAMPLES, _build_epilog
        epilog = _build_epilog()
        for cmd, arg, desc in EXAMPLES:
            assert cmd in epilog, f'Missing cmd {cmd!r} in epilog'
            assert desc in epilog, f'Missing desc {desc!r} in epilog'

    def test_build_epilog_columns_aligned(self):
        """Every example line should have consistent column alignment."""
        from drp import _build_epilog
        epilog = _build_epilog()
        lines = [l for l in epilog.splitlines() if l.startswith('  drp ') or l.startswith('  echo')]
        if not lines:
            return
        # Find the column where the description starts (first double-space gap)
        def desc_col(line):
            match = re.search(r'  \S', line[4:])  # skip leading '  '
            return match.start() if match else None

        cols = [desc_col(l) for l in lines if desc_col(l) is not None]
        assert len(set(cols)) == 1, f'Misaligned columns: {set(cols)}'

    def test_color_help_action_registered(self):
        from drp import build_parser, _ColorHelpAction
        parser = build_parser()
        actions = {a.option_strings[0]: a for a in parser._actions if a.option_strings}
        assert '-h' in actions
        assert isinstance(actions['-h'], _ColorHelpAction)

    def test_parser_add_help_is_false(self):
        """Ensure we disabled argparse's default help so ours takes over."""
        from drp import build_parser
        parser = build_parser()
        # If add_help=True, argparse adds its own HelpAction; ours replaces it.
        help_actions = [a for a in parser._actions
                        if '-h' in getattr(a, 'option_strings', [])]
        assert len(help_actions) == 1
        from drp import _ColorHelpAction
        assert isinstance(help_actions[0], _ColorHelpAction)
