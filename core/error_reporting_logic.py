"""
Pure logic for GitHub issue filing — no Django dependency.
Imported by both core/views/error_reporting.py and the test suite.
"""

import logging
import os
import re

import requests as http

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


def _issue_exists(exc_type, command):
    """
    Return True if an open issue for this exc_type + command already exists,
    or if the flood guard triggers (3+ open auto issues for the same command).
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

        # Exact duplicate
        if any(i['title'] == exact_title for i in open_issues):
            return True

        # Flood guard — if 3+ open auto issues for same command, stop filing
        command_issues = [
            i for i in open_issues
            if i['title'].startswith('[auto] ')
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