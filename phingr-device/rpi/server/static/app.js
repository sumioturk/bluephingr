// phingr Web UI — app.js
// api() and addLog() defined first so other scripts can use them.

// ── API client (must be first) ──────────────────────────────────────

async function api(url, body) {
  const cmd = url.replace('/api/','') + (body ? ' ' + JSON.stringify(body) : '');
  addLog('> ' + cmd);
  const opts = {method: 'POST', headers: {'Content-Type': 'application/json'}};
  if (body) opts.body = JSON.stringify(body);
  try {
    const r = await fetch(url, opts);
    const d = await r.json();
    addLog('< ' + (d.ok ? 'ok' : d.error || JSON.stringify(d)));
    return {json: () => d};
  } catch(e) {
    addLog('< ERR ' + e.message);
    return {json: () => ({ok: false, error: e.message})};
  }
}

function addLog(msg) {
  const el = document.getElementById('log');
  if (!el) return;
  const ts = new Date().toLocaleTimeString('en', {hour12:false, hour:'2-digit', minute:'2-digit', second:'2-digit'});
  const line = document.createElement('div');
  line.textContent = ts + ' ' + msg;
  line.style.whiteSpace = 'nowrap';
  line.style.overflow = 'hidden';
  line.style.textOverflow = 'ellipsis';
  el.prepend(line);
  while (el.children.length > 100) el.lastChild.remove();
}

// ── Auto-detect screen ──────────────────────────────────────────────

let _detectCandidates = [];
let _detectIdx = 0;

async function detectScreen() {
  addLog('detecting screen...');
  const resp = await api('/api/camera/detect_screen');
  const d = resp.json();
  if (!d.ok || !d.candidates || d.candidates.length === 0) {
    addLog('no rectangles detected — adjust manually');
    return;
  }

  _detectCandidates = d.candidates;
  _detectIdx = 0;
  addLog(d.candidates.length + ' candidates found. Click "Next" to cycle, "Accept" to confirm.');
  applyCandidate(0);

  // Show accept/next buttons
  document.getElementById('detectControls').style.display = '';
  document.getElementById('detectInfo').textContent =
    '1/' + _detectCandidates.length + ' (area: ' + (_detectCandidates[0].area * 100).toFixed(1) + '%)';
}

function applyCandidate(idx) {
  const c = _detectCandidates[idx];
  handles = c.corners.map(function(p) { return {x: p.x, y: p.y}; });
  if (typeof drawOverlay === 'function') drawOverlay();
}

function detectNext() {
  _detectIdx = (_detectIdx + 1) % _detectCandidates.length;
  applyCandidate(_detectIdx);
  const c = _detectCandidates[_detectIdx];
  document.getElementById('detectInfo').textContent =
    (_detectIdx + 1) + '/' + _detectCandidates.length + ' (area: ' + (c.area * 100).toFixed(1) + '%)';
}

function detectAccept() {
  localStorage.setItem('phingr_handles', JSON.stringify(handles));
  document.getElementById('detectControls').style.display = 'none';
  const c = _detectCandidates[_detectIdx];
  addLog('accepted candidate ' + (_detectIdx + 1) + ' (area: ' + (c.area * 100).toFixed(1) + '%)');
  _detectCandidates = [];
}

function detectCancel() {
  // Restore saved handles
  const saved = localStorage.getItem('phingr_handles');
  if (saved) {
    try { handles = JSON.parse(saved); } catch(e) {}
  }
  if (typeof drawOverlay === 'function') drawOverlay();
  document.getElementById('detectControls').style.display = 'none';
  _detectCandidates = [];
}

// ── Everything else after DOM is ready ──────────────────────────────

let moveInterval = null;

function getSpeed() {
  return parseInt(document.getElementById('speed').value);
}
function getSpeedCoarse() {
  return parseInt(document.getElementById('speedCoarse').value);
}

function startMove(dx, dy) {
  stopMove();
  const send = () => api('/api/mouse/move', {dx: dx * getSpeed(), dy: dy * getSpeed()});
  send();
  moveInterval = setInterval(send, 80);
}

function startMoveCoarse(dx, dy) {
  stopMove();
  const send = () => api('/api/mouse/move', {dx: dx * getSpeedCoarse(), dy: dy * getSpeedCoarse()});
  send();
  moveInterval = setInterval(send, 80);
}

function stopMove() {
  if (moveInterval) { clearInterval(moveInterval); moveInterval = null; }
}

document.addEventListener('DOMContentLoaded', function() {
  // Divider
  const divider = document.getElementById('divider');
  const cam = document.getElementById('cameraPanel');
  let dragging = false;

  divider.addEventListener('mousedown', function(e) {
    dragging = true; divider.classList.add('active');
    document.body.style.cursor = 'col-resize'; document.body.style.userSelect = 'none';
    e.preventDefault();
  });
  divider.addEventListener('touchstart', function(e) {
    dragging = true; divider.classList.add('active');
    document.body.style.cursor = 'col-resize'; document.body.style.userSelect = 'none';
    e.preventDefault();
  });
  function setDividerPos(x) {
    const w = Math.max(200, Math.min(window.innerWidth - 300, x));
    cam.style.width = w + 'px';
    cam.style.flexShrink = '0';
    // Save as ratio
    localStorage.setItem('phingr_divider_ratio', (w / window.innerWidth).toFixed(4));
  }

  document.addEventListener('mousemove', function(e) {
    if (!dragging) return;
    setDividerPos(e.clientX);
  });
  document.addEventListener('touchmove', function(e) {
    if (!dragging) return;
    setDividerPos(e.touches[0].clientX);
  });
  function stopDrag() {
    if (!dragging) return;
    dragging = false; divider.classList.remove('active');
    document.body.style.cursor = ''; document.body.style.userSelect = '';
  }
  document.addEventListener('mouseup', stopDrag);
  document.addEventListener('touchend', stopDrag);

  // Restore saved divider position or default to 50%
  var savedRatio = parseFloat(localStorage.getItem('phingr_divider_ratio') || '0.5');
  cam.style.width = (window.innerWidth * savedRatio) + 'px';
  cam.style.flexShrink = '0';

  // Keep ratio on window resize
  window.addEventListener('resize', function() {
    var ratio = parseFloat(localStorage.getItem('phingr_divider_ratio') || '0.5');
    cam.style.width = (window.innerWidth * ratio) + 'px';
  });

  // Speed sliders
  document.getElementById('speed').oninput = function() {
    document.getElementById('speedVal').textContent = this.value;
  };
  document.getElementById('speedCoarse').oninput = function() {
    document.getElementById('speedCoarseVal').textContent = this.value;
  };

  // Keyboard shortcuts
  document.addEventListener('keydown', function(e) {
    if (e.target.tagName === 'INPUT') return;
    const s = getSpeed();
    switch(e.key) {
      case 'ArrowUp':    api('/api/mouse/move', {dx:0, dy:-s}); e.preventDefault(); break;
      case 'ArrowDown':  api('/api/mouse/move', {dx:0, dy:s}); e.preventDefault(); break;
      case 'ArrowLeft':  api('/api/mouse/move', {dx:-s, dy:0}); e.preventDefault(); break;
      case 'ArrowRight': api('/api/mouse/move', {dx:s, dy:0}); e.preventDefault(); break;
      case 'Enter':      api('/api/mouse/click'); e.preventDefault(); break;
      case ' ':          api('/api/mouse/click'); e.preventDefault(); break;
    }
  });

  // Load current camera preset
  loadPreset();

  // Load relay state
  loadRelays();
});

// ── External relays ─────────────────────────────────────────────────────

function renderRelay(r) {
  const btn = document.getElementById('relay-' + r.index);
  if (!btn) return;
  btn.textContent = r.name + (r.on ? ' • ON' : '');
  btn.classList.toggle('on', !!r.on);
}

async function loadRelays() {
  try {
    const res = await fetch('/api/relay');
    const d = await res.json();
    if (d.ok && d.relays) d.relays.forEach(renderRelay);
    const st = document.getElementById('relayStatus');
    if (st) st.textContent = d.available ? '' : 'GPIO unavailable (sim)';
  } catch {}
}

async function toggleRelay(index) {
  await api('/api/relay', {index: index, toggle: true});
  // Re-sync all relays from the server (also reflects the new state).
  loadRelays();
}

// ── libimobiledevice ────────────────────────────────────────────────────────

async function runIdeviceCmd() {
  const input = document.getElementById('ideviceCmd');
  const out = document.getElementById('ideviceOutput');
  const cmd = input ? input.value.trim() : '';
  if (!cmd || !out) return;
  out.textContent = '$ ' + cmd + '\n';
  try {
    const r = await fetch('/api/idevice/exec', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({cmd}),
    });
    const d = await r.json();
    let text = '';
    if (d.stdout) text += d.stdout;
    if (d.stderr) text += (text ? '\n' : '') + '[stderr]\n' + d.stderr;
    if (!text) text = d.ok ? '(no output)' : 'failed';
    out.textContent = '$ ' + cmd + '\n' + text;
    out.scrollTop = out.scrollHeight;
  } catch(e) {
    out.textContent = '$ ' + cmd + '\nerror: ' + e.message;
  }
}

function setCmd(cmd) {
  const input = document.getElementById('ideviceCmd');
  if (input) { input.value = cmd; input.focus(); }
}

function clearIdeviceOutput() {
  const out = document.getElementById('ideviceOutput');
  if (out) out.textContent = '';
}

// ── Syslog stream ───────────────────────────────────────────────────────────

let _syslogEvt = null;
let _syslogRunning = false;

function toggleSyslog() {
  _syslogRunning ? stopSyslog() : startSyslog();
}

function startSyslog() {
  stopSyslog();
  _syslogRunning = true;
  const btn = document.getElementById('btn-syslog-toggle');
  if (btn) btn.textContent = 'Stop';
  const process = (document.getElementById('syslogProcess') || {}).value || '';
  const url = '/api/idevice/syslog/stream' + (process ? '?process=' + encodeURIComponent(process) : '');
  _syslogEvt = new EventSource(url);
  _syslogEvt.onmessage = function(e) {
    const filter = ((document.getElementById('syslogFilter') || {}).value || '').toLowerCase();
    if (filter && !e.data.toLowerCase().includes(filter)) return;
    const out = document.getElementById('syslogOutput');
    if (!out) return;
    const line = document.createElement('div');
    line.textContent = e.data;
    out.appendChild(line);
    while (out.children.length > 1000) out.firstChild.remove();
    out.scrollTop = out.scrollHeight;
  };
  _syslogEvt.onerror = function() { stopSyslog(); };
}

function stopSyslog() {
  if (_syslogEvt) { _syslogEvt.close(); _syslogEvt = null; }
  _syslogRunning = false;
  const btn = document.getElementById('btn-syslog-toggle');
  if (btn) btn.textContent = 'Start';
}

function clearSyslog() {
  const out = document.getElementById('syslogOutput');
  if (out) out.innerHTML = '';
}

// ── Camera resolution presets ──────────────────────────────────────────

function highlightPreset(preset) {
  document.querySelectorAll('[id^="btn-preset-"]').forEach(b => {
    b.style.background = '';
    b.style.color = '';
  });
  const btn = document.getElementById('btn-preset-' + preset);
  if (btn) {
    btn.style.background = '#4a9';
    btn.style.color = '#fff';
  }
}

async function loadPreset() {
  try {
    const r = await fetch('/api/camera/preset');
    const d = await r.json();
    if (d.ok) {
      highlightPreset(d.current);
      document.getElementById('presetStatus').textContent = d.presets[d.current] || '';
    }
  } catch {}
}

async function setPreset(preset) {
  const status = document.getElementById('presetStatus');
  status.textContent = 'Switching...';
  try {
    const r = await fetch('/api/camera/preset', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({preset}),
    });
    const d = await r.json();
    if (d.ok) {
      highlightPreset(preset);
      status.textContent = 'Ready';
      // Reload stream to pick up new resolution
      const stream = document.getElementById('stream');
      stream.src = '/api/stream?' + Date.now();
    } else {
      status.textContent = 'Failed';
    }
  } catch (e) {
    status.textContent = 'Error: ' + e.message;
  }
}
