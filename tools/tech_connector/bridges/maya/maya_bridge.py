from __future__ import annotations

"""Direct Maya authenticated JSON socket bridge."""

import base64
import array
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import socket
import tempfile
import time
import zlib
from tech_connector.bridges.error_detection import bridge_output_has_error
from tech_connector.bridges.host_bridge import HostBridgeInfo
from tech_connector.bridges.session_preferences import preferred_session_port
from tech_connector.bridges.session_authorization import bridge_session_token
from tech_connector.models.constants import APP_ROOT, DEFAULT_MAYA_PORT, TOOLS_ROOT
from tech_connector.game_engine.deformation.deformation_contract import (
    normalize_deformation_binding,
    normalize_deformation_frame,
)
from tech_connector.game_engine.scene.scene_delta_contract import normalize_frame_delta
from tech_connector.game_engine.authoring.rig_topology_contract import normalize_rig_topology


def _captured_maya_output_has_error(output: str) -> bool:
    return bridge_output_has_error(output)


def decode_maya_snapshot_geometry(snapshot: dict) -> dict:
    """Decode compact animated vertex payloads outside Maya's main thread."""
    for obj in snapshot.get("objects") or []:
        geometry = obj.get("geometry") if isinstance(obj, dict) else None
        if not isinstance(geometry, dict) or geometry.get("vertex_encoding") not in {"f32-base64", "f32-zlib-base64"}:
            continue
        encoding = geometry.get("vertex_encoding")
        encoded_vertices = geometry.pop(
            "vertices_f32_base64" if encoding == "f32-base64" else "vertices_f32_zlib_base64",
            "",
        )
        packed = array.array("f")
        raw_vertices = base64.b64decode(encoded_vertices.encode("ascii"))
        packed.frombytes(zlib.decompress(raw_vertices) if encoding == "f32-zlib-base64" else raw_vertices)
        geometry["vertices_f32"] = packed
    return snapshot


from tech_connector.services.modular_provider_utils import DCCBridgeDelegateMixin


_MAX_BRIDGE_RESPONSE_BYTES = 32 * 1024 * 1024


class MayaBridge(DCCBridgeDelegateMixin):
    """Deterministic Maya communication via an authenticated localhost socket."""

    info = HostBridgeInfo(
        id="maya",
        display_name="Maya",
        protocol="socket-json",
        default_port=DEFAULT_MAYA_PORT,
        setup_script="installers/maya_command_port_setup.py",
        supports_direct_execute=True,
        supports_mcp=False,
    )

    def __init__(self):
        self.init_delegate("maya")
        if os.environ.get("TECH_CONNECTOR_AUTO_INSTALL_MAYA_BRIDGE", "").strip() == "1":
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
        preferred_port = None if "PORT_FILE" in self.__dict__ else preferred_session_port("maya")
        if preferred_port:
            candidates.append((preferred_port, "preferred"))
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
        candidate_ports: list[int] = []
        sources_by_port: dict[int, set[str]] = {}
        stale_file_ports: list[int] = []
        for port, source in self._candidate_ports():
            if port not in sources_by_port:
                candidate_ports.append(port)
                sources_by_port[port] = set()
            sources_by_port[port].add(source)
        open_ports: set[int] = set()
        max_workers = min(len(candidate_ports), max(1, int(os.environ.get("MAYA_COMMAND_PORT_SCAN_WORKERS", "10"))))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self._is_port_open, host, port): port
                for port in candidate_ports
            }
            for future in as_completed(futures):
                port = futures[future]
                is_open = False
                try:
                    is_open = bool(future.result())
                except Exception:
                    is_open = False
                if is_open:
                    open_ports.add(port)
                elif "file" in sources_by_port.get(port, set()):
                    stale_file_ports.append(port)
        for port in stale_file_ports:
            self._remove_stale_port_file(port)
        return [port for port in candidate_ports if port in open_ports]

    def find_port(self, host="127.0.0.1"):
        stale_file_ports: list[int] = []
        checked_ports: dict[int, bool] = {}
        for port, source in self._candidate_ports():
            if port in checked_ports:
                if source == "file" and not checked_ports[port]:
                    stale_file_ports.append(port)
                continue
            is_open = self._is_port_open(host, port)
            checked_ports[port] = is_open
            if is_open:
                for stale_port in stale_file_ports:
                    self._remove_stale_port_file(stale_port)
                return port
            if source == "file":
                stale_file_ports.append(port)
        for port in stale_file_ports:
            self._remove_stale_port_file(port)
        return None

    def session_info(self, port: int | None = None, timeout: float = 3.0) -> dict:
        port = int(port or self.find_port() or 0)
        if not port:
            return {"ok": False, "error": "No authenticated Maya bridge found."}
        code = """
import json
import os
import maya.cmds as cmds
scene = cmds.file(q=True, sceneName=True) or ""
focused_panel = cmds.getPanel(withFocus=True) or ""
camera = ""
viewports = []
for panel in cmds.getPanel(type="modelPanel") or []:
    try:
        if not cmds.modelPanel(panel, exists=True):
            continue
        panel_camera = cmds.modelPanel(panel, q=True, camera=True) or ""
        active_view = bool(cmds.modelEditor(panel, q=True, activeView=True))
        visible = bool(cmds.control(panel, q=True, visible=True))
        viewports.append({
            "panel": panel,
            "camera": panel_camera,
            "active": active_view,
            "visible": visible,
        })
        if active_view and panel_camera:
            camera = panel_camera
    except Exception:
        continue
if not camera:
    focused_viewport = next((row for row in viewports if row["panel"] == focused_panel), None)
    camera = focused_viewport["camera"] if focused_viewport else ""
if not camera:
    visible_viewport = next((row for row in viewports if row["visible"] and row["camera"]), None)
    camera = visible_viewport["camera"] if visible_viewport else ""
time_unit = cmds.currentUnit(q=True, time=True)
fps_by_unit = {
    "game": 15.0, "film": 24.0, "pal": 25.0, "ntsc": 30.0,
    "show": 48.0, "palf": 50.0, "ntscf": 60.0,
}
try:
    fps = float(time_unit[:-3]) if str(time_unit).endswith("fps") else fps_by_unit.get(time_unit)
except Exception:
    fps = None
pid = os.getpid()
print(json.dumps({
    "session_id": "maya:%s:%s" % (pid, scene or "untitled"),
    "bridge_bootstrap_version": str(globals().get("TECH_CONNECTOR_MAYA_BRIDGE_VERSION", "legacy")),
    "bridge_bootstrap_source": str(globals().get("TECH_CONNECTOR_MAYA_BRIDGE_BOOT_SOURCE", "")),
    "bridge_capture_installed": callable(globals().get("maya_execute_and_capture")),
    "pid": pid,
    "version": cmds.about(version=True),
    "scene": scene,
    "scene_modified": bool(cmds.file(q=True, modified=True)),
    "scene_mtime": os.path.getmtime(scene) if scene and os.path.isfile(scene) else None,
    "workspace": cmds.workspace(q=True, rootDirectory=True),
    "selection": cmds.ls(selection=True) or [],
    "focused_panel": focused_panel,
    "camera": camera,
    "viewports": viewports,
    "timeline": {
        "current": float(cmds.currentTime(q=True)),
        "playback_min": float(cmds.playbackOptions(q=True, minTime=True)),
        "playback_max": float(cmds.playbackOptions(q=True, maxTime=True)),
        "animation_start": float(cmds.playbackOptions(q=True, animationStartTime=True)),
        "animation_end": float(cmds.playbackOptions(q=True, animationEndTime=True)),
        "time_unit": time_unit,
        "fps": fps,
        "playing": bool(cmds.play(q=True, state=True)),
    },
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
        Execute code against Maya's authenticated JSON bridge.
        Returns (success, result_or_error_message).
        """
        port = self.find_port()
        if not port:
            return False, "No authenticated Maya bridge found. Start Maya and update its Tech Connector bridge."
        return self.execute_on_port(code, port=port, timeout=timeout)

    def execute_on_port(
        self,
        code: str,
        port: int,
        timeout: float = 5,
        cancel_event=None,
    ) -> tuple[bool, str]:
        try:
            if cancel_event is not None and cancel_event.is_set():
                return False, "Maya command canceled."
            encoded = base64.b64encode(code.encode("utf-8")).decode("utf-8")
            payload = json.dumps(
                {
                    "code_b64": encoded,
                    "bridge_session": bridge_session_token("maya"),
                }
            ) + "\n"
            deadline = time.monotonic() + max(0.05, float(timeout))

            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(min(1.0, max(0.05, float(timeout))))
                s.connect(("127.0.0.1", port))
                s.sendall(payload.encode("utf-8"))

                chunks: list[bytes] = []
                response_bytes = 0
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        return False, "Maya command canceled."
                    remaining = deadline - time.monotonic()
                    if remaining <= 0.0:
                        return False, f"Maya command timed out after {float(timeout):g} seconds."
                    s.settimeout(min(0.25, remaining))
                    try:
                        data = s.recv(262144)
                    except socket.timeout:
                        continue
                    if not data:
                        break
                    chunks.append(data)
                    response_bytes += len(data)
                    if response_bytes > _MAX_BRIDGE_RESPONSE_BYTES:
                        return False, "Maya bridge response exceeded the 32 MiB wire limit."
                    if b"\n" in data:
                        break

            raw = b"".join(chunks).decode("utf-8", errors="replace").strip()
            if not raw:
                return False, "Maya bridge returned no response."
            response = json.loads(raw)
            result = str(response.get("result") or response.get("error") or "").strip()
            if not response.get("ok"):
                return False, result or "Maya bridge request failed."
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

    def get_viewport_capture_metadata(
        self,
        *,
        port: int | None = None,
        timeout: float = 3.0,
    ) -> tuple[bool, dict | str]:
        code = """
import json
import maya.cmds as cmds
import maya.OpenMayaUI as omui

panel = cmds.getPanel(withFocus=True)
if not panel or cmds.getPanel(typeOf=panel) != "modelPanel":
    visible = cmds.getPanel(visiblePanels=True) or []
    panel = next((name for name in visible if cmds.getPanel(typeOf=name) == "modelPanel"), "")
if not panel:
    raise RuntimeError("No visible Maya modelPanel was found.")
pointer = omui.MQtUtil.findControl(panel)
if not pointer:
    raise RuntimeError("Maya modelPanel has no Qt control pointer: " + panel)
try:
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QWidget
    from shiboken6 import wrapInstance
except Exception:
    from PySide2.QtCore import QPoint
    from PySide2.QtWidgets import QWidget
    from shiboken2 import wrapInstance
widget = wrapInstance(int(pointer), QWidget)
window = widget.window()
frame = window.frameGeometry()
top_left = widget.mapToGlobal(QPoint(0, 0))
width = max(1, int(frame.width()))
height = max(1, int(frame.height()))
payload = {
    "panel": panel,
    "window_title": window.windowTitle(),
    "viewport_rect": [
        max(0.0, min(1.0, float(top_left.x() - frame.x()) / width)),
        max(0.0, min(1.0, float(top_left.y() - frame.y()) / height)),
        max(0.0, min(1.0, float(widget.width()) / width)),
        max(0.0, min(1.0, float(widget.height()) / height)),
    ],
}
print(json.dumps(payload))
"""
        target_port = int(port or self.find_port() or 0)
        if not target_port:
            return False, "No authenticated Maya bridge found for viewport capture metadata."
        ok, raw = self.execute_on_port(code, port=target_port, timeout=timeout)
        if not ok:
            return False, raw
        try:
            return True, json.loads(str(raw or "{}"))
        except Exception as exc:
            return False, f"Could not parse Maya viewport capture metadata: {exc}\n{raw}"

    def get_scene_snapshot_code(
        self,
        *,
        selected_only: bool = False,
        meshes_only: bool = False,
        include_geometry: bool = True,
        include_materials: bool = True,
        include_cameras: bool = True,
        include_faces: bool = True,
        target_native_ids: list[str] | tuple[str, ...] | None = None,
        limit: int = 500,
        max_vertices_per_object: int = 50000,
        max_faces_per_object: int = 50000,
        sample_frame: int | float | None = None,
        fast_sample: bool = False,
        suspend_refresh: bool = False,
        cancel_event=None,
    ) -> str:
        """Return Maya Python that prints isolated scene elements as JSON."""
        target_native_ids_json = json.dumps([str(item) for item in (target_native_ids or [])])
        return f"""
import array
import base64
import json
import maya.cmds as cmds
import maya.api.OpenMaya as om
import os
import zlib

selected_only = {bool(selected_only)!r}
meshes_only = {bool(meshes_only)!r}
include_geometry = {bool(include_geometry)!r}
include_materials = {bool(include_materials)!r}
include_cameras = {bool(include_cameras)!r}
target_native_ids = json.loads({target_native_ids_json!r})
include_faces = {bool(include_faces)!r}
limit = int({int(limit)!r})
max_vertices_per_object = int({int(max_vertices_per_object)!r})
max_faces_per_object = int({int(max_faces_per_object)!r})
sample_frame = {None if sample_frame is None else float(sample_frame)!r}
fast_sample = {bool(fast_sample)!r}
suspend_refresh = {bool(suspend_refresh)!r}

if sample_frame is not None:
    refresh_was_suspended = False
    if suspend_refresh:
        try:
            cmds.refresh(suspend=True)
            refresh_was_suspended = True
        except Exception:
            pass
    try:
        cmds.currentTime(sample_frame, edit=True, update=True)
    finally:
        if refresh_was_suspended:
            try:
                cmds.refresh(suspend=False)
            except Exception:
                pass

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
    node_type = cmds.nodeType(transform)
    lowered = " ".join([node_type] + list(shape_types)).lower()
    if not shape_types:
        return _fallback_bbox(transform, 1.0)
    if any(token in lowered for token in ("joint", "follicle", "constraint", "ikhandle", "rigidbody", "light")):
        return _fallback_bbox(transform, 1.0)
    try:
        bbox = _safe_float_list(cmds.exactWorldBoundingBox(transform), [])
    except Exception:
        bbox = []
    if len(bbox) == 6:
        valid_bounds = (
            all(abs(float(value)) < 1.0e12 for value in bbox)
            and float(bbox[3]) >= float(bbox[0])
            and float(bbox[4]) >= float(bbox[1])
            and float(bbox[5]) >= float(bbox[2])
        )
        extent = max(abs(bbox[3] - bbox[0]), abs(bbox[4] - bbox[1]), abs(bbox[5] - bbox[2])) if valid_bounds else 0.0
        if valid_bounds and extent > 1.0e-5:
            return bbox
    if any(token in lowered for token in ("locator",)):
        return _fallback_bbox(transform, 1.0)
    if any(token in lowered for token in ("nurbssurface", "nurbscurve")):
        return _fallback_bbox(transform, 2.0)
    return bbox

def _mesh_geometry_payload(transform):
    if not include_geometry:
        return None
    vertices = []
    packed_vertices = array.array("f") if fast_sample else None
    sampled_vertex_count = 0
    bbox_min = [float("inf"), float("inf"), float("inf")]
    bbox_max = [float("-inf"), float("-inf"), float("-inf")]
    faces = []
    uvs = []
    face_uv_indices = []
    shape_names = []
    for shape in _mesh_shapes(transform):
        try:
            selection = om.MSelectionList()
            selection.add(shape)
            dag_path = selection.getDagPath(0)
            mesh_fn = om.MFnMesh(dag_path)
            vertex_count = int(mesh_fn.numVertices)
            face_count = int(mesh_fn.numPolygons)
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
            points = mesh_fn.getPoints(om.MSpace.kWorld)
        except Exception:
            points = []
        if len(points) < vertex_count:
            continue
        vertex_offset = len(vertices)
        for point in points:
            coordinates = (float(point.x), float(point.y), float(point.z))
            sampled_vertex_count += 1
            for axis in range(3):
                bbox_min[axis] = min(bbox_min[axis], coordinates[axis])
                bbox_max[axis] = max(bbox_max[axis], coordinates[axis])
            if fast_sample:
                packed_vertices.extend(coordinates)
            else:
                vertices.append(list(coordinates))
        if include_faces:
            try:
                polygon_counts, polygon_connects = mesh_fn.getVertices()
            except Exception:
                polygon_counts, polygon_connects = [], []
            shape_uv_offset = len(uvs)
            try:
                uv_set = mesh_fn.currentUVSetName()
                u_values, v_values = mesh_fn.getUVs(uv_set)
                assigned_uv_counts, assigned_uv_ids = mesh_fn.getAssignedUVs(uv_set)
                uvs.extend([[float(u), float(v)] for u, v in zip(u_values, v_values)])
            except Exception:
                assigned_uv_counts, assigned_uv_ids = [], []
            cursor = 0
            uv_cursor = 0
            for polygon_index, count in enumerate(polygon_counts):
                count = int(count)
                indices = [
                    vertex_offset + int(polygon_connects[cursor + offset])
                    for offset in range(count)
                    if cursor + offset < len(polygon_connects)
                ]
                cursor += count
                if len(indices) >= 3:
                    faces.append(indices)
                    assigned_count = int(assigned_uv_counts[polygon_index]) if polygon_index < len(assigned_uv_counts) else 0
                    if assigned_count == count and uv_cursor + assigned_count <= len(assigned_uv_ids):
                        face_uv_indices.append([
                            shape_uv_offset + int(assigned_uv_ids[uv_cursor + offset])
                            for offset in range(assigned_count)
                        ])
                    else:
                        face_uv_indices.append([-1 for _index in indices])
                    uv_cursor += max(0, assigned_count)
        shape_names.append(shape)
    if sampled_vertex_count <= 0 or (include_faces and not faces):
        return None
    bbox = [bbox_min[0], bbox_min[1], bbox_min[2], bbox_max[0], bbox_max[1], bbox_max[2]]
    if fast_sample:
        return {{
            "representation": "mesh",
            "vertices_f32_base64": base64.b64encode(packed_vertices.tobytes()).decode("ascii"),
            "vertex_encoding": "f32-base64",
            "vertex_count": sampled_vertex_count,
            "faces": [],
            "topology_included": False,
            "shape_names": shape_names,
            "bbox": bbox,
        }}
    return {{
        "representation": "mesh",
        "vertices": vertices,
        "faces": faces,
        "uvs": uvs,
        "face_uv_indices": face_uv_indices,
        "topology_included": bool(include_faces),
        "shape_names": shape_names,
        "bbox": bbox,
    }}

def _material_payload(transform):
    collected_materials = {{}}
    material_assignments = []
    face_offset = 0
    for shape in _mesh_shapes(transform):
        shading_groups = []
        faces_by_shading_group = {{}}
        shape_face_count = 0
        try:
            current_uv_sets = cmds.polyUVSet(shape, query=True, currentUVSet=True) or []
            active_uv_set = str(current_uv_sets[0]) if current_uv_sets else ""
        except Exception:
            active_uv_set = ""
        try:
            selection = om.MSelectionList()
            selection.add(shape)
            dag_path = selection.getDagPath(0)
            mesh_fn = om.MFnMesh(dag_path)
            shape_face_count = int(mesh_fn.numPolygons)
            shader_objects, face_shader_indices = mesh_fn.getConnectedShaders(dag_path.instanceNumber())
            shader_counts = [0 for _shader in shader_objects]
            for shader_index in face_shader_indices:
                if 0 <= int(shader_index) < len(shader_counts):
                    shader_counts[int(shader_index)] += 1
            for face_index, shader_index in enumerate(face_shader_indices):
                index = int(shader_index)
                if 0 <= index < len(shader_objects):
                    shading_group_name = om.MFnDependencyNode(shader_objects[index]).name()
                    faces_by_shading_group.setdefault(shading_group_name, []).append(face_offset + int(face_index))
            shading_groups = [
                om.MFnDependencyNode(shader_objects[index]).name()
                for index in sorted(range(len(shader_objects)), key=lambda item: shader_counts[item], reverse=True)
            ]
        except Exception:
            shading_groups = []
        if not shading_groups:
            try:
                shading_groups = cmds.listConnections(shape, type="shadingEngine") or []
            except Exception:
                shading_groups = []
        shading_groups = sorted(
            dict.fromkeys(shading_groups),
            key=lambda name: str(name).lower() in {"initialshadinggroup", "initialparticlese"},
        )
        for shading_group in shading_groups:
            try:
                materials = cmds.listConnections(shading_group + ".surfaceShader", source=True, destination=False) or []
            except Exception:
                materials = []
            for material in materials:
                result = {{
                    "name": material,
                    "source_material_id": material,
                    "shader_type": cmds.nodeType(material),
                    "color": [0.5, 0.5, 0.5, 1.0],
                    "roughness": 0.5,
                    "metalness": 0.0,
                    "specular": 0.5,
                    "opacity": 1.0,
                    "emission_color": [0.0, 0.0, 0.0],
                    "texture_paths": {{}},
                }}
                for attr in ("baseColor", "color", "diffuseColor"):
                    try:
                        if cmds.attributeQuery(attr, node=material, exists=True):
                            value = cmds.getAttr(material + "." + attr)
                            if isinstance(value, list) and value:
                                value = value[0]
                            if isinstance(value, tuple) and len(value) >= 3:
                                result["color"] = [float(value[0]), float(value[1]), float(value[2]), 1.0]
                                break
                    except Exception:
                        pass
                for result_key, attrs in (
                    ("roughness", ("specularRoughness", "roughness")),
                    ("metalness", ("metalness", "metallic")),
                    ("specular", ("specular", "specularWeight")),
                ):
                    for attr in attrs:
                        try:
                            if cmds.attributeQuery(attr, node=material, exists=True):
                                result[result_key] = float(cmds.getAttr(material + "." + attr))
                                break
                        except Exception:
                            pass
                for attr in ("opacity", "transparency"):
                    try:
                        if not cmds.attributeQuery(attr, node=material, exists=True):
                            continue
                        value = cmds.getAttr(material + "." + attr)
                        if isinstance(value, list) and value:
                            value = value[0]
                        if isinstance(value, tuple):
                            channel = sum(float(component) for component in value[:3]) / 3.0
                        else:
                            channel = float(value)
                        result["opacity"] = 1.0 - channel if attr == "transparency" else channel
                        break
                    except Exception:
                        pass
                for attr in ("emissionColor", "incandescence"):
                    try:
                        if not cmds.attributeQuery(attr, node=material, exists=True):
                            continue
                        value = cmds.getAttr(material + "." + attr)
                        if isinstance(value, list) and value:
                            value = value[0]
                        if isinstance(value, tuple) and len(value) >= 3:
                            result["emission_color"] = [float(value[0]), float(value[1]), float(value[2])]
                            break
                    except Exception:
                        pass
                for slot, attrs in (
                    ("base_color", ("baseColor", "color", "diffuseColor")),
                    ("normal", ("normalCamera",)),
                    ("roughness", ("specularRoughness", "roughness")),
                    ("metalness", ("metalness", "metallic")),
                    ("emission", ("emissionColor", "incandescence")),
                ):
                    for attr in attrs:
                        try:
                            if not cmds.attributeQuery(attr, node=material, exists=True):
                                continue
                            file_nodes = cmds.listConnections(
                                material + "." + attr,
                                source=True,
                                destination=False,
                                type="file",
                            ) or []
                            if file_nodes:
                                path = cmds.getAttr(file_nodes[0] + ".fileTextureName") or ""
                                if path:
                                    try:
                                        color_space = str(cmds.getAttr(file_nodes[0] + ".colorSpace") or "")
                                    except Exception:
                                        color_space = ""
                                    result["texture_paths"][slot] = {{
                                        "path": path,
                                        "color_space": color_space,
                                        "uv_set": active_uv_set or "st",
                                    }}
                                    break
                        except Exception:
                            pass
                if material not in collected_materials:
                    collected_materials[material] = result
                material_assignments.append({{
                    "material_id": material,
                    "slot_index": len(material_assignments),
                    "face_indices": list(faces_by_shading_group.get(shading_group) or []),
                    "uv_set": active_uv_set,
                    "shape_native_id": shape,
                }})
        face_offset += shape_face_count
    materials = list(collected_materials.values())
    if not materials:
        return None
    return {{
        "primary": materials[0],
        "materials": materials,
        "assignments": material_assignments,
    }}

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
    horizontal_aperture = max(1.0e-6, float(cmds.getAttr(camera_shape + ".horizontalFilmAperture") or 1.41732))
    vertical_aperture = max(1.0e-6, float(cmds.getAttr(camera_shape + ".verticalFilmAperture") or 0.94488))
    try:
        aspect_ratio = max(0.01, float(cmds.getAttr("defaultResolution.deviceAspectRatio")))
    except Exception:
        width = max(1.0, float(cmds.getAttr("defaultResolution.width") or 1920.0))
        height = max(1.0, float(cmds.getAttr("defaultResolution.height") or 1080.0))
        pixel_aspect = max(0.01, float(cmds.getAttr("defaultResolution.pixelAspect") or 1.0))
        aspect_ratio = width * pixel_aspect / height
    return {{
        "native_id": transform,
        "name": transform.split("|")[-1],
        "type": "camera",
        "shape": camera_shape,
        "translation": translation,
        "rotation": rotation,
        "world_matrix": matrix,
        "focal_length_mm": float(cmds.getAttr(camera_shape + ".focalLength")),
        "aspect_ratio": aspect_ratio,
        "film_aspect_ratio": horizontal_aperture / vertical_aperture,
        "film_fit": int(cmds.getAttr(camera_shape + ".filmFit") or 0),
        "near_clip": float(cmds.getAttr(camera_shape + ".nearClipPlane")),
        "far_clip": float(cmds.getAttr(camera_shape + ".farClipPlane")),
        "visible": _node_visible(transform),
    }}

def _reference_payload(node):
    try:
        if not cmds.referenceQuery(node, isNodeReferenced=True):
            return None
        reference_node = str(cmds.referenceQuery(node, referenceNode=True) or "")
        source_path = str(cmds.referenceQuery(node, filename=True, withoutCopyNumber=True) or "")
        source_path_with_copy = str(cmds.referenceQuery(node, filename=True, withoutCopyNumber=False) or source_path)
        try:
            namespace = str(cmds.referenceQuery(node, namespace=True) or "")
        except Exception:
            namespace = ""
        try:
            loaded = bool(cmds.referenceQuery(reference_node, isLoaded=True))
        except Exception:
            loaded = True
        return {{
            "source_path": source_path,
            "source_path_with_copy_number": source_path_with_copy,
            "reference_node": reference_node,
            "namespace": namespace,
            "loaded": loaded,
        }}
    except Exception:
        return None

if target_native_ids:
    source_transforms = []
    for node in target_native_ids:
        if not node or not cmds.objExists(node):
            continue
        if cmds.nodeType(node) in ("transform", "joint"):
            source_transforms.append(node)
        else:
            parent = _transform_from_shape(node)
            if parent:
                source_transforms.append(parent)
elif selected_only:
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
        if not fast_sample and not _node_visible(transform):
            continue
        if fast_sample:
            item = {{
                "native_id": transform,
                "name": transform.split("|")[-1],
                "type": "mesh" if "mesh" in shape_types else (shape_types[0] if shape_types else cmds.nodeType(transform)),
                "visible": True,
            }}
            geometry = _mesh_geometry_payload(transform) if "mesh" in shape_types else None
            if geometry and geometry.get("representation") == "mesh":
                item["bbox"] = geometry.pop("bbox", [])
                item["geometry"] = geometry
            else:
                item["translation"] = _safe_float_list(
                    cmds.xform(transform, q=True, ws=True, translation=True),
                    [0, 0, 0],
                )
            objects.append(item)
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
        reference = _reference_payload(transform)
        if reference:
            item["reference"] = reference
        if "mesh" in shape_types:
            if include_materials:
                material_state = _material_payload(transform)
                if material_state:
                    item["material"] = material_state["primary"]
                    item["materials"] = material_state["materials"]
                    item["material_assignments"] = material_state["assignments"]
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
if include_cameras:
    for camera_shape in (cmds.ls(type="camera", long=True) or [])[:100]:
        try:
            cameras.append(_camera_payload(camera_shape))
        except Exception:
            pass

references_by_node = {{}}
for item in objects:
    reference = item.get("reference") if isinstance(item, dict) else None
    if isinstance(reference, dict) and reference.get("reference_node"):
        references_by_node[str(reference["reference_node"])] = reference

active_camera = ""
if include_cameras:
    try:
        panels = cmds.getPanel(type="modelPanel") or []
        active_panels = [panel for panel in panels if cmds.modelEditor(panel, q=True, activeView=True)]
        panel = (active_panels or panels or [""])[0]
        if panel:
            active_camera = cmds.modelPanel(panel, q=True, camera=True) or ""
    except Exception:
        pass

time_unit = str(cmds.currentUnit(q=True, time=True) or "film")
fps = {{
    "game": 15.0, "film": 24.0, "pal": 25.0, "ntsc": 30.0,
    "show": 48.0, "palf": 50.0, "ntscf": 60.0,
}}.get(time_unit, float(time_unit[:-3]) if time_unit.endswith("fps") else 24.0)

payload = {{
    "schema": "tech_connector.maya.scene_snapshot.v1",
    "provider_id": "maya",
    "process_id": int(os.getpid()),
    "scene": cmds.file(q=True, sceneName=True) or "",
    "scene_modified": bool(cmds.file(q=True, modified=True)),
    "application_version": str(cmds.about(version=True)),
    "scene_revision": int(globals().get("_tech_connector_scene_revision", 0) or 0),
    "unit_linear": cmds.currentUnit(q=True, linear=True),
    "up_axis": cmds.upAxis(q=True, axis=True),
    "current_time": float(cmds.currentTime(q=True)),
    "frame_start": float(cmds.playbackOptions(q=True, min=True)),
    "frame_end": float(cmds.playbackOptions(q=True, max=True)),
    "fps": fps,
    "objects": objects,
    "references": list(references_by_node.values()),
    "cameras": cameras,
    "active_camera": active_camera,
    "isolation": {{
        "selected_only": selected_only,
        "meshes_only": meshes_only,
        "include_geometry": include_geometry,
        "include_materials": include_materials,
        "include_cameras": include_cameras,
        "target_native_ids": target_native_ids,
        "transparent_background": True,
        "excluded_categories": ["background", "grid", "hud", "manipulators"],
    }},
}}
print(json.dumps(payload))
"""

    def get_deformation_binding_code(
        self,
        *,
        target_native_ids: list[str] | tuple[str, ...],
        float_path: str,
        weight_path: str,
        max_vertices_per_object: int = 500000,
    ) -> str:
        """Build Maya-side bulk extraction code for rest meshes and skin weights."""
        targets_json = json.dumps([str(item) for item in target_native_ids if str(item)])
        return f"""
import array
import json
import maya.cmds as cmds
import maya.api.OpenMaya as om
import maya.api.OpenMayaAnim as oma

_tc_targets = json.loads({targets_json!r})
_tc_float_path = {str(float_path)!r}
_tc_weight_path = {str(weight_path)!r}
_tc_max_vertices = int({int(max_vertices_per_object)!r})
_tc_floats = array.array("f")
_tc_dense_weights = array.array("d")
_tc_skeletons = []
_tc_meshes = []
_tc_skeleton_ids = set()

def _tc_transform_from_shape(shape):
    parents = cmds.listRelatives(shape, parent=True, fullPath=True) or []
    return parents[0] if parents else shape

def _tc_mesh_paths(node):
    transform = node if cmds.nodeType(node) in ("transform", "joint") else _tc_transform_from_shape(node)
    paths = []
    for shape in cmds.listRelatives(transform, shapes=True, fullPath=True) or []:
        if cmds.nodeType(shape) != "mesh":
            continue
        try:
            if cmds.getAttr(shape + ".intermediateObject"):
                continue
        except Exception:
            pass
        selection = om.MSelectionList()
        selection.add(shape)
        paths.append((transform, shape, selection.getDagPath(0)))
    return paths

def _tc_skin_for_output(output_path):
    history = cmds.listHistory(output_path.fullPathName(), pruneDagObjects=False) or []
    for skin_name in cmds.ls(history, type="skinCluster") or []:
        selection = om.MSelectionList()
        selection.add(skin_name)
        skin_fn = oma.MFnSkinCluster(selection.getDependNode(0))
        for connection in range(skin_fn.numOutputConnections()):
            geometry_index = skin_fn.indexForOutputConnection(connection)
            candidate = skin_fn.getPathAtIndex(geometry_index)
            if candidate.fullPathName() == output_path.fullPathName():
                return skin_name, skin_fn, connection, geometry_index, history
    return None

for _tc_target in _tc_targets:
    if not _tc_target or not cmds.objExists(_tc_target):
        continue
    for _tc_transform, _tc_shape, _tc_output_path in _tc_mesh_paths(_tc_target):
        _tc_skin_result = _tc_skin_for_output(_tc_output_path)
        if _tc_skin_result is None:
            _tc_meshes.append({{
                "native_id": _tc_transform,
                "shape_native_id": _tc_shape,
                "deformation_mode": "static",
                "vertex_count": int(om.MFnMesh(_tc_output_path).numVertices),
                "fallback_reason": "No skinCluster affects this output shape.",
            }})
            continue
        _tc_skin_name, _tc_skin_fn, _tc_connection, _tc_geometry_index, _tc_history = _tc_skin_result
        _tc_input_objects = _tc_skin_fn.getInputGeometry()
        if _tc_connection >= len(_tc_input_objects):
            _tc_meshes.append({{
                "native_id": _tc_transform,
                "shape_native_id": _tc_shape,
                "deformation_mode": "point_cache",
                "vertex_count": int(om.MFnMesh(_tc_output_path).numVertices),
                "fallback_reason": "Maya did not expose the skinCluster input geometry.",
            }})
            continue
        _tc_input_mesh = om.MFnMesh(_tc_input_objects[_tc_connection])
        _tc_vertex_count = int(_tc_input_mesh.numVertices)
        if _tc_vertex_count > _tc_max_vertices:
            _tc_meshes.append({{
                "native_id": _tc_transform,
                "shape_native_id": _tc_shape,
                "deformation_mode": "point_cache",
                "vertex_count": _tc_vertex_count,
                "fallback_reason": "Skin binding exceeds the configured vertex safety limit.",
            }})
            continue

        _tc_influences = _tc_skin_fn.influenceObjects()
        _tc_method = int(cmds.getAttr(_tc_skin_name + ".skinningMethod") or 0)
        _tc_mode = {{0: "linear_blend_skinning", 1: "dual_quaternion_skinning"}}.get(_tc_method, "point_cache")
        _tc_unsupported = []
        for _tc_history_node in _tc_history:
            if _tc_history_node == _tc_skin_name:
                continue
            try:
                if "geometryFilter" in (cmds.nodeType(_tc_history_node, inherited=True) or []):
                    _tc_unsupported.append({{
                        "native_id": _tc_history_node,
                        "type": cmds.nodeType(_tc_history_node),
                    }})
            except Exception:
                pass

        if _tc_skin_name not in _tc_skeleton_ids:
            _tc_inverse_offset = len(_tc_floats)
            _tc_joints = []
            for _tc_influence in _tc_influences:
                _tc_joint_id = _tc_influence.fullPathName()
                _tc_logical_index = int(_tc_skin_fn.indexForInfluenceObject(_tc_influence))
                _tc_parent = cmds.listRelatives(_tc_joint_id, parent=True, fullPath=True) or []
                _tc_bind_pre = cmds.getAttr(_tc_skin_name + ".bindPreMatrix[%d]" % _tc_logical_index)
                _tc_floats.extend(float(value) for value in _tc_bind_pre)
                _tc_joints.append({{
                    "native_id": _tc_joint_id,
                    "name": _tc_joint_id.split("|")[-1],
                    "parent_native_id": _tc_parent[0] if _tc_parent else "",
                    "logical_index": _tc_logical_index,
                }})
            _tc_skeletons.append({{
                "native_id": _tc_skin_name,
                "joints": _tc_joints,
                "inverse_bind_float_offset": _tc_inverse_offset,
                "inverse_bind_float_count": len(_tc_joints) * 16,
                "skinning_method": _tc_method,
            }})
            _tc_skeleton_ids.add(_tc_skin_name)

        _tc_bind_offset = len(_tc_floats)
        for _tc_point in _tc_input_mesh.getPoints(om.MSpace.kObject):
            _tc_floats.extend((float(_tc_point.x), float(_tc_point.y), float(_tc_point.z)))
        _tc_component_fn = om.MFnSingleIndexedComponent()
        _tc_component = _tc_component_fn.create(om.MFn.kMeshVertComponent)
        _tc_component_fn.addElements(range(_tc_vertex_count))
        _tc_weights, _tc_influence_count = _tc_skin_fn.getWeights(_tc_output_path, _tc_component)
        _tc_dense_offset = len(_tc_dense_weights)
        _tc_dense_weights.extend(float(value) for value in _tc_weights)
        _tc_geom_matrix = cmds.getAttr(_tc_skin_name + ".geomMatrix")
        _tc_meshes.append({{
            "native_id": _tc_transform,
            "shape_native_id": _tc_shape,
            "deformation_mode": _tc_mode,
            "skeleton_id": _tc_skin_name,
            "vertex_count": _tc_vertex_count,
            "bind_geometry_matrix": [float(value) for value in _tc_geom_matrix],
            "bind_vertex_float_offset": _tc_bind_offset,
            "dense_weight_double_offset": _tc_dense_offset,
            "dense_weight_count": len(_tc_weights),
            "joint_count": int(_tc_influence_count),
            "unsupported_deformers": _tc_unsupported,
            "fallback_reason": (
                "Maya blended linear/dual-quaternion skinning requires point parity fallback."
                if _tc_method not in (0, 1) else
                ("Additional geometry deformers require calibration before skeletal playback." if _tc_unsupported else "")
            ),
        }})

with open(_tc_float_path, "wb") as _tc_file:
    _tc_floats.tofile(_tc_file)
with open(_tc_weight_path, "wb") as _tc_file:
    _tc_dense_weights.tofile(_tc_file)
print(json.dumps({{
    "schema": "tech_connector.maya.deformation_binding.v1",
    "provider_id": "maya",
    "scene": cmds.file(q=True, sceneName=True) or "",
    "current_time": float(cmds.currentTime(q=True)),
    "frame_start": float(cmds.playbackOptions(q=True, min=True)),
    "frame_end": float(cmds.playbackOptions(q=True, max=True)),
    "unit_linear": cmds.currentUnit(q=True, linear=True),
    "up_axis": cmds.upAxis(q=True, axis=True),
    "scene_revision": int(globals().get("_tech_connector_scene_revision", 0) or 0),
    "skeletons": _tc_skeletons,
    "meshes": _tc_meshes,
}}, separators=(",", ":")))
"""

    def get_deformation_binding(
        self,
        *,
        port: int,
        target_native_ids: list[str] | tuple[str, ...],
        max_vertices_per_object: int = 500000,
        timeout: float = 60.0,
        cancel_event=None,
    ) -> tuple[bool, dict | str]:
        """Extract exact sparse skin bindings once, outside Maya's frame loop."""
        float_handle, float_path = tempfile.mkstemp(prefix="tech_connector_maya_skin_", suffix=".f32")
        weight_handle, weight_path = tempfile.mkstemp(prefix="tech_connector_maya_weights_", suffix=".f64")
        os.close(float_handle)
        os.close(weight_handle)
        raw = ""
        try:
            code = self.get_deformation_binding_code(
                target_native_ids=target_native_ids,
                float_path=float_path,
                weight_path=weight_path,
                max_vertices_per_object=max_vertices_per_object,
            )
            ok, raw = self.execute_on_port(
                code, port=int(port), timeout=timeout, cancel_event=cancel_event
            )
            if not ok:
                return False, raw
            packet = json.loads(str(raw or "{}"))
            floats = array.array("f")
            with open(float_path, "rb") as source:
                floats.fromfile(source, os.path.getsize(float_path) // floats.itemsize)
            dense_weights = array.array("d")
            with open(weight_path, "rb") as source:
                dense_weights.fromfile(source, os.path.getsize(weight_path) // dense_weights.itemsize)
            integers = array.array("I")

            for skeleton in packet.get("skeletons") or []:
                skeleton["inverse_bind_matrices_f32"] = floats
            for mesh in packet.get("meshes") or []:
                if mesh.get("deformation_mode") not in {"linear_blend_skinning", "dual_quaternion_skinning"}:
                    continue
                vertex_count = int(mesh.get("vertex_count", 0) or 0)
                joint_count = int(mesh.get("joint_count", 0) or 0)
                dense_offset = int(mesh.pop("dense_weight_double_offset", 0) or 0)
                dense_count = int(mesh.pop("dense_weight_count", 0) or 0)
                influence_offset_start = len(integers)
                joint_index_start = 0
                weight_start = len(floats)
                counts: list[int] = []
                sparse_indices: list[int] = []
                sparse_weights: list[float] = []
                dense_end = dense_offset + dense_count
                if vertex_count > 0 and joint_count > 0 and dense_end <= len(dense_weights):
                    try:
                        import numpy as np

                        dense_matrix = np.frombuffer(
                            dense_weights,
                            dtype=np.float64,
                            count=dense_count,
                            offset=dense_offset * dense_weights.itemsize,
                        ).reshape((vertex_count, joint_count))
                        nonzero = dense_matrix != 0.0
                        count_values = np.count_nonzero(nonzero, axis=1).astype(np.uint32, copy=False)
                        sparse_indices_np = np.nonzero(nonzero)[1].astype(np.uint32, copy=False)
                        sparse_weights_np = dense_matrix[nonzero].astype(np.float32, copy=False)
                        counts = count_values.tolist()
                        sparse_indices = sparse_indices_np.tolist()
                        sparse_weights = sparse_weights_np.tolist()
                    except Exception:
                        for vertex_index in range(vertex_count):
                            row_start = dense_offset + vertex_index * joint_count
                            count = 0
                            for joint_index, value in enumerate(dense_weights[row_start:row_start + joint_count]):
                                if float(value) == 0.0:
                                    continue
                                sparse_indices.append(joint_index)
                                sparse_weights.append(float(value))
                                count += 1
                            counts.append(count)
                integers.append(0)
                running = 0
                for count in counts:
                    running += count
                    integers.append(running)
                joint_index_start = len(integers)
                integers.extend(sparse_indices)
                floats.extend(sparse_weights)
                mesh.update({
                    "bind_vertices_f32": floats,
                    "influence_offsets_u32": integers,
                    "influence_offset_offset": influence_offset_start,
                    "joint_indices_u32": integers,
                    "joint_index_offset": joint_index_start,
                    "weights_f32": floats,
                    "weight_float_offset": weight_start,
                    "sparse_influence_count": len(sparse_weights),
                    "max_influences_per_vertex": max(counts or [0]),
                    "average_influences_per_vertex": (sum(counts) / max(1, len(counts))),
                })
            return True, normalize_deformation_binding(packet, f"maya:{int(port)}")
        except Exception as exc:
            return False, f"Could not parse Maya deformation binding: {exc}\n{str(raw)[:500]}"
        finally:
            for path in (float_path, weight_path):
                try:
                    os.unlink(path)
                except Exception:
                    pass

    def get_rig_topology(
        self,
        *,
        port: int,
        target_native_ids: list[str] | tuple[str, ...],
        max_nodes: int = 6000,
        max_connections: int = 30000,
        include_attribute_values: bool = False,
        timeout: float = 120.0,
        cancel_event=None,
    ) -> tuple[bool, dict | str]:
        """Extract an ordered DAG and relevant upstream DG from one Maya session."""
        paths_repr = repr(self.SYS_PATHS)
        targets_repr = repr([str(item) for item in target_native_ids if str(item)])
        payload_handle, payload_path = tempfile.mkstemp(prefix="tech_connector_maya_rig_", suffix=".json")
        os.close(payload_handle)
        try:
            code = f"""
import importlib
import json
import sys
for _tc_path in {paths_repr}:
    if _tc_path not in sys.path:
        sys.path.append(_tc_path)
import tech_connector.bridges.maya.rig_topology_extract as _tc_rig_extract
importlib.reload(_tc_rig_extract)
_tc_payload = _tc_rig_extract.extract_rig_topology(
    {targets_repr},
    max_nodes={int(max_nodes)!r},
    max_connections={int(max_connections)!r},
    include_attribute_values={bool(include_attribute_values)!r},
)
with open({str(payload_path)!r}, "w", encoding="utf-8") as _tc_output:
    json.dump(_tc_payload, _tc_output, separators=(",", ":"))
print(json.dumps({{"ok": True, "bytes": int(__import__('os').path.getsize({str(payload_path)!r}))}}))
"""
            ok, raw = self.execute_on_port(
                code, port=int(port), timeout=timeout, cancel_event=cancel_event
            )
            if not ok:
                return False, raw
            try:
                with open(payload_path, "r", encoding="utf-8") as source:
                    packet = json.load(source)
                topology = normalize_rig_topology(packet, provider_id=f"maya:{int(port)}")
            except Exception as exc:
                return False, f"Invalid Maya rig topology payload: {exc}"
            if topology.get("contract_errors"):
                return False, "; ".join(topology["contract_errors"][:8])
            return True, topology
        finally:
            try:
                os.unlink(payload_path)
            except Exception:
                pass

    def prepare_fast_deformation_sampler(
        self,
        *,
        port: int,
        binding: dict,
        timeout: float = 10.0,
        cancel_event=None,
    ) -> tuple[bool, str]:
        """Install persistent Maya DAG paths for compact joint-pose sampling."""
        skeletons = []
        for skeleton in binding.get("skeletons") or []:
            skeletons.append({
                "native_id": str(skeleton.get("native_id") or ""),
                "joints": [str(item.get("native_id") or "") for item in skeleton.get("joints") or []],
                "logical_indices": [int(item.get("logical_index", index) or 0) for index, item in enumerate(skeleton.get("joints") or [])],
            })
        meshes = [
            {
                "native_id": str(mesh.get("native_id") or ""),
                "shape_native_id": str(mesh.get("shape_native_id") or ""),
            }
            for mesh in binding.get("meshes") or []
            if str(mesh.get("native_id") or "")
        ]
        skeletons_json = json.dumps(skeletons)
        meshes_json = json.dumps(meshes)
        code = f"""
import array
import json
import maya.cmds as cmds
import maya.api.OpenMaya as om

_tech_connector_deformation_skeletons = []
for _tc_skeleton in json.loads({skeletons_json!r}):
    _tc_joint_paths = []
    for _tc_joint_name in _tc_skeleton.get("joints") or []:
        try:
            _tc_selection = om.MSelectionList()
            _tc_selection.add(_tc_joint_name)
            _tc_joint_paths.append(_tc_selection.getDagPath(0))
        except Exception:
            pass
    _tc_matrix_plugs = []
    try:
        _tc_skin_selection = om.MSelectionList()
        _tc_skin_selection.add(_tc_skeleton.get("native_id") or "")
        _tc_skin_node = om.MFnDependencyNode(_tc_skin_selection.getDependNode(0))
        _tc_matrix_array = _tc_skin_node.findPlug("matrix", False)
        for _tc_logical_index in _tc_skeleton.get("logical_indices") or []:
            _tc_matrix_plugs.append(_tc_matrix_array.elementByLogicalIndex(int(_tc_logical_index)))
    except Exception:
        _tc_matrix_plugs = []
    _tech_connector_deformation_skeletons.append({{
        "native_id": _tc_skeleton.get("native_id") or "",
        "joint_paths": _tc_joint_paths,
        "matrix_plugs": _tc_matrix_plugs,
    }})
_tech_connector_deformation_meshes = []
for _tc_mesh in json.loads({meshes_json!r}):
    try:
        _tc_selection = om.MSelectionList()
        _tc_selection.add(_tc_mesh.get("native_id") or "")
        _tech_connector_deformation_meshes.append({{
            "native_id": _tc_mesh.get("native_id") or "",
            "shape_native_id": _tc_mesh.get("shape_native_id") or "",
            "dag_path": _tc_selection.getDagPath(0),
        }})
    except Exception:
        pass

def _tech_connector_fast_deformation_sample(frame=None, binary_path=""):
    if frame is None:
        frame = float(cmds.currentTime(q=True))
    else:
        frame = float(frame)
        cmds.currentTime(frame, edit=True, update=True)
    _tc_matrices = array.array("f")
    _tc_skeleton_packets = []
    for _tc_skeleton in _tech_connector_deformation_skeletons:
        _tc_offset = len(_tc_matrices)
        _tc_matrix_plugs = _tc_skeleton.get("matrix_plugs") or []
        if len(_tc_matrix_plugs) == len(_tc_skeleton["joint_paths"]):
            for _tc_matrix_plug in _tc_matrix_plugs:
                _tc_matrix = om.MFnMatrixData(_tc_matrix_plug.asMObject()).matrix()
                _tc_matrices.extend(float(value) for value in _tc_matrix)
        else:
            for _tc_joint_path in _tc_skeleton["joint_paths"]:
                _tc_matrices.extend(float(value) for value in _tc_joint_path.inclusiveMatrix())
        _tc_skeleton_packets.append({{
            "native_id": _tc_skeleton["native_id"],
            "joint_count": len(_tc_skeleton["joint_paths"]),
            "joint_matrix_float_offset": _tc_offset,
        }})
    _tc_objects = []
    for _tc_mesh in _tech_connector_deformation_meshes:
        _tc_objects.append({{
            "native_id": _tc_mesh["native_id"],
            "shape_native_id": _tc_mesh["shape_native_id"],
            "world_matrix": [float(value) for value in _tc_mesh["dag_path"].inclusiveMatrix()],
        }})
    if binary_path:
        with open(binary_path, "wb") as _tc_file:
            _tc_matrices.tofile(_tc_file)
    return json.dumps({{
        "schema": "tech_connector.maya.deformation_frame.v1",
        "provider_id": "maya",
        "scene": cmds.file(q=True, sceneName=True) or "",
        "current_time": frame,
        "scene_revision": int(globals().get("_tech_connector_scene_revision", 0) or 0),
        "skeletons": _tc_skeleton_packets,
        "objects": _tc_objects,
    }}, separators=(",", ":"))

print("OK")
"""
        return self.execute_on_port(
            code, port=int(port), timeout=timeout, cancel_event=cancel_event
        )

    def get_fast_deformation_sample(
        self,
        *,
        port: int,
        frame: int | float | None,
        timeout: float = 10.0,
        cancel_event=None,
    ) -> tuple[bool, dict | str]:
        """Read one compact joint-pose packet from Maya."""
        handle, binary_path = tempfile.mkstemp(prefix="tech_connector_maya_pose_", suffix=".f32")
        os.close(handle)
        raw = ""
        try:
            code = f"print(_tech_connector_fast_deformation_sample({None if frame is None else float(frame)!r}, {binary_path!r}))"
            ok, raw = self.execute_on_port(
                code, port=int(port), timeout=timeout, cancel_event=cancel_event
            )
            if not ok:
                return False, raw
            packet = json.loads(str(raw or "{}"))
            matrices = array.array("f")
            with open(binary_path, "rb") as source:
                matrices.fromfile(source, os.path.getsize(binary_path) // matrices.itemsize)
            for skeleton in packet.get("skeletons") or []:
                skeleton["joint_matrices_f32"] = matrices
            return True, normalize_deformation_frame(packet, f"maya:{int(port)}")
        except Exception as exc:
            return False, f"Could not parse Maya deformation frame: {exc}\n{str(raw)[:500]}"
        finally:
            try:
                os.unlink(binary_path)
            except Exception:
                pass

    def prepare_fast_timeline_sampler(
        self,
        *,
        port: int,
        target_native_ids: list[str] | tuple[str, ...],
        max_vertices_per_object: int = 200000,
        timeout: float = 10.0,
        cancel_event=None,
    ) -> tuple[bool, str]:
        """Install a persistent Maya-side sampler so frame calls stay tiny."""
        targets_json = json.dumps([str(item) for item in target_native_ids if str(item)])
        code = f"""
import array
import base64
import ctypes
import json
import maya.cmds as cmds
import maya.OpenMaya as om1
import maya.api.OpenMaya as om

_tech_connector_timeline_targets = json.loads({targets_json!r})
_tech_connector_timeline_entries = []
_tech_connector_timeline_max_vertices = int({int(max_vertices_per_object)!r})

for _tc_callback_id in list(globals().get("_tech_connector_revision_callbacks", []) or []):
    try:
        om1.MMessage.removeCallback(_tc_callback_id)
    except Exception:
        pass
_tech_connector_revision_callbacks = []
_tech_connector_scene_revision = int(globals().get("_tech_connector_scene_revision", 0) or 0)

def _tc_mark_scene_edited(message, plug, other_plug, client_data):
    global _tech_connector_scene_revision
    edit_mask = (
        om1.MNodeMessage.kAttributeSet
        | om1.MNodeMessage.kConnectionMade
        | om1.MNodeMessage.kConnectionBroken
        | getattr(om1.MNodeMessage, "kAttributeArrayAdded", 0)
        | getattr(om1.MNodeMessage, "kAttributeArrayRemoved", 0)
    )
    if int(message) & int(edit_mask):
        _tech_connector_scene_revision += 1

def _tc_transform_from_shape(shape):
    parents = cmds.listRelatives(shape, parent=True, fullPath=True) or []
    return parents[0] if parents else shape

for _tc_node in _tech_connector_timeline_targets:
    if not _tc_node or not cmds.objExists(_tc_node):
        continue
    _tc_transform = _tc_node if cmds.nodeType(_tc_node) in ("transform", "joint") else _tc_transform_from_shape(_tc_node)
    _tc_shapes = []
    _tc_shape_types = []
    for _tc_shape in cmds.listRelatives(_tc_transform, shapes=True, fullPath=True) or []:
        try:
            if cmds.getAttr(_tc_shape + ".intermediateObject"):
                continue
        except Exception:
            pass
        try:
            _tc_shape_type = cmds.nodeType(_tc_shape)
        except Exception:
            continue
        _tc_shape_types.append(_tc_shape_type)
        if _tc_shape_type == "mesh":
            try:
                _tc_selection = om.MSelectionList()
                _tc_selection.add(_tc_shape)
                _tc_mesh_fn = om.MFnMesh(_tc_selection.getDagPath(0))
                _tc_raw_selection = om1.MSelectionList()
                _tc_raw_selection.add(_tc_shape)
                _tc_raw_dag_path = om1.MDagPath()
                _tc_raw_selection.getDagPath(0, _tc_raw_dag_path)
                _tc_raw_mesh_fn = om1.MFnMesh(_tc_raw_dag_path)
                _tc_shapes.append((_tc_shape, _tc_mesh_fn, _tc_raw_mesh_fn))
            except Exception:
                pass
    _tech_connector_timeline_entries.append({{
        "native_id": _tc_transform,
        "name": _tc_transform.split("|")[-1],
        "type": "mesh" if _tc_shapes else (_tc_shape_types[0] if _tc_shape_types else cmds.nodeType(_tc_transform)),
        "mesh_shapes": _tc_shapes,
    }})

_tc_revision_node_names = set()
for _tc_target in _tech_connector_timeline_targets:
    if not _tc_target or not cmds.objExists(_tc_target):
        continue
    _tc_revision_node_names.add(_tc_target)
    try:
        _tc_revision_node_names.update(cmds.listHistory(_tc_target, pruneDagObjects=False) or [])
    except Exception:
        pass
for _tc_node_name in sorted(_tc_revision_node_names):
    try:
        _tc_node_selection = om1.MSelectionList()
        _tc_node_selection.add(_tc_node_name)
        _tc_node_object = om1.MObject()
        _tc_node_selection.getDependNode(0, _tc_node_object)
        _tech_connector_revision_callbacks.append(
            om1.MNodeMessage.addAttributeChangedCallback(_tc_node_object, _tc_mark_scene_edited)
        )
    except Exception:
        pass

_tech_connector_timeline_camera_shapes = cmds.ls(type="camera", long=True) or []
_tech_connector_timeline_scene = cmds.file(q=True, sceneName=True) or ""
_tech_connector_timeline_unit = cmds.currentUnit(q=True, linear=True)
_tech_connector_timeline_up_axis = cmds.upAxis(q=True, axis=True)
_tech_connector_timeline_start = float(cmds.playbackOptions(q=True, min=True))
_tech_connector_timeline_end = float(cmds.playbackOptions(q=True, max=True))
_tc_time_unit = str(cmds.currentUnit(q=True, time=True) or "film")
_tech_connector_timeline_fps = {{
    "game": 15.0, "film": 24.0, "pal": 25.0, "ntsc": 30.0,
    "show": 48.0, "palf": 50.0, "ntscf": 60.0,
}}.get(_tc_time_unit, float(_tc_time_unit[:-3]) if _tc_time_unit.endswith("fps") else 24.0)

def _tech_connector_fast_timeline_sample(frame=None, include_cameras=True, binary_path=""):
    if frame is None:
        frame = float(cmds.currentTime(q=True))
        _tc_set_frame = False
    else:
        frame = float(frame)
        _tc_set_frame = True
    _tc_refresh_suspended = False
    if _tc_set_frame:
        try:
            cmds.refresh(suspend=True)
            _tc_refresh_suspended = True
        except Exception:
            pass
        try:
            cmds.currentTime(frame, edit=True, update=True)
        finally:
            if _tc_refresh_suspended:
                try:
                    cmds.refresh(suspend=False)
                except Exception:
                    pass
    _tc_objects = []
    _tc_frame_vertices = bytearray()
    for _tc_entry in _tech_connector_timeline_entries:
        _tc_item = {{
            "native_id": _tc_entry["native_id"],
            "name": _tc_entry["name"],
            "type": _tc_entry["type"],
            "visible": True,
        }}
        if _tc_entry["mesh_shapes"]:
            _tc_packed = bytearray()
            _tc_vertex_count = 0
            _tc_shape_names = []
            _tc_too_large = False
            for _tc_shape_name, _tc_mesh_fn, _tc_raw_mesh_fn in _tc_entry["mesh_shapes"]:
                _tc_shape_vertex_count = int(_tc_mesh_fn.numVertices)
                if _tc_shape_vertex_count > _tech_connector_timeline_max_vertices:
                    _tc_too_large = True
                    break
                _tc_shape_names.append(_tc_shape_name)
                _tc_packed.extend(
                    ctypes.string_at(
                        int(_tc_raw_mesh_fn.getRawPoints()),
                        _tc_shape_vertex_count * 3 * 4,
                    )
                )
                _tc_vertex_count += _tc_shape_vertex_count
            if not _tc_too_large and _tc_packed:
                _tc_item["world_matrix"] = [
                    float(value)
                    for value in cmds.xform(_tc_entry["native_id"], q=True, ws=True, matrix=True)
                ]
                _tc_geometry = {{
                    "representation": "mesh",
                    "vertex_count": _tc_vertex_count,
                    "faces": [],
                    "topology_included": False,
                    "coordinate_space": "object",
                    "shape_names": _tc_shape_names,
                }}
                if binary_path:
                    _tc_geometry["vertex_encoding"] = "f32-file-array"
                    _tc_geometry["vertex_float_offset"] = len(_tc_frame_vertices) // 4
                    _tc_frame_vertices.extend(_tc_packed)
                else:
                    _tc_geometry["vertex_encoding"] = "f32-base64"
                    _tc_geometry["vertices_f32_base64"] = base64.b64encode(bytes(_tc_packed)).decode("ascii")
                _tc_item["geometry"] = _tc_geometry
            else:
                _tc_item["translation"] = [float(value) for value in cmds.xform(_tc_entry["native_id"], q=True, ws=True, translation=True)]
        else:
            _tc_item["translation"] = [float(value) for value in cmds.xform(_tc_entry["native_id"], q=True, ws=True, translation=True)]
        _tc_objects.append(_tc_item)
    _tc_cameras = []
    if include_cameras:
        for _tc_camera_shape in _tech_connector_timeline_camera_shapes:
            try:
                _tc_camera_transform = _tc_transform_from_shape(_tc_camera_shape)
                _tc_cameras.append({{
                    "native_id": _tc_camera_transform,
                    "name": _tc_camera_transform.split("|")[-1],
                    "type": "camera",
                    "shape": _tc_camera_shape,
                    "translation": [float(value) for value in cmds.xform(_tc_camera_transform, q=True, ws=True, translation=True)],
                    "rotation": [float(value) for value in cmds.xform(_tc_camera_transform, q=True, ws=True, rotation=True)],
                    "world_matrix": [float(value) for value in cmds.xform(_tc_camera_transform, q=True, ws=True, matrix=True)],
                    "focal_length_mm": float(cmds.getAttr(_tc_camera_shape + ".focalLength")),
                    "aspect_ratio": max(0.01, float(cmds.getAttr("defaultResolution.deviceAspectRatio") or (16.0 / 9.0))),
                    "film_aspect_ratio": (
                        max(1.0e-6, float(cmds.getAttr(_tc_camera_shape + ".horizontalFilmAperture") or 1.41732))
                        / max(1.0e-6, float(cmds.getAttr(_tc_camera_shape + ".verticalFilmAperture") or 0.94488))
                    ),
                    "film_fit": int(cmds.getAttr(_tc_camera_shape + ".filmFit") or 0),
                    "near_clip": float(cmds.getAttr(_tc_camera_shape + ".nearClipPlane")),
                    "far_clip": float(cmds.getAttr(_tc_camera_shape + ".farClipPlane")),
                    "visible": True,
                }})
            except Exception:
                pass
    if binary_path:
        with open(binary_path, "wb") as _tc_binary_file:
            _tc_binary_file.write(_tc_frame_vertices)
    return json.dumps({{
        "schema": "tech_connector.maya.timeline_sample.v2",
        "provider_id": "maya",
        "scene": _tech_connector_timeline_scene,
        "unit_linear": _tech_connector_timeline_unit,
        "up_axis": _tech_connector_timeline_up_axis,
        "current_time": float(frame),
        "frame_start": _tech_connector_timeline_start,
        "frame_end": _tech_connector_timeline_end,
        "fps": _tech_connector_timeline_fps,
        "scene_revision": int(_tech_connector_scene_revision),
        "objects": _tc_objects,
        "cameras": _tc_cameras,
        "active_camera": "",
        "isolation": {{
            "include_geometry": True,
            "include_cameras": bool(include_cameras),
            "target_native_ids": _tech_connector_timeline_targets,
        }},
    }}, separators=(",", ":"))

print("OK")
"""
        return self.execute_on_port(
            code, port=int(port), timeout=timeout, cancel_event=cancel_event
        )

    def get_fast_timeline_sample(
        self,
        *,
        port: int,
        frame: int | float | None,
        include_cameras: bool = True,
        timeout: float = 10.0,
        cancel_event=None,
    ) -> tuple[bool, dict | str]:
        handle, binary_path = tempfile.mkstemp(prefix="tech_connector_maya_frame_", suffix=".f32")
        os.close(handle)
        try:
            code = (
                f"print(_tech_connector_fast_timeline_sample("
                f"{None if frame is None else float(frame)!r}, {bool(include_cameras)!r}, {binary_path!r}))"
            )
            ok, raw = self.execute_on_port(
                code, port=int(port), timeout=timeout, cancel_event=cancel_event
            )
            if not ok:
                return False, raw
            snapshot = json.loads(str(raw or "{}"))
            packed = array.array("f")
            with open(binary_path, "rb") as binary_file:
                packed.fromfile(binary_file, os.path.getsize(binary_path) // packed.itemsize)
            for obj in snapshot.get("objects") or []:
                geometry = obj.get("geometry") if isinstance(obj, dict) else None
                if isinstance(geometry, dict) and geometry.get("vertex_encoding") == "f32-file-array":
                    geometry["vertices_f32"] = packed
            return True, normalize_frame_delta(snapshot, "maya")
        except Exception as exc:
            return False, f"Could not parse Maya timeline sample JSON: {exc}\n{str(raw)[:500]}"
        finally:
            try:
                os.unlink(binary_path)
            except Exception:
                pass

    def get_scene_snapshot(
        self,
        *,
        selected_only: bool = False,
        meshes_only: bool = False,
        include_geometry: bool = True,
        include_materials: bool = True,
        include_cameras: bool = True,
        include_faces: bool = True,
        target_native_ids: list[str] | tuple[str, ...] | None = None,
        limit: int = 500,
        max_vertices_per_object: int = 50000,
        max_faces_per_object: int = 50000,
        timeout: float = 10.0,
        port: int | None = None,
        sample_frame: int | float | None = None,
        fast_sample: bool = False,
        suspend_refresh: bool = False,
        cancel_event=None,
    ) -> tuple[bool, dict | str]:
        """Query Maya for isolated scene objects, cameras, units, and bounds."""
        code = self.get_scene_snapshot_code(
                selected_only=selected_only,
                meshes_only=meshes_only,
                include_geometry=include_geometry,
                include_materials=include_materials,
                include_cameras=include_cameras,
                include_faces=include_faces,
                target_native_ids=target_native_ids,
                limit=limit,
                max_vertices_per_object=max_vertices_per_object,
                max_faces_per_object=max_faces_per_object,
                sample_frame=sample_frame,
                fast_sample=fast_sample,
                suspend_refresh=suspend_refresh,
            )
        ok, raw = (
            self.execute_on_port(
                code, port=int(port), timeout=timeout, cancel_event=cancel_event
            )
            if port
            else self.execute(code, timeout=timeout)
        )
        if not ok:
            return False, raw
        try:
            snapshot = json.loads(str(raw or "{}"))
            return True, decode_maya_snapshot_geometry(snapshot)
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
