"""HTTPS and metadata-boundary tests for licensing network adapters."""

from __future__ import annotations

import json
import urllib.error
from io import BytesIO

import pytest

from tech_connector.licensing.configuration import LicensingConfiguration
from tech_connector.licensing.http_adapters import (
    HttpAuthenticationProvider,
    LicensingNetworkError,
    UrllibJsonTransport,
    _RejectRedirectHandler,
)


class Response:
    status = 200

    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def read(self, _maximum):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def test_transport_requires_credential_free_https_urls():
    for value in (
        "http://license.example.test/login",
        "https://user:password@license.example.test/login",
        "file:///tmp/license",
    ):
        with pytest.raises(ValueError):
            UrllibJsonTransport.validate_url(value)


def test_login_start_sends_only_minimum_identity_metadata():
    captured = {}

    def opener(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return Response({"status": "pending"})

    configuration = LicensingConfiguration(
        product="tech_connector",
        issuer="https://license.example.test",
        audience="tech-connector",
        clock_skew_seconds=60,
        maximum_offline_days=90,
        endpoints={"login_start": "https://license.example.test/v1/login/start"},
        public_keys={},
    )
    provider = HttpAuthenticationProvider(
        configuration,
        UrllibJsonTransport(opener=opener),
    )

    provider.begin_login("sha256:installation")

    assert captured["url"].startswith("https://")
    assert captured["payload"] == {
        "schema_version": 1,
        "product": "tech_connector",
        "device_id_hash": "sha256:installation",
    }
    assert not any(
        key in captured["payload"]
        for key in ("project_path", "assets", "source_files", "prompts", "scene")
    )


def test_transport_refuses_redirect_requests() -> None:
    handler = _RejectRedirectHandler()
    assert handler.redirect_request(None, None, 302, "Found", {}, "http://unsafe.test") is None


def test_http_error_preserves_only_safe_backend_guidance() -> None:
    body = json.dumps(
        {
            "error": {
                "code": "project_terms_acceptance_required",
                "message": "Accept the registered project terms in your account.",
                "action_url": "https://accounts.example.test/projects/prj_test/terms",
            }
        }
    ).encode("utf-8")

    def opener(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url,
            409,
            "Conflict",
            {"Retry-After": "12"},
            BytesIO(body),
        )

    transport = UrllibJsonTransport(opener=opener)
    with pytest.raises(LicensingNetworkError) as captured:
        transport.request("POST", "https://license.example.test/v1/projects/register", payload={})

    error = captured.value
    assert error.status_code == 409
    assert error.error_code == "project_terms_acceptance_required"
    assert error.action_url.startswith("https://")
    assert "Accept the registered project terms" in str(error)


def test_http_error_discards_unsafe_action_url() -> None:
    body = json.dumps(
        {
            "error": {
                "code": "license_selection_required",
                "message": "Choose a license.",
                "action_url": "http://accounts.example.test/licenses",
            }
        }
    ).encode("utf-8")

    def opener(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 409, "Conflict", {}, BytesIO(body))

    with pytest.raises(LicensingNetworkError) as captured:
        UrllibJsonTransport(opener=opener).request(
            "POST",
            "https://license.example.test/v1/activation",
            payload={},
        )

    assert captured.value.action_url == ""
