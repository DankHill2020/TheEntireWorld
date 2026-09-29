"""Readable, privacy-minimal local license acceptance receipts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .domain import EntitlementClaims
from .local_storage import _restrict_to_current_user


class FileLicenseAcceptanceStore:
    """Keep human-readable acceptance evidence without tokens, email, or assets."""

    SCHEMA = "tech_connector.license_acceptance_receipts.v1"

    def __init__(
        self,
        root: str | Path,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.root = Path(root).expanduser()
        self.path = self.root / "license_acceptance_receipts.json"
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def _timestamp(value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    def _load(self) -> dict:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {
                "schema": self.SCHEMA,
                "purpose": "Human-readable local evidence of accepted Tech Connector license terms.",
                "records": [],
            }
        if not isinstance(payload, dict) or payload.get("schema") != self.SCHEMA:
            raise ValueError("license acceptance receipt schema is not recognized")
        records = payload.get("records")
        if not isinstance(records, list):
            raise ValueError("license acceptance receipts must contain a records list")
        return payload

    def _save(self, payload: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        _restrict_to_current_user(temporary)
        temporary.replace(self.path)
        _restrict_to_current_user(self.path)

    def record_local_notice(self, *, agreement_version: str, accepted_at: str) -> Path:
        version = str(agreement_version or "").strip()
        timestamp = str(accepted_at or "").strip()
        if not version or not timestamp:
            raise ValueError("local notice agreement version and acceptance time are required")
        payload = self._load()
        record = {
            "kind": "local_license_notice",
            "agreement_version": version,
            "accepted_at": timestamp,
            "acceptance_scope": "local_notice",
        }
        records = payload["records"]
        if not any(
            item.get("kind") == record["kind"]
            and item.get("agreement_version") == version
            and item.get("accepted_at") == timestamp
            for item in records
            if isinstance(item, dict)
        ):
            records.append(record)
            self._save(payload)
        elif not self.path.is_file():
            self._save(payload)
        return self.path

    def record_verified_entitlement(self, claims: EntitlementClaims) -> Path:
        now = self._timestamp(self.clock())
        record = {
            "kind": "verified_signed_agreement",
            "evidence": "ed25519_verified_entitlement",
            "agreement_version": claims.license.agreement_version,
            "accepted_at": self._timestamp(claims.license.accepted_at),
            "account_id": claims.principal.account_id,
            "organization_id": claims.principal.organization_id,
            "license_id": claims.license.license_id,
            "market_segment": claims.license.market_segment.value,
            "offer_id": claims.license.offer_id,
            "first_recorded_at": now,
            "last_verified_at": now,
            "last_verified_token_id": claims.token_id,
        }
        payload = self._load()
        records = payload["records"]
        match_index = next(
            (
                index
                for index, item in enumerate(records)
                if isinstance(item, dict)
                and item.get("kind") == record["kind"]
                and item.get("license_id") == record["license_id"]
                and item.get("agreement_version") == record["agreement_version"]
                and item.get("accepted_at") == record["accepted_at"]
            ),
            None,
        )
        if match_index is None:
            records.append(record)
        else:
            record["first_recorded_at"] = str(
                records[match_index].get("first_recorded_at") or now
            )
            records[match_index] = record
        self._save(payload)
        return self.path
