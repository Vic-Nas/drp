"""
Bookmark views: save and unsave a drop.

Saving a drop creates a SavedDrop entry for the current user.
It grants no ownership or edit permissions — the drop remains
owned by whoever created it (or nobody, if anonymous).
"""

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from core.models import SavedDrop


@login_required
@require_POST
def save_bookmark(request, ns, key):
    _, created = SavedDrop.objects.get_or_create(
        user=request.user,
        ns=ns,
        key=key,
    )
    return JsonResponse({'saved': True, 'created': created})


@login_required
@require_POST
def unsave_bookmark(request, ns, key):
    deleted, _ = SavedDrop.objects.filter(
        user=request.user,
        ns=ns,
        key=key,
    ).delete()
    return JsonResponse({'saved': False, 'deleted': bool(deleted)})