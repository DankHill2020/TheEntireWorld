from __future__ import print_function

import base64
import json
import os
import socket
import sys
import threading
import traceback
import maya.api.OpenMaya as om
import maya.cmds as cmds
import maya.mel as mel
import maya.utils

_SAVE_CALLBACK_ID = None
_EXIT_CALLBACK_ID = None
_BRIDGE_SERVER = None
_BRIDGE_THREAD = None
_BRIDGE_STOP = threading.Event()
_BRIDGE_PORT = None
_BRIDGE_CLIENT_SLOTS = threading.BoundedSemaphore(32)
MENU_NAME = "theEntireWorldMenu"
MENU_LABEL = "The Entire World Tools"

TECH_CONNECTOR_MAYA_BRIDGE_VERSION = "3"
TECH_CONNECTOR_MAYA_BRIDGE_BOOT_SOURCE = str(globals().get("__file__", ""))
_MAX_BRIDGE_REQUEST_BYTES = 16 * 1024 * 1024
_MAX_BRIDGE_OUTPUT_CHARS = 8 * 1024 * 1024
_MAX_BRIDGE_RESPONSE_BYTES = 32 * 1024 * 1024
_BRIDGE_CONNECTION_TIMEOUT_SECONDS = 30.0

COMMAND_PORT_START = 7001
COMMAND_PORT_FILE = (
    os.path.join(os.path.expanduser("~"), "temp", "maya_port.txt")
)
COMMAND_PORT_SESSION_FILE = (
    os.path.join(os.path.expanduser("~"), "temp", "maya_sessions.json")
)


def log(message):
    print("[The Entire World Tools] {}".format(message))


def log_exception(message):
    log(message)
    traceback.print_exc()


def maya_execute_and_capture(encoded_code, bridge_session=""):
    try:
        from tech_connector.bridges.session_authorization import validate_bridge_session

        if not validate_bridge_session(bridge_session, "maya"):
            return "ERROR: Tech Connector activation is required for this Maya bridge."
    except Exception:
        return "ERROR: Tech Connector licensing components are unavailable."
    class _BoundedCapture:
        def __init__(self, limit):
            self.limit = int(limit)
            self.parts = []
            self.size = 0
            self.truncated = False

        def write(self, value):
            text = str(value)
            remaining = max(0, self.limit - self.size)
            if remaining:
                self.parts.append(text[:remaining])
                self.size += min(len(text), remaining)
            if len(text) > remaining:
                self.truncated = True

        def flush(self):
            pass

        def getvalue(self):
            value = "".join(self.parts)
            if self.truncated:
                value += "\n[Tech Connector: Maya output truncated at 8 MiB]"
            return value

    old_stdout = sys.stdout
    old_stderr = sys.stderr
    sys.stdout = _BoundedCapture(_MAX_BRIDGE_OUTPUT_CHARS)
    sys.stderr = _BoundedCapture(_MAX_BRIDGE_OUTPUT_CHARS)

    try:
        code = base64.b64decode(encoded_code.encode("utf-8")).decode("utf-8")
        exec(code, globals())
    except Exception:
        traceback.print_exc(file=sys.stderr)
    finally:
        out = sys.stdout.getvalue()
        err = sys.stderr.getvalue()

        sys.stdout = old_stdout
        sys.stderr = old_stderr

    if err:
        return "STDOUT:\n{}\nSTDERR:\n{}".format(out, err)

    return out


def _bridge_error(message, code="bridge_request_failed"):
    return {"ok": False, "error": str(message), "code": str(code)}


def _receive_bridge_payload(connection, maximum_bytes=_MAX_BRIDGE_REQUEST_BYTES):
    raw = bytearray()
    while b"\n" not in raw:
        chunk = connection.recv(65536)
        if not chunk:
            break
        raw.extend(chunk)
        if len(raw) > maximum_bytes:
            raise ValueError("Maya bridge request exceeded the 16 MiB limit.")
    return json.loads(bytes(raw).decode("utf-8", errors="strict").strip() or "{}")


def _encode_bridge_response(response):
    encoded = (json.dumps(response, default=str, ensure_ascii=False) + "\n").encode("utf-8")
    if len(encoded) <= _MAX_BRIDGE_RESPONSE_BYTES:
        return encoded
    return (json.dumps(_bridge_error(
        "Maya bridge response exceeded the 32 MiB wire limit.",
        "bridge_response_too_large",
    )) + "\n").encode("utf-8")


def _handle_bridge_client(connection):
    with connection:
        try:
            payload = _receive_bridge_payload(connection)
            session_token = str(payload.get("bridge_session") or "")
            try:
                from tech_connector.bridges.session_authorization import validate_bridge_session

                authorized = validate_bridge_session(session_token, "maya")
            except Exception:
                authorized = False
            if not authorized:
                response = _bridge_error(
                    "Tech Connector activation is required for this Maya bridge.",
                    "bridge_authorization_required",
                )
            else:
                encoded_code = str(payload.get("code_b64") or "")
                result = maya.utils.executeInMainThreadWithResult(
                    lambda: maya_execute_and_capture(encoded_code, session_token)
                )
                response = {"ok": True, "result": str(result or "")}
        except Exception:
            response = _bridge_error(
                "Malformed or incomplete Maya bridge request.",
                "bridge_invalid_request",
            )
        try:
            connection.sendall(_encode_bridge_response(response))
        except Exception:
            pass


def _run_bridge_client(connection):
    try:
        _handle_bridge_client(connection)
    finally:
        _BRIDGE_CLIENT_SLOTS.release()


def _serve_authenticated_bridge(server):
    while not _BRIDGE_STOP.is_set():
        try:
            connection, _address = server.accept()
        except socket.timeout:
            continue
        except OSError:
            break
        connection.settimeout(_BRIDGE_CONNECTION_TIMEOUT_SECONDS)
        if not _BRIDGE_CLIENT_SLOTS.acquire(False):
            try:
                connection.sendall(_encode_bridge_response(_bridge_error(
                    "Maya bridge is busy; retry after active requests finish.",
                    "bridge_busy",
                )))
            finally:
                connection.close()
            continue
        try:
            threading.Thread(
                target=_run_bridge_client,
                args=(connection,),
                daemon=True,
            ).start()
        except Exception:
            _BRIDGE_CLIENT_SLOTS.release()
            connection.close()


def _stop_authenticated_bridge():
    global _BRIDGE_SERVER, _BRIDGE_THREAD, _BRIDGE_PORT
    _BRIDGE_STOP.set()
    server = _BRIDGE_SERVER
    _BRIDGE_SERVER = None
    _BRIDGE_PORT = None
    if server is not None:
        try:
            server.close()
        except Exception:
            pass
    _BRIDGE_THREAD = None


def _current_session_payload(port):
    try:
        return {
            "port": int(port),
            "pid": os.getpid(),
            "scene": cmds.file(q=True, sceneName=True) or "",
            "version": cmds.about(version=True),
        }
    except Exception:
        return {"port": int(port), "pid": os.getpid(), "scene": "", "version": ""}


def _read_session_file():
    try:
        with open(COMMAND_PORT_SESSION_FILE, "r") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _write_session_file(sessions):
    try:
        folder = os.path.dirname(COMMAND_PORT_SESSION_FILE)
        if folder and not os.path.isdir(folder):
            os.makedirs(folder)
        with open(COMMAND_PORT_SESSION_FILE, "w") as f:
            json.dump(sessions, f, indent=2, sort_keys=True)
    except Exception:
        log_exception("Failed to save Maya bridge sessions file.")


def save_session_to_file(port):
    payload = _current_session_payload(port)
    sessions = [
        item for item in _read_session_file()
        if int(item.get("pid", -1)) != int(payload["pid"])
        and int(item.get("port", -1)) != int(payload["port"])
    ]
    sessions.append(payload)
    _write_session_file(sessions)


def cleanup_command_port_files(*args):
    current_port = get_command_port()
    current_pid = os.getpid()
    _stop_authenticated_bridge()
    try:
        sessions = [
            item for item in _read_session_file()
            if int(item.get("pid", -1)) != int(current_pid)
        ]
        _write_session_file(sessions)
    except Exception:
        log_exception("Failed to clean Maya bridge sessions file.")
    try:
        if current_port:
            with open(COMMAND_PORT_FILE, "r") as f:
                if f.read().strip() == str(current_port):
                    os.remove(COMMAND_PORT_FILE)
    except Exception:
        pass


def save_port_to_file(port):
    try:
        folder = os.path.dirname(COMMAND_PORT_FILE)
        if folder and not os.path.isdir(folder):
            os.makedirs(folder)

        with open(COMMAND_PORT_FILE, "w") as f:
            f.write(str(port))
        save_session_to_file(port)

        log("Saved active Maya JSON bridge port to file: {}".format(port))

    except Exception:
        log_exception("Failed to save Maya bridge port to file.")


def get_command_port():
    return _BRIDGE_PORT


def send_command(command, port=COMMAND_PORT_START):
    from tech_connector.bridges.session_authorization import bridge_session_token

    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.settimeout(5.0)

    try:
        client.connect(("127.0.0.1", int(port)))
        encoded = base64.b64encode(str(command).encode("utf-8")).decode("ascii")
        payload = {
            "code_b64": encoded,
            "bridge_session": bridge_session_token("maya"),
        }
        client.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        raw = b""
        while b"\n" not in raw:
            chunk = client.recv(65536)
            if not chunk:
                break
            raw += chunk
        response = json.loads(raw.decode("utf-8", errors="replace").strip() or "{}")
        if not response.get("ok"):
            raise RuntimeError(response.get("error") or "Maya bridge request failed.")
        return str(response.get("result") or "")

    finally:
        try:
            client.close()
        except Exception:
            pass


def _is_port_open(port):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.05)
            return probe.connect_ex(("127.0.0.1", int(port))) == 0
    except Exception:
        return False


def _close_legacy_tech_connector_command_ports():
    # Native commandPort is unavailable in Maya standalone/batch sessions.
    if cmds.about(batch=True):
        return
    try:
        recorded_ports = set()
        try:
            with open(COMMAND_PORT_FILE, "r") as port_file:
                recorded_ports.add(int(port_file.read().strip()))
        except Exception:
            pass
        current_pid = int(os.getpid())
        for item in _read_session_file():
            try:
                if int(item.get("pid", -1)) == current_pid:
                    recorded_ports.add(int(item.get("port", -1)))
            except Exception:
                continue
        active_ports = cmds.commandPort(listPorts=True) or []
        scan_end = COMMAND_PORT_START + max(
            1,
            int(os.environ.get("MAYA_COMMAND_PORT_SCAN_COUNT", "10")),
        )
        for port_name in active_ports:
            try:
                port_number = int(str(port_name).rsplit(":", 1)[-1])
            except Exception:
                continue
            if not COMMAND_PORT_START <= port_number < scan_end:
                continue
            try:
                cmds.commandPort(name=port_name, close=True)
                origin = "recorded" if port_number in recorded_ports else "stale"
                log("Closed {} legacy Tech Connector commandPort: {}".format(origin, port_name))
            except Exception:
                log_exception("Failed to close legacy commandPort: {}".format(port_name))

    except Exception:
        log_exception("Error checking legacy commandPorts.")


def create_command_port(port=COMMAND_PORT_START, stp="python"):
    del stp
    global _BRIDGE_SERVER, _BRIDGE_THREAD, _BRIDGE_PORT
    current_port = get_command_port()
    if current_port and _BRIDGE_THREAD is not None and _BRIDGE_THREAD.is_alive():
        save_port_to_file(current_port)
        return current_port
    _stop_authenticated_bridge()
    _BRIDGE_STOP.clear()
    scan_count = max(1, int(os.environ.get("MAYA_COMMAND_PORT_SCAN_COUNT", "10")))
    last_error = None
    for candidate in range(int(port), int(port) + scan_count):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                server.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(("127.0.0.1", candidate))
            server.listen(16)
            server.settimeout(0.25)
            _BRIDGE_SERVER = server
            _BRIDGE_PORT = candidate
            _BRIDGE_THREAD = threading.Thread(
                target=_serve_authenticated_bridge,
                args=(server,),
                daemon=True,
                name="TechConnectorMayaBridge",
            )
            _BRIDGE_THREAD.start()
            try:
                mel.eval("global int $g_commandPort = {}".format(candidate))
            except Exception:
                pass
            save_port_to_file(candidate)
            log("Authenticated Maya JSON bridge open on 127.0.0.1:{}".format(candidate))
            return candidate
        except Exception as exc:
            last_error = exc
            try:
                server.close()
            except Exception:
                pass
    if last_error is not None:
        log("Maya JSON bridge could not be established: {}".format(last_error))
    return None


def initialize_command_port():
    _close_legacy_tech_connector_command_ports()
    try:
        from tech_connector.bridges.session_authorization import load_bridge_session

        if load_bridge_session("maya") is None:
            log("Activate Tech Connector before starting the Maya command bridge.")
            return None
    except Exception:
        log("Licensing components are unavailable; Maya command bridge not started.")
        return None
    return create_command_port(port=COMMAND_PORT_START)


def on_before_save(*args):
    try:
        scene_name = cmds.file(q=True, sceneName=True)

        if not scene_name:
            return

        tools_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        if tools_dir not in sys.path:
            sys.path.append(tools_dir)

        from utilities import p4_utils
        p4_utils.p4_edit(scene_name)

    except Exception:
        log_exception("P4 Auto-checkout failed.")

def remove_save_callback():
    global _SAVE_CALLBACK_ID

    if _SAVE_CALLBACK_ID is None:
        return

    try:
        om.MMessage.removeCallback(_SAVE_CALLBACK_ID)
        log("Removed kBeforeSave API callback.")
    except Exception:
        log_exception("Failed to remove kBeforeSave API callback.")
    finally:
        _SAVE_CALLBACK_ID = None


def _register_exit_cleanup():
    global _EXIT_CALLBACK_ID

    if _EXIT_CALLBACK_ID is not None:
        return

    try:
        _EXIT_CALLBACK_ID = om.MSceneMessage.addCallback(
            om.MSceneMessage.kMayaExiting,
            cleanup_command_port_files,
        )
        log("Registered Maya authenticated bridge exit cleanup callback.")
    except Exception:
        log_exception("Failed to register Maya bridge exit cleanup callback.")


def _register_before_save_job():
    """
    Register a real Maya API save callback instead of scriptJob.
    This avoids invalid scriptJob events like 'BeforeSave' in Maya 2023.
    """
    global _SAVE_CALLBACK_ID

    if _SAVE_CALLBACK_ID is not None:
        return

    try:
        _SAVE_CALLBACK_ID = om.MSceneMessage.addCallback(
            om.MSceneMessage.kBeforeSave,
            on_before_save
        )

        log("Registered kBeforeSave API callback.")

    except Exception:
        log_exception("Failed to register kBeforeSave API callback.")


def _get_maya_main_window():
    try:
        return mel.eval("$tmp = $gMainWindow")
    except Exception:
        return None


def _show_sequence_ui(*args):
    try:
        from maya_tools.Cinematics.SequenceUI import sequence_ui
        sequence_ui.show_animation_manager()
    except Exception:
        log_exception("Failed to launch Sequence UI.")


def _show_hik_ui(*args):
    try:
        from maya_tools.Rigging.mocap import hik_ui
        import importlib
        importlib.reload(hik_ui)
        hik_ui.launch_hik_ui()
    except Exception:
        log_exception("Failed to launch Human IK UI.")


def create_maya_menu():
    main_window = _get_maya_main_window()

    if not main_window or not cmds.control(main_window, exists=True):
        maya.utils.executeDeferred(create_maya_menu)
        return

    try:
        if cmds.menu(MENU_NAME, exists=True):
            cmds.deleteUI(MENU_NAME, menu=True)

        main_menu = cmds.menu(
            MENU_NAME,
            label=MENU_LABEL,
            parent=main_window,
            tearOff=True
        )

        cmds.menuItem(
            "sequenceUIItem",
            label="Sequence UI",
            parent=main_menu,
            command=_show_sequence_ui
        )

        cmds.menuItem(
            "hikUIItem",
            label="Human IK UI",
            parent=main_menu,
            command=_show_hik_ui
        )

        log("Menu created.")

    except Exception:
        log_exception("Failed to create Maya menu.")


def create_menu_once():
    initialize_command_port()
    _register_exit_cleanup()
    _register_before_save_job()
    maya.utils.executeDeferred(create_maya_menu)


if __name__ == "__main__":
    create_menu_once()
