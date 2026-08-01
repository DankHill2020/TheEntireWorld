from pathlib import Path

from tech_connector.services.asset_provenance_ledger_service import (
    load_asset_ledger,
    register_external_asset,
)


def test_external_asset_ledger_never_promotes_asset_to_knowledge(tmp_path):
    result = register_external_asset(
        tmp_path,
        {
            "provider": "Authenticated Provider",
            "local_path": str(tmp_path / "motion.fbx"),
            "sha256": "abc123",
            "entitlement": "user_owned",
        },
    )
    assert result["ok"]
    row = load_asset_ledger(tmp_path)["assets"][0]
    assert row["record_scope"] == "project_asset"
    assert not row["knowledge_eligible"]
    assert not row["community_share_eligible"]
    assert not row["model_training_eligible"]


def test_external_asset_ledger_deduplicates_by_hash(tmp_path):
    register_external_asset(tmp_path, {"sha256": "same", "provider": "First"})
    register_external_asset(tmp_path, {"sha256": "same", "provider": "Updated"})
    rows = load_asset_ledger(tmp_path)["assets"]
    assert len(rows) == 1
    assert rows[0]["provider"] == "Updated"
