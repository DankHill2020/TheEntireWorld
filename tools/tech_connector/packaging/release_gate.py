"""Fail-closed checks for source publication and production packaging."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import re
import subprocess
import sys
from pathlib import Path

# Keep direct script execution (`python tech_connector/packaging/release_gate.py`)
# equivalent to module execution without relying on a caller's PYTHONPATH.
_TOOLS_ROOT = Path(__file__).resolve().parents[2]
if str(_TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TOOLS_ROOT))

SENSITIVE_SUFFIXES = {
    ".bak",
    ".jks",
    ".key",
    ".keystore",
    ".p12",
    ".pfx",
    ".tfstate",
    ".tfvars",
}
SENSITIVE_NAMES = {
    ".env",
    ".npmrc",
    ".pypirc",
    "id_ed25519",
    "id_rsa",
    "production_secrets.json",
    "service_account.json",
}
ENV_TEMPLATE_NAMES = {".env.example", ".env.sample", ".env.template"}
PRIVATE_SERVICE_DIRECTORIES = {".private_backend"}
GENERATED_DIRECTORIES = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
GENERATED_SUFFIXES = {".db", ".pyc", ".sqlite", ".sqlite3"}
GENERATED_NAME_SUFFIXES = (
    ".build.lock",
    ".db-journal",
    ".db-shm",
    ".db-wal",
    ".sqlite-journal",
    ".sqlite-shm",
    ".sqlite-wal",
)
BACKUP_SUFFIXES = ("~",)
PEM_MARKERS = tuple(
    f"-----BEGIN {label}-----".encode("ascii")
    for label in ("PRIVATE KEY", "RSA PRIVATE KEY", "EC PRIVATE KEY", "OPENSSH PRIVATE KEY")
)


def _git_root(source_root: Path) -> Path:
    result = subprocess.run(
        ("git", "rev-parse", "--show-toplevel"),
        cwd=str(source_root),
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(result.stdout.strip()).resolve()


def publication_candidates(source_root: Path) -> list[Path]:
    git_root = _git_root(source_root)
    relative_root = source_root.resolve().relative_to(git_root).as_posix()
    result = subprocess.run(
        ("git", "ls-files", "--cached", "--others", "--exclude-standard", "--", relative_root),
        cwd=str(git_root),
        check=True,
        capture_output=True,
        text=True,
    )
    return [git_root / line for line in result.stdout.splitlines() if line.strip()]


def sensitive_artifacts(paths: list[Path]) -> list[str]:
    failures = []
    for path in paths:
        if not path.is_file():
            continue
        lowered = path.name.casefold()
        lowered_parts = {part.casefold() for part in path.parts}
        is_environment_secret = (
            (lowered == ".env" or lowered.startswith(".env."))
            and lowered not in ENV_TEMPLATE_NAMES
        )
        if (
            lowered_parts & PRIVATE_SERVICE_DIRECTORIES
            or lowered_parts & GENERATED_DIRECTORIES
            or path.suffix.casefold() in SENSITIVE_SUFFIXES
            or lowered in SENSITIVE_NAMES
            or is_environment_secret
            or path.suffix.casefold() in GENERATED_SUFFIXES
            or lowered.endswith(GENERATED_NAME_SUFFIXES)
            or lowered.endswith(BACKUP_SUFFIXES)
        ):
            failures.append(str(path))
            continue
        try:
            if path.stat().st_size <= 5_000_000:
                content = path.read_bytes()
                if any(marker in content for marker in PEM_MARKERS):
                    failures.append(str(path))
        except OSError:
            failures.append(str(path))
    return failures


def validate_legal_surface(source_root: Path) -> list[str]:
    failures = []
    public_readme_path = source_root / "README.md"
    license_path = source_root / "tech_connector/LICENSE.md"
    readme_path = source_root / "tech_connector/README.md"
    privacy_path = source_root / "tech_connector/PRIVACY.md"
    project_terms_path = source_root / "tech_connector/COMMUNITY_PROJECT_TERMS.md"
    indie_terms_path = source_root / "tech_connector/INDIE_LICENSE_TERMS.md"
    enterprise_terms_path = source_root / "tech_connector/ENTERPRISE_LICENSE_TERMS.md"
    source_access_path = source_root / "tech_connector/docs/SOURCE_ACCESS_MODEL.md"
    launcher_path = source_root / "tech_connector/Start_The_Entire_World_Tech_Connector.bat"
    if not public_readme_path.is_file():
        failures.append("repository-root README.md is missing")
    else:
        public_readme = " ".join(
            public_readme_path.read_text(encoding="utf-8").casefold().split()
        )
        required_public_terms = {
            "source available — not open source": "source-available warning",
            "account activation is required": "account-activation warning",
            "does not create an activated license": "GitHub-download activation warning",
            "application remains locked": "fail-closed startup warning",
        }
        for phrase, label in required_public_terms.items():
            if phrase not in public_readme:
                failures.append(f"repository-root README lacks its {label}")
    if not license_path.is_file():
        failures.append("tech_connector/LICENSE.md is missing")
    else:
        license_text = " ".join(
            license_path.read_text(encoding="utf-8").casefold().split()
        )
        required_license_terms = {
            "source-available": "source-available designation",
            "not licensed as open source software": "not-open-source designation",
            "all rights reserved": "copyright reservation",
            "the entire world, llc": "copyright owner",
            "$500,000": "Community profit threshold",
            "adjusted project profit": "Community calculation basis",
            "entire lifetime": "project-lifetime measurement",
            "redistribut": "redistribution restriction",
            "bypass license": "licensing-circumvention restriction",
        }
        for phrase, label in required_license_terms.items():
            if phrase not in license_text:
                failures.append(f"Tech Connector license lacks its {label}")
    if not readme_path.is_file():
        failures.append("tech_connector/README.md is missing")
    else:
        readme_text = " ".join(
            readme_path.read_text(encoding="utf-8").casefold().split()
        )
        if "source-available" not in readme_text:
            failures.append("Tech Connector README lacks a source-available notice")
        if "not an osi open-source project" not in readme_text:
            failures.append("Tech Connector README does not clearly say it is not OSI open source")
        if "download, account, and activation" not in readme_text:
            failures.append("Tech Connector README lacks its download/activation section")
        if "does not itself activate tech connector" not in readme_text:
            failures.append("Tech Connector README does not explain GitHub activation")
        if "complete first-party official tools bundle source are publicly visible" not in readme_text:
            failures.append("Tech Connector README lacks the complete public Tools source boundary")
        if "delivered separately through an account-gated download or repository" in readme_text:
            failures.append("Tech Connector README still describes the obsolete private Tools repository")
    if not privacy_path.is_file():
        failures.append("tech_connector/PRIVACY.md is missing")
    else:
        privacy_text = " ".join(
            privacy_path.read_text(encoding="utf-8").casefold().split()
        )
        required_privacy_terms = {
            "local-first": "local-first architecture",
            "does not upload project assets": "creative-content upload exclusion",
            "path itself is not sent": "project-path upload exclusion",
            "random installation identifier": "pseudonymous installation identity",
            "private signing keys": "private signing-key boundary",
        }
        for phrase, label in required_privacy_terms.items():
            if phrase not in privacy_text:
                failures.append(f"Tech Connector privacy notice lacks its {label}")
    if not project_terms_path.is_file():
        failures.append("Tech Connector Community project terms are missing")
    else:
        project_terms_text = " ".join(
            project_terms_path.read_text(encoding="utf-8").casefold().split()
        )
        required_project_terms = {
            "$500,000": "profit threshold",
            "entire lifetime": "project-lifetime measurement",
            "actually paid or incurred": "true-cost standard",
            "artificial management fees": "anti-inflation exclusions",
            "marginal residual": "marginal calculation",
            "must not require project assets": "creative-content privacy boundary",
            "acceptance record": "acceptance-evidence boundary",
        }
        for phrase, label in required_project_terms.items():
            if phrase not in project_terms_text:
                failures.append(f"Community project terms lack their {label}")
    for path, label, required_terms in (
        (
            indie_terms_path,
            "Indie license terms",
            {
                "$200 per named user": "annual price",
                "$500 per named user": "perpetual price",
                "major version 6": "covered launch major version",
                "no residual or profit share": "paid no-residual grant",
                "two registered devices": "device allowance",
                "official_tools_bundle": "optional Tools capability boundary",
            },
        ),
        (
            enterprise_terms_path,
            "Enterprise license terms",
            {
                "$1,500 per named user": "annual price",
                "$3,500 per named user": "perpetual price",
                "five-seat minimum": "minimum quantity",
                "no project residual or profit share": "paid no-residual grant",
                "two registered devices": "device allowance",
                "executed order": "custom order boundary",
            },
        ),
    ):
        if not path.is_file():
            failures.append(f"Tech Connector {label} are missing")
            continue
        normalized = " ".join(path.read_text(encoding="utf-8").casefold().split())
        for phrase, description in required_terms.items():
            if phrase not in normalized:
                failures.append(f"{label} lack their {description}")
    if not source_access_path.is_file():
        failures.append("Tech Connector source and product-access model is missing")
    else:
        source_access_text = " ".join(
            source_access_path.read_text(encoding="utf-8").casefold().split()
        )
        required_source_access_terms = {
            "publicly source-available": "public Core boundary",
            "official tools bundle is one product": "single Tools Bundle boundary",
            "official_tools_bundle": "signed Tools Bundle capability",
            "own project directories": "user-owned tool-directory boundary",
            "cannot be remotely erased": "revocation limitation",
            "github app keys": "provider-secret isolation",
        }
        for phrase, label in required_source_access_terms.items():
            if phrase not in source_access_text:
                failures.append(f"Tech Connector source-access model lacks its {label}")
    if not launcher_path.is_file():
        failures.append("Tech Connector public source launcher is missing")
    else:
        launcher_text = launcher_path.read_text(encoding="utf-8-sig").casefold()
        compact_launcher = "".join(launcher_text.split())
        if "tech_connector_dev_license_bypass=1" in compact_launcher:
            failures.append("Tech Connector public source launcher enables a license bypass")
        if "requires account sign-in, license acceptance, and activation" not in launcher_text:
            failures.append("Tech Connector public source launcher lacks its activation notice")
    return failures


def validate_github_root_surface(source_root: Path) -> list[str]:
    """Validate the files GitHub renders at the actual repository root."""
    failures = []
    git_root = _git_root(source_root)
    readme_path = git_root / "README.md"
    license_path = git_root / "LICENSE"
    if not readme_path.is_file():
        failures.append("GitHub repository-root README.md is missing")
    else:
        text = " ".join(readme_path.read_text(encoding="utf-8").casefold().split())
        for phrase, label in {
            "source available — not open source": "source-available warning",
            "account activation is required": "activation warning",
            "does not create an activated license": "download warning",
            "official tools bundle": "Official Tools warning",
            "complete public source-available monorepo": "public monorepo boundary",
            "tools/tech_connector/docs/source_access_model.md": "source-access model link",
        }.items():
            if phrase not in text:
                failures.append(f"GitHub repository-root README lacks its {label}")
    if not license_path.is_file():
        failures.append("GitHub repository-root LICENSE is missing")
    else:
        text = " ".join(license_path.read_text(encoding="utf-8").casefold().split())
        for phrase, label in {
            "source-available": "source-available designation",
            "not unrestricted open-source software": "not-open-source designation",
            "does not create an activated entitlement": "activation requirement",
            "tools/tech_connector/license.md": "controlling-license link",
        }.items():
            if phrase not in text:
                failures.append(f"GitHub repository-root LICENSE lacks its {label}")
    if (git_root / "LICENSE.bak").exists():
        failures.append("obsolete GitHub repository-root LICENSE.bak must be removed")
    return failures


def validate_production_legal_approval(source_root: Path) -> list[str]:
    """Prevent a production build while the checked-in notice is still a draft."""
    failures = []
    required = {
        source_root / "tech_connector/LICENSE.md": "production controlling source license",
        source_root / "tech_connector/PRIVACY.md": "production privacy notice",
        source_root / "tech_connector/COMMUNITY_PROJECT_TERMS.md": (
            "production Community project terms document"
        ),
        source_root / "tech_connector/INDIE_LICENSE_TERMS.md": (
            "production Indie license terms document"
        ),
        source_root / "tech_connector/ENTERPRISE_LICENSE_TERMS.md": (
            "production Enterprise license terms document"
        ),
    }
    for path, label in required.items():
        if not path.is_file():
            failures.append(f"{label} is missing")
            continue
        text = " ".join(path.read_text(encoding="utf-8").casefold().split())
        if "release status: approved" not in text:
            failures.append(f"{label} has not been marked approved by counsel")
    return failures


def validate_production_source_access(source_root: Path) -> list[str]:
    """Block production until the public-monorepo/private-services boundary is verified."""
    path = source_root / "tech_connector/config/source_access.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"production source-access status is unreadable: {exc}"]
    failures = []
    if not isinstance(payload, dict) or payload.get("schema_version") != 3:
        failures.append("production source-access status schema is not supported")
        return failures
    if payload.get("distribution_model") != "public_complete_tools_monorepo":
        failures.append("production source distribution does not use the complete public tools monorepo")
    if payload.get("status") != "operational_verified":
        failures.append("production public tools monorepo is not operational and verified")
    if payload.get("public_repository_contains_complete_source") is not True:
        failures.append("production public repository does not contain the complete intended source")
    if payload.get("public_repository_contains_core_source") is not True:
        failures.append("production public repository does not contain the intended Core source")
    if payload.get("official_tools_source_public") is not True:
        failures.append("production Official Tools source is not declared public")
    if payload.get("official_tools_execution_entitlement_required") is not True:
        failures.append("production Official Tools execution entitlement is not required")
    if payload.get("private_services_excluded") is not True:
        failures.append("production private services are not excluded from the public repository")
    if not str(payload.get("verified_at") or "").strip():
        failures.append("production source-access verification time is missing")
    if not str(payload.get("review_reference") or "").strip():
        failures.append("production source-access review reference is missing")
    return failures


def validate_production_configuration(source_root: Path) -> list[str]:
    path = source_root / "tech_connector/config/licensing.json"
    try:
        from tech_connector.licensing.configuration import (
            configuration_errors,
            load_licensing_configuration,
        )
        configuration = load_licensing_configuration(path)
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        return [f"licensing configuration is unreadable: {exc}"]
    return list(configuration_errors(configuration, production=True))


def validate_production_readiness(
    source_root: Path, *, pending_controls: frozenset[str] = frozenset(),
    required_status: str = "approved_for_production",
    approval_reference_field: str = "release_approval_reference",
) -> list[str]:
    """Require auditable evidence for every externally operated launch control."""
    path = source_root / "tech_connector/config/production_readiness.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"production-readiness evidence is unreadable: {exc}"]
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        return ["production-readiness evidence schema is not supported"]
    required = {
        "legal_and_privacy",
        "production_backend",
        "entitlement_signing_key",
        "payments_and_tax",
        "signed_installers",
        "monitoring_and_incident_response",
        "backups_and_restore",
        "support_operations",
    }
    controls = payload.get("controls")
    if not isinstance(controls, dict):
        return ["production-readiness controls are missing"]
    failures = []
    unknown_pending = set(pending_controls) - required
    if unknown_pending:
        failures.append(
            "production-readiness pending controls are unknown: "
            + ", ".join(sorted(unknown_pending))
        )
    safe_reference = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{5,255}$")
    for name in sorted(required):
        control = controls.get(name)
        if not isinstance(control, dict):
            failures.append(f"production-readiness control is missing: {name}")
            continue
        pending = name in pending_controls
        if pending:
            if control.get("status") not in {"pending_external", "verified"}:
                failures.append(
                    f"production-readiness candidate control has invalid status: {name}"
                )
        else:
            if control.get("status") != "verified":
                failures.append(f"production-readiness control is not verified: {name}")
            for field in ("owner", "verified_at", "evidence_reference"):
                if not str(control.get(field) or "").strip():
                    failures.append(f"production-readiness control {name} lacks {field}")
        verified_at = str(control.get("verified_at") or "").strip()
        if verified_at and not pending:
            try:
                parsed = datetime.fromisoformat(verified_at.replace("Z", "+00:00"))
                if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
                    raise ValueError
            except ValueError:
                failures.append(
                    f"production-readiness control {name} verified_at must be an ISO-8601 UTC timestamp"
                )
        evidence = str(control.get("evidence_reference") or "").strip()
        if evidence and not pending and not safe_reference.fullmatch(evidence):
            failures.append(
                f"production-readiness control {name} has an unsafe evidence_reference"
            )
        runbook = str(control.get("runbook") or "").strip()
        if not runbook:
            failures.append(f"production-readiness control {name} lacks runbook")
        else:
            candidate = (source_root / runbook).resolve()
            operations_root = (
                source_root / "tech_connector" / "docs" / "operations"
            ).resolve()
            try:
                candidate.relative_to(operations_root)
            except ValueError:
                failures.append(
                    f"production-readiness control {name} runbook is outside operations documentation"
                )
            else:
                if not candidate.is_file():
                    failures.append(
                        f"production-readiness control {name} runbook does not exist"
                    )
            if evidence and not pending and evidence == runbook:
                failures.append(
                    f"production-readiness control {name} cites its runbook instead of verification evidence"
                )
    if payload.get("status") != required_status:
        failures.append(
            "production readiness has not been approved for production"
            if required_status == "approved_for_production"
            else "production readiness status must be " + required_status
        )
    approval_reference = str(payload.get(approval_reference_field) or "").strip()
    if not approval_reference:
        failures.append(
            "production readiness lacks a release approval reference"
            if approval_reference_field == "release_approval_reference"
            else f"production readiness lacks {approval_reference_field}"
        )
    elif not safe_reference.fullmatch(approval_reference):
        failures.append(
            "production readiness has an unsafe release approval reference"
            if approval_reference_field == "release_approval_reference"
            else f"production readiness has an unsafe {approval_reference_field}"
        )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", default=".")
    parser.add_argument("--production", action="store_true")
    parser.add_argument(
        "--signed-installer-candidate", action="store_true",
        help="Allow only signed_installers to remain pending while creating a protected signing candidate.",
    )
    args = parser.parse_args()
    source_root = Path(args.source_root).resolve()
    failures = validate_legal_surface(source_root)
    failures.extend(validate_github_root_surface(source_root))
    failures.extend(sensitive_artifacts(publication_candidates(source_root)))
    if args.signed_installer_candidate and not args.production:
        failures.append("--signed-installer-candidate requires --production")
    if args.production:
        if sys.version_info[:2] != (3, 14):
            failures.append("production release checks require CPython 3.14")
        failures.extend(validate_production_configuration(source_root))
        failures.extend(validate_production_legal_approval(source_root))
        failures.extend(validate_production_source_access(source_root))
        if args.signed_installer_candidate:
            failures.extend(validate_production_readiness(
                source_root,
                pending_controls=frozenset({"signed_installers"}),
                required_status="approved_for_signing_candidate",
                approval_reference_field="signing_candidate_approval_reference",
            ))
        else:
            failures.extend(validate_production_readiness(source_root))
    if failures:
        print("Release gate failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print("Release gate passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
