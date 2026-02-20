"""
Drop action API calls: delete, rename, renew, list, key_exists, save_bookmark.

URL conventions:
  Clipboard:  /key/delete|rename|renew|save/
  File:       /f/key/delete|rename|renew|save/
"""

from .auth import get_csrf
from .helpers import err


def _url(host, ns, key, action):
    if ns == 'f':
        return f'{host}/f/{key}/{action}/'
    return f'{host}/{key}/{action}/'


def delete(host, session, key, ns='c'):
    csrf = get_csrf(host, session)
    try:
        res = session.delete(
            _url(host, ns, key, 'delete'),
            headers={'X-CSRFToken': csrf},
            timeout=10,
        )
        if res.ok:
            return True
        if res.status_code == 404:
            # 404 means the key doesn't exist in this namespace — not a success.
            # Most likely cause: user ran `drp rm key` on a file drop without -f.
            err(f'Drop not found. If this is a file drop, use: drp rm -f {key}')
            _report_http('rm', 404, f'delete ns={ns} — likely wrong namespace')
            return False
        _handle_error(res, 'Delete failed')
        _report_http('rm', res.status_code, f'delete ns={ns}')
    except Exception as e:
        err(f'Delete error: {e}')
    return False


def rename(host, session, key, new_key, ns='c'):
    csrf = get_csrf(host, session)
    try:
        res = session.post(
            _url(host, ns, key, 'rename'),
            data={'new_key': new_key, 'csrfmiddlewaretoken': csrf},
            timeout=10,
        )
        if res.ok:
            return res.json().get('key')
        _handle_error(res, 'Rename failed')
        _report_http('mv', res.status_code, f'rename ns={ns}')
    except Exception as e:
        err(f'Rename error: {e}')
    return None


def renew(host, session, key, ns='c'):
    csrf = get_csrf(host, session)
    try:
        res = session.post(
            _url(host, ns, key, 'renew'),
            data={'csrfmiddlewaretoken': csrf},
            timeout=10,
        )
        if res.ok:
            data = res.json()
            return data.get('expires_at'), data.get('renewals')
        _handle_error(res, 'Renew failed')
        _report_http('renew', res.status_code, f'renew ns={ns}')
    except Exception as e:
        err(f'Renew error: {e}')
    return None, None


def save_bookmark(host, session, key, ns='c'):
    """
    Bookmark a drop. Returns True if saved, False on failure.
    Requires login — server returns 403 if not authenticated.
    """
    csrf = get_csrf(host, session)
    try:
        res = session.post(
            _url(host, ns, key, 'save'),
            data={'csrfmiddlewaretoken': csrf},
            timeout=10,
        )
        if res.ok:
            return True
        if res.status_code == 403:
            err('drp save requires a logged-in account. Run: drp login')
            return False
        if res.status_code == 404:
            err(f'Drop /{key}/ not found.')
            return False
        _handle_error(res, 'Save failed')
        _report_http('save', res.status_code, f'save_bookmark ns={ns}')
    except Exception as e:
        err(f'Save error: {e}')
    return False


def list_drops(host, session):
    try:
        res = session.get(
            f'{host}/auth/account/',
            headers={'Accept': 'application/json'},
            timeout=15,
        )
        if res.ok:
            return res.json().get('drops', [])
        if res.status_code in (302, 403):
            return None
        err(f'Server returned {res.status_code}.')
        _report_http('ls', res.status_code, 'list_drops')
    except Exception as e:
        err(f'List error: {e}')
    return None


def key_exists(host, session, key, ns='c'):
    try:
        res = session.get(
            f'{host}/check-key/',
            params={'key': key, 'ns': ns},
            timeout=10,
        )
        if res.ok:
            return not res.json().get('available', True)
    except Exception:
        pass
    return False


def _handle_error(res, prefix):
    try:
        msg = res.json().get('error', res.text[:200])
    except Exception:
        msg = res.text[:200]
    err(f'{prefix}: {msg}')


def _report_http(command: str, status_code: int, context: str) -> None:
    """Fire-and-forget — never raises."""
    try:
        from cli.crash_reporter import report_http_error
        report_http_error(command, status_code, context)
    except Exception:
        pass