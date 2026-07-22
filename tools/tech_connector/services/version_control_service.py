"""Version Control System providers and detection logic."""

from __future__ import annotations

import os
import sys
import re
import subprocess
import json
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Optional

from tech_connector.services.diagnostic_service import log_backend_event

def run_cmd(args, cwd, env=None, timeout=30):
    creationflags = 0
    if sys.platform == "win32":
        creationflags = 0x08000000  # CREATE_NO_WINDOW
    try:
        log_backend_event("vcs.command", "Running backend command", command=args, cwd=cwd)
        result = subprocess.run(
            args,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            env=env,
            creationflags=creationflags,
            check=False,
            timeout=timeout,
        )
        log_backend_event(
            "vcs.command",
            "Backend command finished",
            command=args,
            cwd=cwd,
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
        return result
    except subprocess.TimeoutExpired as exc:
        log_backend_event(
            "vcs.command",
            f"Backend command timed out after {timeout}s",
            command=args,
            cwd=cwd,
            returncode=124,
            stdout=exc.stdout,
            stderr=exc.stderr,
        )
        return subprocess.CompletedProcess(
            args,
            returncode=124,
            stdout=exc.stdout or "",
            stderr=(exc.stderr or "") + f"\nCommand timed out after {timeout}s.",
        )

def apply_vcs_settings(settings: Optional[dict]) -> dict:
    """Apply saved VCS account settings to this process environment."""
    settings = settings or {}
    env_updates = {
        "GITHUB_TOKEN": settings.get("github_token", ""),
        "P4PORT": settings.get("p4_port", ""),
        "P4USER": settings.get("p4_user", ""),
        "P4CLIENT": settings.get("p4_client", ""),
        "P4PASSWD": settings.get("p4_passwd", ""),
    }
    for key, value in env_updates.items():
        value = (value or "").strip()
        if value:
            os.environ[key] = value
    return dict(os.environ)


def github_auth_headers(token: Optional[str] = None) -> dict:
    token = (token or os.environ.get("GITHUB_TOKEN") or "").strip()
    headers = {"User-Agent": "AI-Studio"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def test_github_credentials(token: Optional[str] = None) -> tuple[bool, str]:
    token = (token or os.environ.get("GITHUB_TOKEN") or "").strip()
    if not token:
        return False, "No GitHub token configured."
    req = urllib.request.Request("https://api.github.com/user", headers=github_auth_headers(token))
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8", errors="replace"))
        login = data.get("login") or "unknown"
        return True, f"GitHub authenticated as {login}."
    except Exception as exc:
        return False, f"GitHub authentication failed: {exc}"


def test_perforce_credentials(settings: Optional[dict] = None, cwd: Optional[Path] = None) -> tuple[bool, str]:
    env = apply_vcs_settings(settings)
    root = cwd or Path.cwd()
    res = run_cmd(["p4", "info"], root, env=env)
    msg = (res.stdout + res.stderr).strip()
    return res.returncode == 0, msg or "p4 info returned no output."


def list_perforce_users(settings: Optional[dict] = None, cwd: Optional[Path] = None, limit: int = 200) -> tuple[bool, list[str], str]:
    env = apply_vcs_settings(settings)
    root = cwd or Path.cwd()
    res = run_cmd(["p4", "users"], root, env=env)
    msg = (res.stdout + res.stderr).strip()
    if res.returncode != 0:
        return False, [], msg or "p4 users failed."
    users = []
    for line in res.stdout.splitlines():
        parts = line.strip().split()
        if parts and parts[0] not in users:
            users.append(parts[0])
        if len(users) >= limit:
            break
    return True, users, f"Loaded {len(users)} Perforce user(s)."


def list_perforce_clients(
    settings: Optional[dict] = None,
    user: str = "",
    cwd: Optional[Path] = None,
    limit: int = 200,
) -> tuple[bool, list[str], str]:
    env = apply_vcs_settings(settings)
    root = cwd or Path.cwd()
    args = ["p4", "clients"]
    user = (user or "").strip()
    if user:
        args.extend(["-u", user])
    res = run_cmd(args, root, env=env)
    msg = (res.stdout + res.stderr).strip()
    if res.returncode != 0:
        return False, [], msg or "p4 clients failed."
    clients = []
    for line in res.stdout.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and parts[0].lower() == "client" and parts[1] not in clients:
            clients.append(parts[1])
        if len(clients) >= limit:
            break
    return True, clients, f"Loaded {len(clients)} Perforce workspace(s)."


def launch_github_cli_login() -> tuple[bool, str]:
    try:
        creationflags = 0
        if sys.platform == "win32":
            creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        subprocess.Popen(["gh", "auth", "login", "-w"], creationflags=creationflags)
        return True, "Started GitHub CLI login. Finish the browser/terminal prompts, then click Import gh Token."
    except FileNotFoundError:
        return False, (
            "GitHub CLI is not installed or not on PATH. Install GitHub CLI from https://cli.github.com/ "
            "or create a fine-grained token at https://github.com/settings/tokens and paste it here."
        )
    except Exception as exc:
        return False, str(exc)


def github_token_from_cli() -> tuple[bool, str, str]:
    res = run_cmd(["gh", "auth", "token"], Path.cwd())
    token = res.stdout.strip()
    msg = (res.stderr or "").strip()
    if res.returncode == 0 and token:
        return True, token, "Imported token from GitHub CLI."
    return False, "", msg or "Could not read GitHub CLI token. Run GitHub Login first."


def github_user_from_cli() -> tuple[bool, str, str]:
    res = run_cmd(["gh", "api", "user", "--jq", ".login"], Path.cwd())
    user = res.stdout.strip()
    msg = (res.stderr or "").strip()
    if res.returncode == 0 and user:
        return True, user, "Imported GitHub username from gh."
    return False, "", msg or "Could not read GitHub username from gh."

def git_url_to_https(url: str) -> str:
    url = url.strip()
    if url.startswith("git@"):
        match = re.match(r"git@([^:]+):([^/]+)/(.+?)(?:\.git)?$", url)
        if match:
            host, user, repo = match.groups()
            return f"https://{host}/{user}/{repo}"
    if url.startswith("https://") or url.startswith("http://"):
        if url.endswith(".git"):
            return url[:-4]
        return url
    return url


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text or "").strip("._")[:80] or "changelist"


def _repo_root_from_path(path: Path, marker: str) -> Path:
    current = path.resolve()
    if current.is_file():
        current = current.parent
    for parent in [current] + list(current.parents):
        if (parent / marker).exists():
            return parent
    return current


def _parse_git_status_porcelain(text: str) -> list[dict]:
    files = []
    for raw in (text or "").splitlines():
        if not raw.strip():
            continue
        status = raw[:2]
        path_text = raw[3:].strip()
        if " -> " in path_text:
            _old, path_text = path_text.split(" -> ", 1)
        files.append(
            {
                "path": path_text.strip('"'),
                "status": status.strip() or "modified",
                "source": "working_tree",
            }
        )
    return files


def _parse_p4_opened(text: str) -> list[dict]:
    files = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        match = re.match(r"^(?P<depot>//.+?)#\d+\s+-\s+(?P<action>\w+)\s+", line)
        files.append(
            {
                "path": match.group("depot") if match else line,
                "status": match.group("action") if match else "opened",
                "source": "opened",
                "raw": line,
            }
        )
    return files

class VersionControlProvider:
    @property
    def kind(self) -> str:
        raise NotImplementedError

    def detect(self, root: Path) -> bool:
        raise NotImplementedError

    def status(self, root: Path) -> str:
        raise NotImplementedError

    def sync(self, root: Path) -> tuple[bool, str]:
        raise NotImplementedError

    def checkout_file(self, path: Path) -> tuple[bool, str]:
        raise NotImplementedError

    def revert_file(self, path: Path) -> tuple[bool, str]:
        raise NotImplementedError

    def checkout_state(self, path: Path) -> dict:
        return {"kind": self.kind, "label": "Unknown", "detail": "", "active_count": 0}

    def mark_for_add(self, path: Path) -> tuple[bool, str]:
        return True, "No explicit add step required."

    def changed_files(self, root: Path) -> list[dict]:
        return []

    def create_changelist(self, root: Path, description: str, files: list[str] | None = None) -> tuple[bool, str, dict]:
        return False, "Changelists are not supported by this provider.", {}

    def current_changelists(self, root: Path) -> tuple[bool, str, list[dict]]:
        return True, "No native changelists for this provider.", []

class GitProvider(VersionControlProvider):
    @property
    def kind(self) -> str:
        return "git"

    def detect(self, root: Path) -> bool:
        return (root / ".git").exists()

    def status(self, root: Path) -> str:
        res = run_cmd(["git", "status", "-s"], root)
        return res.stdout.strip() or "Clean (Git)"

    def sync(self, root: Path) -> tuple[bool, str]:
        res = run_cmd(["git", "pull"], root)
        ok = (res.returncode == 0)
        msg = res.stdout + res.stderr
        return ok, msg.strip()

    def checkout_file(self, path: Path) -> tuple[bool, str]:
        # Git does not need explicit checkout to edit, return success
        return True, "Git tracks edits automatically; no checkout is required."

    def revert_file(self, path: Path) -> tuple[bool, str]:
        # Try checking out the specific file path
        res = run_cmd(["git", "checkout", "--", str(path)], path.parent)
        if res.returncode != 0:
            # Try git restore
            res = run_cmd(["git", "restore", str(path)], path.parent)
        ok = (res.returncode == 0)
        msg = res.stdout + res.stderr
        return ok, msg.strip() or f"Reverted {path.name}"

    def get_remote_url(self, root: Path) -> str:
        res = run_cmd(["git", "config", "--get", "remote.origin.url"], root)
        url = res.stdout.strip()
        if url:
            return git_url_to_https(url)
        return ""

    def checkout_state(self, path: Path) -> dict:
        root = path if path.is_dir() else path.parent
        res = run_cmd(["git", "status", "--short"], root)
        lines = [line for line in (res.stdout or "").splitlines() if line.strip()]
        branch = ""
        upstream = ""
        ahead = behind = 0
        branch_res = run_cmd(["git", "branch", "--show-current"], root)
        if branch_res.returncode == 0:
            branch = branch_res.stdout.strip()
        upstream_res = run_cmd(["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], root)
        if upstream_res.returncode == 0:
            upstream = upstream_res.stdout.strip()
            ab_res = run_cmd(["git", "rev-list", "--left-right", "--count", f"HEAD...{upstream}"], root)
            if ab_res.returncode == 0:
                parts = ab_res.stdout.strip().split()
                if len(parts) == 2:
                    ahead, behind = int(parts[0] or 0), int(parts[1] or 0)
        dirty = "clean" if not lines else f"{len(lines)} changed"
        sync_bits = []
        if ahead:
            sync_bits.append(f"ahead {ahead}")
        if behind:
            sync_bits.append(f"behind {behind}")
        sync_label = ", ".join(sync_bits) if sync_bits else "in sync"
        branch_label = f" {branch}" if branch else ""
        label = f"Git{branch_label}: {dirty}, {sync_label}"
        return {
            "kind": "git",
            "label": label,
            "detail": "Git does not require checkout; edits are tracked as changed files.",
            "active_count": len(lines),
            "branch": branch,
            "upstream": upstream,
            "ahead": ahead,
            "behind": behind,
            "out_of_sync_count": behind,
            "raw": res.stdout.strip(),
        }

    def mark_for_add(self, path: Path) -> tuple[bool, str]:
        return True, "Git: new file is untracked until you explicitly stage/commit it."

    def changed_files(self, root: Path) -> list[dict]:
        repo_root = _repo_root_from_path(root, ".git")
        status_res = run_cmd(["git", "status", "--porcelain", "-uall"], repo_root)
        files = _parse_git_status_porcelain(status_res.stdout)

        upstream_res = run_cmd(["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], repo_root)
        if upstream_res.returncode == 0:
            upstream = upstream_res.stdout.strip()
            ahead_res = run_cmd(["git", "diff", "--name-status", f"{upstream}...HEAD"], repo_root)
            existing = {item["path"] for item in files}
            for raw in ahead_res.stdout.splitlines():
                parts = raw.split("\t")
                if len(parts) >= 2 and parts[-1] not in existing:
                    files.append({"path": parts[-1], "status": parts[0], "source": f"commits_since_{upstream}"})
        return files

    def create_changelist(self, root: Path, description: str, files: list[str] | None = None) -> tuple[bool, str, dict]:
        repo_root = _repo_root_from_path(root, ".git")
        candidates = self.changed_files(repo_root)
        selected = set(files or [])
        if selected:
            candidates = [item for item in candidates if item.get("path") in selected or str(repo_root / item.get("path", "")) in selected]
        if not candidates:
            return False, "No Git changes found to package.", {}

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = _slug(description or "git_changelist")
        out_dir = repo_root / ".ai_studio" / "changelists" / f"{stamp}_{name}"
        out_dir.mkdir(parents=True, exist_ok=True)
        patch_path = out_dir / "changes.patch"
        summary_path = out_dir / "summary.json"

        diff_res = run_cmd(["git", "diff", "--binary", "HEAD", "--", *[item["path"] for item in candidates if item.get("status") != "??"]], repo_root, timeout=60)
        patch_text = diff_res.stdout or ""
        untracked = [item["path"] for item in candidates if item.get("status") == "??"]
        if untracked:
            patch_text += "\n\n# Untracked files included in this changelist package:\n"
            patch_text += "\n".join(f"# - {path}" for path in untracked)
        patch_path.write_text(patch_text, encoding="utf-8")
        payload = {
            "schema": "ai_studio.git_changelist.v1",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "description": description,
            "repo_root": str(repo_root),
            "files": candidates,
            "path": str(out_dir),
            "patch": str(patch_path),
            "note": "Git has no native pending changelists; this package records the selected changes for review/commit.",
        }
        summary_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return True, f"Created Git changelist package: {out_dir}", payload

    def current_changelists(self, root: Path) -> tuple[bool, str, list[dict]]:
        repo_root = _repo_root_from_path(root, ".git")
        base = repo_root / ".ai_studio" / "changelists"
        items = []
        if base.exists():
            for path in sorted(base.iterdir(), reverse=True):
                summary = path / "summary.json"
                data = {}
                if summary.exists():
                    try:
                        data = json.loads(summary.read_text(encoding="utf-8"))
                    except Exception:
                        data = {}
                items.append(
                    {
                        "id": path.name,
                        "description": data.get("description") or path.name,
                        "path": str(path),
                        "file_count": len(data.get("files") or []),
                        "provider": "git",
                    }
                )
        return True, f"Git changelist packages: {len(items)}", items

class PerforceProvider(VersionControlProvider):
    @property
    def kind(self) -> str:
        return "perforce"

    def detect(self, root: Path) -> bool:
        return bool(os.environ.get("P4PORT")) or (root / ".p4config").exists()

    def status(self, root: Path) -> str:
        res = run_cmd(["p4", "opened"], root)
        return res.stdout.strip() or "No files opened (Perforce)"

    def sync(self, root: Path) -> tuple[bool, str]:
        res = run_cmd(["p4", "sync"], root)
        ok = (res.returncode == 0)
        msg = res.stdout + res.stderr
        return ok, msg.strip()

    def checkout_file(self, path: Path) -> tuple[bool, str]:
        res = run_cmd(["p4", "edit", str(path)], path.parent)
        ok = (res.returncode == 0)
        msg = res.stdout + res.stderr
        return ok, msg.strip()

    def revert_file(self, path: Path) -> tuple[bool, str]:
        res = run_cmd(["p4", "revert", str(path)], path.parent)
        ok = (res.returncode == 0)
        msg = res.stdout + res.stderr
        return ok, msg.strip()

    def checkout_state(self, path: Path) -> dict:
        root = path if path.is_dir() else path.parent
        res = run_cmd(["p4", "opened"], root)
        lines = [line for line in (res.stdout or "").splitlines() if line.strip()]
        if res.returncode != 0:
            return {
                "kind": "perforce",
                "label": "P4 status unknown",
                "detail": (res.stdout + res.stderr).strip(),
                "active_count": 0,
            }
        sync_preview = run_cmd(["p4", "sync", "-n"], root, timeout=15)
        sync_lines = [
            line for line in (sync_preview.stdout or "").splitlines()
            if line.strip() and " - " in line
        ] if sync_preview.returncode == 0 else []
        opened = "none opened" if not lines else f"{len(lines)} opened"
        sync_label = "sync current" if not sync_lines else f"{len(sync_lines)} to sync"
        label = f"P4: {opened}, {sync_label}"
        return {
            "kind": "perforce",
            "label": label,
            "detail": "Perforce requires files to be opened with p4 edit before writing.",
            "active_count": len(lines),
            "out_of_sync_count": len(sync_lines),
            "raw": res.stdout.strip(),
        }

    def mark_for_add(self, path: Path) -> tuple[bool, str]:
        res = run_cmd(["p4", "add", str(path)], path.parent)
        ok = (res.returncode == 0)
        msg = res.stdout + res.stderr
        return ok, msg.strip()

    def changed_files(self, root: Path) -> list[dict]:
        root = root if root.is_dir() else root.parent
        opened = run_cmd(["p4", "opened"], root)
        files = _parse_p4_opened(opened.stdout)
        status = run_cmd(["p4", "status"], root, timeout=30)
        existing = {item["path"] for item in files}
        for raw in status.stdout.splitlines():
            line = raw.strip()
            if not line:
                continue
            path_text = line.split(" - ", 1)[0].strip()
            if path_text and path_text not in existing:
                action = line.split(" - ", 1)[1].split()[0] if " - " in line else "reconcile"
                files.append({"path": path_text, "status": action, "source": "reconcile_preview", "raw": line})
        return files

    def create_changelist(self, root: Path, description: str, files: list[str] | None = None) -> tuple[bool, str, dict]:
        root = root if root.is_dir() else root.parent
        candidates = self.changed_files(root)
        selected = set(files or [])
        if selected:
            candidates = [item for item in candidates if item.get("path") in selected]
        opened = [item["path"] for item in candidates if item.get("source") == "opened"]
        if not opened:
            return False, "No opened Perforce files found. Run p4 edit/add/reconcile first, then create a changelist.", {"files": candidates}

        spec = (
            "Change: new\n\n"
            f"Description:\n\t{(description or 'Tech Connector changelist').replace(chr(10), chr(10) + chr(9))}\n\n"
            "Files:\n"
        )
        # p4 change -i needs stdin; run_cmd does not support it. Use subprocess here to keep the base helper simple.
        creationflags = 0x08000000 if sys.platform == "win32" else 0
        try:
            log_backend_event("vcs.perforce", "Creating Perforce changelist", command=["p4", "change", "-i"], cwd=root)
            proc = subprocess.run(
                ["p4", "change", "-i"],
                cwd=str(root),
                input=spec,
                capture_output=True,
                text=True,
                creationflags=creationflags,
                check=False,
                timeout=30,
            )
        except subprocess.TimeoutExpired as exc:
            output = ((exc.stdout or "") + (exc.stderr or "")).strip()
            log_backend_event(
                "vcs.perforce",
                "Perforce changelist creation timed out",
                command=["p4", "change", "-i"],
                cwd=root,
                returncode=124,
                stdout=exc.stdout,
                stderr=exc.stderr,
            )
            return False, output or "p4 change -i timed out.", {"files": candidates}
        output = (proc.stdout + proc.stderr).strip()
        log_backend_event(
            "vcs.perforce",
            "Perforce changelist creation finished",
            command=["p4", "change", "-i"],
            cwd=root,
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )
        match = re.search(r"Change\s+(\d+)\s+created", output)
        if proc.returncode != 0 or not match:
            return False, output or "p4 change -i failed.", {"files": candidates}
        change_no = match.group(1)
        reopen = run_cmd(["p4", "reopen", "-c", change_no, *opened], root, timeout=60)
        ok = reopen.returncode == 0
        msg = (reopen.stdout + reopen.stderr).strip()
        payload = {"change": change_no, "files": opened, "all_candidates": candidates}
        return ok, (msg or f"Created Perforce changelist {change_no}.") if ok else msg, payload

    def current_changelists(self, root: Path) -> tuple[bool, str, list[dict]]:
        root = root if root.is_dir() else root.parent
        res = run_cmd(["p4", "changes", "-s", "pending"], root, timeout=30)
        msg = (res.stdout + res.stderr).strip()
        if res.returncode != 0:
            return False, msg or "p4 changes failed.", []
        items = []
        for raw in res.stdout.splitlines():
            line = raw.strip()
            match = re.match(r"^Change\s+(\d+)\s+on\s+(\S+)\s+by\s+(\S+)\s+\*pending\*\s+'(.*)'", line)
            if match:
                change, date, user_client, desc = match.groups()
                items.append(
                    {
                        "id": change,
                        "description": desc,
                        "date": date,
                        "owner": user_client,
                        "provider": "perforce",
                    }
                )
            elif line:
                items.append({"id": line, "description": line, "provider": "perforce"})
        return True, f"Perforce pending changelists: {len(items)}", items

def detect_version_control_for_path(path: Path) -> Optional[VersionControlProvider]:
    providers = detect_version_controls_for_path(path)
    return providers[0] if providers else None


def detect_version_controls_for_path(path: Path) -> list[VersionControlProvider]:
    current = path.resolve()
    if current.is_file():
        current = current.parent

    git_prov = GitProvider()
    p4_prov = PerforceProvider()
    providers = []

    try:
        from tech_connector.services.settings_service import load_settings
        import importlib
        settings = load_settings()
        vcs_module_path = settings.get("vcs_provider_module")
        if vcs_module_path and vcs_module_path != "default":
            if "." in vcs_module_path:
                mod_name, class_name = vcs_module_path.rsplit(".", 1)
                mod = importlib.import_module(mod_name)
                vcs_class = getattr(mod, class_name)
                custom_vcs = vcs_class()
                for parent in [current] + list(current.parents):
                    if custom_vcs.detect(parent):
                        providers.append(custom_vcs)
                        break
    except Exception as e:
        print(f"Error loading custom VCS provider: {e}", flush=True)

    for parent in [current] + list(current.parents):
        if git_prov.detect(parent) and not any(p.kind == "git" for p in providers):
            providers.append(git_prov)
        if p4_prov.detect(parent) and not any(p.kind == "perforce" for p in providers):
            providers.append(p4_prov)
        if len(providers) == 2:
            break
    return providers

def launch_github_desktop(root: Path) -> bool:
    localappdata = os.environ.get("LOCALAPPDATA")
    if localappdata:
        github_desktop = Path(localappdata) / "GitHubDesktop" / "GitHubDesktop.exe"
        if github_desktop.exists():
            try:
                subprocess.Popen([str(github_desktop), str(root)])
                return True
            except Exception:
                pass
    # Fallback to git-gui
    try:
        creationflags = 0
        if sys.platform == "win32":
            creationflags = 0x08000000
        subprocess.Popen(["git", "gui"], cwd=str(root), creationflags=creationflags)
        return True
    except Exception:
        return False

def launch_p4v(root: Path) -> bool:
    p4v_path = Path(r"C:\Program Files\Perforce\p4v.exe")
    if p4v_path.exists():
        try:
            subprocess.Popen([str(p4v_path), "-d", str(root)], cwd=str(root))
            return True
        except Exception:
            pass
    return False
