"""HTTP mobile second-screen server for Tech Connector.

This intentionally exposes commands and state, not desktop button clicks. The
mobile page acts like a zoomable control surface backed by
ApplicationCommandService.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
from pathlib import Path
import secrets
import socket
import threading
from typing import Any
from urllib.parse import parse_qs, urlparse
from zipfile import ZIP_DEFLATED, ZipFile

from tech_connector.services.application_command_service import ApplicationCommandService
from tech_connector.services.qr_code_service import qr_svg


MOBILE_APP_DIR = Path(__file__).resolve().parent.parent / "mobile_app"
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".webmanifest": "application/manifest+json",
    ".json": "application/json",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


MOBILE_INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=5, user-scalable=yes">
  <title>Tech Connector Remote</title>
  <style>
    :root { color-scheme: dark; --bg:#020806; --panel:#06120e; --line:#00c875; --text:#ddffe9; --muted:#7dbb95; --warn:#ffb454; --bad:#ff6b6b; }
    * { box-sizing: border-box; }
    html, body { margin:0; min-height:100%; background:var(--bg); color:var(--text); font:14px/1.4 system-ui, -apple-system, Segoe UI, sans-serif; }
    body { overflow:hidden; touch-action:pan-x pan-y pinch-zoom; }
    button, textarea, input { font:inherit; color:var(--text); background:#010604; border:1px solid var(--line); border-radius:6px; }
    button { padding:8px 10px; font-weight:700; }
    textarea { width:100%; min-height:88px; resize:vertical; padding:10px; }
    .viewport { width:100vw; height:100vh; overflow:auto; touch-action:pan-x pan-y pinch-zoom; }
    .stage { transform-origin:0 0; min-width:980px; padding:14px; }
    header { display:flex; align-items:center; gap:10px; border-bottom:1px solid #075b36; padding-bottom:10px; position:sticky; top:0; background:rgba(2,8,6,.96); z-index:5; }
    h1 { font-size:18px; margin:0; color:#94ffc4; }
    .pill { border:1px solid #0c7a47; border-radius:999px; padding:4px 8px; color:var(--muted); }
    .grid { display:grid; grid-template-columns: 1.1fr .9fr; gap:12px; margin-top:12px; }
    .panel { border:1px solid #075b36; background:var(--panel); border-radius:8px; padding:12px; min-height:120px; }
    .panel h2 { margin:0 0 8px 0; color:#94ffc4; font-size:15px; }
    .toolbar { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
    .muted { color:var(--muted); }
    .warn { color:var(--warn); }
    .bad { color:var(--bad); }
    .list { display:grid; gap:8px; max-height:42vh; overflow:auto; }
    .row { border:1px solid #064326; border-radius:6px; padding:8px; background:#020a07; }
    .mono { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; white-space:pre-wrap; }
    #contextMenu { position:fixed; display:none; z-index:30; min-width:220px; background:#020a07; border:1px solid var(--line); border-radius:8px; padding:6px; box-shadow:0 12px 28px rgba(0,0,0,.45); }
    #contextMenu button { display:block; width:100%; text-align:left; margin:3px 0; border-color:#075b36; }
    @media (max-width: 800px) { .stage { min-width:760px; } .grid { grid-template-columns:1fr; } }
  </style>
</head>
<body>
  <div class="viewport" id="viewport">
    <main class="stage" id="stage">
      <header>
        <h1>Tech Connector Remote</h1>
        <span class="pill" id="online">Connecting</span>
        <span class="pill" id="project">Project</span>
        <span class="pill" id="model">Model</span>
        <div class="toolbar" style="margin-left:auto">
          <button onclick="zoomBy(.9)">-</button>
          <button onclick="zoomReset()">100%</button>
          <button onclick="zoomBy(1.1)">+</button>
          <button onclick="refreshAll()">Refresh</button>
        </div>
      </header>
      <section class="grid">
        <div class="panel" data-menu="prompt">
          <h2>Prompt View</h2>
          <textarea id="prompt" placeholder="Ask Tech Connector..."></textarea>
          <div class="toolbar" style="margin-top:8px">
            <button onclick="submitPrompt()">Send Prompt</button>
            <button onclick="command('continue_conversation', {})">Continue</button>
            <button onclick="command('request_screenshot', {})">Request Screenshot</button>
          </div>
          <p class="muted">Long-press any panel for 2 seconds to open actions. Pinch or use zoom controls to scale the whole screen.</p>
        </div>
        <div class="panel" data-menu="machine">
          <h2>Machine View</h2>
          <div id="status" class="mono muted">Loading...</div>
        </div>
        <div class="panel" data-menu="applications">
          <h2>Application View</h2>
          <div id="applications" class="list"></div>
        </div>
        <div class="panel" data-menu="jobs">
          <h2>Job View</h2>
          <div id="jobs" class="list"></div>
        </div>
        <div class="panel" data-menu="pipelines">
          <h2>Pipelines</h2>
          <div class="toolbar" style="margin-bottom:8px">
            <input id="pipelineFilter" placeholder="Filter pipelines..." oninput="refreshPipelines()" style="padding:8px; min-width:260px">
            <button onclick="refreshPipelines()">Refresh</button>
          </div>
          <div id="pipelines" class="list"></div>
        </div>
        <div class="panel" data-menu="events">
          <h2>Live Events</h2>
          <div id="events" class="list"></div>
        </div>
      </section>
    </main>
  </div>
  <nav id="contextMenu">
    <button onclick="hideMenu(); refreshAll()">Refresh Panel</button>
    <button onclick="hideMenu(); submitPrompt()">Send Prompt</button>
    <button onclick="hideMenu(); command('request_screenshot', {})">Request Snapshot</button>
    <button onclick="hideMenu(); cancelLatest()">Cancel Latest Job</button>
    <button onclick="hideMenu(); zoomBy(1.15)">Zoom In</button>
    <button onclick="hideMenu(); zoomBy(.85)">Zoom Out</button>
  </nav>
  <script>
    const token = new URL(location.href).searchParams.get('token') || '';
    let scale = Number(localStorage.aiStudioRemoteScale || 1);
    let latestJob = '';
    let pressTimer = null;
    const stage = document.getElementById('stage');
    const menu = document.getElementById('contextMenu');
    function applyZoom(){ stage.style.transform = `scale(${scale})`; stage.style.width = `${100 / scale}%`; localStorage.aiStudioRemoteScale = scale; }
    function zoomBy(v){ scale = Math.max(.45, Math.min(2.8, scale * v)); applyZoom(); }
    function zoomReset(){ scale = 1; applyZoom(); }
    async function api(path, options={}){
      const headers = Object.assign({'X-AI-Studio-Token': token}, options.headers || {});
      if (options.body && !headers['Content-Type']) headers['Content-Type'] = 'application/json';
      const res = await fetch(path, Object.assign({}, options, {headers}));
      if (!res.ok) throw new Error(await res.text());
      return await res.json();
    }
    async function command(name, payload){
      const data = await api('/api/command', {method:'POST', body:JSON.stringify({command:name, payload:payload||{}})});
      await refreshAll();
      return data;
    }
    async function submitPrompt(){
      const prompt = document.getElementById('prompt').value.trim();
      if (!prompt) return;
      await command('submit_prompt', {prompt});
      document.getElementById('prompt').value = '';
    }
    async function cancelLatest(){ if (latestJob) await command('cancel_job', {job_id: latestJob}); }
    async function refreshPipelines(){
      const query = document.getElementById('pipelineFilter')?.value || '';
      const data = await api('/api/pipelines?query=' + encodeURIComponent(query));
      window.pipelineCache = data.pipelines || [];
      document.getElementById('pipelines').innerHTML = window.pipelineCache.map((p, i) => `<div class="row"><b>[${p.host}] ${p.name}</b><div>${p.goal || ''}</div><div class="muted">${p.slot_count} slots • ${p.capability_count} capabilities</div><div class="toolbar" style="margin-top:6px"><button onclick="runPipeline(${i})">Run</button><button onclick="openPipeline(${i})">Open on Desktop</button></div></div>`).join('') || '<div class="muted">No saved pipelines</div>';
    }
    async function runPipeline(index){ const p = (window.pipelineCache || [])[index]; if (p) await command('execute_workflow', {pipeline_id:p.id}); }
    async function openPipeline(index){ const p = (window.pipelineCache || [])[index]; if (p) await command('continue_conversation', {prompt:`Open pipeline ${p.name} on desktop`, pipeline_id:p.id}); }
    async function refreshApplications(){
      const data = await api('/api/applications');
      window.applicationCache = data.applications || [];
      document.getElementById('applications').innerHTML = window.applicationCache.map((app, i) => `<div class="row"><b>${app.name}</b> <span class="pill">${app.connected ? 'LIVE' : 'SETUP'}</span><div class="muted">${app.mode}</div><div>${(app.capabilities||[]).join(', ')}</div><div class="toolbar" style="margin-top:6px"><button onclick="monitorApplication(${i})">Monitor</button><button onclick="snapshotApplication(${i})">Snapshot</button></div><div class="muted">${app.monitoring_note || ''}</div></div>`).join('') || '<div class="muted">No application status available</div>';
    }
    async function monitorApplication(index){ const app = (window.applicationCache || [])[index]; if (app) await command('monitor_application', {application_id:app.id, view_mode:'status'}); }
    async function snapshotApplication(index){ const app = (window.applicationCache || [])[index]; if (app) await command('request_screenshot', {application_id:app.id, view_mode:'snapshot'}); }
    async function refreshAll(){
      try {
        const status = await api('/api/status');
        document.getElementById('online').textContent = status.status.studio_running ? 'Online' : 'Offline';
        document.getElementById('project').textContent = status.status.active_project || 'No project';
        document.getElementById('model').textContent = status.status.model || 'No model';
        document.getElementById('status').textContent = JSON.stringify(status.status, null, 2);
        await refreshApplications();
        const jobs = await api('/api/jobs');
        latestJob = jobs.jobs[0]?.job_id || latestJob;
        document.getElementById('jobs').innerHTML = jobs.jobs.map(j => `<div class="row"><b>${j.command}</b> <span class="pill">${j.status}</span><div>${j.current_step}</div><div class="muted">${j.progress}% • ${j.job_id}</div>${j.errors.length ? `<div class="bad">${j.errors.join('<br>')}</div>` : ''}${j.warnings.length ? `<div class="warn">${j.warnings.join('<br>')}</div>` : ''}</div>`).join('') || '<div class="muted">No jobs</div>';
        await refreshPipelines();
        const events = await api('/api/events?limit=40');
        document.getElementById('events').innerHTML = events.events.reverse().map(e => `<div class="row"><b>${e.event_type}</b> <span class="muted">${e.created_at}</span><div>${e.message}</div></div>`).join('') || '<div class="muted">No events</div>';
      } catch (err) {
        document.getElementById('online').textContent = 'Error';
        document.getElementById('status').textContent = String(err);
      }
    }
    function showMenu(x,y){ menu.style.left = x+'px'; menu.style.top = y+'px'; menu.style.display = 'block'; }
    function hideMenu(){ menu.style.display = 'none'; }
    document.addEventListener('pointerdown', e => { hideMenu(); pressTimer = setTimeout(() => showMenu(e.clientX, e.clientY), 2000); });
    document.addEventListener('pointerup', () => clearTimeout(pressTimer));
    document.addEventListener('pointercancel', () => clearTimeout(pressTimer));
    document.addEventListener('contextmenu', e => { e.preventDefault(); showMenu(e.clientX, e.clientY); });
    applyZoom(); refreshAll(); setInterval(refreshAll, 2500);
  </script>
</body>
</html>
"""


def lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except Exception:
        return "127.0.0.1"


class RemoteMobileServer:
    def __init__(
        self,
        command_service: ApplicationCommandService,
        *,
        host: str = "127.0.0.1",
        port: int = 8765,
        token: str = "",
    ):
        self.command_service = command_service
        self.host = host
        self.port = int(port)
        self.token = token or secrets.token_urlsafe(18)
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return self._server is not None

    @property
    def base_url(self) -> str:
        display_host = lan_ip() if self.host in {"0.0.0.0", ""} else self.host
        return f"http://{display_host}:{self.port}/?token={self.token}"

    @property
    def pairing_qr_url(self) -> str:
        display_host = lan_ip() if self.host in {"0.0.0.0", ""} else self.host
        return f"http://{display_host}:{self.port}/pair.svg?token={self.token}"

    @property
    def download_qr_url(self) -> str:
        display_host = lan_ip() if self.host in {"0.0.0.0", ""} else self.host
        return f"http://{display_host}:{self.port}/download.svg?token={self.token}"

    def start(self) -> str:
        if self._server is not None:
            return self.base_url
        handler_cls = self._handler_class()
        self._server = ThreadingHTTPServer((self.host, self.port), handler_cls)
        self.port = int(self._server.server_address[1])
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self.base_url

    def stop(self) -> None:
        server = self._server
        self._server = None
        if server is not None:
            server.shutdown()
            server.server_close()
        self._thread = None

    def _handler_class(self):
        command_service = self.command_service
        token = self.token

        class Handler(BaseHTTPRequestHandler):
            server_version = "TechConnectorMobile/0.2"

            def log_message(self, _format: str, *_args: Any) -> None:
                return

            def do_OPTIONS(self) -> None:
                self.send_response(204)
                self._send_cors_headers()
                self.end_headers()

            def do_GET(self) -> None:
                parsed = urlparse(self.path)
                if parsed.path == "/":
                    self._send_mobile_asset("index.html")
                    return
                if parsed.path in {"/app.css", "/app.js", "/manifest.webmanifest", "/sw.js", "/tech_connector_logo.png"}:
                    self._send_mobile_asset(parsed.path.lstrip("/"))
                    return
                if parsed.path == "/pair.svg":
                    if not self._authorized(parsed):
                        self._send_json({"ok": False, "error": "Unauthorized"}, 401)
                        return
                    self._send_svg(qr_svg(command_service_url()))
                    return
                if parsed.path == "/download.svg":
                    if not self._authorized(parsed):
                        self._send_json({"ok": False, "error": "Unauthorized"}, 401)
                        return
                    self._send_svg(qr_svg(command_service_download_url()))
                    return
                if parsed.path == "/download/mobile-app.zip":
                    if not self._authorized(parsed):
                        self._send_json({"ok": False, "error": "Unauthorized"}, 401)
                        return
                    self._send_mobile_zip()
                    return
                if not self._authorized(parsed):
                    self._send_json({"ok": False, "error": "Unauthorized"}, 401)
                    return
                if parsed.path == "/api/status":
                    self._send_json(command_service.execute("retrieve_status"))
                    return
                if parsed.path == "/api/jobs":
                    query = parse_qs(parsed.query)
                    self._send_json(command_service.execute("list_jobs", {"limit": query.get("limit", ["50"])[0], "state": query.get("state", ["all"])[0]}))
                    return
                if parsed.path == "/api/job":
                    query = parse_qs(parsed.query)
                    self._send_json(command_service.execute("get_job", {"job_id": query.get("job_id", [""])[0]}))
                    return
                if parsed.path == "/api/pipelines":
                    query = parse_qs(parsed.query)
                    self._send_json(command_service.execute("list_pipelines", {"query": query.get("query", [""])[0]}))
                    return
                if parsed.path == "/api/applications":
                    self._send_json(command_service.execute("list_applications"))
                    return
                if parsed.path == "/api/application-progress":
                    query = parse_qs(parsed.query)
                    self._send_json(command_service.execute("application_progress", {"application_id": query.get("application_id", ["tech_connector"])[0]}))
                    return
                if parsed.path == "/api/screen.png":
                    data = command_service.screen_png_bytes(parse_qs(parsed.query).get("target", ["desktop"])[0])
                    if not data:
                        self._send_json({"ok": False, "error": "Screen capture unavailable"}, 503)
                        return
                    self._send_png(data)
                    return
                if parsed.path == "/api/events":
                    query = parse_qs(parsed.query)
                    self._send_json(command_service.execute("recent_events", {"limit": query.get("limit", ["100"])[0], "after_event_id": query.get("after_event_id", [""])[0]}))
                    return
                self._send_json({"ok": False, "error": "Not found"}, 404)

            def do_POST(self) -> None:
                parsed = urlparse(self.path)
                if not self._authorized(parsed):
                    self._send_json({"ok": False, "error": "Unauthorized"}, 401)
                    return
                if parsed.path != "/api/command":
                    self._send_json({"ok": False, "error": "Not found"}, 404)
                    return
                payload = self._read_json()
                self._send_json(command_service.execute(str(payload.get("command") or ""), payload.get("payload") or {}))

            def _authorized(self, parsed) -> bool:
                if not token:
                    return True
                query_token = parse_qs(parsed.query).get("token", [""])[0]
                header_token = self.headers.get("X-AI-Studio-Token", "")
                return secrets.compare_digest(query_token or header_token, token)

            def _read_json(self) -> dict[str, Any]:
                try:
                    length = int(self.headers.get("Content-Length", "0") or "0")
                    raw = self.rfile.read(length).decode("utf-8") if length else "{}"
                    data = json.loads(raw or "{}")
                    return data if isinstance(data, dict) else {}
                except Exception:
                    return {}

            def _send_html(self, text: str, status: int = 200) -> None:
                data = text.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self._send_cors_headers()
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _send_svg(self, text: str, status: int = 200) -> None:
                data = text.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "image/svg+xml")
                self.send_header("Cache-Control", "no-store")
                self._send_cors_headers()
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _send_png(self, data: bytes, status: int = 200) -> None:
                self.send_response(status)
                self.send_header("Content-Type", "image/png")
                self.send_header("Cache-Control", "no-store")
                self._send_cors_headers()
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _send_mobile_asset(self, name: str) -> None:
                path = (MOBILE_APP_DIR / name).resolve()
                root = MOBILE_APP_DIR.resolve()
                if root not in path.parents and path != root:
                    self._send_json({"ok": False, "error": "Not found"}, 404)
                    return
                if not path.exists() or not path.is_file():
                    self._send_json({"ok": False, "error": "Not found"}, 404)
                    return
                data = path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", CONTENT_TYPES.get(path.suffix, "application/octet-stream"))
                self.send_header("Cache-Control", "no-store")
                self._send_cors_headers()
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _send_mobile_zip(self) -> None:
                buffer = BytesIO()
                with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
                    for path in MOBILE_APP_DIR.rglob("*"):
                        if path.is_file():
                            archive.write(path, path.relative_to(MOBILE_APP_DIR).as_posix())
                    archive.writestr(
                        "README.txt",
                        "Tech Connector Remote mobile client.\n\n"
                        "This is the thin second-screen client served by the desktop Tech Connector app. "
                        "For normal use, scan the QR code from Tech Connector so the token and workstation URL are filled in automatically.\n",
                    )
                data = buffer.getvalue()
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Disposition", 'attachment; filename="tech-connector-mobile-app.zip"')
                self.send_header("Cache-Control", "no-store")
                self._send_cors_headers()
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _send_json(self, data: dict[str, Any], status: int = 200) -> None:
                raw = json.dumps(data, ensure_ascii=True).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self._send_cors_headers()
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _send_cors_headers(self) -> None:
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, X-AI-Studio-Token")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

        def command_service_url() -> str:
            return self.base_url

        def command_service_download_url() -> str:
            display_host = lan_ip() if self.host in {"0.0.0.0", ""} else self.host
            return f"http://{display_host}:{self.port}/download/mobile-app.zip?token={token}"

        return Handler
