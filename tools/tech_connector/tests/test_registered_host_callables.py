from __future__ import annotations

from tech_connector.game_engine.integration.dcc_capability_audit_service import (
    AUDITED_HOSTS,
    audit_dcc_host,
)


def test_registered_local_host_callables_resolve_or_are_explicitly_delegated() -> None:
    failures: list[str] = []
    for host in AUDITED_HOSTS:
        if host == "tech_connector":
            continue
        report = audit_dcc_host(host)
        for department in report.departments:
            failures.extend(f"{host}:{operation}" for operation in department.missing_operations)

    assert not failures, "Missing registered host callables: " + ", ".join(failures)
