"""
Run this in MotionBuilder's Python editor/startup to enable The Entire World Tech Connector.

Default port: 7011

This creates a tiny localhost Python socket server that can execute code sent by
the MotionBuilder MCP server and return printed output.
"""

import base64
import ast
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
_MAX_REQUEST_BYTES = 16 * 1024 * 1024


def mobu_execute_and_capture(encoded_payload):
    """
    Executes a base64-encoded Python payload in the MotionBuilder session.

    :param encoded_payload: UTF-8 Python source encoded as base64
    :return: captured standard output and error text
    """
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


def _parse_request(request):
    """
    Parses the bridge's single supported RPC call without evaluating input.

    :param request: command-port request text
    :return: encoded payload argument
    """
    expression = ast.parse(request, filename="<motionbuilder-command-port>", mode="eval")
    call = expression.body
    if not isinstance(call, ast.Call) or call.keywords:
        raise ValueError("Expected mobu_execute_and_capture(<base64 payload>).")
    if not isinstance(call.func, ast.Name) or call.func.id != "mobu_execute_and_capture":
        raise ValueError("Unsupported MotionBuilder command-port operation.")
    if len(call.args) != 1:
        raise ValueError("Expected exactly one encoded payload argument.")
    payload = ast.literal_eval(call.args[0])
    if not isinstance(payload, str):
        raise TypeError("The encoded payload must be a string.")
    return payload


def _client_thread(conn):
    """
    Handles one local command-port request.

    :param conn: accepted client socket
    :return: None
    """
    with conn:
        conn.settimeout(30.0)
        data = b""
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                break
            data += chunk
            if len(data) > _MAX_REQUEST_BYTES:
                raise ValueError("MotionBuilder command-port request is too large.")
            if b"\n" in chunk:
                break

        request = data.decode("utf-8", errors="replace").strip()

        result = ""
        try:
            # Expected: mobu_execute_and_capture('base64...')
            result = str(mobu_execute_and_capture(_parse_request(request)))
        except Exception:
            result = traceback.format_exc()

        conn.sendall((result + "\x00").encode("utf-8", errors="replace"))


def start_motionbuilder_ai_port(port=_PORT):
    """
    Starts the loopback-only MotionBuilder command-port server.

    :param port: local TCP port to bind
    :return: None
    """
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
