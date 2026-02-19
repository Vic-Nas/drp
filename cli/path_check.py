"""
Check that the Python scripts directory is on PATH (mainly relevant on Windows).
"""

import os
import sys


def check_scripts_in_path():
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
            print('  ✓ Added. Restart your terminal for it to take effect.')
    except Exception as e:
        print(f'  ✗ Could not update PATH: {e}\n    Add manually: {scripts_dir}')