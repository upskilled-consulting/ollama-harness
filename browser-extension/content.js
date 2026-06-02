(function () {
  'use strict';

  const HARNESS_API = 'http://localhost:7860/api/page-feedback';
  const LS_KEY      = 'harness_page_feedback';
  const WIDGET_ID   = '__harness_fb_widget__';

  if (document.getElementById(WIDGET_ID)) return;

  // --- corner detection ---
  function pickCorner() {
    const corners = ['bottom-right', 'bottom-left', 'top-right', 'top-left'];
    const fixed = Array.from(document.querySelectorAll('*')).filter(el => {
      const s = window.getComputedStyle(el);
      return s.position === 'fixed' && el.id !== WIDGET_ID;
    });
    function occupied(corner) {
      for (const el of fixed) {
        const r = el.getBoundingClientRect();
        const w = window.innerWidth, h = window.innerHeight;
        if (corner === 'bottom-right' && r.right > w - 100 && r.bottom > h - 100) return true;
        if (corner === 'bottom-left'  && r.left < 100      && r.bottom > h - 100) return true;
        if (corner === 'top-right'    && r.right > w - 100 && r.top < 100)         return true;
        if (corner === 'top-left'     && r.left < 100      && r.top < 100)         return true;
      }
      return false;
    }
    return corners.find(c => !occupied(c)) || 'bottom-right';
  }

  function cornerCSS(corner) {
    const m = '16px';
    if (corner === 'bottom-right') return { bottom: m, right: m };
    if (corner === 'bottom-left')  return { bottom: m, left:  m };
    if (corner === 'top-right')    return { top:    m, right: m };
    return                                { top:    m, left:  m };
  }

  // --- storage helpers ---
  function loadAll() {
    try { return JSON.parse(localStorage.getItem(LS_KEY) || '[]'); } catch { return []; }
  }
  function saveAll(records) {
    try { localStorage.setItem(LS_KEY, JSON.stringify(records)); } catch {}
  }
  function forPage() {
    return loadAll().filter(r => r.url === location.href);
  }
  function toggleDone(id) {
    const all = loadAll();
    const rec = all.find(r => r.id === id);
    if (rec) rec.completed = !rec.completed;
    saveAll(all);
    return rec;
  }
  function addRecord(rec) {
    const all = loadAll();
    all.unshift(rec);
    saveAll(all);
  }

  // --- build shadow DOM ---
  const host = document.createElement('div');
  host.id = WIDGET_ID;
  Object.assign(host.style, { position: 'fixed', zIndex: '2147483647' }, cornerCSS(pickCorner()));
  document.body.appendChild(host);

  const shadow = host.attachShadow({ mode: 'open' });

  shadow.innerHTML = `
<style>
  * { box-sizing: border-box; font-family: system-ui, sans-serif; margin: 0; padding: 0; }

  #wrap { display: flex; flex-direction: column; align-items: flex-end; gap: 8px; }

  /* --- button --- */
  #btn-wrap { position: relative; }
  #dismiss {
    display: none;
    position: absolute; top: -6px; left: -6px;
    width: 16px; height: 16px; border-radius: 50%;
    background: #2a2a3e; border: 1px solid #555;
    color: #888; font-size: 9px; line-height: 1;
    cursor: pointer; align-items: center; justify-content: center;
    transition: background .15s, color .15s;
  }
  #btn-wrap:hover #dismiss { display: flex; }
  #dismiss:hover { background: #ff4444; border-color: #ff4444; color: #fff; }
  #btn {
    width: 44px; height: 44px; border-radius: 50%;
    background: #1a1a2e; border: 2px solid #4ade80;
    color: #4ade80; font-size: 20px; cursor: pointer;
    display: flex; align-items: center; justify-content: center;
    box-shadow: 0 2px 12px rgba(0,0,0,.45);
    transition: transform .15s;
  }
  #btn:hover { transform: scale(1.08); }
  #badge {
    display: none;
    position: absolute; top: -4px; right: -4px;
    min-width: 18px; height: 18px; border-radius: 9px;
    background: #4ade80; color: #0f0f1a;
    font-size: 10px; font-weight: 700;
    align-items: center; justify-content: center;
    padding: 0 4px;
    box-shadow: 0 1px 4px rgba(0,0,0,.4);
  }
  #badge.visible { display: flex; }

  /* --- panel --- */
  #panel {
    display: none; flex-direction: column; gap: 10px;
    background: #1a1a2e; border: 1px solid #4ade80;
    border-radius: 10px; padding: 12px;
    width: 300px; max-height: 480px;
    box-shadow: 0 4px 20px rgba(0,0,0,.55);
    overflow: hidden;
  }
  #panel.open { display: flex; }

  #panel-header {
    display: flex; justify-content: space-between; align-items: center;
    color: #4ade80; font-size: 13px; font-weight: 600; flex-shrink: 0;
  }
  #close-btn {
    background: none; border: none; color: #4ade80;
    font-size: 16px; cursor: pointer; padding: 0 2px; line-height: 1;
  }

  #url-label {
    font-size: 10px; color: #666;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; flex-shrink: 0;
  }

  /* --- checklist --- */
  #list {
    display: flex; flex-direction: column; gap: 6px;
    overflow-y: auto; max-height: 200px; flex-shrink: 0;
  }
  #list:empty { display: none; }
  #list-divider {
    border: none; border-top: 1px solid #2a2a3e; flex-shrink: 0; display: none;
  }
  #list:not(:empty) + #list-divider { display: block; }

  .item {
    display: flex; align-items: flex-start; gap: 8px;
    padding: 6px 4px; border-radius: 6px;
    transition: background .15s;
  }
  .item:hover { background: #22223a; }

  .cb-wrap {
    flex-shrink: 0; margin-top: 1px;
    width: 16px; height: 16px; position: relative; cursor: pointer;
  }
  .cb-wrap input[type=checkbox] {
    appearance: none; -webkit-appearance: none;
    width: 16px; height: 16px; border-radius: 50%;
    border: 2px solid #4ade80; background: transparent;
    cursor: pointer; transition: background .2s, border-color .2s;
    position: absolute; inset: 0; margin: 0;
  }
  .cb-wrap input[type=checkbox]:checked {
    background: #4ade80; border-color: #4ade80;
  }
  .cb-wrap input[type=checkbox]:checked::after {
    content: '';
    position: absolute; top: 2px; left: 5px;
    width: 4px; height: 7px;
    border: 2px solid #0f0f1a;
    border-top: none; border-left: none;
    transform: rotate(45deg);
  }

  .item-body { flex: 1; min-width: 0; }
  .item-text {
    font-size: 12px; color: #c8d6e5; line-height: 1.4;
    word-break: break-word;
    transition: color .3s, text-decoration .3s;
  }
  .item-text.done {
    color: #555;
    text-decoration: line-through;
    text-decoration-color: #4ade80;
  }
  .item-date { font-size: 10px; color: #555; margin-top: 2px; }

  /* --- new feedback form --- */
  textarea {
    resize: vertical; min-height: 72px;
    background: #0f0f1a; border: 1px solid #333;
    border-radius: 6px; color: #e2e8f0;
    font-size: 13px; padding: 8px;
    outline: none; width: 100%; flex-shrink: 0;
    font-family: system-ui, sans-serif;
  }
  textarea:focus { border-color: #4ade80; }

  #submit-btn {
    background: #4ade80; color: #0f0f1a;
    border: none; border-radius: 6px;
    padding: 8px; font-size: 13px; font-weight: 600;
    cursor: pointer; flex-shrink: 0;
  }
  #submit-btn:disabled { opacity: .5; cursor: default; }

  #status { font-size: 11px; color: #4ade80; min-height: 14px; flex-shrink: 0; }

  #clear-btn {
    background: none; border: 1px solid #333; border-radius: 6px;
    color: #666; font-size: 11px; padding: 5px 8px; cursor: pointer;
    flex-shrink: 0; transition: border-color .15s, color .15s;
  }
  #clear-btn:hover { border-color: #ff4444; color: #ff4444; }
  #clear-btn:disabled { opacity: .4; cursor: default; }

  /* scroll bar styling */
  #list::-webkit-scrollbar { width: 4px; }
  #list::-webkit-scrollbar-track { background: transparent; }
  #list::-webkit-scrollbar-thumb { background: #2a2a3e; border-radius: 2px; }
</style>

<div id="wrap">
  <div id="panel">
    <div id="panel-header">
      <span>Page Feedback</span>
      <button id="close-btn" title="Close">&#x2715;</button>
    </div>
    <div id="url-label"></div>
    <div id="list"></div>
    <hr id="list-divider">
    <textarea id="txt" placeholder="What needs to change on this page?"></textarea>
    <button id="submit-btn">Submit</button>
    <button id="clear-btn">Clear notes for this page</button>
    <div id="status"></div>
  </div>
  <div id="btn-wrap">
    <button id="btn" title="Harness feedback">&#128172;</button>
    <div id="badge"></div>
    <button id="dismiss" title="Dismiss">&#x2715;</button>
  </div>
</div>
`;

  const btn       = shadow.getElementById('btn');
  const badge     = shadow.getElementById('badge');
  const panel     = shadow.getElementById('panel');
  const closeBtn  = shadow.getElementById('close-btn');
  const urlLabel  = shadow.getElementById('url-label');
  const list      = shadow.getElementById('list');
  const txt       = shadow.getElementById('txt');
  const submitBtn = shadow.getElementById('submit-btn');
  const clearBtn  = shadow.getElementById('clear-btn');
  const status    = shadow.getElementById('status');

  function fmtDate(iso) {
    try {
      return new Date(iso).toLocaleString(undefined, {
        month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
      });
    } catch { return ''; }
  }

  function renderList() {
    const items = forPage();
    badge.textContent = items.length;
    if (items.length > 0) badge.classList.add('visible');
    else badge.classList.remove('visible');

    list.innerHTML = '';
    items.forEach(rec => {
      const row = document.createElement('div');
      row.className = 'item';

      const cbWrap = document.createElement('div');
      cbWrap.className = 'cb-wrap';
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.checked = !!rec.completed;
      cbWrap.appendChild(cb);

      const body = document.createElement('div');
      body.className = 'item-body';
      const textEl = document.createElement('div');
      textEl.className = 'item-text' + (rec.completed ? ' done' : '');
      textEl.textContent = rec.feedback;
      const dateEl = document.createElement('div');
      dateEl.className = 'item-date';
      dateEl.textContent = fmtDate(rec.created_at);
      body.appendChild(textEl);
      body.appendChild(dateEl);

      cb.addEventListener('change', () => {
        toggleDone(rec.id);
        textEl.classList.toggle('done', cb.checked);
      });

      row.appendChild(cbWrap);
      row.appendChild(body);
      list.appendChild(row);
    });
  }

  function openPanel() {
    urlLabel.textContent = location.href;
    renderList();
    panel.classList.add('open');
    btn.style.display = 'none';
    txt.focus();
  }

  function closePanel() {
    panel.classList.remove('open');
    btn.style.display = '';
    txt.value = '';
    status.textContent = '';
  }

  btn.addEventListener('click', openPanel);
  closeBtn.addEventListener('click', closePanel);
  shadow.getElementById('dismiss').addEventListener('click', () => host.remove());
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closePanel(); });

  submitBtn.addEventListener('click', async () => {
    const text = txt.value.trim();
    if (!text) return;

    submitBtn.disabled = true;
    status.textContent = 'Saving...';

    const record = {
      id:         Math.random().toString(36).slice(2, 10),
      url:        location.href,
      title:      document.title,
      feedback:   text,
      completed:  false,
      created_at: new Date().toISOString(),
    };

    addRecord(record);
    renderList();

    try {
      await fetch(HARNESS_API, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ url: record.url, title: record.title, feedback: record.feedback }),
      });
      status.textContent = 'Saved to harness.';
    } catch (_) {
      status.textContent = 'Saved locally (harness offline).';
    }

    submitBtn.disabled = false;
    txt.value = '';
    setTimeout(() => { status.textContent = ''; }, 2000);
  });

  clearBtn.addEventListener('click', async () => {
    if (!forPage().length) return;
    clearBtn.disabled = true;
    status.textContent = 'Clearing...';

    const all = loadAll();
    saveAll(all.filter(r => r.url !== location.href));

    try {
      await fetch(HARNESS_API + '?url=' + encodeURIComponent(location.href), {
        method: 'DELETE',
      });
    } catch (_) {}

    renderList();
    status.textContent = 'Notes cleared.';
    clearBtn.disabled = false;
    setTimeout(() => { status.textContent = ''; }, 1800);
  });

  // init badge on load
  renderList();

})();
