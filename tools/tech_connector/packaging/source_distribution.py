"""Prepare and validate the anonymous public landing repository payload."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path


TOOLS_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = TOOLS_ROOT.parent
MANIFEST_PATH = TOOLS_ROOT / "tech_connector" / "config" / "public_repository.json"
PUBLIC_MANIFEST_NAME = "PUBLIC_LANDING_MANIFEST.json"
ALLOWED_SUFFIXES = {"", ".md", ".json", ".txt", ".yml", ".yaml"}
SENSITIVE_NAMES = {".env", "production_secrets.json", "service_account.json"}
PEM_MARKERS = tuple(
    f"-----BEGIN {label}-----".encode("ascii")
    for label in ("PRIVATE KEY", "RSA PRIVATE KEY", "EC PRIVATE KEY", "OPENSSH PRIVATE KEY")
)


def _safe_relative(value: str, *, field: str) -> Path:
    relative = Path(str(value or "").replace("\\", "/"))
    if not str(relative) or relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{field} must be a safe repository-relative path")
    return relative


def load_public_repository_manifest(path: Path = MANIFEST_PATH) -> tuple[tuple[Path, Path], ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("public repository manifest schema is not supported")
    rows = payload.get("files")
    if not isinstance(rows, list) or not rows:
        raise ValueError("public repository manifest requires a non-empty files list")
    entries = []
    targets = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("public repository manifest entries must be objects")
        source = _safe_relative(row.get("source"), field="source")
        target = _safe_relative(row.get("target"), field="target")
        normalized_target = target.as_posix().casefold()
        if normalized_target in targets or target.name == PUBLIC_MANIFEST_NAME:
            raise ValueError(f"duplicate or reserved public target: {target.as_posix()}")
        targets.add(normalized_target)
        entries.append((source, target))
    return tuple(entries)


def _payload_files(root: Path) -> list[Path]:
    return sorted(
        (
            path
            for path in root.rglob("*")
            if path.is_file() and path.name != PUBLIC_MANIFEST_NAME
        ),
        key=lambda path: path.relative_to(root).as_posix(),
    )


def validate_public_landing(root: Path, entries: tuple[tuple[Path, Path], ...] | None = None) -> None:
    root = root.resolve()
    configured = entries or load_public_repository_manifest()
    expected = {target.as_posix() for _source, target in configured}
    actual_paths = _payload_files(root)
    actual = {path.relative_to(root).as_posix() for path in actual_paths}
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise RuntimeError(
            "public landing payload differs from its allowlist"
            f"; missing={missing[:10]}; unexpected={unexpected[:10]}"
        )
    for path in actual_paths:
        relative = path.relative_to(root)
        if path.is_symlink():
            raise RuntimeError(f"public landing payload contains a symlink: {relative.as_posix()}")
        if path.suffix.casefold() not in ALLOWED_SUFFIXES:
            raise RuntimeError(f"public landing payload contains protected source/binary: {relative.as_posix()}")
        if path.name.casefold() in SENSITIVE_NAMES:
            raise RuntimeError(f"public landing payload contains a sensitive file: {relative.as_posix()}")
        content = path.read_bytes()
        if any(marker in content for marker in PEM_MARKERS):
            raise RuntimeError(f"public landing payload contains private-key material: {relative.as_posix()}")
    readme = (root / "README.md").read_text(encoding="utf-8").casefold()
    license_text = (root / "LICENSE").read_text(encoding="utf-8").casefold()
    if "account activation is required" not in readme:
        raise RuntimeError("public landing README lacks the account-activation warning")
    if "official tools bundle" not in readme or "official_tools_bundle" not in readme:
        raise RuntimeError("public landing README lacks the Official Tools entitlement warning")
    if "source-available" not in license_text or "activated entitlement" not in license_text:
        raise RuntimeError("public landing LICENSE lacks source-available activation terms")


def write_public_manifest(root: Path) -> Path:
    rows = []
    for path in _payload_files(root):
        content = path.read_bytes()
        rows.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    payload = {
        "schema_version": 1,
        "purpose": "Anonymous Tech Connector landing repository; complete source excluded.",
        "file_count": len(rows),
        "files": rows,
    }
    target = root / PUBLIC_MANIFEST_NAME
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def stage_public_landing(output: Path, *, clean: bool = True) -> Path:
    output = output.resolve()
    if clean and output.exists():
        if not (output / PUBLIC_MANIFEST_NAME).is_file():
            raise RuntimeError(
                "refusing to clean an existing directory that was not created by "
                "the public landing stager"
            )
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)
    entries = load_public_repository_manifest()
    repository_root = REPOSITORY_ROOT.resolve()
    for source_relative, target_relative in entries:
        source = (repository_root / source_relative).resolve()
        try:
            source.relative_to(repository_root)
        except ValueError as exc:
            raise RuntimeError(f"public source escapes repository root: {source_relative}") from exc
        if not source.is_file() or source.is_symlink():
            raise RuntimeError(f"public source file is missing or unsafe: {source_relative.as_posix()}")
        target = output / target_relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    validate_public_landing(output, entries)
    write_public_manifest(output)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="Empty/output directory for public landing files.")
    parser.add_argument("--no-clean", action="store_true")
    args = parser.parse_args()
    output = stage_public_landing(Path(args.out), clean=not args.no_clean)
    print(output)


if __name__ == "__main__":
    main()
