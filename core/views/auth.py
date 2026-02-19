"""
Auth views: register, login, logout, account dashboard, export, import.
"""

import json

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.views.decorators.http import require_POST

from core.models import Drop, Plan, SavedDrop
from .helpers import check_signup_rate, user_plan


# ── Register ──────────────────────────────────────────────────────────────────

def register_view(request):
    if request.user.is_authenticated:
        return redirect('home')

    error = None
    if request.method == 'POST':
        if not check_signup_rate(request):
            error = 'Too many signups from your location. Try again in an hour.'
        else:
            email = request.POST.get('email', '').strip().lower()
            password = request.POST.get('password', '')
            password2 = request.POST.get('password2', '')
            plan_choice = request.POST.get('plan', 'free').strip().lower()

            if not email or not password:
                error = 'Email and password are required.'
            elif password != password2:
                error = 'Passwords do not match.'
            elif len(password) < 8:
                error = 'Password must be at least 8 characters.'
            elif User.objects.filter(email=email).exists():
                error = 'An account with that email already exists.'
            else:
                user = User.objects.create_user(username=email, email=email, password=password)
                login(request, user)
                if plan_choice in ('starter', 'pro'):
                    return redirect(f'/billing/checkout/{plan_choice}/')
                return redirect('home')

    return render(request, 'auth/register.html', {
        'error': error,
        'admin_email': settings.ADMIN_EMAIL,
    })


# ── Login ─────────────────────────────────────────────────────────────────────

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
            return redirect(request.GET.get('next', '/'))
        error = 'Invalid email or password.'

    return render(request, 'auth/login.html', {'error': error})


# ── Logout ────────────────────────────────────────────────────────────────────

def logout_view(request):
    logout(request)
    return redirect('home')


# ── Account ───────────────────────────────────────────────────────────────────

@login_required
def account_view(request):
    profile = request.user.profile
    profile.recalc_storage()

    # Clean expired owned drops
    for d in Drop.objects.filter(owner=request.user):
        if d.is_expired():
            d.hard_delete()

    drops = Drop.objects.filter(owner=request.user).order_by('-created_at')
    saved = SavedDrop.objects.filter(user=request.user).order_by('-saved_at')
    plan_limits = Plan.LIMITS.get(profile.plan, Plan.LIMITS[Plan.FREE])

    if 'application/json' in request.headers.get('Accept', ''):
        return JsonResponse({
            'drops': [_drop_dict(d) for d in drops],
            'saved': [_saved_dict(s) for s in saved],
        })

    return render(request, 'auth/account.html', {
        'profile': profile,
        'drops': drops,
        'saved': saved,
        'plan_limits': plan_limits,
        'Plan': Plan,
    })


# ── Export ────────────────────────────────────────────────────────────────────

@login_required
def export_drops(request):
    drops = Drop.objects.filter(owner=request.user).order_by('-created_at')
    saved = SavedDrop.objects.filter(user=request.user).order_by('-saved_at')

    owned_data = []
    for d in drops:
        entry = _drop_dict(d)
        url = (
            f'{settings.SITE_URL}/f/{d.key}/'
            if d.ns == Drop.NS_FILE
            else f'{settings.SITE_URL}/{d.key}/'
        )
        entry.update({'url': url, 'host': settings.SITE_URL})
        owned_data.append(entry)

    saved_data = [_saved_dict(s, host=settings.SITE_URL) for s in saved]

    response = JsonResponse(
        {'drops': owned_data, 'saved': saved_data},
        json_dumps_params={'indent': 2},
    )
    response['Content-Disposition'] = 'attachment; filename="drp-export.json"'
    return response


# ── Import ────────────────────────────────────────────────────────────────────

@login_required
@require_POST
def import_drops(request):
    """
    Accept a JSON export and bookmark all drops in it for the current user.
    No content is stored. No ownership is transferred.
    The importer gets SavedDrop entries pointing to the original keys.
    """
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'Invalid JSON.'}, status=400)

    # Accept both {drops: [], saved: []} and a bare list
    if isinstance(data, list):
        entries = data
    else:
        # Merge owned drops and previously saved drops from the export
        entries = data.get('drops', []) + data.get('saved', [])

    if not entries:
        return JsonResponse({'imported': 0, 'skipped': 0})

    imported = 0
    skipped = 0

    for entry in entries:
        key = (entry.get('key') or '').strip()
        ns = entry.get('ns', 'c')

        if not key or ns not in ('c', 'f'):
            skipped += 1
            continue

        _, created = SavedDrop.objects.get_or_create(
            user=request.user,
            ns=ns,
            key=key,
        )
        if created:
            imported += 1
        else:
            skipped += 1  # already bookmarked

    return JsonResponse({'imported': imported, 'skipped': skipped})


# ── Internal helpers ──────────────────────────────────────────────────────────

def _drop_dict(d):
    return {
        'key': d.key,
        'ns': d.ns,
        'kind': d.kind,
        'created_at': d.created_at.isoformat(),
        'last_accessed_at': d.last_accessed_at.isoformat() if d.last_accessed_at else None,
        'expires_at': d.expires_at.isoformat() if d.expires_at else None,
        'filename': d.filename or None,
        'filesize': d.filesize,
        'locked': d.locked,
    }


def _saved_dict(s, host=None):
    url_path = f'/f/{s.key}/' if s.ns == Drop.NS_FILE else f'/{s.key}/'
    return {
        'key': s.key,
        'ns': s.ns,
        'saved_at': s.saved_at.isoformat(),
        'url': f'{host}{url_path}' if host else url_path,
    }