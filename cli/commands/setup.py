"""
Setup, login, and logout commands.
"""

import getpass
import os
import subprocess
import sys
from pathlib import Path

import requests

from cli import config, api, DEFAULT_HOST
from cli.session import save_session, clear_session, auto_login
from cli.path_check import check_scripts_in_path


def cmd_setup(args):
    cfg = config.load()
    print('drp setup')
    print('─────────')
    default = cfg.get('host', DEFAULT_HOST)
    cfg['host'] = input(f'  Host [{default}]: ').strip() or default
    config.save(cfg)
    answer = input('  Log in now? (y/n) [y]: ').strip().lower()
    if answer != 'n':
        cmd_login(args)
    check_scripts_in_path()
    _setup_completion()
    print(f'\n  ✓ Config saved to {config.CONFIG_FILE}')


def cmd_login(args):
    cfg = config.load()
    host = cfg.get('host', DEFAULT_HOST)
    email = input('  Email: ').strip()
    password = getpass.getpass('  Password: ')
    session = requests.Session()
    try:
        if api.login(host, session, email, password):
            cfg['email'] = email
            config.save(cfg)
            save_session(session)
            print(f'  ✓ Logged in as {email}')
        else:
            print('  ✗ Login failed — check your email and password.')
            sys.exit(1)
    except Exception as e:
        print(f'  ✗ Login error: {e}')
        sys.exit(1)


def cmd_logout(args):
    cfg = config.load()
    email = cfg.pop('email', None)
    config.save(cfg)
    clear_session()
    print(f'  ✓ Logged out ({email})' if email else '  (already anonymous)')


# ── Completion setup ──────────────────────────────────────────────────────────

def _setup_completion():
    """
    Called at the end of drp setup.

    1. Ensure argcomplete is installed in the current environment.
    2. Write a shell-specific activation line to the user's profile so
       completion survives across sessions.
    3. Print what was done, or what to do manually if auto-install failed.

    Entirely non-fatal — completion is a nice-to-have, not a setup blocker.
    """
    print()
    print('  Tab completion')
    print('  ──────────────')

    # ── Step 1: install argcomplete if missing ─────────────────────────────
    if not _argcomplete_available():
        print('  Installing argcomplete…', end=' ', flush=True)
        ok = _install_argcomplete()
        if ok:
            print('done')
        else:
            print('failed')
            _print_manual_install_hint()
            return
    else:
        print('  argcomplete already installed  ✓')

    # ── Step 2: write activation line to shell profile ─────────────────────
    shell, profile = _detect_shell_and_profile()
    activation = _activation_line(shell)

    if not activation:
        print(f'  Unknown shell ({shell!r}) — see below for manual setup.')
        _print_manual_fallback()
        return

    if profile:
        if _profile_has_activation(profile, activation):
            print(f'  Shell profile already configured  ✓')
        else:
            if _append_to_profile(profile, activation):
                print(f'  Written to {profile}  ✓')
            else:
                print(f'  Could not write to {profile}')
                _print_manual_activation_hint(shell, activation)
                return
    else:
        _print_manual_activation_hint(shell, activation)
        return

    print(f'  Restart your shell (or: source {profile}) to activate.')


def _argcomplete_available() -> bool:
    try:
        import argcomplete  # noqa: F401
        return True
    except ImportError:
        return False


def _install_argcomplete() -> bool:
    """
    Try to install argcomplete into whichever Python is running this process.

    Tries pipx inject first (correct approach when installed via pipx — keeps
    argcomplete inside the drp-cli venv rather than polluting the system).
    Falls back to pip in the current interpreter for pip/venv installs.
    """
    # pipx sets PIPX_HOME; if present, inject into the drp-cli venv.
    if os.environ.get('PIPX_HOME') or _pipx_available():
        result = subprocess.run(
            ['pipx', 'inject', 'drp-cli', 'argcomplete'],
            capture_output=True,
        )
        if result.returncode == 0:
            return True

    # Fall back to pip in the current interpreter.
    result = subprocess.run(
        [sys.executable, '-m', 'pip', 'install', '--quiet', 'argcomplete'],
        capture_output=True,
    )
    return result.returncode == 0


def _pipx_available() -> bool:
    try:
        result = subprocess.run(['pipx', '--version'], capture_output=True)
        return result.returncode == 0
    except FileNotFoundError:
        return False


def _detect_shell_and_profile() -> tuple[str, str | None]:
    """
    Returns (shell_name, profile_path_or_None).

    shell_name — basename of $SHELL, lowercased.
    profile_path — best file to append the activation line to, or None if we
                   can't determine one (unknown shell, no writable candidate).
    """
    shell_path = os.environ.get('SHELL', '')
    shell = os.path.basename(shell_path).lower()
    home = Path.home()

    # Ordered preference: use whichever file already exists; otherwise fall
    # back to the first candidate (we'll create it in _append_to_profile).
    candidates: dict[str, list[Path]] = {
        'bash': [home / '.bashrc', home / '.bash_profile'],
        'zsh':  [home / '.zshrc'],
        'fish': [home / '.config' / 'fish' / 'config.fish'],
    }

    for path in candidates.get(shell, []):
        if path.exists():
            return shell, str(path)

    # No existing file — return the preferred path so we can create it.
    first = candidates.get(shell, [None])[0]
    return shell, str(first) if first else None


def _activation_line(shell: str) -> str | None:
    """One-liner that activates drp completion for the given shell."""
    return {
        'bash': 'eval "$(register-python-argcomplete drp)"',
        'zsh':  (
            'autoload -U bashcompinit && bashcompinit && '
            'eval "$(register-python-argcomplete drp)"'
        ),
        'fish': 'register-python-argcomplete --shell fish drp | source',
    }.get(shell)


def _profile_has_activation(profile_path: str, activation: str) -> bool:
    try:
        return activation in Path(profile_path).read_text()
    except Exception:
        return False


def _append_to_profile(profile_path: str, activation: str) -> bool:
    try:
        p = Path(profile_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open('a') as f:
            f.write(f'\n# drp tab completion\n{activation}\n')
        return True
    except Exception:
        return False


# ── Fallback hints ────────────────────────────────────────────────────────────

def _print_manual_install_hint():
    print()
    print('  Install argcomplete manually, then re-run drp setup:')
    print('    pipx inject drp-cli argcomplete')
    print('    # or: pip install argcomplete')


def _print_manual_activation_hint(shell: str, activation: str):
    print()
    print('  Add this line to your shell profile and restart your shell:')
    print(f'    {activation}')


def _print_manual_fallback():
    print()
    print('  Supported shells: bash, zsh, fish.')
    print('  Add the appropriate line to your shell profile:')
    print()
    print('    bash / zsh:')
    print('      eval "$(register-python-argcomplete drp)"')
    print('    fish:')
    print('      register-python-argcomplete --shell fish drp | source')