"""Locate and read the canonical AI Studio Bridge implementation sources."""

from __future__ import annotations

from pathlib import Path


PLUGIN_NAME = "AIStudioBridge"
MODULE_NAME = "AIStudioBridge"


def canonical_plugin_root() -> Path:
    """
        Gets the canonical plugin root.
    :return: canonical plugin root
    """
    return Path(__file__).resolve().parents[3] / "plugins" / PLUGIN_NAME


def plugin_implementation_paths(plugin_root: str | Path | None = None) -> tuple[Path, ...]:
    """
        Gets all C++ implementation units for the bridge library.
    :param plugin_root: optional plugin root
    :return: ordered implementation paths
    """
    root = Path(plugin_root).resolve() if plugin_root else canonical_plugin_root()
    private_root = root / "Source" / MODULE_NAME / "Private"
    main_path = private_root / "AIStudioBridgeLibrary.cpp"
    paths = [main_path] if main_path.is_file() else []
    paths.extend(sorted(private_root.glob("AIStudioBridgeLibrary*.inl")))
    return tuple(dict.fromkeys(path.resolve() for path in paths if path.is_file()))


def read_plugin_implementation(plugin_root: str | Path | None = None) -> str:
    """
        Reads the combined bridge library implementation.
    :param plugin_root: optional plugin root
    :return: combined source text
    """
    sections = []
    for path in plugin_implementation_paths(plugin_root):
        sections.append(f"\n// TECH_CONNECTOR_SOURCE_UNIT: {path.name}\n")
        sections.append(path.read_text(encoding="utf-8", errors="replace"))
    return "".join(sections)
