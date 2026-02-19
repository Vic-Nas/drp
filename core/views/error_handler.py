"""
Custom Django error handlers.
Wire these up in project/urls.py:
  handler500 = 'core.views.error_handler.server_error'
"""

import sys

from django.views.defaults import server_error as django_server_error

from core.views.error_reporting import report_server_error


def server_error(request, *args, **kwargs):
    exc = sys.exc_info()[1]
    try:
        report_server_error(request, exc)
    except Exception:
        pass  # never let the reporter crash the error page
    return django_server_error(request, *args, **kwargs)