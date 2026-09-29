"""Provider-neutral HTTPS adapters for the private licensing service."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlparse

from .configuration import LicensingConfiguration


class LicensingNetworkError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int = 0,
        retryable: bool = False,
        error_code: str = "",
        action_url: str = "",
        retry_after_seconds: int = 0,
    ) -> None:
        super().__init__(message)
        self.status_code = int(status_code)
        self.retryable = bool(retryable)
        self.error_code = str(error_code or "")
        self.action_url = str(action_url or "")
        self.retry_after_seconds = max(0, min(300, int(retry_after_seconds or 0)))


@dataclass(frozen=True)
class JsonResponse:
    status_code: int
    payload: Mapping[str, Any]


class _RejectRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Never forward licensing requests or bearer tokens to another URL."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class UrllibJsonTransport:
    """Small HTTPS JSON transport with strict size and scheme boundaries."""

    def __init__(self, *, timeout_seconds: float = 10.0, maximum_bytes: int = 1_000_000, opener=None) -> None:
        self.timeout_seconds = float(timeout_seconds)
        self.maximum_bytes = int(maximum_bytes)
        self._opener = opener or urllib.request.build_opener(_RejectRedirectHandler()).open

    @staticmethod
    def validate_url(url: str) -> str:
        value = str(url or "").strip()
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("licensing endpoints must be credential-free HTTPS URLs")
        return value

    def request(
        self,
        method: str,
        url: str,
        *,
        payload: Mapping[str, Any] | None = None,
        access_token: str = "",
    ) -> JsonResponse:
        endpoint = self.validate_url(url)
        body = None if payload is None else json.dumps(dict(payload)).encode("utf-8")
        headers = {
            "Accept": "application/json",
            "User-Agent": "TechConnector-Licensing/1",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        if access_token:
            headers["Authorization"] = "Bearer " + str(access_token)
        request = urllib.request.Request(endpoint, data=body, headers=headers, method=method.upper())
        try:
            response = self._opener(request, timeout=self.timeout_seconds)
            with response:
                raw = response.read(self.maximum_bytes + 1)
                status = int(getattr(response, "status", 200))
        except urllib.error.HTTPError as exc:
            raise _network_error_from_http_error(exc, self.maximum_bytes) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise LicensingNetworkError(
                "The licensing service could not be reached.",
                retryable=True,
            ) from exc
        if len(raw) > self.maximum_bytes:
            raise LicensingNetworkError("Licensing response exceeded the allowed size.")
        try:
            decoded = json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeDecodeError, ValueError) as exc:
            raise LicensingNetworkError("Licensing service returned invalid JSON.") from exc
        if not isinstance(decoded, Mapping):
            raise LicensingNetworkError("Licensing service response must be a JSON object.")
        return JsonResponse(status, decoded)


def _network_error_from_http_error(
    error: urllib.error.HTTPError,
    maximum_bytes: int,
) -> LicensingNetworkError:
    payload: Mapping[str, Any] = {}
    try:
        raw = error.read(maximum_bytes + 1)
        decoded = json.loads(raw.decode("utf-8")) if raw and len(raw) <= maximum_bytes else {}
        if isinstance(decoded, Mapping):
            payload = decoded
    except (OSError, UnicodeDecodeError, ValueError):
        pass

    error_value = payload.get("error")
    details = error_value if isinstance(error_value, Mapping) else payload
    error_code = _safe_text(
        details.get("code") if isinstance(details, Mapping) else error_value,
        maximum=80,
    )
    user_message = _safe_text(
        details.get("message") if isinstance(details, Mapping) else payload.get("message"),
        maximum=300,
    )
    action_url = _safe_action_url(
        details.get("action_url") if isinstance(details, Mapping) else payload.get("action_url")
    )
    retry_after = 0
    try:
        retry_after = int(error.headers.get("Retry-After") or 0)
    except (AttributeError, TypeError, ValueError):
        pass
    retryable = (
        error.code == 429
        or 500 <= error.code < 600
        or error_code in {"rate_limited", "temporarily_unavailable"}
    )
    return LicensingNetworkError(
        user_message or f"Licensing service returned HTTP {error.code}.",
        status_code=error.code,
        retryable=retryable,
        error_code=error_code,
        action_url=action_url,
        retry_after_seconds=retry_after,
    )


def _safe_text(value: Any, *, maximum: int) -> str:
    text = " ".join(str(value or "").split())
    return text[:maximum]


def _safe_action_url(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parsed = urlparse(text)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        return ""
    return text


class HttpAuthenticationProvider:
    def __init__(self, configuration: LicensingConfiguration, transport: UrllibJsonTransport) -> None:
        self.configuration = configuration
        self.transport = transport

    def _endpoint(self, name: str, *, optional: bool = False) -> str:
        value = str(self.configuration.endpoints.get(name) or "").strip()
        if not value and optional:
            return ""
        if not value:
            raise LicensingNetworkError(f"Licensing endpoint '{name}' is not configured.")
        return self.transport.validate_url(value)

    def begin_login(self, device_id_hash: str, project_id: str = "") -> Mapping[str, Any]:
        payload = {
            "schema_version": 1,
            "product": self.configuration.product,
            "device_id_hash": device_id_hash,
        }
        if project_id:
            payload["project_id"] = str(project_id)
        return self.transport.request(
            "POST",
            self._endpoint("login_start"),
            payload=payload,
        ).payload

    def poll_login(self, login_attempt_id: str) -> Mapping[str, Any]:
        return self.transport.request(
            "POST",
            self._endpoint("login_poll"),
            payload={"schema_version": 1, "login_attempt_id": login_attempt_id},
        ).payload

    def refresh_session(self, refresh_credential: str) -> Mapping[str, Any]:
        return self.transport.request(
            "POST",
            self._endpoint("session_refresh"),
            payload={"schema_version": 1, "refresh_credential": refresh_credential},
        ).payload

    def logout(self, access_token: str) -> None:
        endpoint = self._endpoint("logout", optional=True)
        if endpoint:
            self.transport.request("POST", endpoint, payload={"schema_version": 1}, access_token=access_token)


class HttpLicensingGateway:
    def __init__(self, configuration: LicensingConfiguration, transport: UrllibJsonTransport) -> None:
        self.configuration = configuration
        self.transport = transport

    def _endpoint(self, name: str) -> str:
        value = str(self.configuration.endpoints.get(name) or "").strip()
        if not value:
            raise LicensingNetworkError(f"Licensing endpoint '{name}' is not configured.")
        return self.transport.validate_url(value)

    def register_project(self, access_token: str, project_id: str, license_id: str) -> Mapping[str, Any]:
        return self.transport.request(
            "POST",
            self._endpoint("project_registration"),
            payload={"schema_version": 1, "project_id": project_id, "license_id": license_id},
            access_token=access_token,
        ).payload

    def activate_device(self, access_token: str, license_id: str, device_id_hash: str) -> Mapping[str, Any]:
        return self.transport.request(
            "POST",
            self._endpoint("activation"),
            payload={
                "schema_version": 1,
                "license_id": license_id,
                "device_id_hash": device_id_hash,
            },
            access_token=access_token,
        ).payload

    def deactivate_device(self, access_token: str, activation_id: str) -> None:
        self.transport.request(
            "POST",
            self._endpoint("deactivation"),
            payload={"schema_version": 1, "activation_id": activation_id},
            access_token=access_token,
        )

    def refresh_entitlement(self, access_token: str) -> str:
        payload = self.transport.request(
            "POST",
            self._endpoint("entitlement"),
            payload={"schema_version": 1, "product": self.configuration.product},
            access_token=access_token,
        ).payload
        return str(payload.get("entitlement_token") or "").strip()
