UI_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Invoice Parser</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f0f2f5; min-height: 100vh; display: flex; align-items: flex-start; justify-content: center; padding: 40px 16px; }
  .card { background: #fff; border-radius: 12px; box-shadow: 0 2px 16px rgba(0,0,0,.08); width: 100%; max-width: 640px; padding: 36px; }
  h1 { font-size: 22px; font-weight: 700; color: #111; margin-bottom: 6px; }
  .subtitle { font-size: 13px; color: #777; margin-bottom: 28px; }

  /* API key */
  .key-row { display: flex; gap: 8px; margin-bottom: 24px; }
  .key-row input { flex: 1; padding: 9px 12px; border: 1.5px solid #ddd; border-radius: 8px; font-size: 13px; font-family: monospace; }
  .key-row input:focus { outline: none; border-color: #4f46e5; }
  .key-saved { font-size: 12px; color: #16a34a; margin-top: -18px; margin-bottom: 18px; display: none; }

  /* Dropzone */
  .dropzone { border: 2px dashed #cbd5e1; border-radius: 10px; padding: 36px 24px; text-align: center; cursor: pointer; transition: border-color .15s, background .15s; margin-bottom: 16px; }
  .dropzone:hover, .dropzone.drag { border-color: #4f46e5; background: #f5f3ff; }
  .dropzone svg { width: 40px; height: 40px; color: #94a3b8; margin-bottom: 10px; }
  .dropzone .drop-title { font-size: 15px; font-weight: 600; color: #334155; margin-bottom: 4px; }
  .dropzone .drop-sub { font-size: 12px; color: #94a3b8; }
  #file-input { display: none; }

  /* File list */
  #file-list { margin-bottom: 20px; display: none; }
  .file-item { display: flex; align-items: center; justify-content: space-between; padding: 8px 12px; background: #f8fafc; border-radius: 6px; margin-bottom: 6px; font-size: 13px; }
  .file-item .fname { color: #334155; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 380px; }
  .file-item .fsize { color: #94a3b8; font-size: 12px; flex-shrink: 0; }
  .file-item .remove { cursor: pointer; color: #ef4444; font-size: 16px; line-height: 1; padding: 0 4px; flex-shrink: 0; }
  .file-count { font-size: 12px; color: #64748b; margin-bottom: 12px; }

  /* Format select */
  .row { display: flex; gap: 10px; align-items: center; margin-bottom: 20px; }
  .row label { font-size: 13px; color: #64748b; white-space: nowrap; }
  select { padding: 8px 10px; border: 1.5px solid #ddd; border-radius: 8px; font-size: 13px; background: #fff; }
  select:focus { outline: none; border-color: #4f46e5; }

  /* Button */
  button.primary { width: 100%; padding: 12px; background: #4f46e5; color: #fff; border: none; border-radius: 8px; font-size: 15px; font-weight: 600; cursor: pointer; transition: background .15s; }
  button.primary:hover { background: #4338ca; }
  button.primary:disabled { background: #a5b4fc; cursor: not-allowed; }
  button.save-btn { padding: 9px 14px; background: #4f46e5; color: #fff; border: none; border-radius: 8px; font-size: 13px; font-weight: 600; cursor: pointer; white-space: nowrap; }
  button.save-btn:hover { background: #4338ca; }

  /* Status */
  #status-box { margin-top: 24px; display: none; }
  .status-label { font-size: 13px; color: #64748b; margin-bottom: 8px; display: flex; justify-content: space-between; }
  .progress-bar-bg { background: #e2e8f0; border-radius: 99px; height: 8px; overflow: hidden; margin-bottom: 14px; }
  .progress-bar-fill { height: 100%; background: #4f46e5; border-radius: 99px; transition: width .3s; width: 0%; }
  .status-msg { font-size: 13px; color: #475569; background: #f8fafc; border-radius: 8px; padding: 10px 14px; border-left: 3px solid #4f46e5; }
  .status-msg.done { border-color: #16a34a; background: #f0fdf4; color: #15803d; }
  .status-msg.error { border-color: #ef4444; background: #fef2f2; color: #b91c1c; }

  /* Download */
  #download-box { margin-top: 16px; display: none; }
  button.download-btn { width: 100%; padding: 12px; background: #16a34a; color: #fff; border: none; border-radius: 8px; font-size: 15px; font-weight: 600; cursor: pointer; transition: background .15s; }
  button.download-btn:hover { background: #15803d; }

  hr { border: none; border-top: 1px solid #f1f5f9; margin: 24px 0; }
</style>
</head>
<body>
<div class="card">
  <h1>Invoice Parser</h1>
  <p class="subtitle">Upload up to 10 PDF invoices and download the extracted Excel</p>

  <hr>

  <div class="key-row">
    <input type="password" id="api-key-input" placeholder="API key  (aug_...)" autocomplete="off">
    <button class="save-btn" onclick="saveKey()">Save</button>
  </div>
  <div class="key-saved" id="key-saved">Key saved</div>

  <div class="dropzone" id="dropzone" onclick="document.getElementById('file-input').click()">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
      <path d="M12 16V4m0 0L8 8m4-4l4 4M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1"/>
    </svg>
    <div class="drop-title">Drop PDF invoices here</div>
    <div class="drop-sub">or click to browse &mdash; up to 10 files, 50 MB each</div>
    <input type="file" id="file-input" multiple accept=".pdf">
  </div>

  <div id="file-list"></div>

  <div class="row">
    <label>Output format</label>
    <select id="fmt">
      <option value="xlsx">Excel (.xlsx)</option>
      <option value="json">JSON</option>
      <option value="both">Both</option>
    </select>
  </div>

  <button class="primary" id="submit-btn" onclick="submit()">Process Invoices</button>

  <div id="status-box">
    <hr>
    <div class="status-label">
      <span id="status-title">Processing...</span>
      <span id="status-count"></span>
    </div>
    <div class="progress-bar-bg"><div class="progress-bar-fill" id="progress-fill"></div></div>
    <div class="status-msg" id="status-msg">Queued — waiting for worker...</div>
  </div>

  <div id="download-box">
    <button class="download-btn" id="dl-btn" onclick="doDownload()">Download Excel</button>
  </div>
</div>

<script>
  let files = [];
  let pollTimer = null;
  let currentJobId = null;
  let currentFmt = 'xlsx';

  // Restore key
  const stored = localStorage.getItem('inv_api_key');
  if (stored) {
    document.getElementById('api-key-input').value = stored;
    showKeySaved();
  }

  function saveKey() {
    const v = document.getElementById('api-key-input').value.trim();
    if (!v) return;
    localStorage.setItem('inv_api_key', v);
    showKeySaved();
  }

  function showKeySaved() {
    const el = document.getElementById('key-saved');
    el.style.display = 'block';
    setTimeout(() => el.style.display = 'none', 2000);
  }

  function getKey() {
    return (document.getElementById('api-key-input').value.trim() ||
            localStorage.getItem('inv_api_key') || '');
  }

  // Drag and drop
  const dz = document.getElementById('dropzone');
  dz.addEventListener('dragover', e => { e.preventDefault(); dz.classList.add('drag'); });
  dz.addEventListener('dragleave', () => dz.classList.remove('drag'));
  dz.addEventListener('drop', e => {
    e.preventDefault(); dz.classList.remove('drag');
    addFiles([...e.dataTransfer.files]);
  });
  document.getElementById('file-input').addEventListener('change', e => {
    addFiles([...e.target.files]);
    e.target.value = '';
  });

  function addFiles(newFiles) {
    for (const f of newFiles) {
      if (!f.name.toLowerCase().endsWith('.pdf')) continue;
      if (files.length >= 10) { alert('Maximum 10 files'); break; }
      if (files.some(x => x.name === f.name && x.size === f.size)) continue;
      files.push(f);
    }
    renderFileList();
  }

  function removeFile(i) {
    files.splice(i, 1);
    renderFileList();
  }

  function renderFileList() {
    const el = document.getElementById('file-list');
    if (!files.length) { el.style.display = 'none'; return; }
    el.style.display = 'block';
    el.innerHTML = '<div class="file-count">' + files.length + ' file' + (files.length > 1 ? 's' : '') + ' selected</div>' +
      files.map((f, i) =>
        '<div class="file-item">' +
        '<span class="fname">' + esc(f.name) + '</span>' +
        '<span class="fsize">' + fmtSize(f.size) + '</span>' +
        '<span class="remove" onclick="removeFile(' + i + ')">×</span>' +
        '</div>'
      ).join('');
  }

  function fmtSize(b) {
    if (b < 1024) return b + ' B';
    if (b < 1024*1024) return (b/1024).toFixed(0) + ' KB';
    return (b/1024/1024).toFixed(1) + ' MB';
  }

  function esc(s) {
    return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  async function submit() {
    const key = getKey();
    if (!key) { alert('Enter your API key first'); return; }
    if (!files.length) { alert('Select at least one PDF'); return; }

    const fmt = document.getElementById('fmt').value;
    currentFmt = fmt;

    const btn = document.getElementById('submit-btn');
    btn.disabled = true;
    btn.textContent = 'Uploading...';

    document.getElementById('status-box').style.display = 'block';
    document.getElementById('download-box').style.display = 'none';
    setStatus('Uploading files...', 0, '', '');

    try {
      const fd = new FormData();
      for (const f of files) fd.append('files', f);
      fd.append('output_format', fmt);

      const res = await fetch('/jobs', {
        method: 'POST',
        headers: { 'Authorization': 'Bearer ' + key },
        body: fd,
      });

      if (res.status === 401) { alert('Invalid API key'); resetBtn(); return; }
      if (!res.ok) { const t = await res.text(); alert('Upload failed: ' + t); resetBtn(); return; }

      const data = await res.json();
      currentJobId = data.job_id;
      btn.textContent = 'Processing...';
      setStatus('Job queued — waiting for worker...', 0, '0 / ' + files.length + ' files', '');
      pollTimer = setInterval(() => poll(key, currentJobId), 3000);

    } catch(e) {
      alert('Error: ' + e.message);
      resetBtn();
    }
  }

  async function poll(key, jobId) {
    try {
      const res = await fetch('/jobs/' + jobId, {
        headers: { 'Authorization': 'Bearer ' + key }
      });
      if (!res.ok) return;
      const d = await res.json();
      const p = d.progress || {};
      const total = p.files_total || files.length;
      const done = p.files_completed || 0;
      const pct = total ? Math.round(done / total * 100) : 0;

      if (d.status === 'done') {
        clearInterval(pollTimer);
        const inv = (d.result && d.result.summary) ? d.result.summary : {};
        const msg = 'Done! ' + (inv.invoices_total || 0) + ' invoice(s) extracted' +
          (inv.invoices_review ? ', ' + inv.invoices_review + ' flagged for review' : '') + '.';
        setStatus(msg, 100, total + ' / ' + total + ' files', 'done');
        document.getElementById('status-title').textContent = 'Complete';
        document.getElementById('download-box').style.display = 'block';
        updateDownloadBtn(d.result);
        document.getElementById('submit-btn').textContent = 'Process Invoices';
        document.getElementById('submit-btn').disabled = false;

      } else if (d.status === 'failed') {
        clearInterval(pollTimer);
        setStatus('Job failed: ' + (d.error || 'unknown error'), pct, done + ' / ' + total + ' files', 'error');
        resetBtn();

      } else {
        const statusMap = { queued: 'Queued — waiting for worker...', processing: 'Processing...' };
        const msg = statusMap[d.status] || d.status;
        setStatus(msg, pct, done + ' / ' + total + ' files', '');
      }
    } catch(e) { /* ignore transient errors */ }
  }

  function setStatus(msg, pct, countText, cls) {
    document.getElementById('status-msg').textContent = msg;
    document.getElementById('status-msg').className = 'status-msg' + (cls ? ' ' + cls : '');
    document.getElementById('progress-fill').style.width = pct + '%';
    document.getElementById('status-count').textContent = countText;
  }

  function updateDownloadBtn(result) {
    const btn = document.getElementById('dl-btn');
    if (!result || !result.downloads) return;
    if (currentFmt === 'json' && result.downloads.json && !result.downloads.xlsx) {
      btn.textContent = 'Download JSON';
    } else {
      btn.textContent = 'Download Excel';
    }
  }

  function doDownload() {
    const key = getKey();
    const fmt = (currentFmt === 'json') ? 'json' : 'xlsx';
    // Use a hidden link with auth header via fetch + blob
    fetch('/jobs/' + currentJobId + '/download?format=' + fmt, {
      headers: { 'Authorization': 'Bearer ' + key }
    }).then(r => {
      const cd = r.headers.get('Content-Disposition') || '';
      const match = cd.match(/filename="([^"]+)"/);
      const filename = match ? match[1] : ('invoices.' + fmt);
      return r.blob().then(b => ({ b, filename }));
    }).then(({ b, filename }) => {
      const url = URL.createObjectURL(b);
      const a = document.createElement('a');
      a.href = url; a.download = filename;
      document.body.appendChild(a); a.click();
      document.body.removeChild(a); URL.revokeObjectURL(url);
    });
  }

  function resetBtn() {
    const btn = document.getElementById('submit-btn');
    btn.disabled = false;
    btn.textContent = 'Process Invoices';
  }
</script>
</body>
</html>"""
