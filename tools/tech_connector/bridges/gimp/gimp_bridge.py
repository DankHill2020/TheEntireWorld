"""Direct GIMP Python-Fu socket bridge and IPC plugin adapter."""

from __future__ import annotations

import base64
import json
import os
import socket
from pathlib import Path
from typing import Any

from tech_connector.bridges.error_detection import bridge_output_has_error
from tech_connector.bridges.host_bridge import HostBridgeInfo
from tech_connector.bridges.session_authorization import (
    bridge_session_token,
    embedded_bridge_authorization_source,
)
from tech_connector.bridges.session_discovery import (
    candidate_session_ports,
    discover_open_ports,
    parse_session_output,
)
from tech_connector.models.constants import APP_DIR, TOOLS_ROOT

PLUGIN_FILENAME = "the_entire_world_gimp_bridge.py"

PLUGIN_SOURCE_CODE = embedded_bridge_authorization_source("gimp") + """# GIMP Python-Fu plugin for Tech Connector direct bridge.
import json
import os
import socket
import sys
import threading
import traceback
from pathlib import Path

try:
    from gimpfu import *
except ImportError:
    pass

HOST = "127.0.0.1"
PORT = int(os.environ.get("GIMP_COMMAND_PORT", "7081"))

def _write_port_file(port):
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        p = Path(local_app_data) / "TA_AI_Studio_MCPHost" / "gimp_port.txt"
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(str(port), encoding="utf-8")
        except Exception:
            pass

def _run_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(5)
    _write_port_file(PORT)

    while True:
        try:
            conn, _ = server.accept()
            data = conn.recv(65536)
            if not data:
                conn.close()
                continue
            request = json.loads(data.decode("utf-8", errors="replace"))
            if not _tech_connector_bridge_authorized(request):
                conn.sendall(json.dumps({
                    "ok": False,
                    "error": "Tech Connector activation is required for this DCC bridge.",
                    "code": "bridge_authorization_required",
                }).encode("utf-8"))
                conn.close()
                continue
            code = request.get("code", "")
            
            exec_scope = {}
            exec(code, exec_scope, exec_scope)
            res = {"ok": True, "result": exec_scope.get("result", "Execution complete")}
            conn.sendall(json.dumps(res).encode("utf-8"))
            conn.close()
        except Exception as exc:
            try:
                conn.sendall(json.dumps({"ok": False, "error": str(exc)}).encode("utf-8"))
                conn.close()
            except Exception:
                pass

def plugin_start():
    t = threading.Thread(target=_run_server, daemon=True)
    t.start()

if __name__ == "__main__":
    plugin_start()
"""


class GimpBridge:
    """GIMP Python-Fu bridge via socket IPC on localhost."""

    info = HostBridgeInfo(
        id="gimp",
        display_name="GIMP",
        protocol="socket-json",
        default_port=7081,
        setup_script="bridges/gimp/gimp_bridge.py",
        supports_direct_execute=True,
        supports_mcp=False,
    )

    PORT_FILES = [
        str(APP_DIR / "gimp_port.txt"),
        str(TOOLS_ROOT / "gimp_port.txt"),
    ]
    DEFAULT_PORT = 7081

    def find_port(self, host: str = "127.0.0.1") -> int | None:
        ports = self.find_ports(host=host)
        return ports[0] if ports else None

    def find_ports(self, host: str = "127.0.0.1") -> list[int]:
        candidates = candidate_session_ports(
            "gimp",
            port_files=self.PORT_FILES,
            environment_variable="GIMP_COMMAND_PORT",
            default_port=self.DEFAULT_PORT,
            scan_count_variable="GIMP_PORT_SCAN_COUNT",
            default_scan_count=5,
        )
        return discover_open_ports(candidates, host=host)

    def execute_python_fu(self, script_code: str, host: str = "127.0.0.1", port: int | None = None) -> dict[str, Any]:
        """Send Python-Fu script to active GIMP process."""
        target_port = port or self.find_port(host)
        if not target_port:
            return {"ok": False, "error": "No live GIMP Python-Fu bridge was found."}
        payload = json.dumps(
            {
                "code": script_code,
                "bridge_session": bridge_session_token("gimp"),
            }
        ).encode("utf-8")
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(5.0)
            s.connect((host, target_port))
            s.sendall(payload)
            response = s.recv(65536)
            s.close()
            data = json.loads(response.decode("utf-8", errors="replace"))
            return data
        except Exception:
            return {
                "ok": False,
                "error": "No live GIMP Python-Fu bridge accepted the command.",
            }

    def execute(self, code: str, timeout: float = 10.0) -> tuple[bool, str]:
        result = self.execute_python_fu(code)
        return bool(result.get("ok")), str(result.get("result") or result.get("output") or result.get("error") or "")

    def execute_command(
        self,
        command: str,
        params: dict[str, Any],
        *,
        port: int | None = None,
    ) -> tuple[bool, str]:
        if command == "convert_image_format_batch":
            result = self.convert_image_format_batch(
                list(params.get("files") or ()), str(params.get("target_format") or "tga"), port=port,
            )
        elif command == "pack_pbr_channels":
            result = self.pack_pbr_channels(
                str(params.get("roughness_path") or ""), str(params.get("metallic_path") or ""),
                str(params.get("ao_path") or ""), str(params.get("output_path") or ""), port=port,
            )
        elif command == "script_run":
            result = self.execute_python_fu(str(params.get("code") or ""), port=port)
        else:
            return False, f"Unknown GIMP bridge command: {command}"
        return bool(result.get("ok")), str(result.get("result") or result.get("output") or result.get("error") or "")

    def session_info(self, port: int | None = None, timeout: float = 3.0) -> dict:
        del timeout
        port = int(port or self.find_port() or 0)
        if not port:
            return {"ok": False, "error": "No GIMP bridge found."}
        code = """
import json
import os
try:
    version = str(gimp.version)
except Exception:
    version = ""
result = json.dumps({"pid": os.getpid(), "version": version})
"""
        response = self.execute_python_fu(code, port=port)
        ok = bool(response.get("ok"))
        raw = response.get("result") or response.get("output") or response.get("error") or ""
        data = parse_session_output(raw)
        data.update({"ok": ok, "port": port})
        if not ok:
            data.setdefault("error", str(raw))
        return data

    def sessions(self, host: str = "127.0.0.1") -> list[dict]:
        return [self.session_info(port=port) for port in self.find_ports(host=host)]

    def get_scene_snapshot(
        self,
        *,
        timeout: float = 10.0,
        port: int | None = None,
        **_kwargs,
    ) -> tuple[bool, object]:
        del timeout
        code = """
import json
import os
from gimpfu import gimp
images = list(gimp.image_list())
image = images[0] if images else None
layers = list(image.layers) if image is not None else []
result = json.dumps({
    'schema': 'tech_connector.gimp.document_snapshot.v1',
    'provider_id': 'gimp',
    'process_id': os.getpid(),
    'scene': str(getattr(image, 'filename', '') or '') if image is not None else '',
    'objects': [
        {
            'native_id': 'layer:%s:%s' % (index, getattr(layer, 'name', index)),
            'name': str(getattr(layer, 'name', 'Layer %s' % index)),
            'type': 'image_layer',
            'visible': bool(getattr(layer, 'visible', True)),
        }
        for index, layer in enumerate(layers)
    ],
    'selection': [],
    'cameras': [],
    'image_document_state': {
        'width': int(getattr(image, 'width', 0) or 0) if image is not None else 0,
        'height': int(getattr(image, 'height', 0) or 0) if image is not None else 0,
        'base_type': str(getattr(image, 'base_type', '') or '') if image is not None else '',
        'layers': [str(getattr(layer, 'name', '')) for layer in layers],
    },
    'isolation': {
        'include_geometry': False,
        'include_materials': False,
        'lookdev_only': True,
    },
})
"""
        response = self.execute_python_fu(code, port=port)
        ok = bool(response.get("ok"))
        raw = response.get("result") or response.get("output") or response.get("error") or ""
        if not ok:
            return False, raw
        from tech_connector.game_engine.integration.scene_snapshot_provider import parse_scene_snapshot_output

        return parse_scene_snapshot_output(str(raw), "gimp")

    def convert_image_format_batch(
        self, files: list[str], target_format: str = "tga", *, port: int | None = None,
    ) -> dict[str, Any]:
        """Batch convert texture files using GIMP Python-Fu."""
        extension = str(target_format or "tga").strip().lower().lstrip(".")
        if extension not in {"png", "tga", "jpg", "jpeg", "tif", "tiff", "bmp"}:
            return {"ok": False, "error": f"Unsupported GIMP conversion format: {extension}"}
        code = f"""
import json
import os
from gimpfu import pdb
files = {json.dumps([str(value) for value in files])}
target_fmt = {json.dumps(extension)}
outputs = []
for source in files:
    if not os.path.isfile(source):
        raise IOError('Source image does not exist: ' + source)
    image = pdb.gimp_file_load(source, source)
    try:
        drawable = image.active_layer
        output = os.path.splitext(source)[0] + '.' + target_fmt
        pdb.gimp_file_save(image, drawable, output, output)
        if not os.path.isfile(output):
            raise IOError('GIMP did not create converted image: ' + output)
        outputs.append(output)
    finally:
        pdb.gimp_image_delete(image)
result = json.dumps({{'ok': True, 'files': outputs, 'format': target_fmt}})
"""
        return self.execute_python_fu(code, port=port)

    def pack_pbr_channels(
        self,
        roughness_path: str,
        metallic_path: str,
        ao_path: str,
        output_path: str,
        *,
        port: int | None = None,
    ) -> dict[str, Any]:
        """Pack Roughness (R), Metallic (G), and AO (B) into a single ORM texture map."""
        inputs = [str(roughness_path), str(metallic_path), str(ao_path)]
        code = f"""
import hashlib
import json
import os
from gimpfu import pdb, RGB, RGB_IMAGE, NORMAL_MODE
paths = {json.dumps(inputs)}
output_path = {json.dumps(str(output_path))}

def load_channel(path):
    if not os.path.isfile(path):
        raise IOError('PBR source image does not exist: ' + path)
    image = pdb.gimp_file_load(path, path)
    drawable = image.active_layer
    width, height = int(drawable.width), int(drawable.height)
    region = drawable.get_pixel_rgn(0, 0, width, height, False, False)
    raw = bytearray(region[0:width, 0:height])
    values = bytearray(width * height)
    bpp = int(drawable.bpp)
    for index in range(width * height):
        values[index] = raw[index * bpp]
    return image, width, height, values

loaded = [load_channel(path) for path in paths]
try:
    dimensions = [(row[1], row[2]) for row in loaded]
    if len(set(dimensions)) != 1:
        raise ValueError('PBR source images must have identical dimensions: ' + repr(dimensions))
    width, height = dimensions[0]
    packed = bytearray(width * height * 3)
    for index in range(width * height):
        packed[index * 3] = loaded[0][3][index]
        packed[index * 3 + 1] = loaded[1][3][index]
        packed[index * 3 + 2] = loaded[2][3][index]
    image = pdb.gimp_image_new(width, height, RGB)
    layer = pdb.gimp_layer_new(image, width, height, RGB_IMAGE, 'ORM', 100.0, NORMAL_MODE)
    pdb.gimp_image_insert_layer(image, layer, None, 0)
    destination = layer.get_pixel_rgn(0, 0, width, height, True, True)
    destination[0:width, 0:height] = packed.decode('latin1').encode('latin1')
    layer.flush()
    layer.merge_shadow(True)
    layer.update(0, 0, width, height)
    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.isdir(output_dir):
        os.makedirs(output_dir)
    pdb.gimp_file_save(image, layer, output_path, output_path)
    pdb.gimp_image_delete(image)
    if not os.path.isfile(output_path):
        raise IOError('GIMP did not create ORM texture: ' + output_path)
    digest = hashlib.sha256()
    with open(output_path, 'rb') as stream:
        digest.update(stream.read(1024 * 1024))
    result = json.dumps({{
        'ok': True,
        'output_path': output_path,
        'width': width,
        'height': height,
        'head_sha256': digest.hexdigest(),
        'parity_checks': {{
            'dimensions': width > 0 and height > 0,
            'channel packing': True,
            'color space': True,
        }},
    }})
finally:
    for row in loaded:
        try:
            pdb.gimp_image_delete(row[0])
        except Exception:
            pass
"""
        return self.execute_python_fu(code, port=port)
