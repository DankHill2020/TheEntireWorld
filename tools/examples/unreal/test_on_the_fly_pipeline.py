# coding=utf-8
"""
    Test Suite for On-the-Fly Pipeline Asset and Code Downloader.
"""

import os
import sys
import json

# Ensure parent directory is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from utilities.pipeline_asset_downloader import (
    download_pipeline_asset,
    inspect_pipeline_asset,
    generate_unreal_import_script,
    generate_maya_import_script,
    generate_unity_import_manifest,
)


def test_pipeline_asset_fetching():
    """
        Executes end-to-end pipeline test for downloading, inspecting, and generating DCC import manifests.
    :return: True if all tests pass
    """
    output_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "external_tools", "downloaded_assets"))
    
    # Test Asset 1: Duck GLB Model
    duck_url = "https://raw.githubusercontent.com/KhronosGroup/glTF-Sample-Assets/main/Models/Duck/glTF-Binary/Duck.glb"
    print("\n--- Running Pipeline Ingestion Test 1: Duck GLB 3D Model ---")
    duck_path = download_pipeline_asset(duck_url, output_dir)
    duck_meta = inspect_pipeline_asset(duck_path)
    
    unreal_duck_script = generate_unreal_import_script(duck_meta, "/Game/Assets/3DModels")
    maya_duck_script = generate_maya_import_script(duck_meta)
    unity_duck_manifest = generate_unity_import_manifest(duck_meta)
    
    print("\n[Generated Unreal Import Script snippet]:")
    print(unreal_duck_script[:250] + "...")
    print("\n[Generated Maya Import Script snippet]:")
    print(maya_duck_script[:250] + "...")
    print("\n[Generated Unity Import Manifest]:")
    print(json.dumps(unity_duck_manifest, indent=2))
    
    # Test Asset 2: Avocado GLB Model
    avocado_url = "https://raw.githubusercontent.com/KhronosGroup/glTF-Sample-Assets/main/Models/Avocado/glTF-Binary/Avocado.glb"
    print("\n--- Running Pipeline Ingestion Test 2: Avocado GLB 3D Model ---")
    avocado_path = download_pipeline_asset(avocado_url, output_dir)
    avocado_meta = inspect_pipeline_asset(avocado_path)
    
    assert os.path.exists(duck_path), "Duck asset file should exist"
    assert os.path.exists(avocado_path), "Avocado asset file should exist"
    assert duck_meta["asset_type"] == "3D_Model_glTF", "Asset type should be 3D_Model_glTF"
    assert avocado_meta["asset_type"] == "3D_Model_glTF", "Asset type should be 3D_Model_glTF"

    print("\n================================================================================")
    print("ALL PIPELINE ON-THE-FLY DOWNLOAD & INGESTION TESTS PASSED SUCCESSFULLY!")
    print("================================================================================\n")
    return True


if __name__ == "__main__":
    test_pipeline_asset_fetching()
