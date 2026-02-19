import secrets
from datetime import timedelta

import cloudinary.uploader
from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import models as db_models
from django.http import JsonResponse, Http404
from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from .models import Drop, UserProfile, Plan


# ── Rate limiting helpers ─────────────────────────────────────────────────────

def _client_ip(request):
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    return xff.split(',')[0].strip() if xff else request.META.get('REMOTE_ADDR', '')


def _check_signup_rate(request):
    """Max 3 signups per IP per hour."""
    ip = _client_ip(request)
    key = f'signup_rate:{ip}'
    count = cache.get(key, 0)
    if count >= 3:
        return False
    cache.set(key, count + 1, timeout=3600)
    return True


# ── Key helper ────────────────────────────────────────────────────────────────

def _gen_key():
    key = secrets.token_urlsafe(6)
    while Drop.objects.filter(key=key).exists():
        key = secrets.token_urlsafe(6)
    return key


# ── Plan limit helpers ────────────────────────────────────────────────────────

def _user_plan(user):
    if not user.is_authenticated:
        return Plan.ANON
    return getattr(getattr(user, 'profile', None), 'plan', Plan.FREE)


def _max_file_bytes(user):
    return Plan.get(_user_plan(user), 'max_file_mb') * 1024 * 1024


def _max_text_bytes(user):
    return Plan.get(_user_plan(user), 'max_text_kb') * 1024


def _storage_ok(user, extra_bytes):
    if not user.is_authenticated:
        return True
    profile = getattr(user, 'profile', None)
    if not profile:
        return True
    quota = profile.storage_quota_bytes
    if quota is None:
        return True
    return (profile.storage_used_bytes + extra_bytes) <= quota


def _upload_to_cloudinary(file_obj, public_id):
    """Upload a file to Cloudinary. Returns (secure_url, public_id) or raises."""
    result = cloudinary.uploader.upload(
        file_obj,
        resource_type='raw',
        public_id=public_id,
        overwrite=True,
    )
    return result['secure_url'], result['public_id']


# ── Home ──────────────────────────────────────────────────────────────────────

@ensure_csrf_cookie
def home(request):
    server_drops = []
    if request.user.is_authenticated:
        server_drops = (
            Drop.objects
            .filter(owner=request.user)
            .order_by('-created_at')[:50]
        )
    return render(request, 'home.html', {'server_drops': server_drops})


# ── Check key ─────────────────────────────────────────────────────────────────

def check_key(request):
    key = request.GET.get('key', '').strip()
    if not key:
        return JsonResponse({'available': False})
    return JsonResponse({'available': not Drop.objects.filter(key=key).exists()})


# ── Save drop ─────────────────────────────────────────────────────────────────

def save_drop(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    key = request.POST.get('key', '').strip() or _gen_key()

    existing = Drop.objects.filter(key=key).first()
    if existing and existing.is_expired():
        existing.hard_delete()
        existing = None

    if existing and not existing.can_edit(request.user):
        if existing.is_creation_locked():
            return JsonResponse({
                'error': 'This drop was just created and is protected for 24 hours. '
                         'To use this key, wait until the window expires or pick a different key.'
            }, status=403)
        return JsonResponse({'error': 'This drop is locked to its owner.'}, status=403)

    is_paid_user = request.user.is_authenticated and _user_plan(request.user) in (Plan.STARTER, Plan.PRO)

    f = request.FILES.get('file')
    if f:
        if f.size > _max_file_bytes(request.user):
            return JsonResponse(
                {'error': f'File exceeds {Plan.get(_user_plan(request.user), "max_file_mb")}MB limit.'},
                status=400,
            )
        if not _storage_ok(request.user, f.size):
            return JsonResponse({'error': 'Storage quota exceeded.'}, status=400)

        # Upload to Cloudinary directly
        public_id = f'drops/{key}'
        try:
            file_url, file_public_id = _upload_to_cloudinary(f, public_id)
        except Exception as e:
            return JsonResponse({'error': f'File upload failed: {e}'}, status=500)

        if existing:
            # Destroy old Cloudinary file if different public_id
            if existing.file_public_id and existing.file_public_id != file_public_id:
                try:
                    cloudinary.uploader.destroy(existing.file_public_id, resource_type='raw')
                except Exception:
                    pass
            old_size = existing.filesize
            existing.file_url = file_url
            existing.file_public_id = file_public_id
            existing.filename = f.name
            existing.filesize = f.size
            existing.kind = Drop.FILE
            existing.save()
            drop = existing
            if drop.owner_id:
                delta = f.size - old_size
                UserProfile.objects.filter(user_id=drop.owner_id).update(
                    storage_used_bytes=db_models.F('storage_used_bytes') + delta
                )
        else:
            expires_at = None
            locked_until = None
            expiry_days = request.POST.get('expiry_days')

            if is_paid_user and expiry_days:
                try:
                    expiry_days = int(expiry_days)
                    max_days = Plan.get(_user_plan(request.user), 'max_expiry_days')
                    expiry_days = min(expiry_days, max_days)
                    expires_at = timezone.now() + timedelta(days=expiry_days)
                except (ValueError, TypeError):
                    pass
            elif not request.user.is_authenticated:
                locked_until = timezone.now() + timedelta(hours=24)

            owner = request.user if request.user.is_authenticated else None
            drop = Drop.objects.create(
                key=key, kind=Drop.FILE,
                file_url=file_url,
                file_public_id=file_public_id,
                filename=f.name,
                filesize=f.size,
                owner=owner,
                locked=is_paid_user,
                locked_until=locked_until,
                expires_at=expires_at,
            )
            if owner and f.size:
                UserProfile.objects.filter(user=owner).update(
                    storage_used_bytes=db_models.F('storage_used_bytes') + f.size
                )
    else:
        text = request.POST.get('content', '').strip()
        if len(text.encode()) > _max_text_bytes(request.user):
            return JsonResponse(
                {'error': f'Text exceeds {Plan.get(_user_plan(request.user), "max_text_kb")}KB.'},
                status=400,
            )
        if existing:
            existing.content = text
            existing.kind = Drop.TEXT
            existing.created_at = timezone.now()
            existing.save()
            drop = existing
        else:
            expires_at = None
            locked_until = None
            expiry_days = request.POST.get('expiry_days')

            if is_paid_user and expiry_days:
                try:
                    expiry_days = int(expiry_days)
                    max_days = Plan.get(_user_plan(request.user), 'max_expiry_days')
                    expiry_days = min(expiry_days, max_days)
                    expires_at = timezone.now() + timedelta(days=expiry_days)
                except (ValueError, TypeError):
                    pass
            elif not request.user.is_authenticated:
                locked_until = timezone.now() + timedelta(hours=24)

            owner = request.user if request.user.is_authenticated else None
            drop = Drop.objects.create(
                key=key, kind=Drop.TEXT, content=text,
                owner=owner,
                locked=is_paid_user,
                locked_until=locked_until,
                expires_at=expires_at,
            )

    return JsonResponse({
        'key': drop.key,
        'kind': drop.kind,
        'redirect': f'/{drop.key}/',
        'new': existing is None,
    })


# ── View drop ─────────────────────────────────────────────────────────────────

def drop_view(request, key):
    drop = get_object_or_404(Drop, key=key)
    if drop.is_expired():
        drop.hard_delete()
        if 'application/json' in request.headers.get('Accept', ''):
            return JsonResponse({'error': 'expired'}, status=410)
        return render(request, 'expired.html', {'key': key})
    drop.touch()

    if 'application/json' in request.headers.get('Accept', ''):
        data = {'key': drop.key, 'kind': drop.kind, 'created_at': drop.created_at.isoformat()}
        if drop.kind == Drop.TEXT:
            data['content'] = drop.content
        else:
            data['filename'] = drop.filename
            data['filesize'] = drop.filesize
            data['download'] = f'/{drop.key}/download/'
        return JsonResponse(data)

    can_edit = drop.can_edit(request.user)
    plan = _user_plan(request.user)
    max_expiry_days = Plan.get(plan, 'max_expiry_days')
    return render(request, 'drop.html', {
        'drop': drop,
        'can_edit': can_edit,
        'is_owner': request.user.is_authenticated and drop.owner_id == request.user.pk,
        'max_expiry_days': max_expiry_days,
    })


# ── Renew drop ────────────────────────────────────────────────────────────────

def renew_drop(request, key):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    drop = get_object_or_404(Drop, key=key)
    if not (request.user.is_authenticated and drop.owner_id == request.user.pk):
        return JsonResponse({'error': 'Only the owner can renew this drop.'}, status=403)
    if not drop.expires_at:
        return JsonResponse({'error': 'This drop has no expiry to renew.'}, status=400)
    drop.renew()
    return JsonResponse({'expires_at': drop.expires_at.isoformat(), 'renewals': drop.renewal_count})


# ── Rename key ────────────────────────────────────────────────────────────────

def rename_key(request, key):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    drop = get_object_or_404(Drop, key=key)
    if not drop.can_edit(request.user):
        if drop.is_creation_locked():
            return JsonResponse({
                'error': 'This drop is protected for 24 hours after creation and cannot be renamed yet.'
            }, status=403)
        return JsonResponse({'error': 'This drop is locked to its owner.'}, status=403)
    new_key = request.POST.get('new_key', '').strip()
    if not new_key:
        return JsonResponse({'error': 'Key required'}, status=400)
    if Drop.objects.filter(key=new_key).exists():
        return JsonResponse({'error': 'Key taken'}, status=400)
    drop.key = new_key
    drop.save()
    return JsonResponse({'key': new_key, 'redirect': f'/{new_key}/'})


# ── Delete drop ───────────────────────────────────────────────────────────────

def delete_drop(request, key):
    if request.method != 'DELETE':
        return JsonResponse({'error': 'DELETE required'}, status=405)
    drop = get_object_or_404(Drop, key=key)
    if not drop.can_edit(request.user):
        if drop.is_creation_locked():
            return JsonResponse({
                'error': 'This drop is protected for 24 hours after creation and cannot be deleted yet.'
            }, status=403)
        return JsonResponse({'error': 'This drop is locked to its owner.'}, status=403)
    drop.hard_delete()
    return JsonResponse({'deleted': True})


# ── Download ──────────────────────────────────────────────────────────────────

def download_drop(request, key):
    drop = get_object_or_404(Drop, key=key, kind=Drop.FILE)
    if drop.is_expired():
        drop.hard_delete()
        raise Http404
    if not drop.file_url:
        raise Http404
    drop.touch()
    return redirect(drop.file_url)


# ── Help ──────────────────────────────────────────────────────────────────────

def help_view(request):
    return render(request, 'help.html')


# ── Auth: Register ────────────────────────────────────────────────────────────

def register_view(request):
    if request.user.is_authenticated:
        return redirect('home')

    error = None
    if request.method == 'POST':
        if not _check_signup_rate(request):
            error = 'Too many signups from your location. Try again in an hour.'
        else:
            email = request.POST.get('email', '').strip().lower()
            password = request.POST.get('password', '')
            password2 = request.POST.get('password2', '')

            if not email or not password:
                error = 'Email and password are required.'
            elif password != password2:
                error = 'Passwords do not match.'
            elif len(password) < 8:
                error = 'Password must be at least 8 characters.'
            elif User.objects.filter(email=email).exists():
                error = 'An account with that email already exists.'
            else:
                username = email
                user = User.objects.create_user(username=username, email=email, password=password)
                login(request, user)
                return redirect('home')

    return render(request, 'auth/register.html', {
        'error': error,
        'admin_email': settings.ADMIN_EMAIL,
    })


# ── Auth: Login ───────────────────────────────────────────────────────────────

def login_view(request):
    if request.user.is_authenticated:
        return redirect('home')

    error = None
    if request.method == 'POST':
        email = request.POST.get('email', '').strip().lower()
        password = request.POST.get('password', '')
        user = authenticate(request, username=email, password=password)
        if user:
            login(request, user)
            next_url = request.GET.get('next', '/')
            return redirect(next_url)
        else:
            error = 'Invalid email or password.'

    return render(request, 'auth/login.html', {'error': error})


# ── Auth: Logout ──────────────────────────────────────────────────────────────

def logout_view(request):
    logout(request)
    return redirect('home')


# ── Account dashboard ─────────────────────────────────────────────────────────

@login_required
def account_view(request):
    profile = request.user.profile
    profile.recalc_storage()

    # Prune expired drops on the fly
    all_drops = list(Drop.objects.filter(owner=request.user).order_by('-created_at'))
    for d in all_drops:
        if d.is_expired():
            d.hard_delete()
    drops = Drop.objects.filter(owner=request.user).order_by('-created_at')

    plan_limits = Plan.LIMITS.get(profile.plan, Plan.LIMITS[Plan.FREE])

    if 'application/json' in request.headers.get('Accept', ''):
        return JsonResponse({'drops': [
            {
                'key': d.key,
                'kind': d.kind,
                'created_at': d.created_at.isoformat(),
                'expires_at': d.expires_at.isoformat() if d.expires_at else None,
                'filename': d.filename or None,
                'filesize': d.filesize,
                'locked': d.locked,
            }
            for d in drops
        ]})

    return render(request, 'auth/account.html', {
        'profile': profile,
        'drops': drops,
        'plan_limits': plan_limits,
        'Plan': Plan,
    })


# ── Export drops ──────────────────────────────────────────────────────────────

@login_required
def export_drops(request):
    drops = Drop.objects.filter(owner=request.user).order_by('-created_at')
    data = [{
        'key': d.key,
        'kind': d.kind,
        'created_at': d.created_at.isoformat(),
        'expires_at': d.expires_at.isoformat() if d.expires_at else None,
        'filename': d.filename or None,
        'filesize': d.filesize,
        'url': f'{settings.SITE_URL}/{d.key}/',
        'host': settings.SITE_URL,
    } for d in drops]
    import json
    response = JsonResponse({'drops': data}, json_dumps_params={'indent': 2})
    response['Content-Disposition'] = 'attachment; filename="drp-export.json"'
    return response