"""Stage Tech Connector release package tiers.

This creates a clean source payload for either the lean reasoning runtime or
the full tools package. Frozen executable and installer steps can consume the
staged folder.
"""

from __future__ import annotations

import argparse
import fnmatch
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


def stage_package(tier: str, output_dir: Path, clean: bool = True) -> Path:
    manifest = load_manifest()
    tiers = manifest.get("tiers") or {}
    if tier not in tiers:
        raise SystemExit(f"Unknown tier '{tier}'. Valid tiers: {', '.join(sorted(tiers))}")
    cfg = tiers[tier]
    root = repo_root()
    out = output_dir.resolve() / tier
    if clean and out.exists():
        remove_tree(out)
    out.mkdir(parents=True, exist_ok=True)

    excludes = list(cfg.get("exclude") or [])
    for rel in cfg.get("include") or []:
        copy_tree_entry(root, rel, out, excludes)

    (out / "PACKAGE_TIER.txt").write_text(
        f"{cfg.get('display_name', tier)}\n\n{cfg.get('description', '')}\n",
        encoding="utf-8",
    )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage Tech Connector package tier payloads.")
    parser.add_argument("tier", choices=sorted((load_manifest().get("tiers") or {}).keys()))
    parser.add_argument("--out", default="dist/staged", help="Output directory for staged payloads.")
    parser.add_argument("--no-clean", action="store_true", help="Do not delete an existing staged folder first.")
    args = parser.parse_args()

    out = stage_package(args.tier, repo_root() / args.out, clean=not args.no_clean)
    print(out)


if __name__ == "__main__":
    main()
