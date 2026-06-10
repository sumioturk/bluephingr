// perspective.js — Draggable 4-point overlay for screen region mapping
//
// User drags 4 corner handles to mark the phone screen on the camera feed.
// Clicking inside the rectangle sends tap commands with coordinates
// mapped to the phone screen (0-1 normalized).

let handles = [];       // [{x, y}, ...] in image-relative % (0-1)
let draggingHandle = -1;
let overlayActive = false;

const HANDLE_RADIUS = 8;
const HANDLE_COLORS = ['#f00', '#0f0', '#00f', '#ff0']; // TL, TR, BR, BL

// ── Initialize ──────────────────────────────────────────────────────

function initOverlay() {
  const stream = document.getElementById('stream');
  const overlay = document.getElementById('screenOverlay');

  // Default rectangle (centered, roughly phone-shaped)
  const saved = localStorage.getItem('phingr_handles');
  if (saved) {
    try {
      handles = JSON.parse(saved);
    } catch(e) {}
  }
  if (!handles || handles.length !== 4) {
    handles = [
      {x: 0.3, y: 0.15},  // top-left
      {x: 0.7, y: 0.15},  // top-right
      {x: 0.7, y: 0.85},  // bottom-right
      {x: 0.3, y: 0.85},  // bottom-left
    ];
  }

  // Mouse/touch events on overlay
  overlay.addEventListener('mousedown', onDown);
  overlay.addEventListener('mousemove', onMove);
  overlay.addEventListener('mouseup', onUp);
  overlay.addEventListener('mouseleave', onUp);
  overlay.addEventListener('touchstart', onDown, {passive: false});
  overlay.addEventListener('touchmove', onMove, {passive: false});
  overlay.addEventListener('touchend', onUp);

  function syncOverlay() {
    const panel = document.getElementById('cameraPanel');
    const w = panel.clientWidth;
    const h = panel.clientHeight;

    if (w < 10 || h < 10) return;

    if (overlay.width !== w || overlay.height !== h) {
      overlay.width = w;
      overlay.height = h;
      drawOverlay();
    }
  }

  setInterval(syncOverlay, 500);

  overlayActive = true;
  drawOverlay();
}

// ── Drawing ─────────────────────────────────────────────────────────

// Convert image-relative handle (0-1) to canvas pixel coordinate
function handleToCanvas(handle) {
  const img = getImageContentRect();
  return {
    x: img.x + handle.x * img.w,
    y: img.y + handle.y * img.h,
  };
}

function drawOverlay() {
  const overlay = document.getElementById('screenOverlay');
  if (!overlay || !overlay.width) return;
  const ctx = overlay.getContext('2d');
  const w = overlay.width, h = overlay.height;

  // Convert handles to canvas coords for drawing
  const pts = handles.map(handleToCanvas);

  ctx.clearRect(0, 0, w, h);

  // Dim area outside the quad
  ctx.fillStyle = 'rgba(0,0,0,0.4)';
  ctx.fillRect(0, 0, w, h);

  // Cut out the quad
  ctx.save();
  ctx.globalCompositeOperation = 'destination-out';
  ctx.beginPath();
  ctx.moveTo(pts[0].x, pts[0].y);
  for (let i = 1; i < 4; i++) ctx.lineTo(pts[i].x, pts[i].y);
  ctx.closePath();
  ctx.fill();
  ctx.restore();

  // Draw quad outline
  ctx.strokeStyle = '#0f0';
  ctx.lineWidth = 2;
  ctx.setLineDash([6, 3]);
  ctx.beginPath();
  ctx.moveTo(pts[0].x, pts[0].y);
  for (let i = 1; i < 4; i++) ctx.lineTo(pts[i].x, pts[i].y);
  ctx.closePath();
  ctx.stroke();
  ctx.setLineDash([]);

  // Draw handles
  for (let i = 0; i < 4; i++) {
    ctx.strokeStyle = HANDLE_COLORS[i];
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(pts[i].x, pts[i].y, HANDLE_RADIUS, 0, Math.PI * 2);
    ctx.stroke();

    ctx.fillStyle = HANDLE_COLORS[i];
    ctx.globalAlpha = 0.5;
    ctx.beginPath();
    ctx.arc(pts[i].x, pts[i].y, HANDLE_RADIUS - 2, 0, Math.PI * 2);
    ctx.fill();
    ctx.globalAlpha = 1;
  }
}

// ── Image content rect (accounts for object-fit: contain) ──────────

function getImageContentRect() {
  // The image uses object-fit:contain, so it may have letterbox bars.
  // Calculate the actual rendered image area within the panel.
  const stream = document.getElementById('stream');
  const panel = document.getElementById('cameraPanel');
  const panelRect = panel.getBoundingClientRect();
  const pw = panelRect.width, ph = panelRect.height;

  if (!stream.naturalWidth || !stream.naturalHeight) {
    return {x: 0, y: 0, w: pw, h: ph};
  }

  const imgAspect = stream.naturalWidth / stream.naturalHeight;
  const panelAspect = pw / ph;
  let imgW, imgH, imgX, imgY;

  if (imgAspect > panelAspect) {
    // Image wider than panel — bars top/bottom
    imgW = pw;
    imgH = pw / imgAspect;
    imgX = 0;
    imgY = (ph - imgH) / 2;
  } else {
    // Image taller than panel — bars left/right
    imgH = ph;
    imgW = ph * imgAspect;
    imgX = (pw - imgW) / 2;
    imgY = 0;
  }

  return {x: imgX, y: imgY, w: imgW, h: imgH};
}

// ── Handle dragging ─────────────────────────────────────────────────

function getPos(e, overlay) {
  const rect = overlay.getBoundingClientRect();
  let clientX, clientY;
  if (e.changedTouches && e.changedTouches.length > 0) {
    clientX = e.changedTouches[0].clientX;
    clientY = e.changedTouches[0].clientY;
  } else if (e.touches && e.touches.length > 0) {
    clientX = e.touches[0].clientX;
    clientY = e.touches[0].clientY;
  } else {
    clientX = e.clientX;
    clientY = e.clientY;
  }
  // Convert to image-content-relative coordinates (0-1)
  const img = getImageContentRect();
  const px = clientX - rect.left;
  const py = clientY - rect.top;
  return {
    x: (px - img.x) / img.w,
    y: (py - img.y) / img.h,
  };
}

function findHandle(pos) {
  // pos is already image-relative (0-1), same as handles
  const img = getImageContentRect();
  for (let i = 0; i < 4; i++) {
    const dx = (handles[i].x - pos.x) * img.w;
    const dy = (handles[i].y - pos.y) * img.h;
    if (Math.sqrt(dx*dx + dy*dy) < HANDLE_RADIUS * 2) return i;
  }
  return -1;
}

function onDown(e) {
  const overlay = document.getElementById('screenOverlay');
  const pos = getPos(e, overlay);
  const idx = findHandle(pos);
  if (idx >= 0) {
    draggingHandle = idx;
    e.preventDefault();
    e.stopPropagation();
  }
}

function onMove(e) {
  if (draggingHandle < 0) return;
  const overlay = document.getElementById('screenOverlay');
  const pos = getPos(e, overlay);
  handles[draggingHandle].x = Math.max(0, Math.min(1, pos.x));
  handles[draggingHandle].y = Math.max(0, Math.min(1, pos.y));
  drawOverlay();
  e.preventDefault();
}

function onUp(e) {
  if (draggingHandle >= 0) {
    draggingHandle = -1;
    // Save handle positions locally and to server (for phingr-cli access)
    localStorage.setItem('phingr_handles', JSON.stringify(handles));
    api('/api/calib/handles', {handles: handles});
  }
}

// ── Screen gesture: tap and swipe ────────────────────────────────────

let screenGesture = null;  // {startPos, startNorm, startTime}
const SWIPE_THRESHOLD = 10; // pixels on overlay to distinguish tap from swipe
const DOUBLE_TAP_INTERVAL = 400; // ms between taps to trigger double-tap
let lastTapTime = 0;
let lastTapPos = null;

function onScreenDown(e) {
  if (draggingHandle >= 0) return;
  const overlay = document.getElementById('screenOverlay');
  const pos = getPos(e, overlay);
  if (!pointInQuad(pos, handles)) return;
  const norm = mapToScreen(pos, handles);
  if (!norm) return;

  screenGesture = {
    startPos: pos,
    startNorm: norm,
    startTime: Date.now(),
  };
}

function onScreenMove(e) {
  // Visual feedback could go here (draw swipe line)
}

function onScreenUp(e) {
  if (!screenGesture) return;
  if (draggingHandle >= 0) { screenGesture = null; return; }

  const overlay = document.getElementById('screenOverlay');
  const pos = getPos(e, overlay);
  const endNorm = mapToScreen(pos, handles);

  const dx = (pos.x - screenGesture.startPos.x) * overlay.width;
  const dy = (pos.y - screenGesture.startPos.y) * overlay.height;
  const dist = Math.sqrt(dx * dx + dy * dy);

  if (dist < SWIPE_THRESHOLD) {
    const corrected = correctPosition(screenGesture.startNorm.x, screenGesture.startNorm.y);
    const now = Date.now();

    // Double-tap detection: two taps in quick succession at similar position
    if (lastTapPos && (now - lastTapTime) < DOUBLE_TAP_INTERVAL) {
      const tdx = Math.abs(corrected.x - lastTapPos.x);
      const tdy = Math.abs(corrected.y - lastTapPos.y);
      if (tdx < 0.05 && tdy < 0.05) {
        addLog(`double-tap (${corrected.x.toFixed(3)},${corrected.y.toFixed(3)})`);
        // Second tap: click in place without moving cursor
        api('/api/mouse/click', {});
        lastTapTime = 0;
        lastTapPos = null;
        screenGesture = null;
        return;
      }
    }

    // Single tap
    addLog(`tap (${corrected.x.toFixed(3)},${corrected.y.toFixed(3)})`);
    api('/api/tap', {x: corrected.x, y: corrected.y});
    lastTapTime = now;
    lastTapPos = corrected;
  } else if (endNorm) {
    // Swipe — apply calibration correction to both points
    const s = correctPosition(screenGesture.startNorm.x, screenGesture.startNorm.y);
    const end = correctPosition(endNorm.x, endNorm.y);
    const duration = Math.max(150, Math.min(500, Date.now() - screenGesture.startTime));
    addLog(`swipe (${s.x.toFixed(2)},${s.y.toFixed(2)}) -> (${end.x.toFixed(2)},${end.y.toFixed(2)})`);
    api('/api/swipe', {
      x0: s.x, y0: s.y,
      x1: end.x, y1: end.y,
      duration_ms: duration,
    });
  }

  screenGesture = null;
}

function attachScreenGestures() {
  const overlay = document.getElementById('screenOverlay');

  overlay.addEventListener('mousedown', function(e) {
    if (findHandle(getPos(e, overlay)) < 0) onScreenDown(e);
  });
  overlay.addEventListener('touchstart', function(e) {
    if (findHandle(getPos(e, overlay)) < 0) {
      onScreenDown(e);
      e.preventDefault(); // prevent scroll while interacting with overlay
    }
  }, {passive: false});

  overlay.addEventListener('mousemove', onScreenMove);
  overlay.addEventListener('touchmove', function(e) {
    onScreenMove(e);
    e.preventDefault();
  }, {passive: false});
}

// ── Point-in-quad test ──────────────────────────────────────────────

function pointInQuad(p, quad) {
  // Cross product sign test for convex quad
  function cross(o, a, b) {
    return (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x);
  }
  const d1 = cross(quad[0], quad[1], p);
  const d2 = cross(quad[1], quad[2], p);
  const d3 = cross(quad[2], quad[3], p);
  const d4 = cross(quad[3], quad[0], p);
  const hasNeg = (d1 < 0) || (d2 < 0) || (d3 < 0) || (d4 < 0);
  const hasPos = (d1 > 0) || (d2 > 0) || (d3 > 0) || (d4 > 0);
  return !(hasNeg && hasPos);
}

// ── Map point in quad to normalized screen coords ───────────────────

function mapToScreen(p, quad) {
  // Bilinear interpolation inverse:
  // Given point p inside quad[TL, TR, BR, BL], find (u, v) in [0,1]
  // where u=0 is left edge, u=1 is right edge, v=0 is top, v=1 is bottom

  // Iterative approach (Newton's method on bilinear mapping)
  let u = 0.5, v = 0.5;
  for (let iter = 0; iter < 20; iter++) {
    // Bilinear interpolation: Q(u,v) = (1-u)(1-v)*TL + u(1-v)*TR + uv*BR + (1-u)v*BL
    const qx = (1-u)*(1-v)*quad[0].x + u*(1-v)*quad[1].x + u*v*quad[2].x + (1-u)*v*quad[3].x;
    const qy = (1-u)*(1-v)*quad[0].y + u*(1-v)*quad[1].y + u*v*quad[2].y + (1-u)*v*quad[3].y;

    const ex = p.x - qx;
    const ey = p.y - qy;
    if (Math.abs(ex) < 0.0001 && Math.abs(ey) < 0.0001) break;

    // Jacobian
    const dxdu = -(1-v)*quad[0].x + (1-v)*quad[1].x + v*quad[2].x - v*quad[3].x;
    const dxdv = -(1-u)*quad[0].x - u*quad[1].x + u*quad[2].x + (1-u)*quad[3].x;
    const dydu = -(1-v)*quad[0].y + (1-v)*quad[1].y + v*quad[2].y - v*quad[3].y;
    const dydv = -(1-u)*quad[0].y - u*quad[1].y + u*quad[2].y + (1-u)*quad[3].y;

    const det = dxdu * dydv - dxdv * dydu;
    if (Math.abs(det) < 1e-10) break;

    u += (dydv * ex - dxdv * ey) / det;
    v += (dxdu * ey - dydu * ex) / det;
  }

  u = Math.max(0, Math.min(1, u));
  v = Math.max(0, Math.min(1, v));
  return {x: u, y: v};
}

// ── Cursor Calibration ──────────────────────────────────────────────
//
// Process:
// 1. User clicks "Calibrate X" → server resets cursor to origin,
//    moves 500 HID units right
// 2. User sees where cursor landed on camera preview
// 3. User clicks that spot on the overlay
// 4. JS calculates: cursor traveled to X=landed_norm on screen
//    using 500 HID units → full screen = 500 / landed_norm HID units
// 5. Repeat for Y axis

// 10-point diagonal calibration: measures acceleration curve from origin to full screen
const CALIB_NUM_POINTS = 10;

let calibMode = false;
let calibStep = 0;
let calibResults = [];  // [{intended: 0-1, actualX: 0-1, actualY: 0-1}, ...]

function calibPointNorm(idx) {
  // Points along diagonal from 0.1 to 1.0
  return (idx + 1) / CALIB_NUM_POINTS;
}

async function startCalibration() {
  const info = document.getElementById('calibInfo');
  const instr = document.getElementById('calibInstructions');

  try {
    const resp = await api('/api/calib/get');
    const d = resp.json();
    info.textContent = `Current: ${d.screen_w || '?'} x ${d.screen_h || '?'}`;

    calibStep = 0;
    calibResults = [];
    await moveToCalibPoint(0);
  } catch(e) {
    info.textContent = 'Error: ' + e.message;
  }
}

async function moveToCalibPoint(idx) {
  const norm = calibPointNorm(idx);
  const instr = document.getElementById('calibInstructions');

  addLog(`calib ${idx+1}/${CALIB_NUM_POINTS}: moving to (${norm.toFixed(2)}, ${norm.toFixed(2)})`);
  await api('/api/mouse/move_to', {x: norm, y: norm});

  calibMode = true;
  calibStep = idx;
  instr.style.display = 'block';
  instr.textContent = `Point ${idx+1}/${CALIB_NUM_POINTS} — Click where the cursor actually landed.`;
}

function onScreenUpWithCalib(e) {
  if (!calibMode) {
    onScreenUp(e);
    return;
  }

  const overlay = document.getElementById('screenOverlay');
  const pos = getPos(e, overlay);
  if (!pointInQuad(pos, handles)) { calibMode = false; return; }

  const norm = mapToScreen(pos, handles);
  if (!norm) { calibMode = false; return; }

  const intended = calibPointNorm(calibStep);
  addLog(`calib ${calibStep+1}: intended ${intended.toFixed(2)}, actual (${norm.x.toFixed(3)}, ${norm.y.toFixed(3)})`);

  calibResults.push({intended, actualX: norm.x, actualY: norm.y});
  calibMode = false;

  // Stop early if cursor hit the screen edge (>95% on either axis)
  if (norm.x > 0.95 || norm.y > 0.95) {
    addLog(`calib: cursor reached screen edge at point ${calibStep+1}, stopping early`);
    finishCalibration();
  } else if (calibStep < CALIB_NUM_POINTS - 1) {
    moveToCalibPoint(calibStep + 1);
  } else {
    finishCalibration();
  }
}

function finishCalibration() {
  const instr = document.getElementById('calibInstructions');
  instr.style.display = 'none';

  // Build lookup table: intended (0-1) → actual (0-1)
  // This captures the non-linear acceleration curve
  const calibTableX = calibResults.map(r => ({intended: r.intended, actual: r.actualX}));
  const calibTableY = calibResults.map(r => ({intended: r.intended, actual: r.actualY}));

  // Add origin point
  calibTableX.unshift({intended: 0, actual: 0});
  calibTableY.unshift({intended: 0, actual: 0});

  // Sort by intended
  calibTableX.sort((a, b) => a.intended - b.intended);
  calibTableY.sort((a, b) => a.intended - b.intended);

  addLog(`calib done: ${calibResults.length} points captured`);
  addLog(`calib X table: ${calibTableX.map(p => p.intended.toFixed(2)+'→'+p.actual.toFixed(3)).join(', ')}`);
  addLog(`calib Y table: ${calibTableY.map(p => p.intended.toFixed(2)+'→'+p.actual.toFixed(3)).join(', ')}`);

  // Save calibration table
  const calibData = {tableX: calibTableX, tableY: calibTableY};
  localStorage.setItem('phingr_calib_table', JSON.stringify(calibData));

  // Also send to server
  api('/api/calib/table', calibData);

  document.getElementById('calibInfo').textContent = `Calibrated: ${calibResults.length} points`;
}

// ── Calibration correction ──────────────────────────────────────────
// Given a desired normalized position (0-1), look up the calibration
// table to find what value to actually send so the cursor lands there.

function loadCalibTable() {
  const saved = localStorage.getItem('phingr_calib_table');
  if (saved) {
    try {
      return JSON.parse(saved);
    } catch(e) {}
  }
  return null;
}

function correctCoord(desired, table) {
  // table: [{intended, actual}, ...] sorted by intended
  // We want to find: what 'intended' value produces 'desired' as actual?
  // Inverse lookup with linear interpolation

  if (!table || table.length < 2) return desired;

  // Find the two points that bracket desired in the 'actual' column
  for (let i = 0; i < table.length - 1; i++) {
    const a = table[i], b = table[i + 1];
    if (desired >= a.actual && desired <= b.actual) {
      // Linear interpolation
      const t = (b.actual - a.actual) > 0.001
        ? (desired - a.actual) / (b.actual - a.actual)
        : 0;
      return a.intended + t * (b.intended - a.intended);
    }
  }

  // Extrapolate beyond last point
  const last = table[table.length - 1];
  if (last.actual > 0.001) {
    return desired * (last.intended / last.actual);
  }
  return desired;
}

function correctPosition(x, y) {
  const calib = loadCalibTable();
  if (!calib) return {x, y};
  return {
    x: correctCoord(x, calib.tableX),
    y: correctCoord(y, calib.tableY),
  };
}

// ── Init on load ────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', function() {
  initOverlay();
  attachScreenGestures();

  // mouseup/touchend: handles both swipe gesture and calibration
  const overlay = document.getElementById('screenOverlay');
  overlay.addEventListener('mouseup', onScreenUpWithCalib);
  overlay.addEventListener('touchend', onScreenUpWithCalib);

  // Sync handles to server on load (so phingr-cli can fetch them)
  if (handles && handles.length === 4) {
    api('/api/calib/handles', {handles: handles});
  }

  // Restore saved calibration (api() is now available from app.js)
  const sw = localStorage.getItem('phingr_screen_w');
  const sh = localStorage.getItem('phingr_screen_h');
  if (sw && sh) {
    api('/api/configure', {screen_w: parseInt(sw), screen_h: parseInt(sh)}).then(() => {
      const info = document.getElementById('calibInfo');
      if (info) info.textContent = `Loaded: ${sw} x ${sh}`;
    });
  }
});
