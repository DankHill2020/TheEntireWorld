"""Host-aware destination helpers for external asset acquisition."""

from __future__ import annotations

from pathlib import PurePosixPath


DEFAULT_DCC_ASSET_DESTINATIONS: dict[str, str] = {
    "auto": "",
    "unreal": "/Game/AIStudio/Imported",
    "unity": "Assets/AIStudio/Imported",
    "maya": "AIStudio_Imported",
    "blender": "AIStudio_Imported",
    "houdini": "/obj/AIStudio_Imported",
    "motionbuilder": "AIStudio_Imported",
    "substance_painter": "AIStudio_Imported",
}


def canonical_host(host: str | None) -> str:
    """
        Canonicalize a DCC host key.
    :param host: host name from UI, prompt routing, or adapter metadata
    :return: normalized host key
    """
    text = str(host or "auto").strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "ue": "unreal",
        "ue5": "unreal",
        "unreal_engine": "unreal",
        "substance": "substance_painter",
        "painter": "substance_painter",
        "mobu": "motionbuilder",
        "motion_builder": "motionbuilder",
    }
    return aliases.get(text, text or "auto")


def default_asset_destination(host: str | None) -> str:
    """
        Get default destination for a DCC host.
    :param host: host name from UI, prompt routing, or adapter metadata
    :return: default import destination
    """
    return DEFAULT_DCC_ASSET_DESTINATIONS.get(
        canonical_host(host), DEFAULT_DCC_ASSET_DESTINATIONS["auto"]
    )


def normalize_asset_destination(host: str | None, destination: str | None) -> str:
    """
        Normalize a DCC asset destination.
    :param host: target DCC host
    :param destination: destination path, folder, namespace, or collection
    :return: normalized destination string
    """
    key = canonical_host(host)
    text = str(destination or "").strip().replace("\\", "/")
    if not text:
        return default_asset_destination(key)
    if key == "unreal":
        if not text.startswith("/Game"):
            text = "/Game/" + text.strip("/")
        return "/" + str(PurePosixPath(text.strip("/"))).strip("/")
    if key == "unity":
        return str(PurePosixPath(text.strip("/")))
    return text.strip("/")


def unreal_content_folder_from_asset_path(asset_path: str | None) -> str:
    """
        Get Unreal Content Browser folder from an asset path.
    :param asset_path: Unreal package path such as /Game/Foo/Bar.Bar
    :return: Content Browser folder path
    """
    text = str(asset_path or "").strip().replace("\\", "/")
    if not text.startswith("/Game"):
        return ""
    package = text.split(".", 1)[0]
    if "/" not in package.strip("/"):
        return "/Game"
    folder = package.rsplit("/", 1)[0]
    return folder or "/Game"


def infer_destination_from_selected_assets(
    host: str | None, selected_assets: list[str] | tuple[str, ...] | None
) -> str:
    """
        Infer an import destination from selected DCC assets.
    :param host: target DCC host
    :param selected_assets: selected asset paths from the active host
    :return: inferred destination path or an empty string
    """
    key = canonical_host(host)
    assets = [str(item) for item in (selected_assets or []) if str(item).strip()]
    if key == "unreal":
        for asset in assets:
            folder = unreal_content_folder_from_asset_path(asset)
            if folder:
                return folder
    return ""
