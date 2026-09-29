"""Public licensing-client configuration loading."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

from .verification import EntitlementTokenVerifier


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "licensing.json"
REQUIRED_PRODUCTION_ENDPOINTS = (
    "login_start",
    "login_poll",
    "session_refresh",
    "entitlement",
    "activation",
    "deactivation",
    "project_registration",
)


@dataclass(frozen=True)
class LicensingConfiguration:
    product: str
    issuer: str
    audience: str
    clock_skew_seconds: int
    maximum_offline_days: int
    endpoints: Mapping[str, str]
    public_keys: Mapping[str, str]

    def build_verifier(self) -> EntitlementTokenVerifier:
        return EntitlementTokenVerifier.from_base64_keys(
            self.public_keys,
            issuer=self.issuer,
            audience=self.audience,
            clock_skew_seconds=self.clock_skew_seconds,
            maximum_offline_days=self.maximum_offline_days,
        )


def _mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be a JSON object")
    return value


def _credential_free_https_url(value: str, *, allow_query: bool = False) -> bool:
    parsed = urlparse(str(value or "").strip())
    return bool(
        parsed.scheme == "https"
        and parsed.netloc
        and not parsed.username
        and not parsed.password
        and not parsed.fragment
        and (allow_query or not parsed.query)
    )


def configuration_errors(
    configuration: LicensingConfiguration,
    *,
    production: bool = False,
) -> tuple[str, ...]:
    """Return public-client configuration problems without exposing secrets."""
    failures: list[str] = []
    if configuration.product != "tech_connector":
        failures.append("product must be 'tech_connector'")
    if not _credential_free_https_url(configuration.issuer):
        failures.append("issuer must be a credential-free HTTPS URL without a query or fragment")
    if not configuration.audience.strip():
        failures.append("audience is required")
    if not 0 <= configuration.clock_skew_seconds <= 300:
        failures.append("clock_skew_seconds must be between 0 and 300")
    if not 1 <= configuration.maximum_offline_days <= 90:
        failures.append("maximum_offline_days must be between 1 and 90")

    endpoint_names = set(configuration.endpoints)
    endpoint_names.update(REQUIRED_PRODUCTION_ENDPOINTS if production else ())
    for name in sorted(endpoint_names):
        value = str(configuration.endpoints.get(name) or "").strip()
        if not value:
            if production and name in REQUIRED_PRODUCTION_ENDPOINTS:
                failures.append(f"licensing endpoint '{name}' is required")
            continue
        if not _credential_free_https_url(value):
            failures.append(
                f"licensing endpoint '{name}' must be a credential-free HTTPS URL "
                "without a query or fragment"
            )

    if production and not configuration.public_keys:
        failures.append("at least one entitlement public key is required")
    if any(not str(key_id).strip() for key_id in configuration.public_keys):
        failures.append("entitlement public key IDs cannot be empty")
    if configuration.public_keys:
        try:
            configuration.build_verifier()
        except (TypeError, ValueError) as exc:
            failures.append(f"entitlement public keys are invalid: {exc}")
    return tuple(failures)


def load_licensing_configuration(path: str | Path = DEFAULT_CONFIG_PATH) -> LicensingConfiguration:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("licensing configuration must be a JSON object")
    if int(payload.get("schema_version") or 0) != 1:
        raise ValueError("unsupported licensing configuration schema")
    endpoints = _mapping(payload.get("endpoints", {}), "endpoints")
    public_keys = _mapping(payload.get("public_keys", {}), "public_keys")
    configuration = LicensingConfiguration(
        product=str(payload.get("product") or ""),
        issuer=str(payload.get("issuer") or ""),
        audience=str(payload.get("audience") or ""),
        clock_skew_seconds=int(payload.get("clock_skew_seconds") or 0),
        maximum_offline_days=int(payload.get("maximum_offline_days") or 0),
        endpoints={str(key): str(value) for key, value in endpoints.items()},
        public_keys={str(key): str(value) for key, value in public_keys.items()},
    )
    failures = configuration_errors(configuration)
    if failures:
        raise ValueError("invalid licensing configuration: " + "; ".join(failures))
    return configuration
