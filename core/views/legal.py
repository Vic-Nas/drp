"""
Legal pages: privacy policy and terms of service.
"""

from django.shortcuts import render


_LAST_UPDATED = "February 2026"


from django.conf import settings

def privacy_view(request):
    domain = getattr(settings, "DOMAIN", None)
    return render(request, "legal/privacy.html", {"last_updated": _LAST_UPDATED, "domain": domain})


def terms_view(request):
    return render(request, "legal/terms.html", {"last_updated": _LAST_UPDATED})