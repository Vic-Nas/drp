from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse, JsonResponse, Http404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET
from django.utils import timezone
from django.conf import settings
from datetime import timedelta
import json

from .models import Bin, BinFile, Clipboard


# ── Home ──────────────────────────────────────────────────────────────────────

def home(request):
    import secrets
    key = secrets.token_urlsafe(6)
    return redirect(f'/c/{key}/')


# ── Bin ───────────────────────────────────────────────────────────────────────

def bin_view(request, key):
    bin_obj = get_object_or_404(Bin, key=key)
    # Update last_accessed
    bin_obj.save()
    files = bin_obj.files.all().order_by('-uploaded_at')
    return render(request, 'bin.html', {'bin': bin_obj, 'files': files})


@require_POST
def bin_upload(request, key=None):
    max_bytes = settings.ANON_BIN_MAX_SIZE_MB * 1024 * 1024

    # Get or create bin
    if key:
        bin_obj, _ = Bin.objects.get_or_create(key=key)
    else:
        import secrets
        new_key = secrets.token_urlsafe(8)
        while Bin.objects.filter(key=new_key).exists():
            new_key = secrets.token_urlsafe(8)
        bin_obj = Bin.objects.create(key=new_key)

    # Check size limit
    current_size = bin_obj.total_size()
    uploaded_files = request.FILES.getlist('files')

    new_size = sum(f.size for f in uploaded_files)
    if current_size + new_size > max_bytes:
        return JsonResponse({'error': f'Bin exceeds {settings.ANON_BIN_MAX_SIZE_MB}MB limit.'}, status=400)

    saved = []
    for f in uploaded_files:
        bin_file = BinFile.objects.create(
            bin=bin_obj,
            filename=f.name,
            file=f,
            size=f.size,
        )
        saved.append(bin_file.filename)

    return JsonResponse({
        'key': bin_obj.key,
        'files': saved,
        'redirect': f'/b/{bin_obj.key}/',
    })


def bin_check_key(request):
    key = request.GET.get('key', '').strip()
    if not key:
        return JsonResponse({'available': False})
    exists = Bin.objects.filter(key=key).exists()
    return JsonResponse({'available': not exists})


def bin_file_download(request, key, file_id):
    bin_obj = get_object_or_404(Bin, key=key)
    bin_file = get_object_or_404(BinFile, id=file_id, bin=bin_obj)
    # Redirect to cloudinary URL (it handles the actual download)
    return redirect(bin_file.file.url)


def bin_file_delete(request, key, file_id):
    if request.method != 'DELETE':
        return HttpResponse(status=405)
    bin_obj = get_object_or_404(Bin, key=key)
    bin_file = get_object_or_404(BinFile, id=file_id, bin=bin_obj)
    bin_file.file.delete(save=False)
    bin_file.delete()
    return JsonResponse({'deleted': True})


def download_key_file(request, key):
    """Auto-download a .txt file with bin info after upload."""
    bin_obj = get_object_or_404(Bin, key=key)
    files = bin_obj.files.all()
    lines = [
        f'drp — Bin Key File',
        f'==================',
        f'Key:     {bin_obj.key}',
        f'URL:     {request.build_absolute_uri(f"/b/{bin_obj.key}/").rstrip("/")}',
        f'Created: {bin_obj.created_at.strftime("%Y-%m-%d %H:%M UTC")}',
        f'',
        f'Files:',
    ]
    for f in files:
        lines.append(f'  - {f.filename} ({round(f.size/1024, 1)} KB)')
    lines += ['', 'Keep this file to access your bin later.']

    content = '\n'.join(lines)
    response = HttpResponse(content, content_type='text/plain')
    response['Content-Disposition'] = f'attachment; filename="drp-{bin_obj.key}.txt"'
    return response


# ── Clipboard ─────────────────────────────────────────────────────────────────

def clipboard_view(request, key):
    try:
        clip = Clipboard.objects.get(key=key)
        if clip.is_expired():
            clip.delete()
            clip = None
    except Clipboard.DoesNotExist:
        clip = None

    if request.method == 'POST':
        content = request.POST.get('content', '').strip()
        max_bytes = settings.CLIPBOARD_MAX_SIZE_KB * 1024
        if len(content.encode()) > max_bytes:
            return render(request, 'clipboard.html', {
                'key': key, 'clip': clip,
                'error': f'Content exceeds {settings.CLIPBOARD_MAX_SIZE_KB}KB limit.'
            })
        clip, _ = Clipboard.objects.update_or_create(
            key=key,
            defaults={'content': content, 'created_at': timezone.now()}
        )
        return redirect(f'/c/{key}/')

    # Also load any files stored under this key
    try:
        bin_obj = Bin.objects.get(key=key)
        bin_files = bin_obj.files.all().order_by('-uploaded_at')
    except Bin.DoesNotExist:
        bin_files = []

    return render(request, 'clipboard.html', {'key': key, 'clip': clip, 'bin_files': bin_files})