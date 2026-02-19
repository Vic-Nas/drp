"""
Drop creation, retrieval, and download views.
"""

import secrets
from datetime import timedelta

from django.conf import settings
from django.http import JsonResponse, Http404
from django.shortcuts import render, redirect
from django.urls import get_resolver
from django.utils import timezone

from core.models import Drop, Plan, SavedDrop
from .helpers import (
    user_plan, max_file_bytes, max_text_bytes, storage_ok,
    is_paid_user, max_lifetime_secs, gen_key,
    upload_to_cloudinary, destroy_cloudinary, add_storage,
)

ANON_COOKIE = 'drp_anon'


# ── Reserved keys ─────────────────────────────────────────────────────────────

def _get_reserved_keys():
    """
    Derive reserved top-level path segments from the root URL conf.
    Runs once at startup — automatically covers any app added in future.
    """
    resolver = get_resolver()
    reserved = set()
    for pattern in resolver.url_patterns:
        segment = str(pattern.pattern).strip('^').split('/')[0]
        # skip empty segments and regex group openers
        if segment and not segment.startswith(('(', '?', '<')):
            reserved.add(segment)
    return reserved

RESERVED_KEYS = _get_reserved_keys()


# ── Home ──────────────────────────────────────────────────────────────────────

def home(request):
    claimed = request.session.pop('claimed_drops', 0)
    server_drops = []
    saved_drops = []
    if request.user.is_authenticated:
        server_drops = (
            Drop.objects
            .filter(owner=request.user)
            .order_by('-created_at')[:50]
        )
        saved_drops = (
            SavedDrop.objects
            .filter(user=request.user)
            .order_by('-saved_at')[:50]
        )
    return render(request, 'home.html', {
        'server_drops': server_drops,
        'saved_drops': saved_drops,
        'claimed': claimed,
    })


# ── Check key ─────────────────────────────────────────────────────────────────

def check_key(request):
    key = request.GET.get('key', '').strip()
    ns = request.GET.get('ns', Drop.NS_CLIPBOARD)
    if not key:
        return JsonResponse({'error': 'Key required.'}, status=400)
    if key in RESERVED_KEYS:
        return JsonResponse({'available': False, 'reserved': True, 'ns': ns, 'key': key})
    taken = Drop.objects.filter(ns=ns, key=key).exists()
    return JsonResponse({'available': not taken, 'ns': ns, 'key': key})


# ── Save drop ─────────────────────────────────────────────────────────────────

def save_drop(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required.'}, status=405)

    f = request.FILES.get('file')
    ns = Drop.NS_FILE if f else Drop.NS_CLIPBOARD
    key = request.POST.get('key', '').strip() or gen_key(ns)

    if key in RESERVED_KEYS:
        return JsonResponse({'error': f'"{key}" is a reserved key.'}, status=400)

    existing = Drop.objects.filter(ns=ns, key=key).first()
    if existing and existing.is_expired():
        existing.hard_delete()
        existing = None

    if existing and not existing.can_edit(request.user):
        if existing.is_creation_locked():
            return JsonResponse({
                'error': 'This drop was just created and is protected for 24 hours. '
                         'Wait until the window expires or pick a different key.'
            }, status=403)
        return JsonResponse({'error': 'This drop is locked to its owner.'}, status=403)

    paid = is_paid_user(request.user)

    anon_token = None
    if not request.user.is_authenticated:
        anon_token = request.COOKIES.get(ANON_COOKIE) or secrets.token_urlsafe(32)

    if f:
        response = _save_file(request, f, ns, key, existing, paid, anon_token)
    else:
        response = _save_text(request, ns, key, existing, paid, anon_token)

    if anon_token and not existing:
        response.set_cookie(
            ANON_COOKIE,
            anon_token,
            max_age=7 * 24 * 3600,
            httponly=True,
            samesite='Lax',
        )

    return response


def _expiry_and_lock(request, paid):
    """Return (expires_at, locked_until) based on user plan and POST data."""
    expires_at = None
    locked_until = None
    expiry_days = request.POST.get('expiry_days')

    if paid and expiry_days:
        try:
            days = min(
                int(expiry_days),
                Plan.get(user_plan(request.user), 'max_expiry_days')
            )
            expires_at = timezone.now() + timedelta(days=days)
        except (ValueError, TypeError):
            pass
    elif not request.user.is_authenticated:
        locked_until = timezone.now() + timedelta(hours=24)

    return expires_at, locked_until


def _save_file(request, f, ns, key, existing, paid, anon_token):
    if f.size > max_file_bytes(request.user):
        limit = Plan.get(user_plan(request.user), 'max_file_mb')
        return JsonResponse({'error': f'File exceeds {limit} MB limit.'}, status=400)

    if not storage_ok(request.user, f.size):
        return JsonResponse({'error': 'Storage quota exceeded.'}, status=400)

    public_id = f'drops/f/{key}'
    try:
        file_url, file_public_id = upload_to_cloudinary(f, public_id)
    except Exception as e:
        return JsonResponse({'error': f'File upload failed: {e}'}, status=500)

    if existing:
        if existing.file_public_id and existing.file_public_id != file_public_id:
            destroy_cloudinary(existing.file_public_id)
        old_size = existing.filesize
        existing.file_url = file_url
        existing.file_public_id = file_public_id
        existing.filename = f.name
        existing.filesize = f.size
        existing.save()
        if existing.owner_id:
            from django.db import models as db_models
            from core.models import UserProfile
            UserProfile.objects.filter(user_id=existing.owner_id).update(
                storage_used_bytes=db_models.F('storage_used_bytes') + (f.size - old_size)
            )
        drop = existing
    else:
        expires_at, locked_until = _expiry_and_lock(request, paid)
        owner = request.user if request.user.is_authenticated else None
        drop = Drop.objects.create(
            ns=ns, key=key, kind=Drop.FILE,
            file_url=file_url, file_public_id=file_public_id,
            filename=f.name, filesize=f.size,
            owner=owner,
            locked=paid,
            locked_until=locked_until,
            expires_at=expires_at,
            max_lifetime_secs=max_lifetime_secs(request.user, ns),
            anon_token=anon_token,
        )
        add_storage(request.user, f.size)

    return JsonResponse({
        'key': drop.key,
        'ns': drop.ns,
        'kind': drop.kind,
        'url': f'/f/{drop.key}/',
        'new': existing is None,
    })


def _save_text(request, ns, key, existing, paid, anon_token):
    text = request.POST.get('content', '').strip()
    if len(text.encode()) > max_text_bytes(request.user):
        limit = Plan.get(user_plan(request.user), 'max_text_kb')
        return JsonResponse({'error': f'Text exceeds {limit} KB.'}, status=400)

    if existing:
        existing.content = text
        existing.last_accessed_at = timezone.now()
        existing.save()
        drop = existing
    else:
        expires_at, locked_until = _expiry_and_lock(request, paid)
        owner = request.user if request.user.is_authenticated else None
        drop = Drop.objects.create(
            ns=ns, key=key, kind=Drop.TEXT, content=text,
            owner=owner,
            locked=paid,
            locked_until=locked_until,
            expires_at=expires_at,
            max_lifetime_secs=max_lifetime_secs(request.user, ns),
            anon_token=anon_token,
        )

    return JsonResponse({
        'key': drop.key,
        'ns': drop.ns,
        'kind': drop.kind,
        'url': f'/{drop.key}/',
        'new': existing is None,
    })


# ── View drop ─────────────────────────────────────────────────────────────────

def _drop_response(request, drop):
    if drop.is_expired():
        drop.hard_delete()
        if 'application/json' in request.headers.get('Accept', ''):
            return JsonResponse({'error': 'Drop has expired.'}, status=410)
        return render(request, 'expired.html', {'key': drop.key})

    drop.touch()

    if 'application/json' in request.headers.get('Accept', ''):
        data = {
            'key': drop.key,
            'ns': drop.ns,
            'kind': drop.kind,
            'created_at': drop.created_at.isoformat(),
            'last_accessed_at': drop.last_accessed_at.isoformat() if drop.last_accessed_at else None,
            'expires_at': drop.expires_at.isoformat() if drop.expires_at else None,
        }
        if drop.kind == Drop.TEXT:
            data['content'] = drop.content
        else:
            data['filename'] = drop.filename
            data['filesize'] = drop.filesize
            data['download'] = f'/f/{drop.key}/download/'
        return JsonResponse(data)

    plan = user_plan(request.user)
    return render(request, 'drop.html', {
        'drop': drop,
        'can_edit': drop.can_edit(request.user),
        'is_owner': request.user.is_authenticated and drop.owner_id == request.user.pk,
        'max_expiry_days': Plan.get(plan, 'max_expiry_days'),
    })


def clipboard_view(request, key):
    drop = Drop.objects.filter(ns=Drop.NS_CLIPBOARD, key=key).first()
    if not drop:
        if 'application/json' in request.headers.get('Accept', ''):
            return JsonResponse({'error': 'Drop not found.'}, status=404)
        raise Http404
    return _drop_response(request, drop)


def file_view(request, key):
    drop = Drop.objects.filter(ns=Drop.NS_FILE, key=key).first()
    if not drop:
        if 'application/json' in request.headers.get('Accept', ''):
            return JsonResponse({'error': 'Drop not found.'}, status=404)
        raise Http404
    return _drop_response(request, drop)


# ── Download ──────────────────────────────────────────────────────────────────

def download_drop(request, key):
    drop = Drop.objects.filter(ns=Drop.NS_FILE, key=key).first()
    if not drop:
        raise Http404
    if drop.is_expired():
        drop.hard_delete()
        raise Http404
    if not drop.file_url:
        raise Http404
    drop.touch()
    return redirect(drop.file_url)