from __future__ import annotations

from pathlib import Path
import shutil
import time


TARGET = Path(r"C:\depot\tools\maya_tools\maya_menu.py")


def replace_once(text: str, old: str, new: str) -> str:
    if old not in text:
        raise RuntimeError(f"Could not find expected block:\n{old[:160]}")
    return text.replace(old, new, 1)


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")
    backup = TARGET.with_name(f"{TARGET.name}.bak_codex_port_cleanup_{time.strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(TARGET, backup)

    if "import json" not in text:
        text = replace_once(text, "import io\n", "import io\nimport json\n")

    if "_EXIT_CALLBACK_ID" not in text:
        text = replace_once(
            text,
            "_SAVE_CALLBACK_ID = None\n",
            "_SAVE_CALLBACK_ID = None\n_EXIT_CALLBACK_ID = None\n",
        )

    if "COMMAND_PORT_SESSION_FILE" not in text:
        text = replace_once(
            text,
            'COMMAND_PORT_FILE = (\n    "C:/Users/Aaron/temp/maya_port.txt"\n)\n',
            'COMMAND_PORT_FILE = (\n'
            '    "C:/Users/Aaron/temp/maya_port.txt"\n'
            ')\n'
            'COMMAND_PORT_SESSION_FILE = (\n'
            '    "C:/Users/Aaron/temp/maya_sessions.json"\n'
            ')\n',
        )

    old_save = '''def save_port_to_file(port):
    try:
        folder = os.path.dirname(COMMAND_PORT_FILE)
        if folder and not os.path.isdir(folder):
            os.makedirs(folder)

        with open(COMMAND_PORT_FILE, "w") as f:
            f.write(str(port))

        log("Saved active commandPort to file: {}".format(port))

    except Exception:
        log_exception("Failed to save commandPort to file.")
'''
    new_save = '''def _current_session_payload(port):
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
'''
    if "def save_session_to_file(port):" not in text:
        text = replace_once(text, old_save, new_save)

    if "def _register_exit_cleanup():" not in text:
        text = replace_once(
            text,
            "\ndef _register_before_save_job():\n",
            '''
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
''',
        )

    if "_register_exit_cleanup()" not in text.split("def create_menu_once():", 1)[-1]:
        text = replace_once(
            text,
            "def create_menu_once():\n    initialize_command_port()\n    _register_before_save_job()\n",
            "def create_menu_once():\n"
            "    initialize_command_port()\n"
            "    _register_exit_cleanup()\n"
            "    _register_before_save_job()\n",
        )

    with TARGET.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    print(f"Updated {TARGET}")
    print(f"Backup {backup}")


if __name__ == "__main__":
    main()
