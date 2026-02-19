"""
Drop action views: rename, delete, renew.

URL patterns:
  Clipboard:  /key/rename/   /key/delete/   /key/renew/
  File:       /f/key/rename/ /f/key/delete/ /f/key/renew/
"""

from django.http import JsonResponse

from core.models import Drop


def _get_drop(ns, key):
    """Return drop or None."""
    return Drop.objects.filter(ns=ns, key=key).first()


def _edit_error(drop, request):
    """
    Return a JsonResponse error if the user cannot edit this drop, else None.
    Centralises all the lock / ownership error messages.
    """
    if drop.is_expired():
        drop.hard_delete()
        return JsonResponse({'error': 'Drop has expired.'}, status=410)

    if not drop.can_edit(request.user):
        if drop.is_creation_locked():
            return JsonResponse(
                {'error': 'Drop is protected for 24 hours after creation.'},
                status=403,
            )
        return JsonResponse(
            {'error': 'Drop is locked to its owner.'},
            status=403,
        )
    return None


# ── Rename ────────────────────────────────────────────────────────────────────

def rename_drop(request, ns, key):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required.'}, status=405)

    drop = _get_drop(ns, key)
    if not drop:
        return JsonResponse({'error': 'Drop not found.'}, status=404)

    err = _edit_error(drop, request)
    if err:
        return err

    new_key = request.POST.get('new_key', '').strip()
    if not new_key:
        return JsonResponse({'error': 'New key required.'}, status=400)

    if new_key == key:
        return JsonResponse({'error': 'New key is the same as current key.'}, status=400)

    if Drop.objects.filter(ns=ns, key=new_key).exists():
        return JsonResponse({'error': 'Key already taken.'}, status=409)

    drop.key = new_key
    drop.save(update_fields=['key'])

    prefix = '' if ns == Drop.NS_CLIPBOARD else 'f/'
    return JsonResponse({'key': new_key, 'url': f'/{prefix}{new_key}/'})


# ── Delete ────────────────────────────────────────────────────────────────────

def delete_drop(request, ns, key):
    if request.method != 'DELETE':
        return JsonResponse({'error': 'DELETE required.'}, status=405)

    drop = _get_drop(ns, key)
    if not drop:
        # Idempotent — already gone
        return JsonResponse({'deleted': True, 'note': 'Drop was already gone.'})

    err = _edit_error(drop, request)
    if err:
        return err

    drop.hard_delete()
    return JsonResponse({'deleted': True})


# ── Renew ─────────────────────────────────────────────────────────────────────

def renew_drop(request, ns, key):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required.'}, status=405)

    drop = _get_drop(ns, key)
    if not drop:
        return JsonResponse({'error': 'Drop not found.'}, status=404)

    if drop.is_expired():
        drop.hard_delete()
        return JsonResponse({'error': 'Drop has expired.'}, status=410)

    if not (request.user.is_authenticated and drop.owner_id == request.user.pk):
        return JsonResponse({'error': 'Only the owner can renew this drop.'}, status=403)

    if not drop.expires_at:
        return JsonResponse(
            {'error': 'This drop has no explicit expiry date. Only paid drops can be renewed.'},
            status=400,
        )

    drop.renew()
    return JsonResponse({
        'expires_at': drop.expires_at.isoformat(),
        'renewals': drop.renewal_count,
    })