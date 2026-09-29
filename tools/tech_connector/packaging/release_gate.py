"""Fail-closed checks for source publication and production packaging."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

# Keep direct script execution (`python tech_connector/packaging/release_gate.py`)
# equivalent to module execution without relying on a caller's PYTHONPATH.
_TOOLS_ROOT = Path(__file__).resolve().parents[2]
if str(_TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TOOLS_ROOT))

SENSITIVE_SUFFIXES = {".key", ".p12", ".pfx", ".bak"}
SENSITIVE_NAMES = {".env", "production_secrets.json", "service_account.json"}
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
        if (
            path.suffix.casefold() in SENSITIVE_SUFFIXES
            or lowered in SENSITIVE_NAMES
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
    path = source_root / "tech_connector/PRIVACY.md"
    if not path.is_file():
        return ["production privacy notice is missing"]
    text = " ".join(path.read_text(encoding="utf-8").casefold().split())
    if "release status: approved" not in text:
        return ["production privacy notice has not been marked approved by counsel"]
    return []


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", default=".")
    parser.add_argument("--production", action="store_true")
    args = parser.parse_args()
    source_root = Path(args.source_root).resolve()
    failures = validate_legal_surface(source_root)
    failures.extend(validate_github_root_surface(source_root))
    failures.extend(sensitive_artifacts(publication_candidates(source_root)))
    if args.production:
        if sys.version_info[:2] != (3, 14):
            failures.append("production release checks require CPython 3.14")
        failures.extend(validate_production_configuration(source_root))
        failures.extend(validate_production_legal_approval(source_root))
        failures.extend(validate_production_source_access(source_root))
    if failures:
        print("Release gate failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print("Release gate passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
