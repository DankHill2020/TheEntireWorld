"""Pump an isolated Maya 2023 bridge for cross-DCC pipeline qualification."""

import maya.standalone

maya.standalone.initialize(name="python")

import os  # noqa: E402
if os.environ.get("TC_MAYA_BENCHMARK_STATIC_CUBE") == "1":
    import maya.cmds as cmds  # noqa: E402

    cmds.file(new=True, force=True)
    cmds.polyCube(name="MayaPromptCube", width=2, height=2, depth=2)
elif os.environ.get("TC_MAYA_BENCHMARK_MESHES") == "two_props":
    import maya.cmds as cmds  # noqa: E402

    cmds.file(new=True, force=True)
    cmds.polyCube(name="Crate_A", width=2, height=2, depth=2)
    cmds.polyCylinder(name="Barrel_B", radius=1, height=2, subdivisionsX=12)

import maya.utils  # noqa: E402
import queue  # noqa: E402
import threading  # noqa: E402
from maya_tools import maya_menu  # noqa: E402
from PySide2.QtCore import QCoreApplication, QTimer  # noqa: E402


# Maya's desktop event loop services executeInMainThreadWithResult. The
# standalone fixture has only a Qt event loop, so supply the equivalent
# main-thread handoff without changing the production bridge implementation.
_main_thread = threading.current_thread()
_main_thread_calls = queue.Queue()
_long_operation = os.environ.get("TC_MAYA_BENCHMARK_LONG_OPERATION") == "1"


def _execute_on_fixture_main_thread(callback):
    if threading.current_thread() is _main_thread:
        return callback()
    completed = threading.Event()
    result = {}
    _main_thread_calls.put((callback, completed, result))
    if not completed.wait(360 if _long_operation else 110):
        raise TimeoutError("Standalone Maya main-thread dispatcher did not respond.")
    if "error" in result:
        raise result["error"]
    return result.get("value")


def _drain_main_thread_calls():
    while True:
        try:
            callback, completed, result = _main_thread_calls.get_nowait()
        except queue.Empty:
            return
        try:
            result["value"] = callback()
        except BaseException as exc:
            result["error"] = exc
        finally:
            completed.set()


maya.utils.executeInMainThreadWithResult = _execute_on_fixture_main_thread

port = maya_menu.initialize_command_port()
print("TC_LIVE_MAYA_HOST_READY", port, flush=True)
application = QCoreApplication.instance() or QCoreApplication([])
print("TC_LIVE_MAYA_EVENT_LOOP", type(application).__name__, flush=True)
idle_timer = QTimer()
idle_timer.timeout.connect(maya.utils.processIdleEvents)
idle_timer.start(5)
bridge_timer = QTimer()
bridge_timer.timeout.connect(_drain_main_thread_calls)
bridge_timer.start(5)
QTimer.singleShot(420000 if _long_operation else 120000, application.quit)
application.exec_()
