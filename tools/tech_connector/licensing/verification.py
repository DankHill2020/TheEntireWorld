"""Strict Ed25519 entitlement verification. This module never signs tokens."""

from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
except ImportError:  # Keep non-licensing tools importable; verification remains fail-closed.
    class InvalidSignature(Exception):
        pass
    Ed25519PublicKey = None  # type: ignore[assignment,misc]

from .domain import EntitlementClaims


class TokenVerificationError(ValueError):
    """Raised when an entitlement token is malformed, untrusted, or out of date."""


def _b64url_decode(value: str) -> bytes:
    try:
        return base64.b64decode(
            value.encode("ascii") + b"=" * (-len(value) % 4),
            altchars=b"-_",
            validate=True,
        )
    except Exception as exc:
        raise TokenVerificationError("token contains invalid base64url data") from exc


def _json_object(value: bytes, label: str) -> Mapping[str, Any]:
    def reject_duplicates(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise TokenVerificationError(f"{label} contains duplicate key {key!r}")
            result[key] = item
        return result

    try:
        decoded = json.loads(value.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except TokenVerificationError:
        raise
    except Exception as exc:
        raise TokenVerificationError(f"token {label} is not valid JSON") from exc
    if not isinstance(decoded, Mapping):
        raise TokenVerificationError(f"token {label} must be an object")
    return decoded


class EntitlementTokenVerifier:
    """Verify versioned JWS-like entitlement tokens with configured public keys."""

    def __init__(
        self,
        public_keys: Mapping[str, Ed25519PublicKey],
        *,
        issuer: str,
        audience: str,
        clock_skew_seconds: int = 60,
        maximum_offline_days: int = 90,
    ) -> None:
        self._public_keys = dict(public_keys)
        self.issuer = issuer
        self.audience = audience
        self.clock_skew = timedelta(seconds=max(0, int(clock_skew_seconds)))
        self.maximum_offline_window = timedelta(days=max(1, int(maximum_offline_days)))

    @classmethod
    def from_base64_keys(
        cls,
        public_keys: Mapping[str, str],
        *,
        issuer: str,
        audience: str,
        clock_skew_seconds: int = 60,
        maximum_offline_days: int = 90,
    ) -> "EntitlementTokenVerifier":
        if Ed25519PublicKey is None and public_keys:
            raise RuntimeError(
                "Entitlement verification requires the 'cryptography' runtime dependency. "
                "Install the packaged requirements before activating Tech Connector."
            )
        parsed = {}
        for key_id, encoded in public_keys.items():
            raw = _b64url_decode(str(encoded))
            if len(raw) != 32:
                raise ValueError(f"Ed25519 public key {key_id!r} must contain 32 bytes")
            parsed[str(key_id)] = Ed25519PublicKey.from_public_bytes(raw)
        return cls(
            parsed,
            issuer=issuer,
            audience=audience,
            clock_skew_seconds=clock_skew_seconds,
            maximum_offline_days=maximum_offline_days,
        )

    def verify(self, token: str, *, now: datetime | None = None) -> EntitlementClaims:
        parts = str(token or "").strip().split(".")
        if len(parts) != 3:
            raise TokenVerificationError("entitlement token must have three compact JWS segments")
        encoded_header, encoded_payload, encoded_signature = parts
        header = _json_object(_b64url_decode(encoded_header), "header")
        if header.get("typ") != "TC-ENT" or header.get("alg") != "EdDSA":
            raise TokenVerificationError("token type or signing algorithm is not allowed")
        key_id = str(header.get("kid") or "")
        public_key = self._public_keys.get(key_id)
        if public_key is None:
            raise TokenVerificationError("token references an unknown signing key")
        signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
        try:
            public_key.verify(_b64url_decode(encoded_signature), signing_input)
        except InvalidSignature as exc:
            raise TokenVerificationError("entitlement signature did not verify") from exc

        payload = _json_object(_b64url_decode(encoded_payload), "payload")
        try:
            claims = EntitlementClaims.from_payload(payload)
        except (TypeError, ValueError) as exc:
            raise TokenVerificationError(f"entitlement payload is invalid: {exc}") from exc
        if claims.issuer != self.issuer:
            raise TokenVerificationError("entitlement issuer is not trusted")
        if self.audience not in claims.audience:
            raise TokenVerificationError("entitlement audience does not include this product")

        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            raise ValueError("now must include a timezone")
        current = current.astimezone(timezone.utc)
        if current + self.clock_skew < claims.not_before:
            raise TokenVerificationError("entitlement is not active yet")
        if current + self.clock_skew < claims.issued_at:
            raise TokenVerificationError("entitlement issue time is in the future")
        if current - self.clock_skew >= claims.expires_at:
            raise TokenVerificationError("entitlement token has expired")
        if claims.not_before >= claims.expires_at:
            raise TokenVerificationError("entitlement activation time is not before expiration")
        if claims.issued_at >= claims.expires_at:
            raise TokenVerificationError("entitlement issue time is not before expiration")
        if claims.license.accepted_at > claims.issued_at + self.clock_skew:
            raise TokenVerificationError("license acceptance is after entitlement issuance")
        if claims.offline.refresh_after < claims.issued_at - self.clock_skew:
            raise TokenVerificationError("offline refresh date is before entitlement issuance")
        if claims.offline.expires_at > claims.expires_at:
            raise TokenVerificationError("offline expiration exceeds the signed token lifetime")
        if claims.offline.expires_at - claims.issued_at > self.maximum_offline_window + self.clock_skew:
            raise TokenVerificationError("offline window exceeds the configured maximum")
        return claims
