from __future__ import annotations

"""Direct Maya commandPort bridge."""

import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import socket
from tech_connector.bridges.error_detection import bridge_output_has_error
from tech_connector.models.constants import APP_ROOT, DEFAULT_MAYA_PORT, TOOLS_ROOT


def _captured_maya_output_has_error(output: str) -> bool:
    return bridge_output_has_error(output)


MAYA_SETUP_CODE = """import base64
import sys
import traceback

import maya.cmds as cmds
import maya.api.OpenMaya as om
import maya.api.OpenMayaUI as omui


def maya_execute_and_capture(encoded_payload):
    code = base64.b64decode(encoded_payload.encode("utf-8")).decode("utf-8")
    old_stdout = sys.stdout
    old_stderr = sys.stderr

    class Capture:
        def __init__(self):
            self.parts = []

        def write(self, value):
            self.parts.append(str(value))

        def flush(self):
            pass

    capture = Capture()
    sys.stdout = capture
    sys.stderr = capture

    try:
        exec(code, globals(), globals())
    except Exception:
        traceback.print_exc()
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr

    return "".join(capture.parts)


def start_command_port(port=7001):
    name = f":{port}"
    try:
        if cmds.commandPort(name, q=True):
            cmds.commandPort(name=name, close=True)
    except Exception:
        pass

    cmds.commandPort(name=name, sourceType="python", echoOutput=True, noreturn=False)
    print(f"The Entire World AI Maya commandPort running on {port}")


start_command_port(7001)
"""


from tech_connector.services.modular_provider_utils import DCCBridgeDelegateMixin


class MayaBridge(DCCBridgeDelegateMixin):
    """Deterministic Maya communication via commandPort."""

    def __init__(self):
        self.init_delegate("maya")
        self._auto_install_livelink_plugin()

    def _auto_install_livelink_plugin(self):
        try:
            from tech_connector.bridges.maya.maya_livelink_plugin import install_maya_livelink_plugin
            install_maya_livelink_plugin()
        except Exception:
            pass

    PORT_FILE = Path(
        os.environ.get(
            "MAYA_COMMAND_PORT_FILE",
            Path.home() / "temp" / "maya_port.txt",
        )
    ).expanduser()

    SYS_PATHS = [
        str(TOOLS_ROOT),
        str(APP_ROOT),
    ]

    def _candidate_ports(self) -> list[tuple[int, str]]:
        candidates: list[tuple[int, str]] = []
        env_port = os.environ.get("MAYA_COMMAND_PORT")
        if env_port:
            try:
                candidates.append((int(env_port), "env"))
            except Exception:
                pass

        try:
            port_text = self.PORT_FILE.read_text(encoding="utf-8").strip()
            if port_text:
                candidates.append((int(port_text), "file"))
        except Exception:
            pass

        try:
            scan_count = max(1, int(os.environ.get("MAYA_COMMAND_PORT_SCAN_COUNT", "10")))
        except Exception:
            scan_count = 10
        for offset in range(scan_count):
            candidates.append((DEFAULT_MAYA_PORT + offset, "scan"))
        return candidates

    def _is_port_open(self, host: str, port: int) -> bool:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(float(os.environ.get("MAYA_COMMAND_PORT_CONNECT_TIMEOUT", "0.05")))
                return s.connect_ex((host, port)) == 0
        except Exception:
            return False

    def _remove_stale_port_file(self, port: int) -> None:
        try:
            if self.PORT_FILE.read_text(encoding="utf-8").strip() == str(port):
                self.PORT_FILE.unlink(missing_ok=True)
        except Exception:
            pass

    def find_ports(self, host="127.0.0.1") -> list[int]:
        candidates: list[tuple[int, str]] = []
        stale_file_ports: list[int] = []
        seen = set()
        for port, source in self._candidate_ports():
            if port in seen:
                continue
            seen.add(port)
            candidates.append((port, source))
        open_ports: set[int] = set()
        max_workers = min(len(candidates), max(1, int(os.environ.get("MAYA_COMMAND_PORT_SCAN_WORKERS", "10"))))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self._is_port_open, host, port): (port, source)
                for port, source in candidates
            }
            for future in as_completed(futures):
                port, source = futures[future]
                is_open = False
                try:
                    is_open = bool(future.result())
                except Exception:
                    is_open = False
                if is_open:
                    open_ports.add(port)
                elif source == "file":
                    stale_file_ports.append(port)
        for port in stale_file_ports:
            self._remove_stale_port_file(port)
        return [port for port, _source in candidates if port in open_ports]

    def find_port(self, host="127.0.0.1"):
        stale_file_ports: list[int] = []
        seen = set()
        for port, source in self._candidate_ports():
            if port in seen:
                continue
            seen.add(port)
            if self._is_port_open(host, port):
                return port
            if source == "file":
                stale_file_ports.append(port)
        for port in stale_file_ports:
            self._remove_stale_port_file(port)
        return None

    def session_info(self, port: int | None = None, timeout: float = 3.0) -> dict:
        port = int(port or self.find_port() or 0)
        if not port:
            return {"ok": False, "error": "No Maya commandPort found."}
        code = """
import json
import os
import maya.cmds as cmds
print(json.dumps({
    "pid": os.getpid(),
    "version": cmds.about(version=True),
    "scene": cmds.file(q=True, sceneName=True),
    "selection": cmds.ls(selection=True) or [],
}))
"""
        ok, raw = self.execute_on_port(code, port=port, timeout=timeout)
        if not ok:
            return {"ok": False, "port": port, "error": raw}
        try:
            data = json.loads(str(raw or "{}"))
        except Exception:
            data = {"raw": raw}
        data.update({"ok": True, "port": port})
        return data

    def sessions(self, host="127.0.0.1") -> list[dict]:
        return [self.session_info(port=port) for port in self.find_ports(host=host)]

    def execute(self, code: str, timeout: float = 5) -> tuple[bool, str]:
        """
        Execute code against Maya's commandPort capture function.
        Returns (success, result_or_error_message).
        """
        port = self.find_port()
        if not port:
            return False, "No Maya commandPort found. Start Maya and run maya_bridge.py."
        return self.execute_on_port(code, port=port, timeout=timeout)

    def execute_on_port(self, code: str, port: int, timeout: float = 5) -> tuple[bool, str]:
        try:
            encoded = base64.b64encode(code.encode("utf-8")).decode("utf-8")
            payload = f"maya_execute_and_capture('{encoded}')\n"

            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(timeout)
                s.connect(("127.0.0.1", port))
                s.sendall(payload.encode("utf-8"))

                chunks = []
                while True:
                    data = s.recv(4096)
                    if not data:
                        break
                    chunk = data.decode("utf-8", errors="replace")
                    chunks.append(chunk)
                    if "\x00" in chunk:
                        break

            result = "".join(chunks).replace("\x00", "").strip()
            if not result:
                result = "Maya returned no output."
            if _captured_maya_output_has_error(result):
                return False, result
            return True, result
        except Exception as e:
            return False, str(e)

    def call_function(self, function_path: str, args=None, kwargs=None) -> tuple[bool, str]:
        args = args or []
        kwargs = kwargs or {}
        payload = {
            "function": function_path,
            "args": args,
            "kwargs": kwargs,
        }

        paths_repr = repr(self.SYS_PATHS)
        code = f"""
import sys, json, importlib, traceback
for p in {paths_repr}:
    if p not in sys.path:
        sys.path.append(p)

payload = {repr(payload)}
try:
    module_path, func_name = payload["function"].rsplit(".", 1)
    module = importlib.import_module(module_path)
    func = getattr(module, func_name)
    result = func(*payload.get("args", []), **payload.get("kwargs", {{}}))
    print(result)
except Exception:
    traceback.print_exc()
"""
        return self.execute(code)

    def get_selection_code(self) -> str:
        return "import maya.cmds as cmds\nprint(cmds.ls(sl=True))"

    def get_current_file_code(self) -> str:
        return "import maya.cmds as cmds\nprint(cmds.file(q=True, sceneName=True))"

    def get_scene_objects_code(self) -> str:
        return "import maya.cmds as cmds\nprint(cmds.ls(type='transform')[:500])"

    def get_scene_snapshot_code(
        self,
        *,
        selected_only: bool = False,
        meshes_only: bool = False,
        include_geometry: bool = True,
        limit: int = 500,
        max_vertices_per_object: int = 50000,
        max_faces_per_object: int = 50000,
    ) -> str:
        """Return Maya Python that prints isolated scene elements as JSON."""
        return f"""
import json
import maya.cmds as cmds

selected_only = {bool(selected_only)!r}
meshes_only = {bool(meshes_only)!r}
include_geometry = {bool(include_geometry)!r}
limit = int({int(limit)!r})
max_vertices_per_object = int({int(max_vertices_per_object)!r})
max_faces_per_object = int({int(max_faces_per_object)!r})

def _safe_float_list(values, fallback=None):
    try:
        return [float(v) for v in values]
    except Exception:
        return list(fallback or [])

def _node_visible(node):
    try:
        if not cmds.getAttr(node + ".visibility"):
            return False
    except Exception:
        pass
    try:
        parents = cmds.listRelatives(node, parent=True, fullPath=True) or []
        for parent in parents:
            if not _node_visible(parent):
                return False
    except Exception:
        pass
    return True

def _transform_from_shape(shape):
    parents = cmds.listRelatives(shape, parent=True, fullPath=True) or []
    return parents[0] if parents else shape

def _shape_types(transform):
    result = []
    for shape in cmds.listRelatives(transform, shapes=True, fullPath=True) or []:
        try:
            if cmds.getAttr(shape + ".intermediateObject"):
                continue
        except Exception:
            pass
        try:
            result.append(cmds.nodeType(shape))
        except Exception:
            pass
    return sorted(set(result))

def _mesh_shapes(transform):
    result = []
    for shape in cmds.listRelatives(transform, shapes=True, fullPath=True, type="mesh") or []:
        try:
            if cmds.getAttr(shape + ".intermediateObject"):
                continue
        except Exception:
            pass
        result.append(shape)
    return result

def _fallback_bbox(transform, size=1.0):
    try:
        t = _safe_float_list(cmds.xform(transform, q=True, ws=True, translation=True), [0, 0, 0])
    except Exception:
        t = [0, 0, 0]
    half = float(size) * 0.5
    return [t[0] - half, t[1] - half, t[2] - half, t[0] + half, t[1] + half, t[2] + half]

def _bbox_payload(transform, shape_types):
    try:
        bbox = _safe_float_list(cmds.exactWorldBoundingBox(transform), [])
    except Exception:
        bbox = []
    if len(bbox) == 6:
        extent = max(abs(bbox[3] - bbox[0]), abs(bbox[4] - bbox[1]), abs(bbox[5] - bbox[2]))
        if extent > 1.0e-5:
            return bbox
    node_type = cmds.nodeType(transform)
    lowered = " ".join([node_type] + list(shape_types)).lower()
    if any(token in lowered for token in ("joint", "follicle", "locator", "constraint", "ikhandle", "rigidbody", "light")):
        return _fallback_bbox(transform, 1.0)
    if any(token in lowered for token in ("nurbssurface", "nurbscurve")):
        return _fallback_bbox(transform, 2.0)
    return bbox

def _mesh_geometry_payload(transform):
    if not include_geometry:
        return None
    vertices = []
    faces = []
    shape_names = []
    for shape in _mesh_shapes(transform):
        try:
            vertex_count = int(cmds.polyEvaluate(shape, vertex=True) or 0)
            face_count = int(cmds.polyEvaluate(shape, face=True) or 0)
        except Exception:
            continue
        if vertex_count <= 0 or face_count <= 0:
            continue
        if vertex_count > max_vertices_per_object or face_count > max_faces_per_object:
            return {{
                "representation": "bounds",
                "reason": "mesh_too_large",
                "vertex_count": vertex_count,
                "face_count": face_count,
            }}
        try:
            flat_points = cmds.xform(shape + ".vtx[*]", q=True, ws=True, translation=True) or []
        except Exception:
            flat_points = []
        if len(flat_points) < vertex_count * 3:
            continue
        vertex_offset = len(vertices)
        for i in range(0, len(flat_points), 3):
            vertices.append([float(flat_points[i]), float(flat_points[i + 1]), float(flat_points[i + 2])])
        for face_index in range(face_count):
            try:
                lines = cmds.polyInfo(shape + ".f[%d]" % face_index, faceToVertex=True) or []
            except Exception:
                lines = []
            if not lines:
                continue
            text = str(lines[0])
            if ":" in text:
                text = text.split(":", 1)[1]
            indices = []
            for token in text.replace("\\n", " ").split():
                try:
                    indices.append(vertex_offset + int(token))
                except Exception:
                    pass
            if len(indices) >= 3:
                faces.append(indices)
        shape_names.append(shape)
    if not vertices or not faces:
        return None
    return {{
        "representation": "mesh",
        "vertices": vertices,
        "faces": faces,
        "shape_names": shape_names,
    }}

def _material_payload(transform):
    for shape in _mesh_shapes(transform):
        try:
            shading_groups = cmds.listConnections(shape, type="shadingEngine") or []
        except Exception:
            shading_groups = []
        for shading_group in shading_groups:
            try:
                materials = cmds.listConnections(shading_group + ".surfaceShader", source=True, destination=False) or []
            except Exception:
                materials = []
            for material in materials:
                for attr in ("baseColor", "color", "diffuseColor"):
                    try:
                        if cmds.attributeQuery(attr, node=material, exists=True):
                            value = cmds.getAttr(material + "." + attr)
                            if isinstance(value, list) and value:
                                value = value[0]
                            if isinstance(value, tuple) and len(value) >= 3:
                                return {{
                                    "name": material,
                                    "color": [float(value[0]), float(value[1]), float(value[2]), 1.0],
                                }}
                    except Exception:
                        pass
    return None

def _light_payload(transform, shape_types):
    light_shapes = []
    for shape in cmds.listRelatives(transform, shapes=True, fullPath=True) or []:
        try:
            if cmds.nodeType(shape) in ("pointLight", "spotLight", "directionalLight", "areaLight", "volumeLight", "ambientLight"):
                light_shapes.append(shape)
        except Exception:
            pass
    if not light_shapes:
        return None
    shape = light_shapes[0]
    try:
        color = cmds.getAttr(shape + ".color")[0]
    except Exception:
        color = (1.0, 1.0, 1.0)
    try:
        intensity = float(cmds.getAttr(shape + ".intensity"))
    except Exception:
        intensity = 1.0
    try:
        cone_angle = float(cmds.getAttr(shape + ".coneAngle")) if cmds.attributeQuery("coneAngle", node=shape, exists=True) else 40.0
    except Exception:
        cone_angle = 40.0
    return {{
        "kind": cmds.nodeType(shape),
        "shape": shape,
        "color": [float(color[0]), float(color[1]), float(color[2])],
        "intensity": intensity,
        "cone_angle": cone_angle,
    }}

def _camera_payload(camera_shape):
    transform = _transform_from_shape(camera_shape)
    try:
        matrix = _safe_float_list(cmds.xform(transform, q=True, ws=True, matrix=True), [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1])
    except Exception:
        matrix = []
    try:
        translation = _safe_float_list(cmds.xform(transform, q=True, ws=True, translation=True), [0, 0, 0])
    except Exception:
        translation = [0, 0, 0]
    try:
        rotation = _safe_float_list(cmds.xform(transform, q=True, ws=True, rotation=True), [0, 0, 0])
    except Exception:
        rotation = [0, 0, 0]
    return {{
        "native_id": transform,
        "name": transform.split("|")[-1],
        "type": "camera",
        "shape": camera_shape,
        "translation": translation,
        "rotation": rotation,
        "world_matrix": matrix,
        "focal_length_mm": float(cmds.getAttr(camera_shape + ".focalLength")),
        "near_clip": float(cmds.getAttr(camera_shape + ".nearClipPlane")),
        "far_clip": float(cmds.getAttr(camera_shape + ".farClipPlane")),
        "visible": _node_visible(transform),
    }}

if selected_only:
    selected = cmds.ls(selection=True, long=True) or []
    source_transforms = []
    for node in selected:
        if cmds.nodeType(node) in ("transform", "joint"):
            source_transforms.append(node)
        else:
            parent = _transform_from_shape(node)
            if parent:
                source_transforms.append(parent)
else:
    if meshes_only:
        source_transforms = sorted(set(_transform_from_shape(shape) for shape in (cmds.ls(type="mesh", long=True) or [])))
    else:
        source_transforms = []
        for node_type in ("transform", "joint"):
            source_transforms.extend(cmds.ls(type=node_type, long=True) or [])
        for shape_type in ("follicle", "nurbsSurface", "nurbsCurve", "locator", "pointLight", "spotLight", "directionalLight", "areaLight", "volumeLight", "ambientLight"):
            source_transforms.extend(_transform_from_shape(shape) for shape in (cmds.ls(type=shape_type, long=True) or []))
source_transforms = sorted(set(source_transforms))

objects = []
for transform in source_transforms[:limit]:
    try:
        shape_types = _shape_types(transform)
        if "camera" in shape_types:
            continue
        if meshes_only and "mesh" not in shape_types:
            continue
        if not _node_visible(transform):
            continue
        bbox = _bbox_payload(transform, shape_types)
        if len(bbox) != 6:
            continue
        translation = _safe_float_list(cmds.xform(transform, q=True, ws=True, translation=True), [0, 0, 0])
        rotation = _safe_float_list(cmds.xform(transform, q=True, ws=True, rotation=True), [0, 0, 0])
        scale = _safe_float_list(cmds.xform(transform, q=True, relative=True, scale=True), [1, 1, 1])
        item = {{
            "native_id": transform,
            "name": transform.split("|")[-1],
            "type": "mesh" if "mesh" in shape_types else (shape_types[0] if shape_types else cmds.nodeType(transform)),
            "shape_types": shape_types,
            "bbox": bbox,
            "translation": translation,
            "rotation": rotation,
            "scale": scale,
            "visible": True,
        }}
        if "mesh" in shape_types:
            material = _material_payload(transform)
            if material:
                item["material"] = material
            geometry = _mesh_geometry_payload(transform)
            if geometry:
                item["geometry"] = geometry
        light = _light_payload(transform, shape_types)
        if light:
            item["light"] = light
        objects.append(item)
    except Exception as exc:
        objects.append({{
            "native_id": transform,
            "name": transform.split("|")[-1],
            "type": "error",
            "error": str(exc),
        }})

cameras = []
for camera_shape in (cmds.ls(type="camera", long=True) or [])[:100]:
    try:
        cameras.append(_camera_payload(camera_shape))
    except Exception:
        pass

active_camera = ""
try:
    panel = cmds.getPanel(withFocus=True)
    if panel and cmds.getPanel(typeOf=panel) == "modelPanel":
        active_camera = cmds.modelPanel(panel, q=True, camera=True) or ""
except Exception:
    pass

payload = {{
    "schema": "tech_connector.maya.scene_snapshot.v1",
    "provider_id": "maya",
    "scene": cmds.file(q=True, sceneName=True) or "",
    "unit_linear": cmds.currentUnit(q=True, linear=True),
    "up_axis": cmds.upAxis(q=True, axis=True),
    "current_time": float(cmds.currentTime(q=True)),
    "objects": objects,
    "cameras": cameras,
    "active_camera": active_camera,
    "isolation": {{
        "selected_only": selected_only,
        "meshes_only": meshes_only,
        "include_geometry": include_geometry,
        "transparent_background": True,
        "excluded_categories": ["background", "grid", "hud", "manipulators"],
    }},
}}
print(json.dumps(payload))
"""

    def get_scene_snapshot(
        self,
        *,
        selected_only: bool = False,
        meshes_only: bool = False,
        include_geometry: bool = True,
        limit: int = 500,
        max_vertices_per_object: int = 50000,
        max_faces_per_object: int = 50000,
        timeout: float = 10.0,
    ) -> tuple[bool, dict | str]:
        """Query Maya for isolated scene objects, cameras, units, and bounds."""
        ok, raw = self.execute(
            self.get_scene_snapshot_code(
                selected_only=selected_only,
                meshes_only=meshes_only,
                include_geometry=include_geometry,
                limit=limit,
                max_vertices_per_object=max_vertices_per_object,
                max_faces_per_object=max_faces_per_object,
            ),
            timeout=timeout,
        )
        if not ok:
            return False, raw
        try:
            return True, json.loads(str(raw or "{}"))
        except Exception as exc:
            return False, f"Could not parse Maya scene snapshot JSON: {exc}\n{raw}"

    def parse_input(self, text: str):
        """
        Parse raw Python or JSON function payload.
        Returns ('execute', None) for raw code or ('function', payload_dict).
        """
        import json

        if text.startswith("{"):
            data = json.loads(text)
            return "function", data
        return "execute", None
