import json
import tempfile
import unittest
from pathlib import Path

from tech_connector.services.license_entitlement_service import LicenseEntitlement
from tech_connector.services.usage_provenance_service import (
    apply_python_provenance,
    build_usage_tag,
    scan_for_usage_markers,
    write_asset_sidecar,
    write_project_provenance_marker,
)


class UsageProvenanceServiceTests(unittest.TestCase):
    def _entitlement(self) -> LicenseEntitlement:
        return LicenseEntitlement(
            unlocked=True,
            tier="personal",
            account_email="creator@example.com",
            account_id="acct_123",
            license_id="lic_abc",
            capabilities=("local_use",),
        )

    def test_usage_tag_hashes_identity_and_never_allows_resale(self):
        tag = build_usage_tag(self._entitlement(), project_root="C:/project/game", operation="export_fbx")

        self.assertEqual("personal", tag["license_tier"])
        self.assertTrue(tag["account_hash"])
        self.assertNotIn("creator@example.com", json.dumps(tag))
        self.assertFalse(tag["resale_allowed"])
        self.assertFalse(tag["ai_training_allowed"])
        self.assertFalse(tag["direct_code_reuse_allowed"])
        self.assertTrue(tag["official_api_required"])

    def test_python_provenance_header_is_inserted_and_replaced(self):
        tag = build_usage_tag(self._entitlement(), operation="generate_pipeline_code")
        source = "#!/usr/bin/env python\nprint('hello')\n"

        stamped = apply_python_provenance(source, tag)
        restamped = apply_python_provenance(stamped, tag)

        self.assertIn("#!/usr/bin/env python", stamped.splitlines()[0])
        self.assertIn("# Tech Connector:", stamped.splitlines()[1])
        self.assertEqual(1, restamped.count("# Tech Connector:"))

    def test_project_marker_sidecar_and_scan_round_trip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            tag = build_usage_tag(self._entitlement(), project_root=root, operation="maya_export")
            marker_path = write_project_provenance_marker(root, tag)
            asset_path = root / "clip.fbx"
            asset_path.write_text("fake fbx", encoding="utf-8")
            sidecar = write_asset_sidecar(asset_path, tag)
            code_path = root / "generated.py"
            code_path.write_text(apply_python_provenance("print('x')\n", tag), encoding="utf-8")

            markers = scan_for_usage_markers(root)

        paths = {Path(item["path"]).name for item in markers}
        self.assertIn(marker_path.name, paths)
        self.assertIn(sidecar.name, paths)
        self.assertIn(code_path.name, paths)
        self.assertGreaterEqual(len(markers), 3)


if __name__ == "__main__":
    unittest.main()
