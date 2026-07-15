from __future__ import print_function

import base64
import builtins
import io
import json
import os
import socket
import sys
import traceback
import maya.api.OpenMaya as om
import maya.cmds as cmds
import maya.mel as mel
import maya.utils

_SAVE_CALLBACK_ID = None
_EXIT_CALLBACK_ID = None
MENU_NAME = "theEntireWorldMenu"
MENU_LABEL = "The Entire World Tools"

COMMAND_PORT_START = 7001
COMMAND_PORT_FILE = (
    "C:/Users/Aaron/temp/maya_port.txt"
)
COMMAND_PORT_SESSION_FILE = (
    "C:/Users/Aaron/temp/maya_sessions.json"
)


def log(message):
    print("[The Entire World Tools] {}".format(message))


def log_exception(message):
    log(message)
    traceback.print_exc()


def maya_execute_and_capture(encoded_code):
    old_stdout = sys.stdout
    old_stderr = sys.stderr

    sys.stdout = io.StringIO()
    sys.stderr = io.StringIO()

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


builtins.maya_execute_and_capture = maya_execute_and_capture


def apply_command_port_python3_patches():
    try:
        import maya.app.general.CommandPort as cp

        def patched_receiveData(self):
            encoding_type = getattr(cp, "encodingType", "utf8")

            next_data = self.request.recv(self.server.bufferSize)
            if not next_data:
                return None

            data = next_data
            old_timeout = self.request.gettimeout()
            self.request.settimeout(1.5)

            try:
                while len(next_data) >= self.server.bufferSize:
                    try:
                        next_data = self.request.recv(self.server.bufferSize)
                        data += next_data
                    except socket.timeout:
                        break
            finally:
                self.request.settimeout(old_timeout)

            data = data.replace(b"\x00", b"")

            try:
                return data.decode(encoding_type).strip()
            except Exception:
                sys.stderr.write("Invalid UTF-8 data received by Maya commandPort.\n")
                return None

        def patched_handle(self):
            encoding_type = getattr(cp, "encodingType", "utf8")

            try:
                if self.server.echoOutput:
                    self.request.settimeout(1.5)

                while not self.server.die:
                    if self.server.echoOutput:
                        while not self.server.commandMessageQueue.empty():
                            msg = self.server.commandMessageQueue.get() + self.resp_term
                            self.wfile.write(msg.encode(encoding_type))

                    try:
                        self.data = self.receiveData()
                    except socket.timeout:
                        continue

                    if self.data is None:
                        break

                    if self.server.securityWarning:
                        maya.utils.executeInMainThreadWithResult(self.postSecurityWarning)

                        if self.dialog_result is False:
                            msg = "Execution denied by Maya." + self.resp_term
                            self.wfile.write(msg.encode(encoding_type))
                            return

                        if self.dialog_result is True:
                            self.server.securityWarning = False

                    response = maya.utils.executeInMainThreadWithResult(
                        self._languageExecute
                    )

                    if response is None:
                        response = ""

                    self.wfile.write(str(response).encode(encoding_type))

            except socket.error:
                pass
            except Exception:
                log_exception("Error in commandPort handler.")

        cp.TcommandHandler.receiveData = patched_receiveData
        cp.TcommandHandler.handle = patched_handle

    except Exception:
        log_exception("Failed to apply CommandPort monkeypatches.")


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
        log_exception("Failed to save Maya commandPort sessions file.")


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
    try:
        sessions = [
            item for item in _read_session_file()
            if int(item.get("pid", -1)) != int(current_pid)
        ]
        _write_session_file(sessions)
    except Exception:
        log_exception("Failed to clean Maya commandPort sessions file.")
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

        log("Saved active commandPort to file: {}".format(port))

    except Exception:
        log_exception("Failed to save commandPort to file.")


def get_command_port():
    try:
        return mel.eval("$temp = $g_commandPort")
    except Exception:
        return None


def send_command(command, port=COMMAND_PORT_START):
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.settimeout(0.2)

    try:
        client.connect(("127.0.0.1", int(port)))

        if isinstance(command, str):
            command = command.encode("utf-8")

        client.send(command)
        data = client.recv(1024)

        if isinstance(data, bytes):
            data = data.decode("utf-8")

        return data

    finally:
        try:
            client.close()
        except Exception:
            pass


def _is_port_open(port):
    try:
        send_command("print('')", port=port)
        return True
    except Exception:
        return False


def _close_existing_command_ports():
    try:
        active_ports = cmds.commandPort(q=True, listPorts=True) or []

        for port_name in active_ports:
            try:
                cmds.commandPort(name=port_name, close=True)
                log("Closed existing commandPort: {}".format(port_name))
            except Exception:
                log_exception("Failed to close commandPort: {}".format(port_name))

    except Exception:
        log_exception("Error checking existing commandPorts.")


def create_command_port(port=COMMAND_PORT_START, stp="python"):
    current_port = get_command_port()
    if current_port:
        save_port_to_file(current_port)
        return current_port

    try:
        cmds.optionVar(iv=("commandportOpenByDefault", 0))
    except Exception:
        pass

    while _is_port_open(port):
        port += 1

    name_and_port = ":{}".format(port)

    try:
        cmds.commandPort(
            name=name_and_port,
            sourceType=stp,
            echoOutput=False,
            noreturn=False
        )

        mel.eval("global int $g_commandPort = {}".format(port))

        log("Maya commandPort open on {}".format(name_and_port))
        save_port_to_file(port)
        return port

    except Exception:
        log_exception("Maya commandPort could not be established.")
        return None


def initialize_command_port():
    apply_command_port_python3_patches()
    _close_existing_command_ports()
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
        log("Registered Maya exit commandPort cleanup callback.")
    except Exception:
        log_exception("Failed to register Maya exit commandPort cleanup callback.")


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