from __future__ import annotations

"""Direct Adobe Photoshop UXP plugin bridge."""

import base64
import json
import os
import socket
from pathlib import Path
from tech_connector.bridges.error_detection import bridge_output_has_error
from tech_connector.bridges.host_bridge import HostBridgeInfo
from tech_connector.models.constants import APP_DIR, APP_ROOT, TOOLS_ROOT


# ---------------------------------------------------------------------------
# UXP plugin source (JavaScript — dropped into Photoshop's UXP plugin folder)
# ---------------------------------------------------------------------------

PLUGIN_ID = "com.theentireworld.aistudio.bridge"
PLUGIN_FILENAME = "index.js"
PLUGIN_MANIFEST_FILENAME = "manifest.json"

PLUGIN_MANIFEST = json.dumps({
    "id": PLUGIN_ID,
    "name": "The Entire World Tech Connector Bridge",
    "version": "1.0.0",
    "host": {
        "app": "PS",
        "minVersion": "23.0"
    },
    "entrypoints": [
        {
            "type": "command",
            "id": "startBridge",
            "label": {"default": "Start Tech Connector Bridge"}
        },
        {
            "type": "panel",
            "id": "bridgePanel",
            "label": {"default": "Tech Connector Bridge"},
            "minimumSize": {"width": 200, "height": 80}
        }
    ],
    "requiredPermissions": {
        "network": {
            "domains": ["localhost", "127.0.0.1"]
        },
        "localFileSystem": "request",
        "ipc": {
            "enablePluginCommunication": True
        }
    }
}, indent=2)

PLUGIN_JS_SOURCE = r"""/**
 * The Entire World Tech Connector Bridge — Photoshop UXP Plugin
 * Starts a simple HTTP JSON server on localhost so the Studio can
 * execute ExtendScript / batchPlay / DOM calls.
 */

const { app, core, action, imaging } = require("photoshop");
const { entrypoints, storage, network } = require("uxp");
const fs = storage.localFileSystem;

const HOST = "127.0.0.1";
const PORT = 7061;
let server = null;

async function executeCode(jsCode) {
    try {
        // UXP cannot eval arbitrary JS safely, so we support a limited
        // command set sent as { "command": "...", "params": {...} }
        const cmd = JSON.parse(jsCode);
        return await dispatchCommand(cmd);
    } catch (e) {
        // Fallback: try as batchPlay descriptor JSON
        try {
            const descriptor = JSON.parse(jsCode);
            const result = await core.executeAsModal(
                async () => await action.batchPlay([descriptor], {}),
                { commandName: "Tech Connector Bridge" }
            );
            return { ok: true, result: JSON.stringify(result) };
        } catch (e2) {
            return { ok: false, error: String(e2) };
        }
    }
}

async function dispatchCommand(cmd) {
    const { command, params } = cmd;
    try {
        if (command === "document.path") {
            return { ok: true, result: app.activeDocument ? app.activeDocument.path : "No document open" };
        }
        if (command === "document.name") {
            return { ok: true, result: app.activeDocument ? app.activeDocument.name : "No document open" };
        }
        if (command === "layer.list") {
            const doc = app.activeDocument;
            if (!doc) return { ok: false, error: "No document open" };
            const names = doc.layers.map(l => l.name);
            return { ok: true, result: JSON.stringify(names) };
        }
        if (command === "selection.info") {
            const doc = app.activeDocument;
            if (!doc) return { ok: false, error: "No document open" };
            const sel = doc.selection;
            return { ok: true, result: sel ? JSON.stringify(sel.bounds) : "No selection" };
        }
        if (command === "document.info") {
            const doc = app.activeDocument;
            if (!doc) return { ok: false, error: "No document open" };
            return {
                ok: true,
                result: JSON.stringify({
                    name: doc.name,
                    path: doc.path,
                    width: doc.width,
                    height: doc.height,
                    resolution: doc.resolution,
                    colorMode: doc.mode,
                    layerCount: doc.layers.length
                })
            };
        }
        return { ok: false, error: `Unknown command: ${command}` };
    } catch (e) {
        return { ok: false, error: String(e) };
    }
}

async function startServer() {
    if (server) { console.log("Tech Connector Bridge already running."); return; }
    try {
        server = network.createServer();
        server.on("connection", (socket) => {
            let buf = "";
            socket.on("data", (data) => {
                buf += data;
                const headerEnd = buf.indexOf("\r\n\r\n");
                if (headerEnd < 0) return;
                const body = buf.slice(headerEnd + 4);
                const clMatch = buf.match(/Content-Length:\s*(\d+)/i);
                const cl = clMatch ? parseInt(clMatch[1]) : 0;
                if (body.length < cl) return;
                handleRequest(body.slice(0, cl)).then(resp => {
                    const bodyStr = JSON.stringify(resp);
                    const headers = [
                        "HTTP/1.1 200 OK",
                        "Content-Type: application/json",
                        `Content-Length: ${bodyStr.length}`,
                        "Connection: close",
                        "", ""
                    ].join("\r\n");
                    socket.write(headers + bodyStr);
                    socket.end();
                });
            });
        });
        await server.listen(PORT, HOST);
        console.log(`Tech Connector Bridge listening on ${HOST}:${PORT}`);
    } catch (e) {
        console.error("Tech Connector Bridge failed to start:", e);
        server = null;
    }
}

async function handleRequest(body) {
    try {
        const payload = JSON.parse(body);
        const code = payload.code || JSON.stringify(payload);
        return await executeCode(code);
    } catch (e) {
        return { ok: false, error: String(e) };
    }
}

entrypoints.setup({
    commands: {
        startBridge: { run: startServer }
    },
    panels: {
        bridgePanel: {
            show() {},
            create(event) {
                startServer();
            }
        }
    }
});
"""


class PhotoshopBridge:
    """Photoshop UXP plugin bridge via HTTP/JSON on localhost."""

    info = HostBridgeInfo(
        id="photoshop",
        display_name="Adobe Photoshop",
        protocol="http-json",
        default_port=7061,
        setup_script="bridges/photoshop/photoshop_bridge.py",
        supports_direct_execute=True,
        supports_mcp=False,
    )
    PORT_FILES = [
        str(APP_DIR / "photoshop_port.txt"),
        str(TOOLS_ROOT / "photoshop_port.txt"),
    ]
    DEFAULT_PORT = 7061
    SYS_PATHS = [
        str(TOOLS_ROOT),
        str(APP_ROOT),
    ]

    def find_port(self, host: str = "127.0.0.1") -> int | None:
        candidates = []

        for path in self.PORT_FILES:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    candidates.append(int(f.read().strip()))
            except Exception:
                pass

        env_port = os.environ.get("PHOTOSHOP_BRIDGE_PORT")
        if env_port:
            try:
                candidates.append(int(env_port))
            except Exception:
                pass

        candidates.append(self.DEFAULT_PORT)

        seen = set()
        for port in candidates:
            if port in seen:
                continue
            seen.add(port)
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(0.3)
                    if s.connect_ex((host, port)) == 0:
                        return port
            except Exception:
                pass
        return None

    def execute(self, code: str, timeout: float = 10) -> tuple[bool, str]:
        """Send a command dict or raw batchPlay JSON to the Photoshop UXP bridge."""
        port = self.find_port()
        if not port:
            return (
                False,
                "No Photoshop bridge found. Install the UXP plugin via Photoshop > Plugins > "
                "Load Unsigned Plugin, then open the Tech Connector Bridge panel.",
            )
        try:
            body = code.encode("utf-8")
            request = (
                f"POST / HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{port}\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(body)}\r\n"
                f"Connection: close\r\n\r\n"
            ).encode("utf-8") + body

            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(timeout)
                s.connect(("127.0.0.1", port))
                s.sendall(request)
                chunks = []
                while True:
                    chunk = s.recv(4096)
                    if not chunk:
                        break
                    chunks.append(chunk.decode("utf-8", errors="replace"))

            raw = "".join(chunks)
            # Strip HTTP headers
            if "\r\n\r\n" in raw:
                raw = raw.split("\r\n\r\n", 1)[1]

            raw = raw.strip()
            if not raw:
                return True, "Photoshop returned no output."

            try:
                parsed = json.loads(raw)
                result = parsed.get("result") or parsed.get("error") or raw
                ok = bool(parsed.get("ok", True)) and not bridge_output_has_error(result)
                return ok, str(result).strip() or "Photoshop returned no output."
            except Exception:
                return (False, raw) if bridge_output_has_error(raw) else (True, raw)
        except Exception as e:
            return False, str(e)

    def _command(self, command: str, params: dict | None = None) -> tuple[bool, str]:
        payload = json.dumps({"command": command, **(params or {})})
        return self.execute(payload)

    def get_current_file_code(self) -> str:
        return json.dumps({"command": "document.path"})

    def get_project_status_code(self) -> str:
        return json.dumps({"command": "document.info"})

    def get_scene_objects_code(self) -> str:
        return json.dumps({"command": "layer.list"})

    def get_selection_code(self) -> str:
        return json.dumps({"command": "selection.info"})

    def parse_input(self, text: str):
        try:
            data = json.loads(text)
            if "command" in data or "action" in data:
                return "command", data
        except Exception:
            pass
        return "execute", None


def plugin_dir_candidates() -> list[Path]:
    """Return candidate paths for the Photoshop UXP plugin directory."""
    base = Path(os.environ.get("USERPROFILE", ""))
    return [
        base / "AppData" / "Roaming" / "Adobe" / "UXP" / "Plugins" / "External" / PLUGIN_ID,
        base / "AppData" / "Roaming" / "Adobe" / "CEP" / "extensions" / PLUGIN_ID,
    ]


def default_plugin_dir() -> Path:
    candidates = plugin_dir_candidates()
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def plugin_needs_install(plugin_dir: Path) -> bool:
    target_js = Path(plugin_dir) / PLUGIN_FILENAME
    target_manifest = Path(plugin_dir) / PLUGIN_MANIFEST_FILENAME
    if not target_js.exists() or not target_manifest.exists():
        return True
    try:
        return target_js.read_text(encoding="utf-8") != PLUGIN_JS_SOURCE
    except Exception:
        return True


def install_to_plugin_dir(plugin_dir: Path, dry_run: bool = False) -> Path:
    plugin_dir = Path(plugin_dir)
    if not dry_run:
        plugin_dir.mkdir(parents=True, exist_ok=True)
        (plugin_dir / PLUGIN_FILENAME).write_text(PLUGIN_JS_SOURCE, encoding="utf-8")
        (plugin_dir / PLUGIN_MANIFEST_FILENAME).write_text(PLUGIN_MANIFEST, encoding="utf-8")
    return plugin_dir
