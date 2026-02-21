"""
Legal pages: privacy policy and terms of service.
"""

from django.shortcuts import render


_LAST_UPDATED = "February 2026"


def privacy_view(request):
    return render(request, "legal/privacy.html", {"last_updated": _LAST_UPDATED})


def terms_view(request):
    return render(request, "legal/terms.html", {"last_updated": _LAST_UPDATED})