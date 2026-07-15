"""GitHub ingestion service preserving repo folder structure and supporting main/master fallback."""

from dataclasses import dataclass
import io
import json
import shutil
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

try:
    from services.version_control_service import github_auth_headers
except Exception:
    def github_auth_headers(_token=None):
        return {"User-Agent": "AI-Studio"}

MAX_REPO_ZIP_BYTES = 250 * 1024 * 1024
MAX_EXTRACTED_FILES = 25_000
MAX_EXTRACTED_BYTES = 750 * 1024 * 1024


@dataclass(frozen=True)
class GitHubRepoRef:
    owner: str
    repo: str
    ref: Optional[str] = None
    ref_kind: str = "branch"

    @property
    def clean_url(self) -> str:
        return f"https://github.com/{self.owner}/{self.repo}"

    @property
    def api_url(self) -> str:
        return f"https://api.github.com/repos/{self.owner}/{self.repo}"

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repo}"


def parse_github_repo_reference(repo_ref: str) -> GitHubRepoRef:
    """Parse GitHub URL, shorthand, or SSH repo references into a canonical ref."""
    text = (repo_ref or "").strip().rstrip("/")
    if not text:
        raise ValueError("Expected a GitHub repository URL or owner/repo reference.")

    if text.startswith("git@github.com:"):
        parts = [part for part in text[len("git@github.com:"):].split("/") if part]
    else:
        if text.startswith("github.com/"):
            text = "https://" + text
        if "://" not in text and "/" in text and not text.startswith("/"):
            parts = [part for part in text.split("/") if part]
        else:
            parsed = urllib.parse.urlparse(text)
            host = parsed.netloc.lower()
            if parsed.scheme not in {"http", "https"} or host not in {"github.com", "www.github.com"}:
                raise ValueError(f"Only GitHub repository URLs are supported, got: {repo_ref}")
            parts = [part for part in parsed.path.split("/") if part]

    if len(parts) < 2:
        raise ValueError(f"Expected a GitHub repository URL, got: {repo_ref}")

    owner = urllib.parse.unquote(parts[0])
    repo = urllib.parse.unquote(parts[1])
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not owner or not repo or any(part in {".", ".."} for part in (owner, repo)):
        raise ValueError(f"Expected a GitHub repository URL, got: {repo_ref}")

    ref = None
    ref_kind = "branch"
    if len(parts) >= 4 and parts[2] == "tree":
        ref = "/".join(urllib.parse.unquote(part) for part in parts[3:])
    elif len(parts) >= 5 and parts[2] == "releases" and parts[3] == "tag":
        ref = urllib.parse.unquote(parts[4])
        ref_kind = "tag"
    elif len(parts) >= 4 and parts[2] == "commit":
        ref = urllib.parse.unquote(parts[3])
        ref_kind = "commit"

    return GitHubRepoRef(owner=owner, repo=repo, ref=ref, ref_kind=ref_kind)


def _utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _write_ingest_log(target_dir: Path, events: list[dict]) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "ai_studio_ingest_log.json").write_text(json.dumps(events, indent=2), encoding="utf-8")


def _log_event(events: list[dict], target_dir: Path, event: str, **details) -> None:
    entry = {"time": _utc_now(), "event": event}
    if details:
        entry.update(details)
    events.append(entry)
    try:
        _write_ingest_log(target_dir, events)
    except Exception:
        pass


def _safe_repo_dir_name(repo_name: str, repo_url: str) -> str:
    raw_name = (repo_name or "").strip()
    if not raw_name:
        clean_url, _ = normalize_github_repo_url(repo_url)
        raw_name = "/".join(urllib.parse.urlparse(clean_url).path.strip("/").split("/")[:2])
    clean = "".join(ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in raw_name.replace("/", "_"))
    return clean.strip("._") or "github_repo"


def _unique_target_dir(target_parent_dir: Path, repo_name: str, repo_url: str) -> Path:
    base = _safe_repo_dir_name(repo_name, repo_url)
    candidate = target_parent_dir / base
    if not candidate.exists() or not any(candidate.iterdir()):
        return candidate
    for index in range(2, 1000):
        candidate = target_parent_dir / f"{base}_{index}"
        if not candidate.exists() or not any(candidate.iterdir()):
            return candidate
    raise ValueError(f"Could not find an available ingest folder for {repo_name!r}")


def normalize_github_repo_url(repo_url: str) -> tuple[str, Optional[str]]:
    ref = parse_github_repo_reference(repo_url)
    branch = ref.ref if ref.ref_kind == "branch" else None
    return ref.clean_url, branch


def github_zip_urls(repo_url: str) -> list[str]:
    ref = parse_github_repo_reference(repo_url)
    if ref.ref and ref.ref_kind == "tag":
        return [f"{ref.clean_url}/archive/refs/tags/{urllib.parse.quote(ref.ref, safe='/')}.zip"]
    if ref.ref and ref.ref_kind == "commit":
        return [f"{ref.clean_url}/archive/{urllib.parse.quote(ref.ref, safe='')}.zip"]

    branches = [ref.ref] if ref.ref else ["main", "master"]
    return [f"{ref.clean_url}/archive/refs/heads/{urllib.parse.quote(item, safe='/')}.zip" for item in branches]


def github_api_repo_url(repo_ref: str) -> str:
    return parse_github_repo_reference(repo_ref).api_url


def _emit_progress(progress_cb: Optional[Callable], message: str, current: int = 0, total: int = 0) -> None:
    if not progress_cb:
        return
    try:
        progress_cb(message, current, total)
    except TypeError:
        progress_cb(message)
    except Exception:
        pass


def download_and_extract_repo(repo_name: str, repo_url: str, target_parent_dir: Path, progress_cb=None) -> Path:
    target_parent_dir = Path(target_parent_dir).expanduser().resolve()
    target_parent_dir.mkdir(parents=True, exist_ok=True)
    target_dir = _unique_target_dir(target_parent_dir, repo_name, repo_url)
    target_dir.mkdir(parents=True, exist_ok=True)
    events = []
    _log_event(events, target_dir, "ingest_started", repo_name=repo_name, repo_url=repo_url)
    
    zip_urls = github_zip_urls(repo_url)
    zip_data = None
    last_err = None
    
    for url in zip_urls:
        _emit_progress(progress_cb, f"Downloading from {url}...", 0, 0)
        try:
            _log_event(events, target_dir, "download_attempt_started", url=url)
            req = urllib.request.Request(url, headers=github_auth_headers())
            with urllib.request.urlopen(req, timeout=15) as response:
                total_bytes = int(response.headers.get("Content-Length") or 0)
                chunks = []
                downloaded = 0
                while True:
                    chunk = response.read(1024 * 256)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    downloaded += len(chunk)
                    if downloaded > MAX_REPO_ZIP_BYTES:
                        raise IOError(f"Repository zip is too large: {downloaded} bytes")
                    _emit_progress(
                        progress_cb,
                        f"Downloading repository zip: {downloaded // 1024:,} KB"
                        + (f" / {total_bytes // 1024:,} KB" if total_bytes else ""),
                        downloaded,
                        total_bytes,
                    )
                zip_data = b"".join(chunks)
            if len(zip_data) > MAX_REPO_ZIP_BYTES:
                raise IOError(f"Repository zip is too large: {len(zip_data)} bytes")
            _log_event(events, target_dir, "download_attempt_finished", url=url, bytes=len(zip_data))
            break
        except Exception as e:
            last_err = e
            _log_event(events, target_dir, "download_attempt_failed", url=url, error=str(e))
            
    if not zip_data:
        _log_event(events, target_dir, "ingest_failed", error=str(last_err))
        raise IOError(f"Failed to download repository from candidates {zip_urls}. Error: {last_err}")
        
    _emit_progress(progress_cb, "Extracting repository preserving structure...", 0, 0)
        
    extracted_files = 0
    temp_dir = target_dir.parent / f".{target_dir.name}.extracting"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(zip_data)) as zip_ref:
        namelist = zip_ref.namelist()
        if not namelist:
            _log_event(events, target_dir, "ingest_failed", error="Empty zip archive received.")
            raise ValueError("Empty zip archive received.")
            
        root_prefix = namelist[0].split("/")[0] + "/"
        resolved_target_dir = temp_dir.resolve()
        extracted_bytes = 0
        
        for info in zip_ref.infolist():
            member = info.filename
            if member.endswith("/"):
                continue
                
            rel = member.replace(root_prefix, "", 1)
            if not rel:
                continue
            normalized_rel = rel.replace("\\", "/")
            first_part = Path(normalized_rel).parts[0] if Path(normalized_rel).parts else ""
            if (
                normalized_rel.startswith("/")
                or ":" in first_part
                or any(part in {"", ".", ".."} for part in normalized_rel.split("/"))
            ):
                _log_event(events, target_dir, "ingest_failed", error=f"Unsafe archive member path: {member}")
                raise ValueError(f"Unsafe archive member path: {member}")
            if extracted_files >= MAX_EXTRACTED_FILES:
                raise IOError(f"Repository archive has too many files: more than {MAX_EXTRACTED_FILES}")
            extracted_bytes += int(info.file_size or 0)
            if extracted_bytes > MAX_EXTRACTED_BYTES:
                raise IOError(f"Repository archive expands too large: more than {MAX_EXTRACTED_BYTES} bytes")
                
            target = temp_dir / normalized_rel
            resolved_target = target.resolve()
            if resolved_target_dir != resolved_target and resolved_target_dir not in resolved_target.parents:
                _log_event(events, target_dir, "ingest_failed", error=f"Unsafe archive member path: {member}")
                raise ValueError(f"Unsafe archive member path: {member}")
            target.parent.mkdir(parents=True, exist_ok=True)
            
            with zip_ref.open(member) as source, open(target, "wb") as f:
                shutil.copyfileobj(source, f)
            extracted_files += 1
            if extracted_files == 1 or extracted_files % 25 == 0:
                _emit_progress(
                    progress_cb,
                    f"Extracting files: {extracted_files:,} / {len(namelist):,}",
                    extracted_files,
                    len(namelist),
                )

    for extracted in temp_dir.iterdir():
        destination = target_dir / extracted.name
        if destination.exists():
            if destination.is_dir():
                shutil.rmtree(destination)
            else:
                destination.unlink()
        shutil.move(str(extracted), str(destination))
    shutil.rmtree(temp_dir)

    _log_event(events, target_dir, "extract_finished", files=extracted_files)
    _log_event(events, target_dir, "ingest_finished", path=str(target_dir))
    _emit_progress(progress_cb, f"Ingest complete: {target_dir}", 1, 1)
                
    return target_dir


def ingest_github_repo(repo_ref: GitHubRepoRef, target_dir: Path, progress_cb=None) -> dict:
    """Compatibility wrapper used by acquisition flows.

    target_dir names the desired local repo folder. The structured extractor still
    owns collision handling and returns the actual created path.
    """
    try:
        repo_ref = repo_ref if isinstance(repo_ref, GitHubRepoRef) else parse_github_repo_reference(str(repo_ref))
        target_dir = Path(target_dir).expanduser().resolve()
        local_path = download_and_extract_repo(
            target_dir.name or repo_ref.repo,
            repo_ref.clean_url + (f"/tree/{repo_ref.ref}" if repo_ref.ref and repo_ref.ref_kind == "branch" else ""),
            target_dir.parent,
            progress_cb=progress_cb,
        )
        return {"ok": True, "path": str(local_path)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
