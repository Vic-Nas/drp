// ── Utilities ────────────────────────────────────────────────────────────────

function getCookie(name) {
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) return parts.pop().split(';').shift();
}

function showToast(msg) {
  let toast = document.getElementById('toast');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = 'toast';
    toast.className = 'toast';
    document.body.appendChild(toast);
  }
  toast.textContent = msg;
  toast.classList.add('show');
  setTimeout(() => toast.classList.remove('show'), 2200);
}

function formatSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

// ── Upload flow ───────────────────────────────────────────────────────────────

const dropZone = document.getElementById('dropZone');
const fileInput = document.getElementById('fileInput');
const uploadBtn = document.getElementById('uploadBtn');
const fileListEl = document.getElementById('fileList');
const keyInput = document.getElementById('keyInput');
const keyStatus = document.getElementById('keyStatus');

let selectedFiles = [];
let keyCheckTimeout = null;

if (dropZone) {
  dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('dragover'); });
  dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
  dropZone.addEventListener('drop', e => {
    e.preventDefault();
    dropZone.classList.remove('dragover');
    addFiles([...e.dataTransfer.files]);
  });
  dropZone.addEventListener('click', () => fileInput && fileInput.click());
}

if (fileInput) {
  fileInput.addEventListener('change', () => addFiles([...fileInput.files]));
}

function addFiles(files) {
  selectedFiles = [...selectedFiles, ...files];
  renderFileList();
  if (uploadBtn) uploadBtn.disabled = selectedFiles.length === 0;
}

function renderFileList() {
  if (!fileListEl) return;
  if (selectedFiles.length === 0) {
    fileListEl.classList.add('hidden');
    return;
  }
  fileListEl.classList.remove('hidden');
  fileListEl.innerHTML = selectedFiles.map((f, i) => `
    <div class="file-item">
      <span class="fname">${f.name}</span>
      <span class="fsize">${formatSize(f.size)}</span>
      <button class="btn-sm danger" onclick="removeFile(${i})">✕</button>
    </div>
  `).join('');
}

function removeFile(i) {
  selectedFiles.splice(i, 1);
  renderFileList();
  if (uploadBtn) uploadBtn.disabled = selectedFiles.length === 0;
}

// Key availability check
if (keyInput) {
  keyInput.addEventListener('input', () => {
    clearTimeout(keyCheckTimeout);
    const val = keyInput.value.trim();
    if (!val) { keyStatus.textContent = ''; return; }
    keyCheckTimeout = setTimeout(async () => {
      const res = await fetch(`/check-key/?key=${encodeURIComponent(val)}`);
      const data = await res.json();
      keyStatus.textContent = data.available ? '✓ available' : '✗ taken';
      keyStatus.className = data.available ? 'ok' : 'taken';
    }, 400);
  });
}

// Upload
if (uploadBtn) {
  uploadBtn.addEventListener('click', async () => {
    if (selectedFiles.length === 0) return;
    uploadBtn.disabled = true;
    uploadBtn.textContent = 'uploading…';

    const key = keyInput ? keyInput.value.trim() : '';
    const url = key ? `/b/${key}/upload/` : '/upload/';

    const formData = new FormData();
    selectedFiles.forEach(f => formData.append('files', f));
    formData.append('csrfmiddlewaretoken', getCookie('csrftoken'));

    try {
      const res = await fetch(url, { method: 'POST', body: formData });
      const data = await res.json();
      if (res.ok) {
        // Auto-download key file
        window.location.href = `/b/${data.key}/key-file/`;
        // Then redirect to bin
        setTimeout(() => { window.location.href = `/b/${data.key}/`; }, 800);
      } else {
        showToast(data.error || 'Upload failed.');
        uploadBtn.disabled = false;
        uploadBtn.textContent = 'upload';
      }
    } catch (e) {
      showToast('Network error.');
      uploadBtn.disabled = false;
      uploadBtn.textContent = 'upload';
    }
  });
}

// Bin page upload (compact)
if (typeof UPLOAD_URL !== 'undefined' && uploadBtn) {
  uploadBtn.addEventListener('click', async () => {
    if (selectedFiles.length === 0) return;
    uploadBtn.disabled = true;
    uploadBtn.textContent = 'uploading…';

    const formData = new FormData();
    selectedFiles.forEach(f => formData.append('files', f));
    formData.append('csrfmiddlewaretoken', getCookie('csrftoken'));

    const res = await fetch(UPLOAD_URL, { method: 'POST', body: formData });
    if (res.ok) {
      window.location.reload();
    } else {
      const data = await res.json();
      showToast(data.error || 'Upload failed.');
      uploadBtn.disabled = false;
      uploadBtn.textContent = 'upload';
    }
  });
}