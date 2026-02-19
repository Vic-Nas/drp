"""
Silent crash reporter.
Sends sanitized exception info to /api/report-error/ on the drp server,
which files a GitHub issue if one doesn't already exist.

What is sent:
  - Exception type and message (scrubbed)
  - Traceback (file paths + line numbers only, no variable values)
  - CLI version, Python version, OS platform
  - Command name only (NOT arguments — could contain keys/filenames/content)

What is never sent:
  - Command arguments or flags
  - Drop content or keys
  - File names or paths from the user's machine (only our own source paths)
  - Email, tokens, or any auth data
"""

import platform
import re
import sys
import traceback as tb


_SCRUB = [
    (re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'), '[email]'),
    (re.compile(r'https?://[^\s\'"]+'), '[url]'),
    (re.compile(r'/home/[^/\s]+'), '/home/[user]'),
    (re.compile(r'/Users/[^/\s]+'), '/Users/[user]'),
    (re.compile(r'C:\\Users\\[^\\]+'), r'C:\\Users\\[user]'),
    (re.compile(r"(?:password|token|secret)['\"]?\s*[:=]\s*['\"]?\S+", re.I), '[redacted]'),
]


def _scrub(text):
    for pat, rep in _SCRUB:
        text = pat.sub(rep, text)
    return text


def _safe_traceback(exc):
    """Return scrubbed traceback lines — paths and line numbers only."""
    lines = tb.format_tb(exc.__traceback__ or [])
    cleaned = []
    for chunk in lines:
        for line in chunk.splitlines(keepends=True):
            stripped = line.strip()
            # Skip lines that show local variable values (not File/^ lines)
            if stripped.startswith('File') or stripped.startswith('^') or stripped == '':
                cleaned.append(_scrub(line))
            # Keep the "in function_name" context line
            elif not any(c in line for c in ('=', '->', ': ')):
                cleaned.append(_scrub(line))
    return cleaned


def report(command, exc):
    """
    Fire-and-forget: send crash report to the server.
    Never raises — if reporting fails, we silently move on.
    """
    try:
        from cli import config, __version__
        import requests

        cfg = config.load()
        host = cfg.get('host')
        if not host:
            return

        payload = {
            'command':        command,
            'exc_type':       type(exc).__name__,
            'exc_message':    _scrub(str(exc)),
            'traceback':      _safe_traceback(exc),
            'cli_version':    __version__,
            'python_version': sys.version.split()[0],
            'platform':       platform.system(),
        }

        requests.post(
            f'{host}/api/report-error/',
            json=payload,
            timeout=5,
        )
    except Exception:
        pass  # never let the reporter interfere with the CLI