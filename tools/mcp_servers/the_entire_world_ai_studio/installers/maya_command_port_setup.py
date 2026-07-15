import base64
import sys
import traceback

import maya.cmds as cmds


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