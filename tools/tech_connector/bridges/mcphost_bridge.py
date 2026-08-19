"""MCPHost terminal bridge."""

import atexit
import os
import queue
import subprocess
import sys
import threading
import time

from PySide6.QtCore import QObject, Signal


class TerminalBridge(QObject):
    output = Signal(str)
    exited = Signal(str)

    def __init__(self):
        super().__init__()
        self.mode = None
        self.pty = None
        self.proc = None
        self.running = False
        self.thread = None
        self._emit_queue = queue.Queue()
        self._emit_thread = None
        atexit.register(self.stop)

    def start(self, command_args, env=None, use_pty=False):
        """
        Start MCPHost.

        Default is normal subprocess pipes, not PTY. MCPHost's terminal UI works visually
        in a real terminal, but PTY mode is fragile when driven from a GUI.
        """
        if self.running:
            return
        if self.proc is not None or self.pty is not None:
            self.stop()

        self.running = True
        self._emit_queue = queue.Queue()
        env_full = os.environ.copy()
        launch_env = dict(env or {})
        python_dir = os.path.dirname(sys.executable)
        current_path = launch_env.get("PATH", env_full.get("PATH", ""))
        launch_env["PATH"] = os.pathsep.join(
            part for part in (python_dir, current_path) if part
        )
        env_full.update(launch_env)

        if use_pty:
            try:
                import winpty

                self.mode = "pty"
                self.pty = winpty.PTY(160, 48)
                command_line = subprocess.list2cmdline(command_args)

                old_env = {}
                for key, value in launch_env.items():
                    old_env[key] = os.environ.get(key)
                    os.environ[key] = value

                try:
                    self.pty.spawn(command_line)
                finally:
                    for key, old_value in old_env.items():
                        if old_value is None:
                            os.environ.pop(key, None)
                        else:
                            os.environ[key] = old_value

                self._emit_output("[PTY active]\n")
                self.thread = threading.Thread(target=self._read_pty, daemon=True)
                self.thread.start()
                self._ensure_emit_thread()
                return
            except Exception as e:
                self._emit_output(f"[PTY unavailable, using subprocess pipes: {e}]\n")

        self.mode = "pipes"
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        try:
            self.proc = subprocess.Popen(
                command_args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env_full,
                bufsize=1,
                shell=False,
                creationflags=creationflags,
            )
        except Exception as e:
            self.running = False
            self.exited.emit(f"Failed to start MCPHost: {e}")
            return

        self._emit_output("[subprocess pipe active]\n")
        self.thread = threading.Thread(target=self._read_pipes, daemon=True)
        self.thread.start()
        self._ensure_emit_thread()

    def _ensure_emit_thread(self):
        if self._emit_thread and self._emit_thread.is_alive():
            return
        self._emit_thread = threading.Thread(target=self._emit_loop, daemon=True)
        self._emit_thread.start()

    def _emit_output(self, text):
        if not text:
            return
        try:
            self._emit_queue.put_nowait(text)
        except Exception:
            pass

    def _emit_loop(self):
        pending = []
        pending_size = 0
        last_flush = time.monotonic()
        while self.running or not self._emit_queue.empty() or pending:
            try:
                item = self._emit_queue.get(timeout=0.015)
                if item:
                    pending.append(item)
                    pending_size += len(item)
            except Exception:
                pass
            now = time.monotonic()
            if pending and (
                pending_size >= 4096 or (now - last_flush) >= 0.08 or not self.running
            ):
                self.output.emit("".join(pending))
                pending = []
                pending_size = 0
                last_flush = now

    def _read_pty(self):
        consecutive_errors = 0
        try:
            while self.running and self.pty:
                try:
                    try:
                        data = self.pty.read(blocking=True)
                    except TypeError:
                        data = self.pty.read(True)

                    consecutive_errors = 0
                    if data:
                        self._emit_output(data)
                    else:
                        time.sleep(0.03)

                except EOFError:
                    break
                except Exception as e:
                    consecutive_errors += 1
                    msg = str(e).strip()

                    if not msg and consecutive_errors < 10:
                        time.sleep(0.1)
                        continue

                    self._emit_output(
                        f"\n[PTY read warning: {msg or 'transient empty read'}]\n"
                    )

                    if consecutive_errors >= 10:
                        break

                    time.sleep(0.1)
        finally:
            self.running = False
            self.exited.emit("MCPHost exited.")

    def _read_pipes(self):
        try:
            import ctypes
            import msvcrt

            kernel32 = ctypes.windll.kernel32
        except Exception:
            kernel32 = None

        try:
            while self.running:
                proc = self.proc
                if proc is None:
                    break
                avail = 0
                if os.name == "nt" and kernel32:
                    try:
                        if proc.stdout is None:
                            break
                        fd = proc.stdout.fileno()
                        handle = msvcrt.get_osfhandle(fd)
                        avail_bytes = ctypes.c_ulong()
                        if kernel32.PeekNamedPipe(
                            handle, None, 0, None, ctypes.byref(avail_bytes), None
                        ):
                            avail = avail_bytes.value
                    except Exception:
                        pass
                else:
                    import select

                    try:
                        if proc.stdout is None:
                            break
                        r, _, _ = select.select([proc.stdout], [], [], 0)
                        avail = 1 if r else 0
                    except Exception:
                        avail = 1

                if avail > 0:
                    read_size = 128 if avail <= 128 else min(avail, 1024)
                    data = proc.stdout.read(read_size) if proc.stdout else ""
                    if data:
                        self._emit_output(data)
                        continue

                if proc.poll() is not None:
                    try:
                        remaining = proc.stdout.read() if proc.stdout else ""
                        if remaining:
                            self._emit_output(remaining)
                    except Exception:
                        pass
                    break
                time.sleep(0.01)
        finally:
            self.running = False
            self.exited.emit("MCPHost exited.")

    def _one_line_prompt(self, text: str) -> str:
        """
        MCPHost is an interactive terminal prompt. Sending literal newlines can submit
        partial prompts early. Convert multiline text into one terminal line with visible
        \\n escapes.
        """
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        return text.replace("\n", "\\n")

    def write(self, text):
        if not self.running:
            return False

        line = self._one_line_prompt(text)

        try:
            if self.mode == "pty" and self.pty:
                self.pty.write("\x1b[200~")
                self.pty.write(line)
                self.pty.write("\x1b[201~")
                self.pty.write("\r")
                return True

            if self.mode == "pipes" and self.proc and self.proc.stdin:
                self.proc.stdin.write(line + "\n")
                self.proc.stdin.flush()
                return True
        except Exception as e:
            self._emit_output(f"\n[Send failed: {e}]\n")
            return False

        return False

    def interrupt(self):
        """Send Ctrl+C to cancel current active generation/step."""
        if not self.running:
            return False
        try:
            if self.mode == "pty" and self.pty:
                self.pty.write("\x03")
                return True
            if self.mode == "pipes" and self.proc:
                if self.proc.stdin:
                    try:
                        self.proc.stdin.write("\x03\n")
                        self.proc.stdin.flush()
                    except Exception:
                        pass
                if os.name == "nt":
                    # On Windows, generate a CTRL_C_EVENT to the process group.
                    # Note: this requires generating it to process group or sending SIGINT if supported.
                    # We can use taskkill or send Ctrl+C event. Let's do GenerateConsoleCtrlEvent:
                    import ctypes

                    ctypes.windll.kernel32.GenerateConsoleCtrlEvent(0, self.proc.pid)
                else:
                    import signal

                    os.kill(self.proc.pid, signal.SIGINT)
                return True
        except Exception as e:
            self._emit_output(f"\n[Interrupt failed: {e}]\n")
            return False
        return False

    def stop(self):
        """Stop and reap the owned MCPHost process; safe to call repeatedly."""
        self.running = False
        pty = self.pty
        self.pty = None
        try:
            if self.mode == "pty" and pty:
                pty.close()
        except Exception:
            pass

        proc = self.proc
        self.proc = None
        try:
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    if os.name == "nt":
                        subprocess.run(
                            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                            capture_output=True,
                            check=False,
                        )
                    else:
                        proc.kill()
                    proc.wait(timeout=1.0)
        except Exception:
            try:
                if proc and proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=1.0)
            except Exception:
                pass
        finally:
            if proc:
                for stream_name in ("stdin", "stdout", "stderr"):
                    stream = getattr(proc, stream_name, None)
                    try:
                        if stream:
                            stream.close()
                    except Exception:
                        pass
        self.mode = None
        return True
