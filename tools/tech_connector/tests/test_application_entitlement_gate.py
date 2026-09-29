"""Tests for the official-build entitlement bypass boundary."""

from __future__ import annotations

from types import SimpleNamespace

from tech_connector.services.licensing_startup_policy import (
    development_entitlement_bypass_allowed,
    legacy_entitlement_allowed,
)
from tech_connector.services.license_entitlement_service import verify_entitlement


def test_development_bypass_requires_explicit_source_environment(monkeypatch) -> None:
    monkeypatch.delenv("TECH_CONNECTOR_DEV_LICENSE_BYPASS", raising=False)
    monkeypatch.delattr("sys.frozen", raising=False)
    assert not development_entitlement_bypass_allowed()

    monkeypatch.setenv("TECH_CONNECTOR_DEV_LICENSE_BYPASS", "1")
    assert development_entitlement_bypass_allowed()


def test_development_bypass_is_disabled_in_frozen_release(monkeypatch) -> None:
    monkeypatch.setenv("TECH_CONNECTOR_DEV_LICENSE_BYPASS", "1")
    monkeypatch.setattr("sys.frozen", True, raising=False)
    assert not development_entitlement_bypass_allowed()


def test_legacy_entitlements_are_disabled_in_frozen_release(monkeypatch) -> None:
    monkeypatch.setenv("TECH_CONNECTOR_ALLOW_LEGACY_ENTITLEMENT", "1")
    monkeypatch.setattr("sys.frozen", True, raising=False)
    assert not legacy_entitlement_allowed()


def test_legacy_local_unlock_flags_are_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("TECH_CONNECTOR_ALLOW_LEGACY_ENTITLEMENT", raising=False)
    monkeypatch.delattr("sys.frozen", raising=False)

    entitlement = verify_entitlement(
        {
            "tech_connector_require_login": False,
            "tech_connector_account_email": "creator@example.com",
            "tech_connector_allow_offline_community": True,
        }
    )

    assert not entitlement.unlocked
    assert entitlement.source == "legacy_disabled"


def test_desktop_does_not_construct_main_window_when_preflight_denies(monkeypatch) -> None:
    from tech_connector.app import application
    from tech_connector.app import licensing_gate
    from tech_connector.services import application_service

    events = []

    class Signal:
        def connect(self, callback):
            events.append(("exit_handler_connected", callback))

    class FakeApplication:
        def __init__(self, _args):
            self.aboutToQuit = Signal()

        def quit(self):
            events.append(("quit", None))

    class FakeService:
        pass

    def forbidden_main_window(*_args, **_kwargs):
        raise AssertionError("MainWindow must not be constructed before licensing succeeds")

    monkeypatch.delenv("TECH_CONNECTOR_SMOKE_TEST", raising=False)
    monkeypatch.setattr(application, "QApplication", FakeApplication)
    monkeypatch.setattr(application, "MainWindow", forbidden_main_window)
    monkeypatch.setattr(application_service, "ApplicationService", FakeService)
    monkeypatch.setattr(
        licensing_gate,
        "ensure_desktop_preflight",
        lambda _service: (False, "License acceptance required", ()),
    )
    monkeypatch.setattr(
        application,
        "QMessageBox",
        SimpleNamespace(
            critical=lambda _parent, title, reason: events.append(
                ("critical", (title, reason))
            )
        ),
    )

    application.run_application()

    assert ("critical", ("Activation required", "License acceptance required")) in events
    assert ("quit", None) in events
