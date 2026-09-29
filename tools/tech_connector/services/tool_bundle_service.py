"""Discover separately installed tool bundles without inspecting user content."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Mapping

from tech_connector.licensing.domain import EntitlementClaims
from tech_connector.licensing.products import (
    ProductAccessDecision,
    evaluate_product_access,
)


TOOL_BUNDLE_MANIFEST = "official_tools_bundle.json"
TOOL_BUNDLE_SCHEMA = "tech_connector.tool_bundle.v1"
_IDENTIFIER = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")


@dataclass(frozen=True)
class ToolBundle:
    root: Path
    package_id: str
    display_name: str
    version: str
    compatible_connector_versions: str
    required_capability: str
    tool_roots: tuple[Path, ...]


@dataclass(frozen=True)
class ToolBundleAccess:
    bundle: ToolBundle
    decision: ProductAccessDecision


def _required_text(payload: Mapping[str, Any], key: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise ValueError(f"tool bundle {key} is required")
    return value


def load_tool_bundle(path: str | Path) -> ToolBundle:
    """Load and validate a bundle manifest using only local metadata."""
    candidate = Path(path).expanduser()
    manifest_path = candidate if candidate.is_file() else candidate / TOOL_BUNDLE_MANIFEST
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"tool bundle manifest is unreadable: {manifest_path}") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("tool bundle manifest must be an object")
    if payload.get("schema") != TOOL_BUNDLE_SCHEMA:
        raise ValueError("unsupported tool bundle schema")

    package_id = _required_text(payload, "package_id")
    capability = _required_text(payload, "required_capability")
    if not _IDENTIFIER.fullmatch(package_id):
        raise ValueError("tool bundle package_id is invalid")
    if not _IDENTIFIER.fullmatch(capability):
        raise ValueError("tool bundle required_capability is invalid")

    root = manifest_path.parent.resolve()
    raw_roots = payload.get("tool_roots")
    if not isinstance(raw_roots, list) or not raw_roots:
        raise ValueError("tool bundle tool_roots must be a non-empty list")
    resolved: list[Path] = []
    for raw in raw_roots:
        relative = Path(str(raw or "").strip())
        if not str(relative) or relative.is_absolute() or ".." in relative.parts:
            raise ValueError("tool bundle roots must be safe relative paths")
        tool_root = (root / relative).resolve()
        try:
            tool_root.relative_to(root)
        except ValueError as exc:
            raise ValueError("tool bundle root escapes the bundle directory") from exc
        if not tool_root.is_dir():
            raise ValueError(f"tool bundle root is missing: {relative.as_posix()}")
        if tool_root not in resolved:
            resolved.append(tool_root)

    return ToolBundle(
        root=root,
        package_id=package_id,
        display_name=_required_text(payload, "display_name"),
        version=_required_text(payload, "version"),
        compatible_connector_versions=_required_text(
            payload,
            "compatible_connector_versions",
        ),
        required_capability=capability,
        tool_roots=tuple(resolved),
    )


def configured_bundle_roots(settings: Mapping[str, Any] | None) -> tuple[Path, ...]:
    """Return explicit bundle candidates, reusing existing extra directories."""
    values = settings or {}
    candidates = [
        *(values.get("tool_bundle_dirs") or []),
        *(values.get("extra_dirs") or []),
    ]
    roots: list[Path] = []
    for raw in candidates:
        text = str(raw or "").strip()
        if not text:
            continue
        try:
            root = Path(text).expanduser().resolve()
        except (OSError, RuntimeError):
            root = Path(text).expanduser()
        if (root / TOOL_BUNDLE_MANIFEST).is_file() and root not in roots:
            roots.append(root)
    return tuple(roots)


def discover_tool_bundles(settings: Mapping[str, Any] | None) -> tuple[ToolBundle, ...]:
    """Discover only explicitly configured bundle roots; never scan user projects."""
    return tuple(load_tool_bundle(root) for root in configured_bundle_roots(settings))


def _version_parts(value: str) -> tuple[int, ...]:
    text = str(value or "").strip().lstrip("vV")
    match = re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", text)
    if not match:
        raise ValueError(f"unsupported version value: {value}")
    return tuple(int(part) for part in text.split("."))


def connector_version_is_compatible(version: str, requirement: str) -> bool:
    """Evaluate the small comparison grammar used by bundle manifests."""
    current = _version_parts(version)
    clauses = [item.strip() for item in str(requirement or "").split(",") if item.strip()]
    if not clauses:
        raise ValueError("tool bundle compatible_connector_versions is empty")
    for clause in clauses:
        match = re.fullmatch(r"(>=|<=|==|>|<)\s*([0-9]+(?:\.[0-9]+)*)", clause)
        if not match:
            raise ValueError(f"unsupported connector version requirement: {clause}")
        operator, expected_text = match.groups()
        expected = _version_parts(expected_text)
        width = max(len(current), len(expected))
        left = current + (0,) * (width - len(current))
        right = expected + (0,) * (width - len(expected))
        comparisons = {
            ">=": left >= right,
            "<=": left <= right,
            "==": left == right,
            ">": left > right,
            "<": left < right,
        }
        if not comparisons[operator]:
            return False
    return True


def evaluate_tool_bundles(
    settings: Mapping[str, Any] | None,
    claims: EntitlementClaims | None,
    connector_version: str = "",
) -> tuple[ToolBundleAccess, ...]:
    accesses: list[ToolBundleAccess] = []
    for bundle in discover_tool_bundles(settings):
        decision = evaluate_product_access(claims, bundle.required_capability)
        if (
            decision.allowed
            and connector_version
            and not connector_version_is_compatible(
                connector_version,
                bundle.compatible_connector_versions,
            )
        ):
            decision = ProductAccessDecision(
                bundle.required_capability,
                False,
                "bundle_version_incompatible",
                (
                    f"Bundle {bundle.version} requires Tech Connector "
                    f"{bundle.compatible_connector_versions}."
                ),
            )
        accesses.append(ToolBundleAccess(bundle, decision))
    return tuple(accesses)


def authorized_tool_roots(
    settings: Mapping[str, Any] | None,
    claims: EntitlementClaims | None,
    connector_version: str = "",
) -> tuple[Path, ...]:
    """Return first-party roots only when the signed capability is present."""
    roots: list[Path] = []
    for access in evaluate_tool_bundles(settings, claims, connector_version):
        if not access.decision.allowed:
            continue
        for path in access.bundle.tool_roots:
            if path not in roots:
                roots.append(path)
    return tuple(roots)


def compose_project_roots_with_bundles(
    settings: Mapping[str, Any] | None,
    project_roots: tuple[str, ...] | list[str],
    claims: EntitlementClaims | None,
    connector_version: str = "",
) -> tuple[str, ...]:
    """Keep ordinary roots and replace configured bundles with authorized tools."""
    accesses = evaluate_tool_bundles(settings, claims, connector_version)
    bundle_roots = {access.bundle.root for access in accesses}
    output: list[str] = []
    for raw in project_roots:
        try:
            path = Path(raw).expanduser().resolve()
        except (OSError, RuntimeError):
            path = Path(raw).expanduser()
        if path in bundle_roots:
            continue
        value = str(path)
        if value not in output:
            output.append(value)
    for access in accesses:
        if not access.decision.allowed:
            continue
        for path in access.bundle.tool_roots:
            value = str(path)
            if value not in output:
                output.append(value)
    return tuple(output)
