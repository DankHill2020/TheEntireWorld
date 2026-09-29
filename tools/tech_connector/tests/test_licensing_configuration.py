"""Production licensing configuration validation tests."""

from __future__ import annotations

import base64
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tech_connector.licensing.configuration import (
    LicensingConfiguration,
    configuration_errors,
    load_licensing_configuration,
)


def _public_key() -> str:
    value = Ed25519PrivateKey.generate().public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _configuration(**overrides) -> LicensingConfiguration:
    values = {
        "product": "tech_connector",
        "issuer": "https://license.example.test",
        "audience": "tech-connector",
        "clock_skew_seconds": 60,
        "maximum_offline_days": 90,
        "endpoints": {
            "login_start": "https://license.example.test/v1/login/start",
            "login_poll": "https://license.example.test/v1/login/poll",
            "session_refresh": "https://license.example.test/v1/session/refresh",
            "entitlement": "https://license.example.test/v1/entitlement",
            "activation": "https://license.example.test/v1/activation",
            "deactivation": "https://license.example.test/v1/deactivation",
            "project_registration": "https://license.example.test/v1/projects/register",
        },
        "public_keys": {"production-2026-01": _public_key()},
    }
    values.update(overrides)
    return LicensingConfiguration(**values)


def test_complete_production_configuration_is_accepted() -> None:
    assert configuration_errors(_configuration(), production=True) == ()


def test_production_configuration_requires_every_endpoint_and_a_valid_key() -> None:
    failures = configuration_errors(
        _configuration(endpoints={}, public_keys={"bad": "not-a-key"}),
        production=True,
    )

    assert any("login_start" in failure for failure in failures)
    assert any("public keys are invalid" in failure for failure in failures)


@pytest.mark.parametrize(
    "endpoint",
    (
        "https://user:password@license.example.test/v1/activation",
        "https://license.example.test/v1/activation?api_key=secret",
        "https://license.example.test/v1/activation#fragment",
        "http://license.example.test/v1/activation",
    ),
)
def test_production_configuration_rejects_unsafe_endpoint_shapes(endpoint: str) -> None:
    endpoints = dict(_configuration().endpoints)
    endpoints["activation"] = endpoint

    assert any(
        "activation" in failure
        for failure in configuration_errors(
            _configuration(endpoints=endpoints),
            production=True,
        )
    )


def test_loader_rejects_non_object_endpoint_configuration(tmp_path) -> None:
    path = tmp_path / "licensing.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "product": "tech_connector",
                "issuer": "https://license.example.test",
                "audience": "tech-connector",
                "clock_skew_seconds": 60,
                "maximum_offline_days": 90,
                "endpoints": [],
                "public_keys": {},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="endpoints must be a JSON object"):
        load_licensing_configuration(path)
