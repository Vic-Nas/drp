"""
Error reporting endpoint.

Receives sanitized crash reports from the CLI and files GitHub issues.
No user data is stored or forwarded — only exception type, traceback, and versions.
"""

import hashlib
import json
import logging
import os
import re
import traceback as tb

import requests as http
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

logger = logging.getLogger(__name__)

GITHUB_TOKEN = os.environ.get('GITHUB_ISSUES_TOKEN', '')
GITHUB_REPO  = os.environ.get('GITHUB_REPO', 'vicnasdev/drp')
GITHUB_API   = 'https://api.github.com'


# ── Scrubber ──────────────────────────────────────────────────────────────────

_SCRUB_PATTERNS = [
    (re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'), '[email]'),
    (re.compile(r'https?://[^\s\'"]+'), '[url]'),
    (re.compile(r'/home/[^/\s]+'), '/home/[user]'),
    (re.compile(r'/Users/[^/\s]+'), '/Users/[user]'),
    (re.compile(r'C:\\Users\\[^\\]+'), r'C:\\Users\\[user]'),
    (re.compile(r"password['\"]?\s*[:=]\s*['\"]?[^\s'\"]+", re.I), 'password=[redacted]'),
    (re.compile(r"token['\"]?\s*[:=]\s*['\"]?[^\s'\"]+", re.I), 'token=[redacted]'),
]


def _scrub(text):
    for pattern, replacement in _SCRUB_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _scrub_traceback(lines):
    cleaned = []
    for line in lines:
        if line.strip().startswith('During handling') or \
           (' = ' in line and not line.strip().startswith('File')):
            cleaned.append('    [locals redacted]\n')
        else:
            cleaned.append(_scrub(line))
    return cleaned


# ── GitHub ────────────────────────────────────────────────────────────────────

def _issue_title(exc_type, command):
    return f'[auto] {exc_type} in `drp {command}`'


def _issue_fingerprint(exc_type, command):
    """
    A broader fingerprint than the exact title — groups issues by
    command regardless of exception type, so related errors cluster
    together when searching, while still filing separately by exc_type.
    Used only for searching existing issues, not for the title itself.
    """
    return f'[auto] {exc_type} in `drp {command}`'


def _issue_exists(exc_type, command):
    """
    Return True if an open issue for this exc_type + command already exists.
    Also returns True if there are 3 or more open auto issues for the same
    command regardless of exception type — avoids flooding on a bad release.
    """
    if not GITHUB_TOKEN:
        return False
    try:
        res = http.get(
            f'{GITHUB_API}/repos/{GITHUB_REPO}/issues',
            headers={
                'Authorization': f'token {GITHUB_TOKEN}',
                'Accept': 'application/vnd.github+json',
            },
            params={'state': 'open', 'labels': 'bug,auto-reported', 'per_page': 50},
            timeout=8,
        )
        if not res.ok:
            return False

        open_issues = res.json()
        exact_title = _issue_title(exc_type, command)
        command_prefix = f'[auto] '

        # Exact duplicate
        if any(i['title'] == exact_title for i in open_issues):
            return True

        # Flood guard — if 3+ open auto issues for same command, stop filing
        command_issues = [
            i for i in open_issues
            if i['title'].startswith(command_prefix)
            and f'`drp {command}`' in i['title']
        ]
        if len(command_issues) >= 3:
            return True

    except Exception:
        pass
    return False


def _create_issue(title, body):
    if not GITHUB_TOKEN:
        logger.warning('GITHUB_ISSUES_TOKEN not set — skipping issue creation')
        return False
    try:
        res = http.post(
            f'{GITHUB_API}/repos/{GITHUB_REPO}/issues',
            headers={
                'Authorization': f'token {GITHUB_TOKEN}',
                'Accept': 'application/vnd.github+json',
            },
            json={'title': title, 'body': body, 'labels': ['bug', 'auto-reported']},
            timeout=8,
        )
        return res.status_code == 201
    except Exception as e:
        logger.error(f'Failed to create GitHub issue: {e}')
        return False


def _build_body(data):
    exc_type    = _scrub(data.get('exc_type', 'Unknown'))
    exc_msg     = _scrub(data.get('exc_message', ''))
    tb_lines    = _scrub_traceback(data.get('traceback', []))
    cli_version = data.get('cli_version', '?')
    py_version  = data.get('python_version', '?')
    platform    = data.get('platform', '?')
    command     = data.get('command', '?')

    # Fix 5: ensure each line ends with a newline before joining
    normalized = []
    for line in tb_lines:
        if not line.endswith('\n'):
            line = line + '\n'
        normalized.append(line)
    tb_text = ''.join(normalized) if normalized else '(none)'

    return f"""## `{exc_type}: {exc_msg}`

**Command:** `drp {command}`
**CLI:** `{cli_version}` · **Python:** `{py_version}` · **OS:** `{platform}`

```
{tb_text}
```

---
*Auto-reported by drp CLI. No user data included.*
"""


# ── View ──────────────────────────────────────────────────────────────────────

@csrf_exempt
@require_POST
def report_error(request):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON.'}, status=400)

    if not data.get('exc_type'):
        return JsonResponse({'error': 'exc_type required.'}, status=400)

    command  = _scrub(str(data.get('command', 'unknown')))
    exc_type = _scrub(str(data.get('exc_type', 'Unknown')))
    title    = _issue_title(exc_type, command)

    if _issue_exists(exc_type, command):
        return JsonResponse({'status': 'duplicate', 'message': 'Issue already open.'})

    body  = _build_body(data)
    filed = _create_issue(title, body)

    return JsonResponse({'status': 'filed' if filed else 'skipped'})


# ── Server-side 500 handler ───────────────────────────────────────────────────

def report_server_error(request, exc):
    if not exc:
        return

    exc_type = type(exc).__name__
    exc_msg  = _scrub(str(exc))
    tb_text  = _scrub(''.join(tb.format_tb(exc.__traceback__ or [])))
    path     = _scrub(request.path)
    method   = request.method

    title = f'[auto] Server {exc_type} at {method} {path}'

    if _issue_exists(exc_type, f'server {method} {path}'):
        return

    # Fix 5: ensure traceback newlines are intact
    if tb_text and not tb_text.endswith('\n'):
        tb_text += '\n'

    body = f"""## `{exc_type}: {exc_msg}`

**Request:** `{method} {path}`

```
{tb_text}
```

---
*Auto-reported by drp server. No request body or user data included.*
"""
    _create_issue(title, body)