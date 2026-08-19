from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from tech_connector.game_engine.integration.dcc_source_parity_qualification_service import (
    SOURCE_PARITY_QUALIFICATION_SCHEMA,
    qualify_available_dcc_sources,
    qualify_dcc_source_parity,
    source_parity_ledger,
    store_source_parity_receipt,
    validate_source_parity_receipt,
)


class _FakeSourceBridge:
    def __init__(self, host: str, snapshot: dict, *, port: int = 7011):
        self.host = host
        self.snapshot = snapshot
        self.port = port
        self.frame = 12
        self.dirty = False
        self.pid = 4200
        self.closed = False
        self.calls: list[tuple[str, int]] = []

    def find_ports(self):
        return [self.port]

    def session_info(self, *, port: int, timeout: float):
        self.calls.append(("identity", port))
        if self.closed:
            return {"ok": False, "port": port, "error": "closed"}
        return {
            "ok": True,
            "port": port,
            "pid": self.pid,
            "session_id": f"{self.host}:{self.pid}",
            "scene": self.snapshot.get("scene", "C:/show/asset.scene"),
            "frame": self.frame,
            "dirty": self.dirty,
        }

    def get_scene_snapshot(self, *, port: int, **kwargs):
        self.calls.append(("snapshot", port))
        assert kwargs["include_geometry"] is False
        assert kwargs["include_materials"] is True
        if self.host == "maya":
            assert kwargs["meshes_only"] is True
        return True, deepcopy(self.snapshot)


def _material_snapshot(host: str = "maya") -> dict:
    return {
        "schema": f"tech_connector.{host}.scene_snapshot.v1",
        "provider_id": host,
        "process_id": 4200,
        "scene": "C:/show/asset.scene",
        "isolation": {"include_materials": True, "include_geometry": False},
        "objects": [{
            "native_id": "mesh:body",
            "name": "body",
            "type": "mesh",
            "material": {
                "source_material_id": "mat:skin",
                "name": "skin",
                "source_shader": "standard_surface",
            },
            "material_assignments": [{"material_id": "mat:skin", "slot_index": 0}],
        }],
    }


def test_native_source_parity_uses_exact_port_and_material_evidence() -> None:
    bridge = _FakeSourceBridge("maya", _material_snapshot())

    receipt = qualify_dcc_source_parity("maya", 7011, bridge=bridge)

    assert receipt["schema"] == SOURCE_PARITY_QUALIFICATION_SCHEMA
    assert receipt["status"] == "qualified"
    assert receipt["exact_session_verified"]
    assert receipt["non_mutating_verified"]
    assert receipt["role_evidence"]["material_count"] == 1
    assert receipt["role_evidence"]["assignment_count"] == 1
    assert receipt["source_fingerprint"] == {"exists": False}
    assert receipt["integrity"]["snapshot_digest"] == receipt["snapshot_digest"]
    assert bridge.calls == [("identity", 7011), ("snapshot", 7011), ("identity", 7011)]


def test_source_parity_receipt_validates_integrity_and_rejects_tampering() -> None:
    bridge = _FakeSourceBridge("maya", _material_snapshot())
    receipt = qualify_dcc_source_parity("maya", 7011, bridge=bridge)

    valid = validate_source_parity_receipt("maya", receipt, bridge=bridge)
    tampered = deepcopy(receipt)
    tampered["role_evidence"]["material_count"] = 999
    invalid = validate_source_parity_receipt("maya", tampered, bridge=bridge)

    assert valid["valid"]
    assert not invalid["valid"]
    assert "receipt_integrity" in invalid["gates"]


def test_source_revision_and_receipt_age_invalidate_qualification(tmp_path) -> None:
    source = tmp_path / "asset.ma"
    source.write_text("version one", encoding="utf-8")
    snapshot = _material_snapshot()
    snapshot["scene"] = str(source)
    bridge = _FakeSourceBridge("maya", snapshot)
    receipt = qualify_dcc_source_parity("maya", 7011, bridge=bridge)

    source.write_text("version two", encoding="utf-8")
    changed = validate_source_parity_receipt("maya", receipt, bridge=bridge)
    checked_at = datetime.fromisoformat(receipt["checked_at"])
    expired = validate_source_parity_receipt(
        "maya",
        receipt,
        bridge=bridge,
        check_source=False,
        now=checked_at + timedelta(days=2),
        max_age_seconds=24 * 60 * 60,
    )

    assert "source_revision_changed" in changed["gates"]
    assert "receipt_freshness" in expired["gates"]


def test_changed_bridge_implementation_invalidates_receipt() -> None:
    class ReplacementBridge(_FakeSourceBridge):
        pass

    bridge = _FakeSourceBridge("maya", _material_snapshot())
    receipt = qualify_dcc_source_parity("maya", 7011, bridge=bridge)
    replacement = ReplacementBridge("maya", _material_snapshot())

    validation = validate_source_parity_receipt("maya", receipt, bridge=replacement)

    assert "bridge_implementation_changed" in validation["gates"]


def test_closed_or_restarted_live_session_invalidates_receipt() -> None:
    bridge = _FakeSourceBridge("maya", _material_snapshot())
    receipt = qualify_dcc_source_parity("maya", 7011, bridge=bridge)

    bridge.closed = True
    closed = validate_source_parity_receipt("maya", receipt, bridge=bridge)
    bridge.closed = False
    bridge.pid = 7777
    restarted = validate_source_parity_receipt("maya", receipt, bridge=bridge)

    assert "live_session_unavailable" in closed["gates"]
    assert "live_session_identity_changed" in restarted["gates"]


def test_live_session_dirty_state_invalidates_without_caring_about_frame_or_selection() -> None:
    bridge = _FakeSourceBridge("maya", _material_snapshot())
    receipt = qualify_dcc_source_parity("maya", 7011, bridge=bridge)
    bridge.frame = 99

    clean = validate_source_parity_receipt("maya", receipt, bridge=bridge)
    bridge.dirty = True
    dirty = validate_source_parity_receipt("maya", receipt, bridge=bridge)

    assert clean["valid"]
    assert "live_source_state_changed" in dirty["gates"]


def test_empty_lookdev_snapshot_cannot_prove_source_parity() -> None:
    snapshot = _material_snapshot()
    snapshot["objects"] = []

    receipt = qualify_dcc_source_parity("maya", 7011, bridge=_FakeSourceBridge("maya", snapshot))

    assert receipt["status"] == "unqualified"
    assert "role_source_evidence" in receipt["missing_gates"]


def test_source_snapshot_rejects_observer_state_mutation() -> None:
    class MutatingBridge(_FakeSourceBridge):
        def get_scene_snapshot(self, *, port: int, **kwargs):
            result = super().get_scene_snapshot(port=port, **kwargs)
            self.frame += 1
            self.dirty = True
            return result

    receipt = qualify_dcc_source_parity(
        "maya", 7011, bridge=MutatingBridge("maya", _material_snapshot()),
    )

    assert receipt["status"] == "unqualified"
    assert "non_mutating_readback" in receipt["missing_gates"]
    assert set(receipt["changed_observer_state"]) == {"dirty", "frame"}


def test_source_snapshot_rejects_wrong_session_payload() -> None:
    snapshot = _material_snapshot()
    snapshot["process_id"] = 9999

    receipt = qualify_dcc_source_parity("maya", 7011, bridge=_FakeSourceBridge("maya", snapshot))

    assert receipt["status"] == "unqualified"
    assert "exact_session_snapshot" in receipt["missing_gates"]


def test_motionbuilder_qualifies_without_lookdev_evidence() -> None:
    snapshot = {
        "schema": "tech_connector.motionbuilder.scene_snapshot.v1",
        "provider_id": "motionbuilder",
        "process_id": 4200,
        "scene": "C:/show/walk.fbx",
        "objects": [{"native_id": "Hips", "name": "Hips", "type": "FBModelSkeleton"}],
        "cameras": [],
    }

    receipt = qualify_dcc_source_parity(
        "motionbuilder", 7011, bridge=_FakeSourceBridge("motionbuilder", snapshot),
    )

    assert receipt["status"] == "qualified"
    assert receipt["capture_profile"]["capture_status"] == "not_role_required"
    assert receipt["role_evidence"]["material_count"] == 0


@pytest.mark.parametrize("host", ["photoshop", "gimp"])
def test_image_hosts_require_document_and_layer_evidence(host: str) -> None:
    snapshot = {
        "schema": f"tech_connector.{host}.document_snapshot.v1",
        "provider_id": host,
        "process_id": 4200,
        "scene": "C:/show/skin.psd",
        "objects": [{"native_id": "layer:0", "name": "Base", "type": "image_layer"}],
        "image_document_state": {"width": 2048, "height": 2048, "layers": ["Base"]},
    }

    qualified = qualify_dcc_source_parity(host, 7011, bridge=_FakeSourceBridge(host, snapshot))
    snapshot["image_document_state"] = {"width": 0, "height": 0, "layers": []}
    empty = qualify_dcc_source_parity(host, 7011, bridge=_FakeSourceBridge(host, snapshot))

    assert qualified["status"] == "qualified"
    assert empty["status"] == "unqualified"
    assert "role_source_evidence" in empty["missing_gates"]


def test_painter_requires_texture_set_metadata() -> None:
    snapshot = _material_snapshot("substance_painter")
    snapshot["objects"][0]["type"] = "texture_set"

    receipt = qualify_dcc_source_parity(
        "substance_painter", 7011, bridge=_FakeSourceBridge("substance_painter", snapshot),
    )

    assert receipt["status"] == "qualified"
    assert receipt["role_evidence"]["texture_set_count"] == 1


def test_source_parity_receipt_round_trips_atomically(tmp_path) -> None:
    path = tmp_path / "source_parity.json"
    receipt = qualify_dcc_source_parity(
        "maya", 7011, bridge=_FakeSourceBridge("maya", _material_snapshot()),
    )

    ledger = store_source_parity_receipt(receipt, path)
    reloaded = source_parity_ledger(path)

    assert ledger["summary"]["qualified_hosts"] == 1
    assert reloaded["receipts"]["maya"]["receipt_id"] == receipt["receipt_id"]


def test_batch_qualification_never_guesses_among_multiple_sessions(monkeypatch) -> None:
    class MultiBridge(_FakeSourceBridge):
        def find_ports(self):
            return [7011, 7014]

    monkeypatch.setattr(
        "tech_connector.game_engine.integration.dcc_source_parity_qualification_service.preferred_session_port",
        lambda _host: None,
    )
    factory = lambda host: MultiBridge(host, _material_snapshot(host), port=7011)

    ambiguous = qualify_available_dcc_sources(hosts=["maya"], bridge_factory=factory)
    selected = qualify_available_dcc_sources(
        hosts=["maya"], session_ports={"maya": 7014}, bridge_factory=factory,
    )

    assert ambiguous["hosts"][0]["status"] == "selection_required"
    assert "receipt" not in ambiguous["hosts"][0]
    assert selected["hosts"][0]["status"] == "qualified"
    assert selected["hosts"][0]["selected_port"] == 7014
