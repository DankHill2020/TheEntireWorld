# coding=utf-8
"""
    Pipeline Asset Downloader and DCC Ingestion Engine.
"""

import os
import sys
import json
import urllib.request
import urllib.parse
import hashlib
from pathlib import Path


def download_pipeline_asset(asset_url: str, destination_dir: str, timeout: int = 30) -> str:
    """
        Downloads a remote asset or code file on the fly for pipeline processing.
    :param asset_url: remote HTTP/HTTPS URL of the asset or code file
    :param destination_dir: local target directory to save the asset
    :param timeout: socket timeout in seconds
    :return: absolute path to the downloaded asset file
    """
    os.makedirs(destination_dir, exist_ok=True)
    parsed_url = urllib.parse.urlparse(asset_url)
    filename = os.path.basename(parsed_url.path) or "downloaded_asset.bin"
    target_path = os.path.join(destination_dir, filename)

    print(f"[Pipeline Downloader] Fetching asset from: {asset_url}")
    req = urllib.request.Request(
        asset_url,
        headers={"User-Agent": "TechConnector-Pipeline/1.0"}
    )

    with urllib.request.urlopen(req, timeout=timeout) as response, open(target_path, "wb") as out_file:
        chunk_size = 65536
        total_downloaded = 0
        while True:
            chunk = response.read(chunk_size)
            if not chunk:
                break
            out_file.write(chunk)
            total_downloaded += len(chunk)

    print(f"[Pipeline Downloader] Download complete ({total_downloaded} bytes): {target_path}")
    return os.path.abspath(target_path)


def inspect_pipeline_asset(file_path: str) -> dict:
    """
        Inspects a downloaded asset file and extracts metadata for pipeline import.
    :param file_path: absolute path to the downloaded asset file
    :return: dictionary containing asset metadata, file format, size, and checksum
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Asset file not found: {file_path}")

    file_size = os.path.getsize(file_path)
    extension = os.path.splitext(file_path)[1].lower()

    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(65536), b""):
            sha256_hash.update(byte_block)

    metadata = {
        "file_path": os.path.abspath(file_path),
        "file_name": os.path.basename(file_path),
        "extension": extension,
        "size_bytes": file_size,
        "sha256": sha256_hash.hexdigest(),
        "asset_type": "unknown"
    }

    if extension in [".glb", ".gltf"]:
        metadata["asset_type"] = "3D_Model_glTF"
    elif extension in [".fbx", ".obj"]:
        metadata["asset_type"] = f"3D_Model_{extension[1:].upper()}"
    elif extension in [".png", ".jpg", ".jpeg", ".tga", ".exr"]:
        metadata["asset_type"] = "Texture_Image"
    elif extension in [".py", ".json", ".c", ".cpp", ".cs"]:
        metadata["asset_type"] = "Source_Code_Or_Manifest"

    print(f"[Pipeline Inspector] Asset '{metadata['file_name']}' identified as {metadata['asset_type']}")
    return metadata


def generate_unreal_import_script(asset_metadata: dict, unreal_destination_path: str = "/Game/DownloadedAssets") -> str:
    """
        Generates Python import instructions for Unreal Engine.
    :param asset_metadata: metadata dictionary returned by inspect_pipeline_asset
    :param unreal_destination_path: target content path in Unreal project
    :return: string containing executable Python code for Unreal Engine editor
    """
    source_file = asset_metadata["file_path"].replace("\\", "/")
    script = f'''# Unreal Engine Asset Import Script
import unreal

def import_asset_to_unreal():
    """
        Imports downloaded asset into Unreal Engine.
    :return: imported asset object or list
    """
    source_path = "{source_file}"
    destination_path = "{unreal_destination_path}"
    
    task = unreal.AssetImportTask()
    task.filename = source_path
    task.destination_path = destination_path
    task.automated = True
    task.replace_existing = True
    task.save = True
    
    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    asset_tools.import_asset_tasks([task])
    print(f"[Unreal Pipeline] Asset imported to {{destination_path}}")
    return task.get_objects()

if __name__ == "__main__":
    import_asset_to_unreal()
'''
    return script


def generate_maya_import_script(asset_metadata: dict) -> str:
    """
        Generates Python import instructions for Autodesk Maya.
    :param asset_metadata: metadata dictionary returned by inspect_pipeline_asset
    :return: string containing executable Python code for Maya
    """
    source_file = asset_metadata["file_path"].replace("\\", "/")
    script = f'''# Autodesk Maya Asset Import Script
import maya.cmds as cmds

def import_asset_to_maya():
    """
        Imports downloaded asset into Maya scene.
    :return: list of imported nodes
    """
    source_path = "{source_file}"
    imported_nodes = cmds.file(source_path, i=True, returnNewNodes=True, ignoreVersion=True)
    print(f"[Maya Pipeline] Imported {{len(imported_nodes)}} nodes into scene.")
    return imported_nodes

if __name__ == "__main__":
    import_asset_to_maya()
'''
    return script


def generate_unity_import_manifest(asset_metadata: dict, unity_relative_path: str = "Assets/DownloadedAssets") -> dict:
    """
        Generates asset import manifest for Unity Engine pipeline.
    :param asset_metadata: metadata dictionary returned by inspect_pipeline_asset
    :param unity_relative_path: target relative path inside Unity Assets directory
    :return: dictionary representing the Unity asset import manifest
    """
    manifest = {
        "engine": "Unity",
        "source_file": asset_metadata["file_path"],
        "target_unity_path": os.path.join(unity_relative_path, asset_metadata["file_name"]).replace("\\", "/"),
        "asset_type": asset_metadata["asset_type"],
        "checksum": asset_metadata["sha256"],
        "import_settings": {
            "generate_materials": True,
            "import_animation": True,
            "mesh_compression": "Off"
        }
    }
    return manifest
