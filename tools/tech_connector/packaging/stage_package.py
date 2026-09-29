"""Stage composable Tech Connector Core and Official Tools deliverables."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import shutil
import stat
import sys
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_manifest() -> dict:
    path = Path(__file__).with_name("package_tiers.json")
    return json.loads(path.read_text(encoding="utf-8"))


def matches_any(path_text: str, patterns: list[str]) -> bool:
    normalized = path_text.replace("\\", "/")
    parts = normalized.split("/")
    for pattern in patterns:
        pattern = pattern.replace("\\", "/")
        if fnmatch.fnmatch(normalized, pattern):
            return True
        if pattern.startswith("**/"):
            tail = pattern[3:]
            if any(fnmatch.fnmatch(part, tail) for part in parts):
                return True
        if normalized == pattern or normalized.startswith(pattern.rstrip("/") + "/"):
            return True
    return False


def copy_tree_entry(src_root: Path, rel: str, out_root: Path, excludes: list[str]) -> None:
    src = src_root / rel
    if not src.exists():
        return
    if src.is_file():
        if matches_any(rel, excludes):
            return
        dest = out_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        make_writable(dest)
        return

    for path in src.rglob("*"):
        rel_path = path.relative_to(src_root).as_posix()
        if matches_any(rel_path, excludes):
            continue
        if path.is_dir():
            continue
        dest = out_root / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
        make_writable(dest)


def copy_repository_files(
    src_root: Path,
    out_root: Path,
    entries: list[dict],
    excludes: list[str],
) -> None:
    """Copy explicit source files to repository-root destinations."""
    resolved_root = src_root.resolve()
    resolved_output = out_root.resolve()
    for entry in entries:
        source_relative = Path(str(entry.get("source") or "").replace("\\", "/"))
        target_relative = Path(str(entry.get("target") or "").replace("\\", "/"))
        for field, value in (("source", source_relative), ("target", target_relative)):
            if not str(value) or value.is_absolute() or ".." in value.parts:
                raise RuntimeError(f"repository file {field} must be a safe relative path")
        if matches_any(source_relative.as_posix(), excludes):
            raise RuntimeError(
                f"repository file source is excluded: {source_relative.as_posix()}"
            )
        source = (resolved_root / source_relative).resolve()
        destination = (resolved_output / target_relative).resolve()
        try:
            source.relative_to(resolved_root)
            destination.relative_to(resolved_output)
        except ValueError as exc:
            raise RuntimeError("repository file mapping escapes its package boundary") from exc
        if not source.is_file() or source.is_symlink():
            raise RuntimeError(
                f"repository file source is missing or unsafe: {source_relative.as_posix()}"
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        make_writable(destination)


def make_writable(path: Path) -> None:
    try:
        path.chmod(path.stat().st_mode | stat.S_IWRITE | stat.S_IREAD)
    except OSError:
        pass


def remove_tree(path: Path) -> None:
    def onerror(func, failed_path, _exc_info):
        try:
            os.chmod(failed_path, stat.S_IWRITE | stat.S_IREAD)
            func(failed_path)
        except Exception:
            raise

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=lambda func, failed_path, _exc: onerror(func, failed_path, None))
    else:
        shutil.rmtree(path, onerror=onerror)


def write_package_manifest(
    package_root: Path,
    tier: str,
    *,
    requested_tier: str = "",
    product_id: str = "",
    required_capability: str = "",
) -> Path:
    """
        Writes a deterministic inventory for a staged package.

    :param package_root: staged package directory
    :param tier: package tier identifier
    :return: generated manifest path
    """
    manifest_path = package_root / "PACKAGE_MANIFEST.json"
    entries = []
    for path in sorted(package_root.rglob("*")):
        if not path.is_file() or path == manifest_path:
            continue
        content = path.read_bytes()
        entries.append(
            {
                "path": path.relative_to(package_root).as_posix(),
                "size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    payload = {
        "schema_version": 1,
        "tier": tier,
        "requested_tier": requested_tier or tier,
        "product_id": product_id,
        "required_capability": required_capability,
        "file_count": len(entries),
        "total_bytes": sum(entry["size"] for entry in entries),
        "files": entries,
    }
    manifest_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def validate_staged_package(
    package_root: Path,
    required_files: list[str] | tuple[str, ...] | None = None,
) -> None:
    """
        Validates legal, install, and generated-artifact release boundaries.

    :param package_root: staged package directory
    :return: None
    """
    required = tuple(required_files or (
        "README.md",
        "LICENSE",
        "tech_connector/LICENSE.md",
        "tech_connector/PRIVACY.md",
        "tech_connector/README.md",
        "tech_connector/CONTRIBUTING.md",
        "tech_connector/packaging/requirements-runtime.txt",
    ))
    missing = [value for value in required if not (package_root / value).is_file()]
    if missing:
        raise RuntimeError(
            "Staged package is missing required release files: " + ", ".join(missing)
        )
    forbidden = []
    sensitive = []
    sensitive_suffixes = {".key", ".p12", ".pfx"}
    sensitive_names = {
        ".env",
        "production_secrets.json",
        "service_account.json",
    }
    # Build PEM sentinels at runtime so this scanner does not flag its own
    # source after the packaging helpers are copied into a release payload.
    private_key_markers = tuple(
        f"-----BEGIN {label}-----".encode("ascii")
        for label in (
            "PRIVATE KEY",
            "RSA PRIVATE KEY",
            "EC PRIVATE KEY",
            "OPENSSH PRIVATE KEY",
        )
    )
    for path in package_root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(package_root)
        normalized = relative.as_posix()
        is_runtime_port = path.name.casefold().endswith("_port.txt")
        approved_port = normalized.startswith("tech_connector/bridges/ports/")
        if (
            "__pycache__" in relative.parts
            or path.suffix.lower() in {".pyc", ".pyo", ".orig", ".rej"}
            or path.name.endswith("~")
            or (is_runtime_port and not approved_port)
        ):
            forbidden.append(relative.as_posix())
        lowered_name = path.name.casefold()
        if path.suffix.casefold() in sensitive_suffixes or lowered_name in sensitive_names:
            sensitive.append(relative.as_posix())
            continue
        try:
            if path.stat().st_size <= 5_000_000:
                content = path.read_bytes()
                if any(marker in content for marker in private_key_markers):
                    sensitive.append(relative.as_posix())
        except OSError:
            continue
    if forbidden:
        raise RuntimeError(
            "Staged package contains generated or runtime-state artifacts: "
            + ", ".join(forbidden[:20])
        )
    if sensitive:
        raise RuntimeError(
            "Staged package contains a private key or production-secret artifact: "
            + ", ".join(sensitive[:20])
        )


def stage_package(tier: str, output_dir: Path, clean: bool = True) -> Path:
    manifest = load_manifest()
    tiers = manifest.get("tiers") or {}
    aliases = manifest.get("aliases") or {}
    canonical_tier = str(aliases.get(tier) or tier)
    if canonical_tier not in tiers:
        choices = sorted({*tiers, *aliases})
        raise SystemExit(f"Unknown tier '{tier}'. Valid tiers: {', '.join(choices)}")
    cfg = tiers[canonical_tier]
    root = repo_root()
    out = output_dir.resolve() / tier
    if clean and out.exists():
        remove_tree(out)
    out.mkdir(parents=True, exist_ok=True)

    excludes = list(cfg.get("exclude") or [])
    for rel in cfg.get("include") or []:
        copy_tree_entry(root, rel, out, excludes)
    copy_repository_files(root, out, list(cfg.get("repository_files") or []), excludes)

    (out / "PACKAGE_TIER.txt").write_text(
        f"{cfg.get('display_name', tier)}\n\n{cfg.get('description', '')}\n",
        encoding="utf-8",
    )
    validate_staged_package(out, list(cfg.get("required_files") or []))
    write_package_manifest(
        out,
        canonical_tier,
        requested_tier=tier,
        product_id=str(cfg.get("product_id") or ""),
        required_capability=str(cfg.get("required_capability") or ""),
    )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage Tech Connector package tier payloads.")
    manifest = load_manifest()
    tier_choices = sorted(
        {
            *(manifest.get("tiers") or {}).keys(),
            *(manifest.get("aliases") or {}).keys(),
        }
    )
    parser.add_argument("tier", choices=tier_choices)
    parser.add_argument("--out", default="dist/staged", help="Output directory for staged payloads.")
    parser.add_argument("--no-clean", action="store_true", help="Do not delete an existing staged folder first.")
    args = parser.parse_args()

    out = stage_package(args.tier, repo_root() / args.out, clean=not args.no_clean)
    print(out)


if __name__ == "__main__":
    main()
