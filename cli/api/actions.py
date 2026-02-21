"""
Drop action API calls: delete, rename, renew, list, key_exists, save_bookmark.

URL conventions:
  Clipboard:  /key/delete|rename|renew|save/
  File:       /f/key/delete|rename|renew|save/

Return value conventions for callers (manage.py):
  rename() → new_key string   on success
             False             on a known/reported error (404, 409, 403 …)
             None              on an unexpected error (network, bad JSON, etc.)
  delete() → True / False (unchanged)
  renew()  → (expires_at, renewals) / (None, None) (unchanged)
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
            err(f'Drop not found. If this is a file drop, use: drp rm -f {key}')
            _report_http('rm', 404, f'delete ns={ns} — likely wrong namespace')
            return False
        _handle_error(res, 'Delete failed')
        _report_http('rm', res.status_code, f'delete ns={ns}')
    except Exception as e:
        err(f'Delete error: {e}')
    return False


def rename(host, session, key, new_key, ns='c'):
    """
    Rename a drop key.

    Returns:
      str   — the new key on success
      False — a known error that has already been printed and reported
               (404 wrong-namespace, 409 key taken, 403 locked, 400 bad input)
      None  — an unexpected error (network failure, unhandled status code)
               caller should file a SilentFailure report
    """
    csrf = get_csrf(host, session)
    try:
        res = session.post(
            _url(host, ns, key, 'rename'),
            data={'new_key': new_key, 'csrfmiddlewaretoken': csrf},
            timeout=10,
        )
        if res.ok:
            return res.json().get('key')

        # ── Known errors — print a helpful message and report, then return
        # False so the caller knows not to file a redundant SilentFailure. ──
        if res.status_code == 404:
            ns_flag = '-f ' if ns == 'f' else ''
            other_flag = '' if ns == 'f' else '-f '
            err(
                f'Drop /{ns_flag}{key}/ not found. '
                f'If this is a {"file" if ns == "c" else "clipboard"} drop, '
                f'use: drp mv {other_flag}{key} {new_key}'
            )
            _report_http('mv', 404, f'rename ns={ns} — likely wrong namespace')
            return False

        if res.status_code == 409:
            err(f'Key "{new_key}" is already taken.')
            _report_http('mv', 409, f'rename ns={ns} key conflict')
            return False

        if res.status_code == 403:
            try:
                msg = res.json().get('error', 'Permission denied.')
            except Exception:
                msg = 'Permission denied.'
            err(f'Rename blocked: {msg}')
            _report_http('mv', 403, f'rename ns={ns}')
            return False

        if res.status_code == 400:
            _handle_error(res, 'Rename failed')
            _report_http('mv', 400, f'rename ns={ns}')
            return False

        # Unexpected status — let caller decide whether to report
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
            allow_redirects=False,
        )
        if res.status_code in (301, 302, 303):
            err('drp save requires a logged-in account. Run: drp login')
            return False
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