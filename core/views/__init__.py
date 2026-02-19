"""
Re-export all view callables so urls.py can do `from core import views` unchanged.
"""

from .drops import home, check_key, save_drop, clipboard_view, file_view, download_drop, help_view
from .actions import rename_drop, delete_drop, renew_drop
from .auth import register_view, login_view, logout_view, account_view, export_drops

__all__ = [
    'home', 'check_key', 'save_drop', 'clipboard_view', 'file_view',
    'download_drop', 'help_view',
    'rename_drop', 'delete_drop', 'renew_drop',
    'register_view', 'login_view', 'logout_view', 'account_view', 'export_drops',
]