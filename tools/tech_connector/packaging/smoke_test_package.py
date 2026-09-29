"""Smoke tests for staged or frozen Tech Connector package payloads."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def verify_package_manifest(package_root: Path) -> dict:
    """Reject a staged payload that changed after its manifest was written."""
    manifest_path = package_root / "PACKAGE_MANIFEST.json"
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Package manifest is unreadable: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise RuntimeError("Package manifest schema is not supported")
    rows = payload.get("files")
    if not isinstance(rows, list):
        raise RuntimeError("Package manifest files must be a list")

    expected: dict[str, tuple[int, str]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise RuntimeError("Package manifest contains an invalid file entry")
        relative = str(row.get("path") or "").replace("\\", "/")
        parts = Path(relative).parts
        if (
            not relative
            or Path(relative).is_absolute()
            or ".." in parts
            or relative == "PACKAGE_MANIFEST.json"
            or relative in expected
        ):
            raise RuntimeError(f"Package manifest contains an unsafe or duplicate path: {relative!r}")
        expected[relative] = (int(row.get("size") or 0), str(row.get("sha256") or ""))

    actual = {
        path.relative_to(package_root).as_posix(): path
        for path in package_root.rglob("*")
        if path.is_file() and path != manifest_path
    }
    if set(actual) != set(expected):
        missing = sorted(set(expected) - set(actual))
        unexpected = sorted(set(actual) - set(expected))
        raise RuntimeError(
            "Package contents do not match the manifest"
            f"; missing={missing[:10]}; unexpected={unexpected[:10]}"
        )
    for relative, path in actual.items():
        expected_size, expected_digest = expected[relative]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if path.stat().st_size != expected_size or digest != expected_digest:
            raise RuntimeError(f"Package file failed manifest verification: {relative}")
    if int(payload.get("file_count", -1)) != len(expected):
        raise RuntimeError("Package manifest file_count does not match its inventory")
    if int(payload.get("total_bytes", -1)) != sum(value[0] for value in expected.values()):
        raise RuntimeError("Package manifest total_bytes does not match its inventory")
    return payload


def smoke_tool_bundle(package_root: Path, package_manifest: dict) -> None:
    """Validate the content-only Official Tools package without importing Core."""
    manifest_path = package_root / "official_tools_bundle.json"
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Official Tools manifest is unreadable: {exc}") from exc
    if payload.get("schema") != "tech_connector.tool_bundle.v1":
        raise RuntimeError("Official Tools manifest schema is not supported")
    if payload.get("required_capability") != "official_tools_bundle":
        raise RuntimeError("Official Tools manifest does not require its bundle capability")
    if package_manifest.get("required_capability") != "official_tools_bundle":
        raise RuntimeError("Package inventory does not require the Official Tools capability")
    roots = payload.get("tool_roots")
    if not isinstance(roots, list) or not roots:
        raise RuntimeError("Official Tools manifest requires tool roots")
    for raw in roots:
        relative = Path(str(raw or "").replace("\\", "/"))
        if not str(relative) or relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"Official Tools manifest contains an unsafe root: {raw!r}")
        if not (package_root / relative).is_dir():
            raise RuntimeError(f"Official Tools root is missing: {relative.as_posix()}")
    if (package_root / "tech_connector" / "app").exists():
        raise RuntimeError("Official Tools package unexpectedly contains the Core application")
    print(
        "bundle_ok",
        payload.get("version"),
        payload.get("package_id"),
        len(roots),
    )


def smoke_import(package_root: Path) -> None:
    package_manifest = verify_package_manifest(package_root)
    if package_manifest.get("product_id") == "official_tools_bundle":
        smoke_tool_bundle(package_root, package_manifest)
        return
    with tempfile.TemporaryDirectory(prefix="tech_connector_package_smoke_") as state_dir:
        env = dict(os.environ)
        env["AI_STUDIO_TOOLS_ROOT"] = str(package_root)
        env["AI_STUDIO_APP_DIR"] = state_dir
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        code = (
            "import os, sys; "
            "sys.path.insert(0, os.environ['AI_STUDIO_TOOLS_ROOT']); "
            "import tech_connector; "
            "from tech_connector.models.constants import APP_ROOT, TOOLS_ROOT, APP_VERSION; "
            "from tech_connector.app.application import run_application; "
            "print('import_ok', APP_VERSION, APP_ROOT, TOOLS_ROOT)"
        )
        subprocess.run(
            [sys.executable, "-B", "-c", code],
            cwd=str(package_root),
            env=env,
            check=True,
        )


def smoke_frozen_exe(exe_path: Path, timeout: float) -> None:
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = env.get("QT_QPA_PLATFORM", "offscreen")
    env["TECH_CONNECTOR_SMOKE_TEST"] = "1"
    env["AI_STUDIO_SKIP_SPLASH"] = "1"
    proc = subprocess.Popen([str(exe_path)], cwd=str(exe_path.parent), env=env)
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        print("frozen_launch_ok timeout_terminated")
        return
    if proc.returncode not in (0, None):
        raise SystemExit(f"Frozen executable exited with code {proc.returncode}")
    print("frozen_launch_ok exited")


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke test staged or frozen Tech Connector packages.")
    parser.add_argument("path", help="Path to staged package root or frozen TechConnector.exe.")
    parser.add_argument("--timeout", type=float, default=12.0)
    args = parser.parse_args()

    path = Path(args.path).resolve()
    if path.is_file() and path.suffix.lower() == ".exe":
        smoke_frozen_exe(path, args.timeout)
    else:
        smoke_import(path)


if __name__ == "__main__":
    main()
