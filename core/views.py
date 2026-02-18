import secrets
from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse, JsonResponse, Http404
from django.utils import timezone
from django.conf import settings
from .models import Drop


def _gen_key():
    key = secrets.token_urlsafe(6)
    while Drop.objects.filter(key=key).exists():
        key = secrets.token_urlsafe(6)
    return key


# ── Home ──────────────────────────────────────────────────────────────────────

def home(request):
    return render(request, 'home.html')


# ── Check key availability ────────────────────────────────────────────────────

def check_key(request):
    key = request.GET.get('key', '').strip()
    if not key:
        return JsonResponse({'available': False})
    return JsonResponse({'available': not Drop.objects.filter(key=key).exists()})


# ── Save a drop (text or file) ────────────────────────────────────────────────

def save_drop(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    key = request.POST.get('key', '').strip() or _gen_key()

    # Check if key exists — if so, only allow overwrite (same session intent)
    existing = Drop.objects.filter(key=key).first()
    if existing and existing.is_expired():
        existing.hard_delete()
        existing = None

    # File upload?
    f = request.FILES.get('file')
    if f:
        max_bytes = settings.ANON_BIN_MAX_SIZE_MB * 1024 * 1024
        if f.size > max_bytes:
            return JsonResponse({'error': f'File exceeds {settings.ANON_BIN_MAX_SIZE_MB}MB limit.'}, status=400)
        if existing:
            if existing.file:
                existing.file.delete(save=False)
            existing.file = f
            existing.filename = f.name
            existing.filesize = f.size
            existing.kind = Drop.FILE
            existing.save()
            drop = existing
        else:
            drop = Drop.objects.create(key=key, kind=Drop.FILE, file=f, filename=f.name, filesize=f.size)
    else:
        content = request.POST.get('content', '').strip()
        max_bytes = settings.CLIPBOARD_MAX_SIZE_KB * 1024
        if len(content.encode()) > max_bytes:
            return JsonResponse({'error': f'Text exceeds {settings.CLIPBOARD_MAX_SIZE_KB}KB.'}, status=400)
        if existing:
            existing.content = content
            existing.kind = Drop.TEXT
            existing.created_at = timezone.now()
            existing.save()
            drop = existing
        else:
            drop = Drop.objects.create(key=key, kind=Drop.TEXT, content=content)

    return JsonResponse({'key': drop.key, 'kind': drop.kind, 'redirect': f'/{drop.key}/'})


# ── View / edit a drop ────────────────────────────────────────────────────────

def drop_view(request, key):
    drop = get_object_or_404(Drop, key=key)

    if drop.is_expired():
        drop.hard_delete()
        return render(request, 'expired.html', {'key': key})

    drop.touch()
    return render(request, 'drop.html', {'drop': drop})


# ── Rename key ────────────────────────────────────────────────────────────────

def rename_key(request, key):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    drop = get_object_or_404(Drop, key=key)
    new_key = request.POST.get('new_key', '').strip()
    if not new_key:
        return JsonResponse({'error': 'Key required'}, status=400)
    if Drop.objects.filter(key=new_key).exists():
        return JsonResponse({'error': 'Key taken'}, status=400)
    drop.key = new_key
    drop.save()
    return JsonResponse({'key': new_key, 'redirect': f'/{new_key}/'})


# ── Delete a drop ─────────────────────────────────────────────────────────────

def delete_drop(request, key):
    if request.method != 'DELETE':
        return JsonResponse({'error': 'DELETE required'}, status=405)
    drop = get_object_or_404(Drop, key=key)
    drop.hard_delete()
    return JsonResponse({'deleted': True})


# ── File download ─────────────────────────────────────────────────────────────

def download_drop(request, key):
    drop = get_object_or_404(Drop, key=key, kind=Drop.FILE)
    if drop.is_expired():
        drop.hard_delete()
        raise Http404
    drop.touch()
    return redirect(drop.file.url)