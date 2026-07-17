"""Git-backed application update helpers."""

from dataclasses import dataclass
from pathlib import Path
import subprocess

from tech_connector.services.diagnostic_service import log_backend_event


@dataclass
class UpdateResult:
    ok: bool
    message: str
    output: str = ""
    restart_required: bool = False


def find_repo_root(start=None) -> Path:
    path = Path(start or __file__).resolve()
    if path.is_file():
        path = path.parent

    for candidate in [path] + list(path.parents):
        if (candidate / ".git").exists():
            return candidate

    raise RuntimeError("This copy is not inside a Git checkout.")


class GitUpdater:
    def __init__(self, repo_root=None, runner=None, progress_cb=None):
        self.repo_root = Path(repo_root) if repo_root else find_repo_root(Path(__file__).resolve().parent.parent)
        self.runner = runner or self._run
        self.progress_cb = progress_cb

    def progress(self, message: str) -> None:
        if not self.progress_cb:
            return
        try:
            self.progress_cb(message)
        except Exception:
            pass

    def _run(self, args, timeout=120):
        log_backend_event("app_update.command", "Running app update command", command=args, cwd=self.repo_root)
        result = subprocess.run(
            args,
            cwd=str(self.repo_root),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        log_backend_event(
            "app_update.command",
            "App update command finished",
            command=args,
            cwd=self.repo_root,
            returncode=result.returncode,
            stdout=result.stdout,
        )
        return result

    def git(self, *args, timeout=120):
        self.progress("git " + " ".join(args))
        result = self.runner(["git", *args], timeout=timeout)
        output = (result.stdout or "").strip()
        if result.returncode != 0:
            raise RuntimeError(output or "git " + " ".join(args) + " failed")
        return output

    def status(self) -> UpdateResult:
        try:
            branch = self.git("branch", "--show-current")
            head = self.git("rev-parse", "--short", "HEAD")
            remote = self.git("remote", "get-url", "origin")
            dirty = self.git("status", "--porcelain")
            upstream = self._upstream()

            lines = [
                "Repository: " + str(self.repo_root),
                "Branch: " + (branch or "(detached)"),
                "Commit: " + head,
                "Origin: " + remote,
                "Working tree: " + ("has local changes" if dirty else "clean"),
            ]
            if upstream:
                ahead_behind = self.git("rev-list", "--left-right", "--count", f"HEAD...{upstream}")
                ahead, behind = ahead_behind.split()
                lines.append(f"Tracking: {upstream} ({ahead} ahead, {behind} behind)")
            else:
                lines.append("Tracking: none")

            return UpdateResult(ok=True, message="Git status ready.", output="\n".join(lines))
        except Exception as e:
            return UpdateResult(ok=False, message=str(e))

    def update_latest(self) -> UpdateResult:
        try:
            self.progress("Checking working tree...")
            dirty = self.git("status", "--porcelain")
            if dirty:
                return UpdateResult(
                    ok=False,
                    message="Working tree has local changes. Commit, stash, or discard them before updating.",
                    output=dirty,
                )

            upstream = self._upstream()
            if not upstream:
                return UpdateResult(
                    ok=False,
                    message="Current branch has no upstream. Set an upstream or use Update from Git Ref.",
                )

            before = self.git("rev-parse", "--short", "HEAD")
            self.progress("Fetching updates from remote...")
            fetch_out = self.git("fetch", "--all", "--prune", timeout=240)
            self.progress("Applying fast-forward pull...")
            pull_out = self.git("pull", "--ff-only", timeout=240)
            after = self.git("rev-parse", "--short", "HEAD")
            changed = before != after

            output = "\n".join(part for part in [fetch_out, pull_out, f"{before} -> {after}"] if part)
            return UpdateResult(
                ok=True,
                message="Updated to latest upstream." if changed else "Already at latest upstream.",
                output=output,
                restart_required=changed,
            )
        except Exception as e:
            return UpdateResult(ok=False, message=str(e))

    def update_ref(self, ref: str) -> UpdateResult:
        ref = (ref or "").strip()
        if not ref:
            return UpdateResult(ok=False, message="Enter a branch, tag, or commit SHA.")

        try:
            self.progress("Checking working tree...")
            dirty = self.git("status", "--porcelain")
            if dirty:
                return UpdateResult(
                    ok=False,
                    message="Working tree has local changes. Commit, stash, or discard them before changing refs.",
                    output=dirty,
                )

            before = self.git("rev-parse", "--short", "HEAD")
            self.progress("Fetching refs from remote...")
            fetch_out = self.git("fetch", "--all", "--prune", timeout=240)
            self.progress(f"Checking out {ref}...")
            checkout_out = self.git("checkout", ref, timeout=120)
            after = self.git("rev-parse", "--short", "HEAD")
            changed = before != after
            output = "\n".join(part for part in [fetch_out, checkout_out, f"{before} -> {after}"] if part)
            return UpdateResult(
                ok=True,
                message=f"Updated to Git ref: {ref}",
                output=output,
                restart_required=changed,
            )
        except Exception as e:
            return UpdateResult(ok=False, message=str(e))

    def _upstream(self) -> str:
        try:
            return self.git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
        except Exception:
            return ""
