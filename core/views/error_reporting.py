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
    _issue_title,
    _issue_exists,
    _create_issue,
    _build_body,
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