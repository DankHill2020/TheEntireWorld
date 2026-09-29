"""Dependency-aware export packages for external engines and DCC applications."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import shutil
from typing import Any, Iterable

from .asset_database_service import AssetDatabase


EXPORT_TARGETS = ("generic", "unreal", "unity", "blender", "maya", "houdini")
INTERCHANGE_EXTENSIONS = frozenset({".fbx", ".obj", ".gltf", ".glb", ".usd", ".usda", ".usdc", ".abc", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".exr", ".wav", ".ogg"})


@dataclass(frozen=True)
class AssetExportReceipt:
    target: str
    destination: Path
    asset_ids: tuple[str, ...]
    copied_files: tuple[str, ...]
    warnings: tuple[str, ...]
    manifest_path: Path

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self); payload["destination"] = str(self.destination); payload["manifest_path"] = str(self.manifest_path); return payload


class AssetExportService:
    """Build portable, dependency-closed packages without discarding TC source data."""

    def __init__(self, project_root: str | Path, database: AssetDatabase) -> None:
        self.project_root = Path(project_root).expanduser().resolve(); self.database = database

    def export_assets(self, asset_ids: Iterable[str], destination: str | Path, *, target: str = "generic", include_dependencies: bool = True) -> AssetExportReceipt:
        provider = str(target or "generic").casefold()
        if provider not in EXPORT_TARGETS: raise ValueError(f"Unsupported export target: {target}")
        requested = tuple(dict.fromkeys(str(value) for value in asset_ids if str(value)))
        if not requested: raise ValueError("Select at least one asset to export.")
        ordered = self._dependency_closure(requested) if include_dependencies else requested
        root = Path(destination).expanduser().resolve(); root.mkdir(parents=True, exist_ok=True)
        content = root / "Content"; content.mkdir(exist_ok=True)
        rows: list[dict[str, Any]] = []; copied: list[str] = []; warnings: list[str] = []
        for asset_id in ordered:
            record = self.database.asset(asset_id)
            if record is None: warnings.append(f"Missing asset: {asset_id}"); continue
            source = record.source_path
            try: relative = source.relative_to(self.project_root)
            except ValueError: relative = Path("External") / asset_id / source.name
            target_path = content / relative; target_path.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(source, target_path)
            copied.append(target_path.relative_to(root).as_posix())
            sidecar = Path(str(source) + ".tcmeta")
            if sidecar.is_file():
                sidecar_target = Path(str(target_path) + ".tcmeta"); shutil.copy2(sidecar, sidecar_target); copied.append(sidecar_target.relative_to(root).as_posix())
            rows.append({"asset_id": asset_id, "type_id": record.asset_type, "source": target_path.relative_to(root).as_posix(), "dependencies": list(self.database.dependencies(asset_id)), "revision": record.revision, "content_hash": record.content_hash, "interchange_ready": source.suffix.casefold() in INTERCHANGE_EXTENSIONS, "metadata": record.metadata})
        manifest = {"schema": "tech_connector.export_package.v1", "target": provider, "project": self.project_root.name, "requested_asset_ids": list(requested), "dependency_closed": bool(include_dependencies), "assets": rows}
        manifest_path = root / "tech_connector_export.json"; manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        adapter = self._write_adapter(root, provider); copied.extend([adapter.relative_to(root).as_posix()] if adapter else [])
        return AssetExportReceipt(provider, root, tuple(row["asset_id"] for row in rows), tuple(copied), tuple(warnings), manifest_path)

    def _dependency_closure(self, roots: tuple[str, ...]) -> tuple[str, ...]:
        result: list[str] = []; visited: set[str] = set()
        def visit(asset_id: str) -> None:
            if asset_id in visited: return
            visited.add(asset_id)
            for dependency in self.database.dependencies(asset_id): visit(str(dependency))
            result.append(asset_id)
        for root in roots: visit(root)
        return tuple(result)

    @staticmethod
    def _write_adapter(root: Path, target: str) -> Path | None:
        if target == "unreal":
            path = root / "ImportToUnreal.py"; path.write_text("""# Run in Unreal's Python console.\nimport json, pathlib, unreal\nroot = pathlib.Path(__file__).parent\ndata = json.loads((root / 'tech_connector_export.json').read_text())\nfiles = [str(root / row['source']) for row in data['assets'] if pathlib.Path(row['source']).suffix.lower() in {'.fbx','.obj','.gltf','.glb','.png','.jpg','.jpeg','.tif','.tiff','.exr','.wav'}]\ntask = unreal.AssetImportTask(); task.filenames = files; task.destination_path = '/Game/TechConnectorImports'; task.automated = False; task.save = True\nunreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])\n""", encoding="utf-8"); return path
        if target == "blender":
            path = root / "ImportToBlender.py"; path.write_text("""# Run from Blender's Scripting workspace.\nimport json, pathlib, bpy\nroot = pathlib.Path(__file__).parent\ndata = json.loads((root / 'tech_connector_export.json').read_text())\nfor row in data['assets']:\n p = root / row['source']; ext = p.suffix.lower()\n if ext == '.fbx': bpy.ops.import_scene.fbx(filepath=str(p))\n elif ext in {'.gltf','.glb'}: bpy.ops.import_scene.gltf(filepath=str(p))\n elif ext == '.obj': bpy.ops.wm.obj_import(filepath=str(p))\n""", encoding="utf-8"); return path
        if target in {"unity", "maya", "houdini"}:
            path = root / f"IMPORT_{target.upper()}.md"; path.write_text(f"# Tech Connector → {target.title()}\n\nImport interchange-ready files under `Content/`. `tech_connector_export.json` preserves UUIDs, types, dependencies, and metadata for an importer or pipeline script. Native Tech Connector authoring files are retained as source data rather than silently flattened.\n", encoding="utf-8"); return path
        return None
