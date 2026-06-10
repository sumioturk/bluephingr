/* phingr-cli frontend */

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

// ---- API helper ----

async function api(method, path, body, raw) {
  const opts = { method, headers: {} };
  if (body) {
    if (raw) {
      opts.headers["Content-Type"] = "text/yaml";
      opts.body = body;
    } else {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
  }
  const r = await fetch("/api" + path, opts);
  if (!r.ok) {
    const text = await r.text();
    throw new Error(`${r.status}: ${text}`);
  }
  const ct = r.headers.get("content-type") || "";
  if (ct.includes("json")) return r.json();
  return r.text();
}

// ---- Navigation ----

function showView(name) {
  $$(".view").forEach((v) => v.classList.remove("active"));
  $$(".tab-btn").forEach((b) => b.classList.remove("active"));
  $(`#view-${name}`).classList.add("active");
  const tab = $(`.tab-btn[data-view="${name}"]`);
  if (tab) tab.classList.add("active");
  if (name === "list") { loadFlows(); loadRuns(); }
  if (name === "editor") loadEditorTemplates();
  if (name === "device") { loadDeviceIframe(); refreshTemplatesList(); }
}

$$(".tab-btn").forEach((btn) =>
  btn.addEventListener("click", () => showView(btn.dataset.view))
);

// ---- Device Connection ----

let connectedDeviceUrl = "";
let devicePreviewInterval = null;
let deviceCheckInterval = null;

// Restore last connected device
const savedDevice = localStorage.getItem("phingr_device_url");
if (savedDevice) {
  $("#device-url").value = savedDevice;
  // Auto-connect on load
  setTimeout(() => connectDevice(savedDevice), 500);
}

async function connectDevice(url) {
  if (!url) return;

  $("#device-status").textContent = "Connecting...";
  $("#device-status").className = "device-status disconnected";

  try {
    const r = await fetch(`/api/device/screenshot?url=${encodeURIComponent(url)}`, {signal: AbortSignal.timeout(5000)});
    if (r.ok) {
      connectedDeviceUrl = url;
      _iframeLoadedUrl = "";  // reset so iframe reloads on next tab switch
      localStorage.setItem("phingr_device_url", url);
      $("#device-status").textContent = "Connected";
      $("#device-status").className = "device-status connected";

      const blob = await r.blob();
      $("#device-preview").src = URL.createObjectURL(blob);
      $("#device-preview").style.display = "block";

      // Sync handles
      fetch(`/api/device/sync-handles?url=${encodeURIComponent(url)}`, {method: "POST"}).catch(() => {});

      startDeviceMonitor();
      return true;
    }
    throw new Error(`HTTP ${r.status}`);
  } catch (e) {
    $("#device-status").textContent = "Disconnected";
    $("#device-status").className = "device-status disconnected";
    $("#device-preview").style.display = "none";
    return false;
  }
}

function startDeviceMonitor() {
  // Preview refresh
  if (devicePreviewInterval) clearInterval(devicePreviewInterval);
  devicePreviewInterval = setInterval(() => {
    if (connectedDeviceUrl) {
      $("#device-preview").src = `/api/device/screenshot?url=${encodeURIComponent(connectedDeviceUrl)}&t=${Date.now()}`;
    }
  }, 5000);

  // Connection health check + auto-reconnect
  if (deviceCheckInterval) clearInterval(deviceCheckInterval);
  deviceCheckInterval = setInterval(async () => {
    if (!connectedDeviceUrl) return;
    try {
      const r = await fetch(`/api/device/screenshot?url=${encodeURIComponent(connectedDeviceUrl)}`, {signal: AbortSignal.timeout(5000)});
      if (r.ok) {
        if ($("#device-status").textContent !== "Connected") {
          $("#device-status").textContent = "Connected";
          $("#device-status").className = "device-status connected";
          $("#device-preview").style.display = "block";
        }
      } else {
        throw new Error();
      }
    } catch {
      $("#device-status").textContent = "Reconnecting...";
      $("#device-status").className = "device-status error";
    }
  }, 10000);
}

$("#btn-device-connect").addEventListener("click", () => {
  connectDevice($("#device-url").value.trim());
});

let _iframeLoadedUrl = "";
async function loadDeviceIframe() {
  const url = connectedDeviceUrl || $("#device-url").value.trim();
  if (!url) return;
  if (_iframeLoadedUrl === url) return;
  _iframeLoadedUrl = url;

  // Resolve .local hostname to IP server-side (Android lacks mDNS)
  let iframeUrl = url;
  try {
    const r = await fetch(`/api/device/resolve?url=${encodeURIComponent(url)}`);
    const data = await r.json();
    if (data.ok && data.url) iframeUrl = data.url;
  } catch {}

  $("#device-iframe").src = iframeUrl;
}

// ---- Flows List ----

async function loadFlows() {
  try {
    const flows = await api("GET", "/flows");
    const tbody = $("#flows-tbody");
    tbody.innerHTML = "";
    if (flows.length === 0) {
      $("#flows-empty").style.display = "block";
      return;
    }
    $("#flows-empty").style.display = "none";
    for (const f of flows) {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${esc(f.name)}</td>
        <td>${esc(f.filename)}</td>
        <td>${f.command_count}</td>
        <td>
          <button class="btn" onclick="runFlow('${esc(f.filename)}', '${esc(f.name)}')">Run</button>
          <button class="btn" onclick="editFlow('${esc(f.filename)}')">Edit</button>
          <button class="btn btn-danger" onclick="deleteFlow('${esc(f.filename)}')">Delete</button>
        </td>`;
      tbody.appendChild(tr);
    }
  } catch (e) {
    console.error("Failed to load flows:", e);
  }
}

async function deleteFlow(filename) {
  if (!confirm(`Delete flow "${filename}"?`)) return;
  await api("DELETE", `/flows/${filename}`);
  loadFlows();
}

// Export all flows + templates
$("#btn-export-all").addEventListener("click", () => {
  window.open("/api/export-all", "_blank");
});

// Show selected filename
$("#import-file").addEventListener("change", (e) => {
  const name = e.target.files[0]?.name || "No file selected";
  $("#import-filename").textContent = name;
});

// Import all flows + templates
$("#btn-import").addEventListener("click", async () => {
  const file = $("#import-file").files[0];
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  try {
    const r = await fetch("/api/import-all", { method: "POST", body: form });
    const data = await r.json();
    if (data.ok) {
      const parts = [`${data.flows_imported} flows`, `${data.templates_imported} templates`];
      if (data.calibration_restored) parts.push("calibration");
      alert(`Imported: ${parts.join(", ")}`);
      loadFlows();
    } else {
      alert(`Import failed: ${data.detail || "unknown error"}`);
    }
  } catch (e) {
    alert(`Import failed: ${e.message}`);
  }
});

async function editFlow(filename) {
  const yaml = await api("GET", `/flows/${filename}`);
  $("#editor-filename").value = filename;
  $("#editor-yaml").value = yaml;
  $("#editor-status").textContent = "";
  showView("editor");
}

$("#btn-refresh").addEventListener("click", () => { loadFlows(); loadRuns(); });

async function loadRuns() {
  try {
    const runs = await api("GET", "/runs");
    const tbody = $("#runs-tbody");
    tbody.innerHTML = "";
    if (runs.length === 0) {
      $("#runs-empty").style.display = "block";
      return;
    }
    $("#runs-empty").style.display = "none";
    for (const r of runs) {
      const tr = document.createElement("tr");
      const statusClass = r.status === "success" ? "badge success" :
                          r.status === "failed" ? "badge failed" :
                          r.status === "running" ? "badge running" : "badge";
      const started = new Date(r.started_at * 1000).toLocaleTimeString();
      tr.innerHTML = `
        <td>${esc(r.flow_name)}</td>
        <td><span class="${statusClass}">${r.status}</span></td>
        <td>${r.current_command + 1}/${r.total_commands}</td>
        <td>${started}</td>
        <td>
          <button class="btn" onclick="viewRun('${r.run_id}', '${esc(r.flow_name)}', '${esc(r.filename)}')">View</button>
          ${r.status === "running" ? `<button class="btn btn-danger" onclick="stopRun('${r.run_id}')">Stop</button>` : ""}
          <button class="btn btn-danger" onclick="deleteRun('${r.run_id}')">Del</button>
        </td>`;
      tbody.appendChild(tr);
    }
  } catch (e) {
    console.error("Failed to load runs:", e);
  }
}

async function stopRun(runId) {
  await api("POST", `/runs/${runId}/stop`);
  loadRuns();
}

async function deleteRun(runId) {
  await api("DELETE", `/runs/${runId}`);
  loadRuns();
}

$("#btn-new-flow").addEventListener("click", () => {
  $("#editor-filename").value = "";
  const deviceUrl = connectedDeviceUrl || "http://localhost:8080";
  $("#editor-yaml").value = `name: My Flow\ndevice: ${deviceUrl}\n---\n- pressKey: home\n- wait: 1\n`;
  showView("editor");
});

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

// ---- Editor ----

$("#btn-save").addEventListener("click", async () => {
  const filename = $("#editor-filename").value.trim();
  if (!filename) { $("#editor-status").textContent = "Enter a filename"; return; }
  try {
    const r = await api("PUT", `/flows/${filename}`, $("#editor-yaml").value, true);
    $("#editor-status").textContent = `Saved: ${r.name} (${r.command_count} commands)`;
  } catch (e) {
    $("#editor-status").textContent = `Error: ${e.message}`;
  }
});

$("#btn-validate").addEventListener("click", async () => {
  const filename = $("#editor-filename").value.trim();
  if (!filename) { $("#editor-status").textContent = "Save first"; return; }
  try {
    await api("PUT", `/flows/${filename}`, $("#editor-yaml").value, true);
    const r = await api("POST", `/flows/${filename}/validate`);
    if (r.ok) {
      $("#editor-status").textContent = `Valid: ${r.command_count} commands`;
      renderTree(r.commands || []);
    } else {
      $("#editor-status").textContent = `Invalid: ${r.error}`;
      $("#editor-tree").textContent = r.error;
    }
  } catch (e) {
    $("#editor-status").textContent = `Error: ${e.message}`;
  }
});

function renderTree(commands) {
  const el = $("#editor-tree");
  if (!commands.length) { el.textContent = "(empty flow)"; return; }
  let html = `<div class="tree-node"><span class="tree-branch">┌</span> <span class="tree-key">Flow</span> (${commands.length} commands)</div>`;
  commands.forEach((cmd, i) => {
    const isLast = i === commands.length - 1;
    const branch = isLast ? "└" : "├";
    const line = isLast ? " " : "│";
    // Parse command string to highlight parts
    const m = cmd.match(/^(\w+):\s*(.*)/);
    if (m) {
      html += `<div class="tree-node"><span class="tree-branch">${branch}──</span> <span class="tree-cmd">${esc(m[1])}</span>: <span class="tree-val">${esc(m[2])}</span></div>`;
    } else {
      html += `<div class="tree-node"><span class="tree-branch">${branch}──</span> <span class="tree-val">${esc(cmd)}</span></div>`;
    }
  });
  el.innerHTML = html;
}

// Auto-render tree on save too
const origSave = $("#btn-save").onclick;

async function loadEditorTemplates() {
  try {
    const templates = await api("GET", "/templates");
    const el = $("#editor-templates-list");
    if (templates.length === 0) {
      el.textContent = "No templates registered. Go to Templates tab to register.";
      return;
    }
    el.textContent = templates.map(t => `"${t.name}" (${t.size[0]}x${t.size[1]}px)`).join("\n");
  } catch (e) {
    $("#editor-templates-list").textContent = "Failed to load";
  }
}

// Gutter tree lines — synced with textarea
function updateGutter() {
  const textarea = $("#editor-yaml");
  const gutter = $("#editor-gutter");
  const lines = textarea.value.split("\n");
  const separator = lines.indexOf("---");

  let gutterLines = [];
  let cmdLines = []; // indices of command lines (after ---)

  for (let i = 0; i < lines.length; i++) {
    if (i <= separator || separator < 0) {
      gutterLines.push(" ");
      continue;
    }
    const line = lines[i];
    if (line.match(/^\s*#/) || line.trim() === "") {
      gutterLines.push("│");
      continue;
    }
    if (line.match(/^- /)) {
      cmdLines.push(i);
    }
    gutterLines.push(null); // placeholder
  }

  // Fill in tree symbols for command lines
  for (let j = 0; j < cmdLines.length; j++) {
    const idx = cmdLines[j];
    const isLast = j === cmdLines.length - 1;
    gutterLines[idx] = isLast ? "└" : "├";

    // Mark continuation lines between this command and the next
    const nextCmd = j < cmdLines.length - 1 ? cmdLines[j + 1] : lines.length;
    for (let k = idx + 1; k < nextCmd; k++) {
      if (gutterLines[k] === null) {
        gutterLines[k] = isLast ? " " : "│";
      }
    }
  }

  // Fill remaining nulls
  gutterLines = gutterLines.map(g => g === null ? "│" : g);

  gutter.textContent = gutterLines.join("\n");
}

// Sync gutter scroll with textarea
$("#editor-yaml").addEventListener("scroll", () => {
  $("#editor-gutter").style.transform = `translateY(-${$("#editor-yaml").scrollTop}px)`;
});

$("#editor-yaml").addEventListener("input", updateGutter);

// Initial render
setTimeout(updateGutter, 100);

// Tab key in editor
$("#editor-yaml").addEventListener("keydown", (e) => {
  if (e.key === "Tab") {
    e.preventDefault();
    const ta = e.target;
    const start = ta.selectionStart;
    ta.value = ta.value.substring(0, start) + "  " + ta.value.substring(ta.selectionEnd);
    ta.selectionStart = ta.selectionEnd = start + 2;
  }
});

// ---- Templates Tab ----

let tplDragStart = null;

function refreshTplScreenshot() {
  const deviceUrl = connectedDeviceUrl || $("#device-url").value.trim();
  if (!deviceUrl) { $("#tpl-status").textContent = "Connect to device first"; return; }

  // Sync handles for proper cropping
  fetch(`/api/device/sync-handles?url=${encodeURIComponent(deviceUrl)}`, {method: "POST"}).catch(() => {});

  const url = `/api/device/screenshot?url=${encodeURIComponent(deviceUrl)}&t=${Date.now()}`;
  $("#tpl-screenshot").src = url;
  $("#tpl-status").textContent = "Screenshot loaded. Drag to select element.";
}

async function refreshTemplatesList() {
  try {
    const templates = await api("GET", "/templates");
    const el = $("#tpl-list");
    if (templates.length === 0) {
      el.innerHTML = '<span class="muted">No templates registered yet.</span>';
      return;
    }
    el.innerHTML = templates.map(t => {
      const off = t.tap_offset || [0.5, 0.5];
      return `
      <div class="tpl-item">
        <img src="/api/templates/${encodeURIComponent(t.name)}/image" alt="${esc(t.name)}" class="tpl-thumb">
        <span>"${esc(t.name)}" ${t.size[0]}x${t.size[1]} tap@(${off[0]},${off[1]})</span>
        <span>
          <button class="btn" onclick="testTemplate('${esc(t.name)}')">Test</button>
          <button class="btn btn-danger" onclick="deleteTemplate('${esc(t.name)}')">Delete</button>
        </span>
      </div>`;
    }).join("");
  } catch (e) {
    $("#tpl-list").textContent = "Failed to load";
  }
}

async function deleteTemplate(name) {
  if (!confirm(`Delete template "${name}"?`)) return;
  await api("DELETE", `/templates/${name}`);
  refreshTemplatesList();
}

async function testTemplate(name) {
  const deviceUrl = connectedDeviceUrl || $("#device-url").value.trim();
  $("#tpl-status").textContent = `Testing "${name}"...`;
  try {
    const r = await fetch(`/api/templates/${name}/test`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({device_url: deviceUrl}),
    });
    const blob = await r.blob();
    $("#tpl-screenshot").src = URL.createObjectURL(blob);
    const matchX = r.headers.get("X-Match-X");
    const matchY = r.headers.get("X-Match-Y");
    if (matchX && matchY) {
      $("#tpl-status").textContent = `MATCH: "${name}" at (${(+matchX).toFixed(4)}, ${(+matchY).toFixed(4)})`;
    } else {
      $("#tpl-status").textContent = `NOT FOUND: "${name}"`;
    }
  } catch (e) {
    $("#tpl-status").textContent = `Test failed: ${e.message}`;
  }
}

$("#btn-tpl-refresh").addEventListener("click", () => { refreshTplScreenshot(); refreshTemplatesList(); });


$("#btn-tpl-test").addEventListener("click", () => {
  const name = $("#tpl-name").value.trim();
  if (name) testTemplate(name);
  else $("#tpl-status").textContent = "Enter template name to test";
});

// Drag to register template
$("#tpl-canvas").addEventListener("mousedown", (e) => {
  const rect = e.target.getBoundingClientRect();
  tplDragStart = {
    x: (e.clientX - rect.left) / rect.width,
    y: (e.clientY - rect.top) / rect.height,
  };
  e.preventDefault();
});

$("#tpl-canvas").addEventListener("mousemove", (e) => {
  if (!tplDragStart) return;
  const rect = e.target.getBoundingClientRect();
  const canvas = e.target;
  const ctx2d = canvas.getContext("2d");
  canvas.width = canvas.offsetWidth;
  canvas.height = canvas.offsetHeight;
  ctx2d.clearRect(0, 0, canvas.width, canvas.height);
  const x = tplDragStart.x * canvas.width;
  const y = tplDragStart.y * canvas.height;
  const w = ((e.clientX - rect.left) / rect.width) * canvas.width - x;
  const h = ((e.clientY - rect.top) / rect.height) * canvas.height - y;
  ctx2d.strokeStyle = "#f85149";
  ctx2d.lineWidth = 2;
  ctx2d.setLineDash([5, 3]);
  ctx2d.strokeRect(x, y, w, h);
  ctx2d.setLineDash([]);
});

$("#tpl-canvas").addEventListener("mouseup", async (e) => {
  if (!tplDragStart) return;
  const rect = e.target.getBoundingClientRect();
  const endX = (e.clientX - rect.left) / rect.width;
  const endY = (e.clientY - rect.top) / rect.height;

  const x1 = Math.min(tplDragStart.x, endX);
  const y1 = Math.min(tplDragStart.y, endY);
  const x2 = Math.max(tplDragStart.x, endX);
  const y2 = Math.max(tplDragStart.y, endY);
  tplDragStart = null;

  if (Math.abs(x2 - x1) < 0.02 || Math.abs(y2 - y1) < 0.02) {
    $("#tpl-status").textContent = "Drag a larger region";
    return;
  }

  const name = $("#tpl-name").value.trim();
  if (!name) {
    $("#tpl-status").textContent = "Enter a template name first";
    return;
  }

  const deviceUrl = connectedDeviceUrl || $("#device-url").value.trim();
  try {
    const offsetX = parseFloat($("#tpl-offset-x").value) || 0.5;
    const offsetY = parseFloat($("#tpl-offset-y").value) || 0.5;
    await api("POST", `/templates/${name}`, {
      device_url: deviceUrl,
      x1: +x1.toFixed(4), y1: +y1.toFixed(4),
      x2: +x2.toFixed(4), y2: +y2.toFixed(4),
      tap_offset_x: offsetX,
      tap_offset_y: offsetY,
    });
    $("#tpl-status").textContent = `Template "${name}" saved!`;
    $("#tpl-name").value = "";
    refreshTemplatesList();
  } catch (e) {
    $("#tpl-status").textContent = `Failed: ${e.message}`;
  }
});

// ---- Run View ----

let runEventSource = null;
let runAnnotatedInterval = null;
let currentRunId = null;

async function runFlow(filename, flowName) {
  let runId;
  try {
    const r = await api("POST", `/flows/${filename}/run`);
    runId = r.run_id;
  } catch (e) {
    alert(`Failed to start: ${e.message}`);
    return;
  }

  viewRun(runId, flowName, filename);
}

function viewRun(runId, flowName, filename) {
  showView("device");
  currentRunId = runId;

  // Show run bar
  $("#run-bar").style.display = "flex";
  $("#run-bar-title").textContent = flowName;
  $("#run-log").textContent = "";
  $("#run-progress-fill").style.width = "0%";
  $("#run-progress-text").textContent = "starting...";
  updateBadge("running");

  // Show annotated screenshots in capture panel during run
  startAnnotatedRefresh(runId);

  if (runEventSource) runEventSource.close();
  runEventSource = new EventSource(`/api/runs/${runId}/status`);

  runEventSource.onmessage = (e) => {
    const status = JSON.parse(e.data);
    const pct = status.total_commands > 0
      ? Math.round(((status.current_command + 1) / status.total_commands) * 100) : 0;
    $("#run-progress-fill").style.width = pct + "%";
    $("#run-progress-text").textContent = `${status.current_command + 1}/${status.total_commands}`;
    updateBadge(status.status);
    $("#run-log").textContent = (status.log || []).join("\n");
    $("#run-log").scrollTop = $("#run-log").scrollHeight;
    if (status.status === "success" || status.status === "failed") {
      runEventSource.close();
      runEventSource = null;
      stopAnnotatedRefresh();
      loadRuns();
    }
  };

  runEventSource.onerror = () => {
    if (runEventSource) runEventSource.close();
    runEventSource = null;
    stopAnnotatedRefresh();
  };
}

function startAnnotatedRefresh(runId) {
  const refresh = () => {
    const img = $("#tpl-screenshot");
    const newImg = new Image();
    newImg.onload = () => { img.src = newImg.src; };
    newImg.src = `/api/runs/${runId}/annotated?t=${Date.now()}`;
  };
  refresh();
  runAnnotatedInterval = setInterval(refresh, 1000);
}

function stopAnnotatedRefresh() {
  if (runAnnotatedInterval) { clearInterval(runAnnotatedInterval); runAnnotatedInterval = null; }
}

function updateBadge(status) {
  const badge = $("#run-status-badge");
  badge.textContent = status;
  badge.className = "badge " + status;
}

$("#btn-run-stop").addEventListener("click", async () => {
  if (currentRunId) {
    try { await api("POST", `/runs/${currentRunId}/stop`); } catch (_) {}
  }
  if (runEventSource) { runEventSource.close(); runEventSource = null; }
  stopAnnotatedRefresh();
  updateBadge("failed");
});

// ---- Resizable dividers ----

function initDivider(dividerId, leftSel, rightSel, layoutSel, mode) {
  const divider = $(`#${dividerId}`);
  if (!divider) return;
  let dragging = false;

  divider.addEventListener("mousedown", (e) => { dragging = true; e.preventDefault(); });

  document.addEventListener("mousemove", (e) => {
    if (!dragging) return;
    const layout = $(layoutSel);
    const rect = layout.getBoundingClientRect();
    const left = $(leftSel);
    const right = $(rightSel);

    if (mode === "left") {
      const newW = e.clientX - rect.left;
      if (newW > 150 && newW < rect.width - 300) {
        left.style.flex = "none";
        left.style.width = newW + "px";
      }
    } else {
      const newW = rect.right - e.clientX;
      if (newW > 150 && newW < rect.width - 300) {
        right.style.flex = "none";
        right.style.width = newW + "px";
      }
    }
  });

  document.addEventListener("mouseup", () => { dragging = false; });
}

// Editor divider
initDivider("editor-divider", ".editor-panel", ".editor-sidebar", ".editor-layout", "right");

// Device panel dividers
initDivider("divider-1", "#device-iframe-panel", "#device-capture-panel", ".device-templates-layout", "left");
initDivider("divider-2", "#device-capture-panel", "#device-tpl-list-panel", ".device-templates-layout", "right");

// ---- Init ----

loadFlows();
loadRuns();
