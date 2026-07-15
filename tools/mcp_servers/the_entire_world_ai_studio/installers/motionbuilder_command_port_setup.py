"""
Run this in MotionBuilder's Python editor/startup to enable The Entire World Tech Connector.

Default port: 7011

This creates a tiny localhost Python socket server that can execute code sent by
the MotionBuilder MCP server and return printed output.
"""

import base64
import socket
import sys
import threading
import traceback

try:
    from pyfbsdk import FBSystem
except Exception:
    FBSystem = None


_HOST = "127.0.0.1"
_PORT = 7011


def mobu_execute_and_capture(encoded_payload):
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


def _client_thread(conn):
    with conn:
        data = b""
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                break
            data += chunk
            if b"\n" in chunk:
                break

        request = data.decode("utf-8", errors="replace").strip()

        result = ""
        try:
            # Expected: mobu_execute_and_capture('base64...')
            ns = {"mobu_execute_and_capture": mobu_execute_and_capture}
            result = str(eval(request, ns, ns))
        except Exception:
            result = traceback.format_exc()

        conn.sendall((result + "\x00").encode("utf-8", errors="replace"))


def start_motionbuilder_ai_port(port=_PORT):
    def server():
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((_HOST, port))
        s.listen(5)
        print("The Entire World AI MotionBuilder socket server running on %s:%s" % (_HOST, port))

        while True:
            conn, _addr = s.accept()
            threading.Thread(target=_client_thread, args=(conn,), daemon=True).start()

    threading.Thread(target=server, daemon=True).start()


start_motionbuilder_ai_port()