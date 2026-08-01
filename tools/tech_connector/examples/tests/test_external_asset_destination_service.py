from __future__ import annotations

import unittest

from tech_connector.services.external_asset_destination_service import (
    canonical_host,
    default_asset_destination,
    infer_destination_from_selected_assets,
    normalize_asset_destination,
    unreal_content_folder_from_asset_path,
)


class TestExternalAssetDestinationService(unittest.TestCase):
    def test_canonical_host_aliases(self) -> None:
        """Verify DCC host aliases normalize before acquisition planning."""
        self.assertEqual(canonical_host("UE5"), "unreal")
        self.assertEqual(canonical_host("Motion Builder"), "motionbuilder")
        self.assertEqual(canonical_host("Substance"), "substance_painter")

    def test_default_destinations_cover_multiple_dcc_hosts(self) -> None:
        """Verify acquisition destinations are not Unreal-only."""
        self.assertEqual(default_asset_destination("unreal"), "/Game/AIStudio/Imported")
        self.assertEqual(default_asset_destination("unity"), "Assets/AIStudio/Imported")
        self.assertEqual(default_asset_destination("maya"), "AIStudio_Imported")
        self.assertEqual(default_asset_destination("houdini"), "/obj/AIStudio_Imported")

    def test_normalize_unreal_destination_accepts_relative_folder(self) -> None:
        """Verify API callers can pass friendly Unreal folder strings."""
        self.assertEqual(
            normalize_asset_destination("unreal", "Characters/Hero"),
            "/Game/Characters/Hero",
        )
        self.assertEqual(
            normalize_asset_destination("unreal", "/Game/Characters/Hero/"),
            "/Game/Characters/Hero",
        )

    def test_infer_unreal_folder_from_selected_asset(self) -> None:
        """Verify Content Browser selection can seed import destinations."""
        self.assertEqual(
            unreal_content_folder_from_asset_path("/Game/Characters/Hero/BP_Hero.BP_Hero"),
            "/Game/Characters/Hero",
        )
        self.assertEqual(
            infer_destination_from_selected_assets(
                "unreal", ["/Game/VFX/Fire/NS_Flame.NS_Flame"]
            ),
            "/Game/VFX/Fire",
        )


if __name__ == "__main__":
    unittest.main()
