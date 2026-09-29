from __future__ import annotations

"""Direct Adobe Photoshop UXP plugin bridge."""

import base64
import json
import os
import socket
from pathlib import Path
from tech_connector.bridges.error_detection import bridge_output_has_error
from tech_connector.bridges.host_bridge import HostBridgeInfo
from tech_connector.bridges.session_discovery import (
    candidate_session_ports,
    discover_open_ports,
    parse_session_output,
)
from tech_connector.models.constants import APP_DIR, APP_ROOT, TOOLS_ROOT


# ---------------------------------------------------------------------------
# UXP plugin source (JavaScript — dropped into Photoshop's UXP plugin folder)
# ---------------------------------------------------------------------------

PLUGIN_ID = "com.theentireworld.aistudio.bridge"
PLUGIN_FILENAME = "index.js"
PLUGIN_MANIFEST_FILENAME = "manifest.json"

_DISABLED_MESSAGE = (
    "The Photoshop UXP bridge is disabled until entitlement-derived pairing is available. "
    "Source developers may opt in with the documented development-only flags."
)


def experimental_photoshop_bridge_allowed() -> bool:
    """Allow the unauthenticated prototype only in explicit, non-frozen development."""
    from tech_connector.services.licensing_startup_policy import (
        development_entitlement_bypass_allowed,
    )

    return (
        development_entitlement_bypass_allowed()
        and os.environ.get(
            "TECH_CONNECTOR_ENABLE_EXPERIMENTAL_PHOTOSHOP_BRIDGE",
            "",
        ).strip()
        == "1"
    )

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
            const nativePath = String(doc.path || "");
            const normalizedPath = nativePath.replace(/[\\\\/]+$/, "");
            const filePath = normalizedPath && normalizedPath.endsWith(String(doc.name || ""))
                ? normalizedPath
                : (normalizedPath && doc.name ? `${normalizedPath}/${doc.name}` : "");
            const bitDepth = String(doc.bitsPerChannel || "");
            const colorProfile = String(doc.colorProfileName || "");
            return {
                ok: true,
                result: JSON.stringify({
                    name: doc.name,
                    path: doc.path,
                    file_path: filePath,
                    width: doc.width,
                    height: doc.height,
                    resolution: doc.resolution,
                    colorMode: doc.mode,
                    bitDepth: bitDepth,
                    colorProfile: colorProfile,
                    layerCount: doc.layers.length,
                    parity_checks: {
                        "dimensions and bit depth": Number(doc.width) > 0 && Number(doc.height) > 0 && Boolean(bitDepth),
                        "layer order": Array.isArray(doc.layers) && doc.layers.length > 0,
                        "color profile": Boolean(colorProfile)
                    }
                })
            };
        }
        if (command === "batch_play") {
            if (!params || !params.descriptor) return { ok: false, error: "batch_play requires params.descriptor" };
            const result = await core.executeAsModal(
                async () => await action.batchPlay([params.descriptor], params.options || {}),
                { commandName: params.commandName || "Tech Connector BatchPlay" }
            );
            return { ok: true, result: JSON.stringify(result) };
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
        supports_direct_execute=False,
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
        ports = self.find_ports(host=host)
        return ports[0] if ports else None

    def find_ports(self, host: str = "127.0.0.1") -> list[int]:
        candidates = candidate_session_ports(
            "photoshop",
            port_files=self.PORT_FILES,
            environment_variable="PHOTOSHOP_BRIDGE_PORT",
            default_port=self.DEFAULT_PORT,
            scan_count_variable="PHOTOSHOP_PORT_SCAN_COUNT",
            default_scan_count=5,
        )
        return discover_open_ports(candidates, host=host)

    def execute(self, code: str, timeout: float = 10) -> tuple[bool, str]:
        """Send a command dict or raw batchPlay JSON to the Photoshop UXP bridge."""
        if not experimental_photoshop_bridge_allowed():
            return False, _DISABLED_MESSAGE
        port = self.find_port()
        if not port:
            return (
                False,
                "No Photoshop bridge found. Install the UXP plugin via Photoshop > Plugins > "
                "Load Unsigned Plugin, then open the Tech Connector Bridge panel.",
            )
        return self.execute_on_port(code, port=port, timeout=timeout)

    def execute_on_port(self, code: str, *, port: int, timeout: float = 10) -> tuple[bool, str]:
        if not experimental_photoshop_bridge_allowed():
            return False, _DISABLED_MESSAGE
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
                result_text = json.dumps(result) if isinstance(result, (dict, list)) else str(result)
                return ok, result_text.strip() or "Photoshop returned no output."
            except Exception:
                return (False, raw) if bridge_output_has_error(raw) else (True, raw)
        except Exception as e:
            return False, str(e)

    def _command(self, command: str, params: dict | None = None) -> tuple[bool, str]:
        payload = json.dumps({"command": command, "params": dict(params or {})})
        return self.execute(payload)

    def execute_command(self, command: str, params: dict | None = None) -> tuple[bool, str]:
        return self._command(command, params)

    def session_info(self, port: int | None = None, timeout: float = 3.0) -> dict:
        port = int(port or self.find_port() or 0)
        if not port:
            return {"ok": False, "error": "No Photoshop bridge found."}
        payload = json.dumps({"command": "document.info", "params": {}})
        ok, raw = self.execute_on_port(payload, port=port, timeout=timeout)
        data = parse_session_output(raw)
        data.update({"ok": bool(ok), "port": port})
        if not ok:
            data.setdefault("error", str(raw))
        return data

    def sessions(self, host: str = "127.0.0.1") -> list[dict]:
        return [self.session_info(port=port) for port in self.find_ports(host=host)]

    def get_current_file_code(self) -> str:
        return json.dumps({"command": "document.path"})

    def get_project_status_code(self) -> str:
        return json.dumps({"command": "document.info"})

    def get_scene_objects_code(self) -> str:
        return json.dumps({"command": "layer.list"})

    def get_selection_code(self) -> str:
        return json.dumps({"command": "selection.info"})

    def get_scene_snapshot(
        self,
        *,
        timeout: float = 10.0,
        port: int | None = None,
        **_kwargs,
    ) -> tuple[bool, object]:
        target_port = int(port or self.find_port() or 0)
        if not target_port:
            return False, "No Photoshop bridge found."

        def command(name: str) -> tuple[bool, object]:
            ok, raw = self.execute_on_port(
                json.dumps({"command": name, "params": {}}),
                port=target_port,
                timeout=timeout,
            )
            if not ok:
                return False, raw
            try:
                return True, json.loads(str(raw))
            except Exception:
                return True, raw

        ok, info = command("document.info")
        if not ok or not isinstance(info, dict):
            return False, info
        layers_ok, layers = command("layer.list")
        layer_names = list(layers) if layers_ok and isinstance(layers, list) else []
        scene = str(info.get("file_path") or info.get("path") or "")
        return True, {
            "schema": "tech_connector.photoshop.document_snapshot.v1",
            "provider_id": "photoshop",
            "scene": scene,
            "objects": [
                {
                    "native_id": f"layer:{index}:{name}",
                    "name": str(name),
                    "type": "image_layer",
                    "visible": True,
                }
                for index, name in enumerate(layer_names)
            ],
            "selection": [],
            "cameras": [],
            "image_document_state": {**info, "layers": layer_names},
            "isolation": {
                "include_geometry": False,
                "include_materials": False,
                "lookdev_only": True,
            },
        }

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
    if not dry_run and not experimental_photoshop_bridge_allowed():
        raise PermissionError(_DISABLED_MESSAGE)
    if not dry_run:
        plugin_dir.mkdir(parents=True, exist_ok=True)
        (plugin_dir / PLUGIN_FILENAME).write_text(PLUGIN_JS_SOURCE, encoding="utf-8")
        (plugin_dir / PLUGIN_MANIFEST_FILENAME).write_text(PLUGIN_MANIFEST, encoding="utf-8")
    return plugin_dir
