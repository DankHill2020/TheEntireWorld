from pathlib import Path
from tempfile import TemporaryDirectory

from tech_connector.services.asset_lineage_service import record_asset_lineage


def test_lineage_hashes_sources_and_output():
    with TemporaryDirectory() as root:
        source = Path(root) / "source.amc"
        output = Path(root) / "derived.fbx"
        source.write_bytes(b"motion")
        output.write_bytes(b"fbx")
        result = record_asset_lineage(
            output,
            sources=[{"local_path": str(source), "source_url": "https://example.test/source"}],
            transformations=[{"tool": "converter", "result": "passed"}],
            license_record={"status": "accepted"},
            semantic_contract={"role": "climb_source", "accepted": False},
        )
        assert result["ok"]
        assert result["sources"][0]["sha256"]
        assert Path(result["manifest_path"]).is_file()


def test_lineage_rejects_missing_source():
    with TemporaryDirectory() as root:
        output = Path(root) / "derived.fbx"
        output.write_bytes(b"fbx")
        result = record_asset_lineage(
            output,
            sources=[{"local_path": str(Path(root) / "missing.amc")}],
            transformations=[],
            license_record={},
            semantic_contract={},
        )
        assert not result["ok"]
