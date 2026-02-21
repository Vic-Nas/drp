"""
Error reporting endpoint.

Receives sanitized crash reports from the CLI and files GitHub issues.
No user data is stored or forwarded — only exception type, traceback, and versions.

Pure logic lives in core/error_reporting_logic.py (no Django dependency)
so it can be unit tested without a Django setup.
"""

import json
import traceback as tb

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from core.error_reporting_logic import (
    _scrub,
    _scrub_traceback,
    maybe_file_issue,
)


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

    filed = maybe_file_issue(data)
    return JsonResponse({'status': 'filed' if filed else 'duplicate'})


# ── Server-side 500 handler ───────────────────────────────────────────────────

def report_server_error(request, exc):
    if not exc:
        return

    tb_lines = tb.format_tb(exc.__traceback__ or [])

    data = {
        'command':        f'server {request.method} {_scrub(request.path)}',
        'exc_type':       type(exc).__name__,
        'exc_message':    str(exc),
        'traceback':      tb_lines,
        'cli_version':    'server',
        'python_version': '',
        'platform':       '',
    }

    maybe_file_issue(data)