"""Dependency-aware export packages for external engines and DCC applications."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import shutil
from typing import Any, Iterable

from .asset_database_service import AssetDatabase
from .asset_conversion_service import (
    CONVERSION_TARGETS,
    conversion_coverage_report,
    plan_asset_conversion,
)
from .asset_type_registry import AssetTypeRegistry, builtin_asset_type_registry


EXPORT_TARGETS = CONVERSION_TARGETS
@dataclass(frozen=True)
class AssetExportReceipt:
    target: str
    destination: Path
    asset_ids: tuple[str, ...]
    copied_files: tuple[str, ...]
    warnings: tuple[str, ...]
    manifest_path: Path
    ready: bool
    blockers: tuple[str, ...]
    conversion_report_path: Path

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["destination"] = str(self.destination)
        payload["manifest_path"] = str(self.manifest_path)
        payload["conversion_report_path"] = str(self.conversion_report_path)
        return payload


class AssetExportService:
    """Build portable, dependency-closed packages without discarding TC source data."""

    def __init__(self, project_root: str | Path, database: AssetDatabase, registry: AssetTypeRegistry | None = None) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.database = database
        self.registry = registry or builtin_asset_type_registry()

    def export_assets(
        self,
        asset_ids: Iterable[str],
        destination: str | Path,
        *,
        target: str = "generic",
        include_dependencies: bool = True,
        require_ready: bool = False,
    ) -> AssetExportReceipt:
        provider = str(target or "generic").casefold()
        if provider not in EXPORT_TARGETS: raise ValueError(f"Unsupported export target: {target}")
        requested = tuple(dict.fromkeys(str(value) for value in asset_ids if str(value)))
        if not requested: raise ValueError("Select at least one asset to export.")
        ordered = self._dependency_closure(requested) if include_dependencies else requested
        preflight: list[tuple[Any, Any]] = []
        missing: list[str] = []
        blockers: list[str] = []
        for asset_id in ordered:
            record = self.database.asset(asset_id)
            if record is None:
                missing.append(f"Missing asset: {asset_id}")
                continue
            plan = plan_asset_conversion(record.asset_type, record.source_path, provider, registry=self.registry)
            preflight.append((record, plan))
            if not plan.ready:
                blockers.append(f"{asset_id} ({record.asset_type}): {plan.reason}")
        if require_ready and (missing or blockers):
            details = "\n".join(f"- {value}" for value in [*missing, *blockers])
            raise ValueError(f"Export is not conversion-ready for {provider}:\n{details}")
        root = Path(destination).expanduser().resolve(); root.mkdir(parents=True, exist_ok=True)
        content = root / "Content"; content.mkdir(exist_ok=True)
        rows: list[dict[str, Any]] = []; copied: list[str] = []; warnings: list[str] = list(missing)
        warnings.extend(blockers)
        for record, plan in preflight:
            asset_id = record.asset_id
            source = record.source_path
            try: relative = source.relative_to(self.project_root)
            except ValueError: relative = Path("External") / asset_id / source.name
            target_path = content / relative; target_path.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(source, target_path)
            copied.append(target_path.relative_to(root).as_posix())
            sidecar = Path(str(source) + ".tcmeta")
            if sidecar.is_file():
                sidecar_target = Path(str(target_path) + ".tcmeta"); shutil.copy2(sidecar, sidecar_target); copied.append(sidecar_target.relative_to(root).as_posix())
            rows.append({"asset_id": asset_id, "type_id": record.asset_type, "source": target_path.relative_to(root).as_posix(), "dependencies": list(self.database.dependencies(asset_id)), "revision": record.revision, "content_hash": record.content_hash, "interchange_ready": plan.ready and plan.mode == "direct_import", "conversion": plan.to_dict(), "metadata": record.metadata})
        summary = {
            "ready": len([row for row in rows if row["conversion"]["ready"]]),
            "blocked": len([row for row in rows if not row["conversion"]["ready"]]),
            "modes": {},
        }
        for row in rows:
            mode = row["conversion"]["mode"]
            summary["modes"][mode] = summary["modes"].get(mode, 0) + 1
        manifest = {"schema": "tech_connector.export_package.v2", "target": provider, "project": self.project_root.name, "requested_asset_ids": list(requested), "dependency_closed": bool(include_dependencies), "conversion_ready": not blockers and not missing, "conversion_summary": summary, "assets": rows}
        manifest_path = root / "tech_connector_export.json"; manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        conversion_report_path = root / "conversion_report.json"
        conversion_report_path.write_text(json.dumps({
            "schema": "tech_connector.asset_export_conversion_report.v1",
            "target": provider,
            "ready": not blockers and not missing,
            "summary": summary,
            "blockers": [*missing, *blockers],
            "assets": [{"asset_id": row["asset_id"], **row["conversion"]} for row in rows],
        }, indent=2, sort_keys=True), encoding="utf-8")
        adapter = self._write_adapter(root, provider, rows); copied.extend([adapter.relative_to(root).as_posix()] if adapter else [])
        return AssetExportReceipt(provider, root, tuple(row["asset_id"] for row in rows), tuple(copied), tuple(warnings), manifest_path, not blockers and not missing, tuple([*missing, *blockers]), conversion_report_path)

    def conversion_coverage(self) -> dict[str, Any]:
        return conversion_coverage_report(registry=self.registry)

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
    def _write_adapter(root: Path, target: str, rows: list[dict[str, Any]]) -> Path | None:
        if target == "unreal":
            path = root / "ImportToUnreal.py"; path.write_text("""# Run in Unreal's Python console. One task is required per source file.
import json, pathlib, unreal
root = pathlib.Path(__file__).parent
data = json.loads((root / 'tech_connector_export.json').read_text(encoding='utf-8'))
tasks = []
for row in data['assets']:
    if not row.get('conversion', {}).get('ready') or row.get('conversion', {}).get('mode') != 'direct_import':
        continue
    task = unreal.AssetImportTask()
    task.filename = str(root / row['source'])
    task.destination_path = '/Game/TechConnectorImports'
    task.automated = True
    task.replace_existing = False
    task.save = True
    tasks.append(task)
if tasks:
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks(tasks)
blocked = [row for row in data['assets'] if not row.get('conversion', {}).get('ready')]
if blocked:
    unreal.log_warning(f'Tech Connector preserved {len(blocked)} source asset(s) that require baking or a native adapter; see conversion_report.json.')
""", encoding="utf-8"); return path
        if target == "unity":
            ready_files = [row["source"] for row in rows if row["conversion"]["ready"] and row["conversion"]["mode"] == "direct_import"]
            literals = ",\n        ".join(json.dumps(value) for value in ready_files)
            path = root / "ImportToUnity.cs"
            path.write_text(f"""// Put this file under Assets/Editor, then run Tools > Tech Connector > Import Package.
#if UNITY_EDITOR
using System.IO;
using UnityEditor;
using UnityEngine;

public static class TechConnectorPackageImporter
{{
    [MenuItem("Tools/Tech Connector/Import Package")]
    public static void ImportPackage()
    {{
        var root = EditorUtility.OpenFolderPanel("Select Tech Connector export package", "", "");
        if (string.IsNullOrEmpty(root)) return;
        var files = new string[] {{
        {literals}
        }};
        foreach (var relative in files)
        {{
            var source = Path.Combine(root, relative.Replace('/', Path.DirectorySeparatorChar));
            var contentRelative = relative.StartsWith("Content/") ? relative.Substring(8) : relative;
            var destination = Path.Combine(Application.dataPath, "TechConnectorImports", contentRelative.Replace('/', Path.DirectorySeparatorChar));
            Directory.CreateDirectory(Path.GetDirectoryName(destination));
            File.Copy(source, destination, true);
        }}
        AssetDatabase.Refresh(ImportAssetOptions.ForceUpdate);
        Debug.Log($"Tech Connector imported {{files.Length}} directly supported asset(s). Check conversion_report.json for assets requiring a bake or adapter.");
    }}
}}
#endif
""", encoding="utf-8")
            return path
        if target == "blender":
            path = root / "ImportToBlender.py"; path.write_text("""# Run from Blender's Scripting workspace.\nimport json, pathlib, bpy\nroot = pathlib.Path(__file__).parent\ndata = json.loads((root / 'tech_connector_export.json').read_text())\nfor row in data['assets']:\n p = root / row['source']; ext = p.suffix.lower()\n if ext == '.fbx': bpy.ops.import_scene.fbx(filepath=str(p))\n elif ext in {'.gltf','.glb'}: bpy.ops.import_scene.gltf(filepath=str(p))\n elif ext == '.obj': bpy.ops.wm.obj_import(filepath=str(p))\n""", encoding="utf-8"); return path
        if target in {"maya", "houdini"}:
            path = root / f"IMPORT_{target.upper()}.md"; path.write_text(f"# Tech Connector → {target.title()}\n\nImport interchange-ready files under `Content/`. `tech_connector_export.json` preserves UUIDs, types, dependencies, and metadata for an importer or pipeline script. Native Tech Connector authoring files are retained as source data rather than silently flattened.\n", encoding="utf-8"); return path
        return None
