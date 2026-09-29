"""Tests for provider-neutral login and activation orchestration."""

from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tech_connector.licensing.activation_client import LoginState, LicensingActivationClient
from tech_connector.licensing.configuration import LicensingConfiguration
from tech_connector.licensing.context import LicensingContext
from tech_connector.licensing.local_storage import FileEntitlementStore
from tech_connector.tests.test_licensing_foundation import NOW, _payload, _sign


class MemoryCredentials:
    def __init__(self):
        self.values = {}

    def load(self, key):
        return self.values.get(key, "")

    def save(self, key, value):
        self.values[key] = value

    def delete(self, key):
        self.values.pop(key, None)


class MemoryAudit:
    def __init__(self):
        self.events = []

    def record(self, event, metadata):
        self.events.append((event, dict(metadata)))


class Device:
    def device_id_hash(self):
        return "device_hash"


class Authentication:
    def __init__(self):
        self.poll_payload = {"status": "pending"}

    def begin_login(self, device_id_hash, project_id=""):
        assert device_id_hash == "device_hash"
        return {
            "login_attempt_id": "login_1",
            "verification_uri": "https://accounts.example.test/device",
            "verification_uri_complete": "https://accounts.example.test/device?code=ABCD",
            "user_code": "ABCD",
            "expires_at": (NOW + timedelta(minutes=10)).isoformat(),
            "poll_interval_seconds": 2,
        }

    def poll_login(self, login_attempt_id):
        assert login_attempt_id == "login_1"
        return self.poll_payload

    def refresh_session(self, refresh_credential):
        assert refresh_credential == "refresh_1"
        return {
            "access_token": "access_2",
            "refresh_credential": "refresh_2",
            "access_expires_at": (NOW + timedelta(minutes=20)).isoformat(),
        }

    def logout(self, access_token):
        return None


class Gateway:
    def __init__(self, token):
        self.token = token
        self.registered = None
        self.deactivated = None

    def register_project(self, access_token, project_id, license_id):
        self.registered = (access_token, project_id, license_id)
        return {"status": "registered"}

    def activate_device(self, access_token, license_id, device_id_hash):
        assert access_token == "access_1"
        assert device_id_hash == "device_hash"
        return {"entitlement_token": self.token}

    def deactivate_device(self, access_token, activation_id):
        self.deactivated = (access_token, activation_id)

    def refresh_entitlement(self, access_token):
        return self.token


def _client(tmp_path):
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    configuration = LicensingConfiguration(
        product="tech_connector",
        issuer="https://license.theentireworld.com",
        audience="tech-connector",
        clock_skew_seconds=0,
        maximum_offline_days=90,
        endpoints={},
        public_keys={"test-key": base64.urlsafe_b64encode(public_key).decode("ascii").rstrip("=")},
    )
    context = LicensingContext(
        configuration,
        entitlement_store=FileEntitlementStore(tmp_path / "licensing"),
        device_identity=Device(),
    )
    token = _sign(_payload(), private_key)
    authentication = Authentication()
    credentials = MemoryCredentials()
    client = LicensingActivationClient(
        configuration,
        authentication=authentication,
        gateway=Gateway(token),
        credential_store=credentials,
        licensing_context=context,
        clock=lambda: NOW,
    )
    return client, authentication, credentials


def test_login_challenge_and_verified_session(tmp_path):
    client, authentication, credentials = _client(tmp_path)
    challenge = client.begin_login()
    assert challenge.user_code == "ABCD"

    authentication.poll_payload = {
        "status": "authenticated",
        "account_id": "acct_1",
        "email": "creator@example.com",
        "email_verified": True,
        "access_token": "access_1",
        "refresh_credential": "refresh_1",
        "access_expires_at": (NOW + timedelta(minutes=20)).isoformat(),
    }
    result = client.poll_login(challenge.login_attempt_id)

    assert result.state is LoginState.AUTHENTICATED
    assert credentials.values[client.REFRESH_CREDENTIAL_KEY] == "refresh_1"


def test_activation_caches_only_verified_device_bound_entitlement(tmp_path):
    client, authentication, _credentials = _client(tmp_path)
    authentication.poll_payload = {
        "status": "authenticated",
        "account_id": "acct_1",
        "email": "creator@example.com",
        "email_verified": True,
        "access_token": "access_1",
        "refresh_credential": "refresh_1",
        "access_expires_at": (NOW + timedelta(minutes=20)).isoformat(),
    }
    client.poll_login("login_1")

    outcome = client.activate_device()

    assert outcome.license_id == "lic_test"
    assert client.licensing_context.entitlement_store.load_token()


def test_project_registration_sends_uuid_not_local_path(tmp_path):
    client, authentication, _credentials = _client(tmp_path)
    authentication.poll_payload = {
        "status": "authenticated",
        "account_id": "acct_1",
        "email": "creator@example.com",
        "email_verified": True,
        "access_token": "access_1",
        "refresh_credential": "refresh_1",
        "access_expires_at": (NOW + timedelta(minutes=20)).isoformat(),
    }
    client.poll_login("login_1")
    project_root = tmp_path / "private_project_name"
    project_root.mkdir()

    client.register_project(project_root, "lic_test")

    _access_token, project_id, license_id = client.gateway.registered
    assert project_id.startswith("prj_")
    assert "private_project_name" not in project_id
    assert license_id == "lic_test"


def test_deactivation_releases_device_and_clears_local_session(tmp_path):
    client, authentication, credentials = _client(tmp_path)
    authentication.poll_payload = {
        "status": "authenticated",
        "account_id": "acct_1",
        "email": "creator@example.com",
        "email_verified": True,
        "access_token": "access_1",
        "refresh_credential": "refresh_1",
        "access_expires_at": (NOW + timedelta(minutes=20)).isoformat(),
    }
    client.poll_login("login_1")
    outcome = client.activate_device()

    client.deactivate_device(outcome.activation_id)

    assert client.gateway.deactivated == ("access_1", "act_test")
    assert client.licensing_context.entitlement_store.load_token() == ""
    assert client.REFRESH_CREDENTIAL_KEY not in credentials.values


def test_activation_lifecycle_records_only_opaque_audit_identifiers(tmp_path):
    client, authentication, _credentials = _client(tmp_path)
    audit = MemoryAudit()
    client.audit_sink = audit
    authentication.poll_payload = {
        "status": "authenticated",
        "account_id": "acct_1",
        "email": "creator@example.com",
        "email_verified": True,
        "access_token": "access_1",
        "refresh_credential": "refresh_1",
        "access_expires_at": (NOW + timedelta(minutes=20)).isoformat(),
    }

    client.poll_login("login_1")
    outcome = client.activate_device()
    client.deactivate_device(outcome.activation_id)

    assert [event for event, _metadata in audit.events] == [
        "login_authenticated",
        "device_activated",
        "device_deactivated",
    ]
    serialized = json.dumps(audit.events)
    assert "creator@example.com" not in serialized
    assert "access_1" not in serialized
    assert "refresh_1" not in serialized
