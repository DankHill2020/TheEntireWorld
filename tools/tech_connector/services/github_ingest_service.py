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
    from tech_connector.services.version_control_service import github_auth_headers
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


def _get_github_ingest_module_path(settings) -> str:
    prov_type = settings.get("github_ingest_provider_type", "default")
    if prov_type == "mod_tech_labs":
        return "tech_connector.services.custom_providers.mod_tech_labs_ingest"
    elif prov_type == "custom":
        return settings.get("github_ingest_provider_module", "default")
    return "default"


def parse_github_repo_reference(repo_ref: str) -> GitHubRepoRef:
    try:
        from tech_connector.services.settings_service import load_settings
        settings = load_settings()
        custom_module = _get_github_ingest_module_path(settings)
        if custom_module and custom_module != "default":
            from tech_connector.services.modular_provider_utils import invoke_custom_provider, resolve_custom_provider_binding
            return invoke_custom_provider(
                resolve_custom_provider_binding("github_ingest_module", custom_module, "parse_github_repo_reference", settings),
                _parse_github_repo_reference_impl,
                repo_ref
            )
    except Exception as e:
        print(f"Error calling custom parse_github_repo_reference: {e}", flush=True)
    return _parse_github_repo_reference_impl(repo_ref)

def _parse_github_repo_reference_impl(repo_ref: str) -> GitHubRepoRef:
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


def _repository_license(repo_dir: Path) -> tuple[str, str]:
    """Return a conservative license label and relative evidence path."""

    candidates = sorted(
        (
            path
            for path in repo_dir.rglob("*")
            if path.is_file()
            and (
                path.name.casefold().startswith("license")
                or path.name.casefold() in {"copying", "copying.txt", "unlicense"}
            )
        ),
        key=lambda path: (len(path.relative_to(repo_dir).parts), str(path)),
    )
    if not candidates:
        return "Unknown - review required", ""
    path = candidates[0]
    try:
        text = path.read_text(encoding="utf-8", errors="replace")[:32_000]
    except OSError:
        text = ""
    lowered = text.casefold()
    markers = (
        ("mit license", "MIT"),
        ("apache license", "Apache-2.0"),
        ("gnu lesser general public license", "LGPL"),
        ("gnu general public license", "GPL"),
        ("mozilla public license", "MPL-2.0"),
        ("bsd license", "BSD"),
        ("the unlicense", "Unlicense"),
        ("cc0", "CC0"),
    )
    license_name = next(
        (label for marker, label in markers if marker in lowered),
        "Present - review required",
    )
    return license_name, str(path.relative_to(repo_dir)).replace("\\", "/")


def write_repository_attribution(
    repo_dir: Path,
    repo_ref: GitHubRepoRef,
    *,
    archive_url: str = "",
    archive_sha256: str = "",
) -> dict:
    """Write mandatory local credit metadata for downloaded source code."""

    repo_dir = Path(repo_dir)
    license_name, license_file = _repository_license(repo_dir)
    verified_license = license_name not in {
        "Unknown - review required",
        "Present - review required",
    }
    payload = {
        "schema": "tech_connector.third_party_source_attribution.v1",
        "source_type": "github_repository",
        "repository": repo_ref.full_name,
        "creator": repo_ref.owner,
        "repository_url": repo_ref.clean_url,
        "requested_ref": repo_ref.ref or "",
        "requested_ref_kind": repo_ref.ref_kind or "",
        "archive_url": archive_url,
        "archive_sha256": archive_sha256,
        "downloaded_at": _utc_now(),
        "license": license_name,
        "license_file": license_file,
        "license_verified": verified_license,
        "attribution": (
            f"Third-party source from {repo_ref.full_name} "
            f"({repo_ref.clean_url}); retain its license and source credit."
        ),
        "usage_policy": (
            "Downloaded source is review-only until a callable is AST-verified "
            "and license terms are accepted."
        ),
    }
    manifest_path = repo_dir / "TECH_CONNECTOR_ATTRIBUTION.json"
    manifest_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    payload["manifest_path"] = str(manifest_path)

    if verified_license:
        try:
            from tech_connector.services.knowledge_credits_service import (
                register_open_knowledge_sources,
            )
            credit_result = register_open_knowledge_sources(
                [{
                    "title": repo_ref.full_name,
                    "creator": repo_ref.owner,
                    "url": repo_ref.clean_url,
                    "license": license_name,
                    "attribution": payload["attribution"],
                    "public_access": True,
                    "access": "public",
                }],
                what_learned="Reviewed source repository acquired for callable discovery.",
                domains=["third_party_code", "capability_acquisition"],
            )
            payload["credits_registry"] = str(credit_result.get("path") or "")
        except Exception as exc:
            payload["credits_error"] = f"{type(exc).__name__}: {exc}"
        manifest_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    return payload


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


def safe_extract_zip_to_dir(
    zip_data: bytes,
    target_dir: Path,
    *,
    strip_single_root: bool = True,
    max_files: int = MAX_EXTRACTED_FILES,
    max_bytes: int = MAX_EXTRACTED_BYTES,
    progress_cb=None,
) -> int:
    """Extract a zip archive while enforcing path, file count, and size limits."""
    target_dir = Path(target_dir).expanduser().resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    extracted_files = 0
    extracted_bytes = 0
    with zipfile.ZipFile(io.BytesIO(zip_data)) as zip_ref:
        infos = zip_ref.infolist()
        if not infos:
            raise ValueError("Empty zip archive received.")
        names = [info.filename.replace("\\", "/") for info in infos if info.filename]
        root_prefix = ""
        if strip_single_root:
            file_names = [name for name in names if not name.endswith("/")]
            top_parts = {name.split("/", 1)[0] for name in file_names if "/" in name}
            if top_parts and len(top_parts) == 1:
                top_part = next(iter(top_parts))
                if top_part not in {"", ".", ".."} and ":" not in top_part and all(name.startswith(top_part + "/") for name in file_names):
                    root_prefix = top_part + "/"
        for info in infos:
            member = info.filename.replace("\\", "/")
            if not member or member.endswith("/"):
                continue
            rel = member[len(root_prefix):] if root_prefix and member.startswith(root_prefix) else member
            if not rel:
                continue
            parts = rel.split("/")
            first_part = parts[0] if parts else ""
            if rel.startswith("/") or ":" in first_part or any(part in {"", ".", ".."} for part in parts):
                raise ValueError(f"Unsafe archive member path: {info.filename}")
            if extracted_files >= max_files:
                raise IOError(f"Repository archive has too many files: more than {max_files}")
            extracted_bytes += int(info.file_size or 0)
            if extracted_bytes > max_bytes:
                raise IOError(f"Repository archive expands too large: more than {max_bytes} bytes")
            destination = (target_dir / rel).resolve()
            if destination != target_dir and target_dir not in destination.parents:
                raise ValueError(f"Unsafe archive member path: {info.filename}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            with zip_ref.open(info) as source, open(destination, "wb") as target:
                shutil.copyfileobj(source, target)
            extracted_files += 1
            if extracted_files == 1 or extracted_files % 25 == 0:
                _emit_progress(progress_cb, f"Extracting files: {extracted_files:,} / {len(infos):,}", extracted_files, len(infos))
    return extracted_files


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
    try:
        from tech_connector.services.settings_service import load_settings
        settings = load_settings()
        custom_module = _get_github_ingest_module_path(settings)
        if custom_module and custom_module != "default":
            from tech_connector.services.modular_provider_utils import invoke_custom_provider, resolve_custom_provider_binding
            return invoke_custom_provider(
                resolve_custom_provider_binding("github_ingest_module", custom_module, "github_api_repo_url", settings),
                _github_api_repo_url_impl,
                repo_ref
            )
    except Exception as e:
        print(f"Error calling custom github_api_repo_url: {e}", flush=True)
    return _github_api_repo_url_impl(repo_ref)

def _github_api_repo_url_impl(repo_ref: str) -> str:
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
    custom_module = "default"
    try:
        from tech_connector.services.settings_service import load_settings
        settings = load_settings()
        custom_module = _get_github_ingest_module_path(settings)
        if custom_module and custom_module != "default":
            from tech_connector.services.modular_provider_utils import invoke_custom_provider, resolve_custom_provider_binding
            downloaded_path = Path(invoke_custom_provider(
                resolve_custom_provider_binding("github_ingest_module", custom_module, "download_and_extract_repo", settings),
                _download_and_extract_repo_impl,
                repo_name,
                repo_url,
                target_parent_dir,
                progress_cb,
                allow_fallback=False,
            ))
            attribution_path = downloaded_path / "TECH_CONNECTOR_ATTRIBUTION.json"
            if not attribution_path.exists():
                write_repository_attribution(
                    downloaded_path,
                    parse_github_repo_reference(repo_url),
                )
            return downloaded_path
    except Exception as e:
        if custom_module and custom_module != "default":
            raise
        print(f"Error calling custom download_and_extract_repo: {e}", flush=True)
    return _download_and_extract_repo_impl(repo_name, repo_url, target_parent_dir, progress_cb)


def _download_and_extract_repo_impl(repo_name: str, repo_url: str, target_parent_dir: Path, progress_cb=None) -> Path:
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
    import hashlib
    archive_sha256 = hashlib.sha256(zip_data).hexdigest()
    archive_url = url
        
    _emit_progress(progress_cb, "Extracting repository preserving structure...", 0, 0)
        
    temp_dir = target_dir.parent / f".{target_dir.name}.extracting"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)
    extracted_files = safe_extract_zip_to_dir(zip_data, temp_dir, progress_cb=progress_cb)

    for extracted in temp_dir.iterdir():
        destination = target_dir / extracted.name
        if destination.exists():
            if destination.is_dir():
                shutil.rmtree(destination)
            else:
                destination.unlink()
        shutil.move(str(extracted), str(destination))
    shutil.rmtree(temp_dir)

    attribution = write_repository_attribution(
        target_dir,
        parse_github_repo_reference(repo_url),
        archive_url=archive_url,
        archive_sha256=archive_sha256,
    )
    _log_event(events, target_dir, "extract_finished", files=extracted_files)
    _log_event(
        events,
        target_dir,
        "attribution_written",
        manifest=attribution.get("manifest_path"),
        license=attribution.get("license"),
        license_verified=attribution.get("license_verified"),
    )
    _log_event(events, target_dir, "ingest_finished", path=str(target_dir))
    _emit_progress(progress_cb, f"Ingest complete: {target_dir}", 1, 1)
                
    return target_dir


def ingest_github_repo(repo_ref: GitHubRepoRef, target_dir: Path, progress_cb=None) -> dict:
    custom_module = "default"
    try:
        from tech_connector.services.settings_service import load_settings
        settings = load_settings()
        custom_module = _get_github_ingest_module_path(settings)
        if custom_module and custom_module != "default":
            from tech_connector.services.modular_provider_utils import invoke_custom_provider, resolve_custom_provider_binding
            result = invoke_custom_provider(
                resolve_custom_provider_binding("github_ingest_module", custom_module, "ingest_github_repo", settings),
                _ingest_github_repo_impl,
                repo_ref,
                target_dir,
                progress_cb
            )
            if isinstance(result, dict) and result.get("ok") and result.get("path"):
                downloaded_path = Path(result["path"])
                attribution_path = (
                    downloaded_path / "TECH_CONNECTOR_ATTRIBUTION.json"
                )
                if attribution_path.exists():
                    try:
                        attribution = json.loads(
                            attribution_path.read_text(encoding="utf-8")
                        )
                    except (OSError, ValueError, TypeError):
                        attribution = {}
                else:
                    attribution = write_repository_attribution(
                        downloaded_path,
                        repo_ref,
                    )
                result = {**result, "attribution": attribution}
            return result
    except Exception as e:
        if custom_module and custom_module != "default":
            return {"ok": False, "error": str(e), "provider": custom_module}
        print(f"Error calling custom ingest_github_repo: {e}", flush=True)
    return _ingest_github_repo_impl(repo_ref, target_dir, progress_cb)


def _ingest_github_repo_impl(repo_ref: GitHubRepoRef, target_dir: Path, progress_cb=None) -> dict:
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

        # Trigger Asset Optimization Hook if configured
        try:
            from tech_connector.services.settings_service import load_settings
            settings = load_settings()
            opt_module = settings.get("asset_optimizer_provider_module", "default")
            if opt_module and opt_module != "default":
                if progress_cb:
                    try:
                        progress_cb("Triggering custom asset optimization hook...", 95, 100)
                    except Exception:
                        pass
                from tech_connector.services.modular_provider_utils import invoke_custom_provider, resolve_custom_provider_binding
                invoke_custom_provider(
                    resolve_custom_provider_binding("asset_optimizer_module", opt_module, "optimize_assets", settings),
                    lambda path: None,
                    local_path
                )
        except Exception as opt_err:
            print(f"[Optimizer] Warning: Custom optimizer failed: {opt_err}", flush=True)

        attribution_path = Path(local_path) / "TECH_CONNECTOR_ATTRIBUTION.json"
        try:
            attribution = json.loads(
                attribution_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError, TypeError):
            attribution = {}
        return {
            "ok": True,
            "path": str(local_path),
            "attribution": attribution,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
