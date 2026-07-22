from __future__ import annotations

"""Risk- and host-aware validation profiles for Milestone C."""

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class ValidationCheck:
    key: str
    command: str
    reason: str
    required: bool = True
    runtime: str = "local"
    paths: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ValidationProfile:
    key: str
    checks: list[ValidationCheck] = field(default_factory=list)
    claims_allowed: list[str] = field(default_factory=list)
    claims_forbidden: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "checks": [check.to_dict() for check in self.checks],
            "claims_allowed": list(self.claims_allowed),
            "claims_forbidden": list(self.claims_forbidden),
        }


def choose_validation_profile(
    paths: Iterable[str],
    *,
    host: str = "",
    risk_level: str = "",
    predicted_failure_modes: Iterable[str] = (),
    selected_experts: Iterable[dict[str, Any]] = (),
) -> ValidationProfile:
    normalized = [str(Path(path)) for path in paths if str(path or "").strip()]
    py_files = [path for path in normalized if path.lower().endswith(".py")]
    expert_domains = {str(item.get("domain") or "") for item in selected_experts if isinstance(item, dict)}
    failures = " ".join(str(item) for item in predicted_failure_modes).lower()
    checks: list[ValidationCheck] = []
    for path in py_files:
        checks.append(ValidationCheck("python_compile", f"py_compile {Path(path).name}", "Every modified Python file must parse and compile.", True, "local", (path,)))

    ui_risk = any("ui" in domain or "async" in domain for domain in expert_domains) or any(term in failures for term in ("ui", "thread", "signal", "widget"))
    if ui_risk:
        checks.append(ValidationCheck("qt_import_smoke", "import changed UI module", "Catch import-time and missing-symbol UI failures.", True, "local", tuple(py_files)))
        checks.append(ValidationCheck("qt_widget_smoke", "construct widget offscreen", "Verify widget construction and signal wiring without claiming interactive correctness.", False, "local", tuple(py_files)))

    if host == "maya" or any("maya" in domain for domain in expert_domains):
        checks.append(ValidationCheck("maya_import_smoke", "import/reload module in Maya", "Desktop syntax does not prove Maya API/runtime behavior.", True if risk_level == "high" else False, "maya", tuple(py_files)))
        checks.append(ValidationCheck("maya_readback", "query affected Maya state", "Verify created or modified scene state after execution.", False, "maya"))
    if host == "unreal" or any("unreal" in domain for domain in expert_domains):
        checks.append(ValidationCheck("unreal_import_smoke", "load changed Python/module in Unreal", "Verify Unreal editor API availability.", False, "unreal", tuple(py_files)))
        checks.append(ValidationCheck("unreal_compile_readback", "compile/load affected asset and inspect result", "Static Python validation cannot prove asset or graph correctness.", True if risk_level == "high" else False, "unreal"))

    if risk_level == "high":
        checks.append(ValidationCheck("rollback_probe", "verify rollback snapshot/session", "High-risk edits require a tested recovery path.", True, "local", tuple(normalized)))

    return ValidationProfile(
        key=_profile_key(host, ui_risk, risk_level),
        checks=_dedupe(checks),
        claims_allowed=["static syntax verified"] if py_files else [],
        claims_forbidden=[
            "Do not claim host-runtime success from py_compile alone.",
            "Do not claim complete success when a required validation check failed or did not run.",
        ],
    )


def validation_complete(profile: ValidationProfile | dict[str, Any], results: Iterable[dict[str, Any]]) -> tuple[bool, list[str]]:
    p = profile if isinstance(profile, ValidationProfile) else ValidationProfile(
        key=str(profile.get("key") or ""),
        checks=[ValidationCheck(**item) for item in profile.get("checks") or []],
        claims_allowed=list(profile.get("claims_allowed") or []),
        claims_forbidden=list(profile.get("claims_forbidden") or []),
    )
    by_key = {str(item.get("key") or ""): item for item in results if isinstance(item, dict)}
    failures: list[str] = []
    for check in p.checks:
        if not check.required:
            continue
        result = by_key.get(check.key)
        if not result:
            failures.append(f"Required validation did not run: {check.key}")
        elif not bool(result.get("ok")):
            failures.append(f"Required validation failed: {check.key}: {result.get('message') or ''}".rstrip())
    return not failures, failures


def _profile_key(host: str, ui_risk: bool, risk_level: str) -> str:
    parts = [host or "local"]
    if ui_risk:
        parts.append("ui")
    parts.append(risk_level or "standard")
    return ".".join(parts)


def _dedupe(checks: list[ValidationCheck]) -> list[ValidationCheck]:
    seen: set[tuple[str, tuple[str, ...]]] = set()
    out: list[ValidationCheck] = []
    for check in checks:
        key = (check.key, check.paths)
        if key not in seen:
            seen.add(key)
            out.append(check)
    return out
