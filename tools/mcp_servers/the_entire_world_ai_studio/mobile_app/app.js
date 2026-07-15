const state = {
  token: new URL(location.href).searchParams.get("token") || localStorage.aiStudioRemoteToken || "",
  serverBase: new URL(location.href).searchParams.get("token") ? currentOrigin() : (localStorage.aiStudioRemoteServerBase || ""),
  scale: Number(localStorage.aiStudioRemoteScale || 1),
  latestJob: "",
  pressTimer: null,
  scannerStream: null,
  scannerDetector: null,
  scannerActive: false,
  pipelines: [],
  applications: [],
  applicationProgress: null,
  activeJobs: [],
  finishedJobs: [],
  jobSteps: [],
  selectedJobId: "",
  installPrompt: null,
};

function currentOrigin() {
  return location.origin && location.origin !== "null" ? location.origin : "";
}

const els = {
  stage: document.getElementById("stage"),
  pairScreen: document.getElementById("pairScreen"),
  pairScanner: document.getElementById("pairScanner"),
  qrVideo: document.getElementById("qrVideo"),
  pairHelp: document.getElementById("pairHelp"),
  pairUrlInput: document.getElementById("pairUrlInput"),
  menu: document.getElementById("contextMenu"),
  online: document.getElementById("online"),
  project: document.getElementById("project"),
  model: document.getElementById("model"),
  status: document.getElementById("status"),
  jobs: document.getElementById("jobs"),
  finishedJobs: document.getElementById("finishedJobs"),
  jobDetail: document.getElementById("jobDetail"),
  events: document.getElementById("events"),
  pipelines: document.getElementById("pipelines"),
  applications: document.getElementById("applications"),
  screenImage: document.getElementById("screenImage"),
  screenStatus: document.getElementById("screenStatus"),
  prompt: document.getElementById("prompt"),
  jobTitle: document.getElementById("jobTitle"),
  jobProvider: document.getElementById("jobProvider"),
  jobSteps: document.getElementById("jobSteps"),
  pipelineFilter: document.getElementById("pipelineFilter"),
  connectPanel: document.getElementById("connectPanel"),
  tokenInput: document.getElementById("tokenInput"),
  installHelp: document.getElementById("installHelp"),
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function applyZoom() {
  els.stage.style.transform = `scale(${state.scale})`;
  els.stage.style.width = `${100 / state.scale}%`;
  localStorage.aiStudioRemoteScale = String(state.scale);
}

function zoomBy(multiplier) {
  state.scale = Math.max(.45, Math.min(2.8, state.scale * multiplier));
  applyZoom();
}

function zoomReset() {
  state.scale = 1;
  applyZoom();
}

async function api(path, options = {}) {
  const headers = Object.assign({ "X-AI-Studio-Token": state.token }, options.headers || {});
  if (options.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
  const response = await fetch(apiUrl(path), Object.assign({}, options, { headers }));
  if (!response.ok) throw new Error(await response.text());
  return await response.json();
}

function apiUrl(path) {
  const base = state.serverBase || currentOrigin();
  if (!base) throw new Error("Pair by scanning the PC QR code so the workstation URL is available.");
  return new URL(path, base).toString();
}

async function command(name, payload = {}) {
  const data = await api("/api/command", {
    method: "POST",
    body: JSON.stringify({ command: name, payload }),
  });
  await refreshAll();
  return data;
}

async function submitPrompt() {
  const prompt = els.prompt.value.trim();
  if (!prompt) return;
  await command("submit_prompt", { prompt });
  els.prompt.value = "";
}

async function cancelLatest() {
  if (state.latestJob) await command("cancel_job", { job_id: state.latestJob });
}

function setPaired(isPaired) {
  document.body.classList.toggle("paired", Boolean(isPaired));
  if (!isPaired) {
    els.online.textContent = "Pair";
    els.status.textContent = "Pair this device with the desktop app.";
  }
}

function extractPairing(value) {
  const raw = String(value || "").trim();
  if (!raw) return { token: "", serverBase: "" };
  try {
    const parsed = new URL(raw);
    return {
      token: parsed.searchParams.get("token") || raw,
      serverBase: parsed.origin,
    };
  } catch (_error) {
    return { token: raw, serverBase: state.serverBase || currentOrigin() };
  }
}

function savePairing(value) {
  const pairing = extractPairing(value);
  if (!pairing.token || !pairing.serverBase) {
    els.pairHelp.textContent = "Paste the full QR link from the PC app, not only the token.";
    return false;
  }
  state.token = pairing.token;
  state.serverBase = pairing.serverBase;
  localStorage.aiStudioRemoteToken = state.token;
  localStorage.aiStudioRemoteServerBase = state.serverBase;
  els.tokenInput.value = state.token;
  stopScanner();
  setPaired(true);
  refreshAll();
  return true;
}

async function startPairing() {
  els.pairScanner.hidden = false;
  els.pairHelp.textContent = "Scan the QR code shown by Tech Connector on the PC app.";
  if (!("BarcodeDetector" in window) || !navigator.mediaDevices?.getUserMedia) {
    els.pairHelp.textContent = "Camera QR scanning is not available here. Paste the QR link or token below.";
    return;
  }
  try {
    state.scannerDetector = new BarcodeDetector({ formats: ["qr_code"] });
    state.scannerStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
    els.qrVideo.srcObject = state.scannerStream;
    els.qrVideo.hidden = false;
    await els.qrVideo.play();
    state.scannerActive = true;
    scanLoop();
  } catch (_error) {
    els.pairHelp.textContent = "Camera permission was blocked or unavailable. Paste the QR link or token below.";
  }
}

async function scanLoop() {
  if (!state.scannerActive || !state.scannerDetector) return;
  try {
    const codes = await state.scannerDetector.detect(els.qrVideo);
    const value = codes?.[0]?.rawValue || "";
    if (value && savePairing(value)) return;
  } catch (_error) {}
  requestAnimationFrame(scanLoop);
}

function stopScanner() {
  state.scannerActive = false;
  if (state.scannerStream) {
    for (const track of state.scannerStream.getTracks()) track.stop();
  }
  state.scannerStream = null;
  els.qrVideo.hidden = true;
  els.qrVideo.srcObject = null;
}

function addJobStep(type = "DCC Command", label = "") {
  const number = state.jobSteps.length + 1;
  state.jobSteps.push({
    id: `node_${Date.now()}_${number}`,
    type,
    label: label || `${type} ${number}`,
    detail: "",
  });
  renderJobSteps();
}

function updateJobStep(index, field, value) {
  if (!state.jobSteps[index]) return;
  state.jobSteps[index][field] = value;
}

function removeJobStep(index) {
  state.jobSteps.splice(index, 1);
  renderJobSteps();
}

function renderJobSteps() {
  els.jobSteps.innerHTML = state.jobSteps.map((step, index) => {
    const next = state.jobSteps[index + 1]?.label || "Finish";
    const types = ["Inspect", "Pipeline", "DCC Command", "Validate", "Report"];
    return `<div class="node-card">
      <div class="node-title">
        <span class="node-port"></span>
        <input value="${escapeHtml(step.label)}" data-step-label="${index}" placeholder="Node name">
      </div>
      <select data-step-type="${index}">
        ${types.map((type) => `<option value="${type}" ${step.type === type ? "selected" : ""}>${type}</option>`).join("")}
      </select>
      <textarea data-step-detail="${index}" placeholder="What data does this node need, produce, or validate?">${escapeHtml(step.detail)}</textarea>
      <div class="node-flow">flows to ${escapeHtml(next)}</div>
      <div class="toolbar top-space"><button data-remove-step="${index}">Remove Node</button></div>
    </div>`;
  }).join("") || '<div class="muted">No nodes yet. Add nodes for a mobile-friendly job graph.</div>';
}

async function createJob() {
  const title = els.jobTitle.value.trim() || "Mobile job";
  const goal = els.prompt.value.trim();
  const provider = els.jobProvider.value.trim();
  const steps = state.jobSteps.map((step, index) => ({
    label: `${step.type || "Node"}: ${step.label || `Node ${index + 1}`}`,
    detail: step.detail || "",
    node_id: step.id,
    node_type: step.type || "DCC Command",
    next_node_id: state.jobSteps[index + 1]?.id || "",
  }));
  await command("create_job", { title, goal, provider, steps });
  els.jobTitle.value = "";
  els.prompt.value = "";
  els.jobProvider.value = "";
  state.jobSteps = [];
  renderJobSteps();
}

async function installApp() {
  if (state.installPrompt) {
    state.installPrompt.prompt();
    await state.installPrompt.userChoice.catch(() => {});
    state.installPrompt = null;
    return;
  }
  downloadApp();
}

function downloadApp() {
  const link = document.createElement("a");
  link.href = apiUrl(`/download/mobile-app.zip?token=${encodeURIComponent(state.token)}`);
  link.download = "tech-connector-mobile-app.zip";
  document.body.appendChild(link);
  link.click();
  link.remove();
}

async function refreshScreen(applicationId = "tech_connector") {
  const data = await api(`/api/application-progress?application_id=${encodeURIComponent(applicationId)}`);
  state.applicationProgress = data.progress || {};
  const desktop = state.applicationProgress.desktop || {};
  const hostView = state.applicationProgress.host_view || {};
  const stamp = Date.now();
  els.screenImage.src = apiUrl(`/api/screen.png?target=desktop&token=${encodeURIComponent(state.token)}&t=${stamp}`);
  els.screenStatus.textContent = JSON.stringify({
    active_tab: desktop.active_tab || "",
    active_editor_tab: desktop.active_editor_tab || "",
    current_file_path: desktop.current_file_path || "",
    live_process: desktop.live_process || "",
    host_view: hostView.message || "",
  }, null, 2);
}

async function refreshApplications() {
  const data = await api("/api/applications");
  state.applications = data.applications || [];
  els.applications.innerHTML = state.applications.map((app, index) => {
    const caps = (app.capabilities || []).map(escapeHtml).join(", ");
    const mode = escapeHtml(app.mode || "");
    const note = escapeHtml(app.monitoring_note || "");
    return `<div class="row">
      <b>${escapeHtml(app.name)}</b> <span class="pill">${app.connected ? "LIVE" : "SETUP"}</span>
      <div class="muted">${mode}</div>
      <div>${caps}</div>
      <div class="toolbar top-space">
        <button data-monitor-app="${index}">Monitor</button>
        <button data-snapshot-app="${index}">Snapshot</button>
        <button data-screen-app="${index}">Screen</button>
      </div>
      <div class="muted">${note}</div>
    </div>`;
  }).join("") || '<div class="muted">No application status available</div>';
}

async function refreshPipelines() {
  const query = els.pipelineFilter.value || "";
  const data = await api(`/api/pipelines?query=${encodeURIComponent(query)}`);
  state.pipelines = data.pipelines || [];
  els.pipelines.innerHTML = state.pipelines.map((pipeline, index) => {
    return `<div class="row">
      <b>[${escapeHtml(pipeline.host)}] ${escapeHtml(pipeline.name)}</b>
      <div>${escapeHtml(pipeline.goal || "")}</div>
      <div class="muted">${pipeline.slot_count} slots - ${pipeline.capability_count} capabilities</div>
      <div class="toolbar top-space">
        <button data-run-pipeline="${index}">Run</button>
        <button data-open-pipeline="${index}">Open on Desktop</button>
        <button data-create-from-pipeline="${index}">Create Job From This</button>
      </div>
    </div>`;
  }).join("") || '<div class="muted">No saved pipelines</div>';
}

function renderJobCard(job, index, source) {
    const errors = (job.errors || []).map(escapeHtml).join("<br>");
    const warnings = (job.warnings || []).map(escapeHtml).join("<br>");
    return `<div class="row">
      <b>${escapeHtml(job.command)}</b> <span class="pill">${escapeHtml(job.status)}</span>
      <div>${escapeHtml(job.current_step)}</div>
      <div class="muted">${job.progress}% - ${escapeHtml(job.job_id)}</div>
      <div class="toolbar top-space"><button data-view-job="${source}:${index}">View Logs</button></div>
      ${errors ? `<div class="bad">${errors}</div>` : ""}
      ${warnings ? `<div class="warn">${warnings}</div>` : ""}
    </div>`;
}

async function refreshJobs() {
  const active = await api("/api/jobs?state=active");
  const finished = await api("/api/jobs?state=finished");
  state.activeJobs = active.jobs || [];
  state.finishedJobs = finished.jobs || [];
  state.latestJob = state.activeJobs?.[0]?.job_id || state.finishedJobs?.[0]?.job_id || state.latestJob;
  els.jobs.innerHTML = state.activeJobs.map((job, index) => renderJobCard(job, index, "active")).join("") || '<div class="muted">No active jobs</div>';
  els.finishedJobs.innerHTML = state.finishedJobs.map((job, index) => renderJobCard(job, index, "finished")).join("") || '<div class="muted">No finished jobs</div>';
  if (state.selectedJobId) await refreshJobDetail(state.selectedJobId);
}

async function refreshJobDetail(jobId) {
  if (!jobId) return;
  state.selectedJobId = jobId;
  const data = await api(`/api/job?job_id=${encodeURIComponent(jobId)}`);
  if (!data.ok) {
    els.jobDetail.innerHTML = `<div class="row bad">${escapeHtml(data.error || "Job not found")}</div>`;
    return;
  }
  const job = data.job;
  const changes = job.changes || {};
  const changeRows = Object.entries(changes).map(([key, value]) => {
    const count = Array.isArray(value) ? value.length : 0;
    return `<div class="row"><b>${escapeHtml(key)}</b><div class="muted">${count} item(s)</div>${count ? `<div class="mono">${escapeHtml(JSON.stringify(value, null, 2))}</div>` : ""}</div>`;
  }).join("");
  const logs = (job.output_log || []).map((entry) => {
    return `<div class="row log-entry ${escapeHtml(entry.severity || "")}">
      <b>${escapeHtml(entry.kind)}</b> <span class="muted">${escapeHtml(entry.time || "")}</span>
      <div>${escapeHtml(entry.message || "")}</div>
      ${entry.payload && Object.keys(entry.payload).length ? `<div class="mono muted">${escapeHtml(JSON.stringify(entry.payload, null, 2))}</div>` : ""}
    </div>`;
  }).join("");
  const reports = (job.reports || []).map((report) => `<div class="row"><b>${escapeHtml(report.type || "report")}</b><div>${escapeHtml(report.summary || "")}</div><div class="mono muted">${escapeHtml(JSON.stringify(report, null, 2))}</div></div>`).join("");
  els.jobDetail.innerHTML = `
    <div class="row selected">
      <b>${escapeHtml(job.command)}</b> <span class="pill">${escapeHtml(job.status)}</span>
      <div>${escapeHtml(job.current_step)}</div>
      <div class="muted">${escapeHtml(job.job_id)}</div>
    </div>
    <h2>Changes / Outputs</h2>
    <div class="change-grid">${changeRows || '<div class="muted">No changes reported</div>'}</div>
    <h2>Reports</h2>
    ${reports || '<div class="muted">No reports</div>'}
    <h2>Output Log</h2>
    ${logs || '<div class="muted">No output log entries</div>'}
  `;
}

async function refreshEvents() {
  const data = await api("/api/events?limit=40");
  els.events.innerHTML = (data.events || []).reverse().map((event) => {
    return `<div class="row">
      <b>${escapeHtml(event.event_type)}</b> <span class="muted">${escapeHtml(event.created_at)}</span>
      <div>${escapeHtml(event.message)}</div>
    </div>`;
  }).join("") || '<div class="muted">No events</div>';
}

async function refreshAll() {
  try {
    if (!state.token || !state.serverBase) {
      setPaired(false);
      els.connectPanel.hidden = false;
      return;
    }
    setPaired(true);
    els.connectPanel.hidden = true;
    const status = await api("/api/status");
    els.online.textContent = status.status.studio_running ? "Online" : "Offline";
    els.project.textContent = status.status.active_project || "No project";
    els.model.textContent = status.status.model || "No model";
    els.status.textContent = JSON.stringify(status.status, null, 2);
    await refreshApplications();
    await refreshScreen();
    await refreshJobs();
    await refreshPipelines();
    await refreshEvents();
  } catch (error) {
    els.connectPanel.hidden = false;
    els.online.textContent = "Error";
    els.status.textContent = String(error);
  }
}

function showMenu(x, y) {
  els.menu.style.left = `${x}px`;
  els.menu.style.top = `${y}px`;
  els.menu.style.display = "block";
}

function hideMenu() {
  els.menu.style.display = "none";
}

function saveToken() {
  savePairing(els.tokenInput.value.trim());
}

function onClick(event) {
  const target = event.target.closest("button");
  if (!target) return;
  const action = target.dataset.action;
  const commandName = target.dataset.command;
  hideMenu();
  if (action === "zoom-in") zoomBy(1.15);
  if (action === "zoom-out") zoomBy(.85);
  if (action === "zoom-reset") zoomReset();
  if (action === "refresh") refreshAll();
  if (action === "send-prompt") submitPrompt();
  if (action === "create-job") createJob();
  if (action === "add-job-node") addJobStep();
  if (action === "start-pairing") startPairing();
  if (action === "save-pair-url") savePairing(els.pairUrlInput.value);
  if (action === "cancel-latest") cancelLatest();
  if (action === "install-app") installApp();
  if (action === "download-app") downloadApp();
  if (action === "toggle-install-help") els.installHelp.hidden = !els.installHelp.hidden;
  if (action === "save-token") saveToken();
  if (action === "refresh-pipelines") refreshPipelines();
  if (action === "refresh-screen") refreshScreen();
  if (commandName) command(commandName, {});
  if (target.dataset.monitorApp) {
    const app = state.applications[Number(target.dataset.monitorApp)];
    if (app) {
      command("monitor_application", { application_id: app.id, view_mode: "status" });
      refreshScreen(app.id);
    }
  }
  if (target.dataset.snapshotApp) {
    const app = state.applications[Number(target.dataset.snapshotApp)];
    if (app) command("request_screenshot", { application_id: app.id, view_mode: "snapshot" });
  }
  if (target.dataset.screenApp) {
    const app = state.applications[Number(target.dataset.screenApp)];
    if (app) refreshScreen(app.id);
  }
  if (target.dataset.runPipeline) {
    const pipeline = state.pipelines[Number(target.dataset.runPipeline)];
    if (pipeline) command("execute_workflow", { pipeline_id: pipeline.id });
  }
  if (target.dataset.createFromPipeline) {
    const pipeline = state.pipelines[Number(target.dataset.createFromPipeline)];
    if (pipeline) {
      els.jobTitle.value = `Run ${pipeline.name}`;
      els.prompt.value = pipeline.goal || "";
      els.jobProvider.value = pipeline.host || "";
      state.jobSteps = [
        { id: `node_${Date.now()}_1`, type: "Pipeline", label: "Load pipeline", detail: pipeline.manifest_path || pipeline.id },
        { id: `node_${Date.now()}_2`, type: "Validate", label: "Validate required inputs", detail: JSON.stringify(pipeline.slots || {}, null, 2) },
        { id: `node_${Date.now()}_3`, type: "Report", label: "Run and report outputs", detail: "Show files/assets changed, warnings, errors, and validation result." },
      ];
      renderJobSteps();
    }
  }
  if (target.dataset.viewJob) {
    const [source, rawIndex] = target.dataset.viewJob.split(":");
    const list = source === "finished" ? state.finishedJobs : state.activeJobs;
    const job = list[Number(rawIndex)];
    if (job) refreshJobDetail(job.job_id);
  }
  if (target.dataset.openPipeline) {
    const pipeline = state.pipelines[Number(target.dataset.openPipeline)];
    if (pipeline) {
      command("continue_conversation", {
        prompt: `Open pipeline ${pipeline.name} on desktop`,
        pipeline_id: pipeline.id,
      });
    }
  }
}

document.addEventListener("click", onClick);
document.addEventListener("input", (event) => {
  const labelIndex = event.target.dataset.stepLabel;
  const detailIndex = event.target.dataset.stepDetail;
  const typeIndex = event.target.dataset.stepType;
  if (labelIndex !== undefined) updateJobStep(Number(labelIndex), "label", event.target.value);
  if (detailIndex !== undefined) updateJobStep(Number(detailIndex), "detail", event.target.value);
  if (typeIndex !== undefined) updateJobStep(Number(typeIndex), "type", event.target.value);
});
document.addEventListener("click", (event) => {
  const target = event.target.closest("button");
  if (target?.dataset.removeStep !== undefined) removeJobStep(Number(target.dataset.removeStep));
});
els.pipelineFilter.addEventListener("input", refreshPipelines);
document.addEventListener("pointerdown", (event) => {
  hideMenu();
  state.pressTimer = setTimeout(() => showMenu(event.clientX, event.clientY), 2000);
});
document.addEventListener("pointerup", () => clearTimeout(state.pressTimer));
document.addEventListener("pointercancel", () => clearTimeout(state.pressTimer));
document.addEventListener("contextmenu", (event) => {
  event.preventDefault();
  showMenu(event.clientX, event.clientY);
});
window.addEventListener("beforeinstallprompt", (event) => {
  event.preventDefault();
  state.installPrompt = event;
});

if (state.token) localStorage.aiStudioRemoteToken = state.token;
if (state.serverBase) localStorage.aiStudioRemoteServerBase = state.serverBase;
els.tokenInput.value = state.token;
applyZoom();
renderJobSteps();
setPaired(Boolean(state.token && state.serverBase));
refreshAll();
setInterval(refreshAll, 2500);

if ("serviceWorker" in navigator && location.protocol === "https:") {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}
