"""
File drop API calls.

Upload flow (CLI → B2 direct, never through Railway):
  1. POST /upload/prepare/  → get presigned PUT URL + confirmed key
  2. PUT  <presigned_url>   → stream file bytes directly to B2
  3. POST /upload/confirm/  → Django verifies + creates Drop record

Download flow:
  GET /f/<key>/             → JSON with { download: "/f/<key>/download/" }
  GET /f/<key>/download/    → 302 to presigned B2 GET URL
  Follow the redirect and stream to disk.

Both upload and download show a progress bar on stderr.
Files are streamed in chunks — never fully loaded into memory.
"""

import os
import mimetypes

import requests as _requests

from .auth import get_csrf
from .helpers import err

CHUNK = 256 * 1024  # 256 KB read/write chunks


# ── Upload ────────────────────────────────────────────────────────────────────

def upload_file(host, session, filepath, key=None, expiry_days=None):
    """
    Upload a file using the prepare → direct-PUT → confirm flow.

    Returns the drop key string on success, None on failure.
    Progress is shown on stderr.
    """
    from cli.progress import ProgressBar

    size         = os.path.getsize(filepath)
    filename     = os.path.basename(filepath)
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"

    # ── Step 1: prepare ───────────────────────────────────────────────────────
    payload = {
        "filename":     filename,
        "size":         size,
        "content_type": content_type,
        "ns":           "f",
    }
    if key:
        payload["key"] = key
    if expiry_days:
        payload["expiry_days"] = expiry_days

    try:
        csrf = get_csrf(host, session)
        res  = session.post(
            f"{host}/upload/prepare/",
            json=payload,
            headers={"X-CSRFToken": csrf},
            timeout=30,
        )
        if not res.ok:
            _handle_error(res, "Prepare failed")
            return None
        prep = res.json()
    except Exception as e:
        err(f"Prepare error: {e}")
        return None

    presigned_url = prep["presigned_url"]
    drop_key      = prep["key"]

    # ── Step 2: stream file directly to B2 ───────────────────────────────────
    bar = ProgressBar(size, label="uploading")

    def _file_iter():
        with open(filepath, "rb") as f:
            while True:
                chunk = f.read(CHUNK)
                if not chunk:
                    break
                bar.update(len(chunk))
                yield chunk

    try:
        put_res = _requests.put(
            presigned_url,
            data=_file_iter(),
            headers={
                "Content-Type":   content_type,
                "Content-Length": str(size),
            },
            timeout=None,  # no timeout — large files can take a while
        )
        if not put_res.ok:
            err(f"B2 upload failed (HTTP {put_res.status_code}): {put_res.text[:200]}")
            return None
    except Exception as e:
        err(f"Upload error: {e}")
        return None

    bar.done()

    # ── Step 3: confirm ───────────────────────────────────────────────────────
    confirm_payload = {
        "key":          drop_key,
        "ns":           "f",
        "filename":     filename,
        "content_type": content_type,
    }
    if expiry_days:
        confirm_payload["expiry_days"] = expiry_days

    try:
        csrf = get_csrf(host, session)
        res  = session.post(
            f"{host}/upload/confirm/",
            json=confirm_payload,
            headers={"X-CSRFToken": csrf},
            timeout=30,
        )
        if res.ok:
            return res.json().get("key")
        _handle_error(res, "Confirm failed")
    except Exception as e:
        err(f"Confirm error: {e}")

    return None


# ── Download ──────────────────────────────────────────────────────────────────

def get_file(host, session, key):
    """
    Fetch a file drop.
    Returns ('file', (bytes_content, filename)) or (None, None).

    Flow:
      1. GET /f/<key>/         → JSON metadata including /f/<key>/download/
      2. GET /f/<key>/download/ → 302 to presigned B2 URL
      3. Stream bytes from B2 to memory / disk
    """
    from cli.progress import ProgressBar

    try:
        res = session.get(
            f"{host}/f/{key}/",
            headers={"Accept": "application/json"},
            timeout=30,
        )
        if not res.ok:
            _handle_http_error(res, key)
            return None, None

        data = res.json()
        if data.get("kind") != "file":
            err(f"/f/{key}/ is not a file drop.")
            return None, None

        download_path = data["download"]          # e.g. /f/report/download/
        filename      = data.get("filename", key)
        filesize      = data.get("filesize", 0)

        # Follow the redirect to the presigned B2 URL
        dl_res = session.get(
            f"{host}{download_path}",
            timeout=10,
            allow_redirects=False,
        )
        if dl_res.status_code in (301, 302, 303, 307, 308):
            b2_url = dl_res.headers["Location"]
        elif dl_res.ok:
            # Shouldn't happen, but handle gracefully
            return "file", (dl_res.content, filename)
        else:
            err(f"Download redirect failed (HTTP {dl_res.status_code}).")
            return None, None

        # Stream from B2 — no session cookies needed
        bar    = ProgressBar(max(filesize, 1), label="downloading")
        chunks = []
        with _requests.get(b2_url, stream=True, timeout=None) as stream:
            if not stream.ok:
                err(f"B2 download failed (HTTP {stream.status_code}).")
                return None, None
            for chunk in stream.iter_content(chunk_size=CHUNK):
                if chunk:
                    chunks.append(chunk)
                    bar.update(len(chunk))

        bar.done()
        return "file", (b"".join(chunks), filename)

    except Exception as e:
        err(f"Get error: {e}")
        return None, None


# ── Internal helpers ──────────────────────────────────────────────────────────

def _handle_error(res, prefix):
    try:
        msg = res.json().get("error", res.text[:200])
    except Exception:
        msg = res.text[:200]
    err(f"{prefix}: {msg}")


def _handle_http_error(res, key):
    if res.status_code == 404:
        err(f"File /f/{key}/ not found.")
    elif res.status_code == 410:
        err(f"File /f/{key}/ has expired.")
    else:
        err(f"Server returned {res.status_code}.")