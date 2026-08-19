"""Verified Unreal Data Table creation and row-authoring operations."""

from __future__ import annotations

import json


def _asset_parts(asset_path):
    """
        Gets the package path and asset name.

    :param asset_path: Unreal content path
    :return: package path and asset name
    """
    value = str(asset_path or "").strip().rstrip("/")
    if not value.startswith("/Game/") or "/" not in value[1:]:
        raise ValueError("Data Table asset path must be below /Game: " + value)
    package_path, asset_name = value.rsplit("/", 1)
    if not asset_name:
        raise ValueError("Data Table asset name cannot be blank")
    return package_path, asset_name


def _load_row_struct(unreal, row_struct_path):
    """
        Loads a native or asset-backed row ScriptStruct.

    :param unreal: Unreal Python module
    :param row_struct_path: Unreal row-struct object path
    :return: loaded ScriptStruct
    """
    path = str(row_struct_path or "").strip()
    value = unreal.EditorAssetLibrary.load_asset(path)
    if value is None:
        try:
            value = unreal.load_object(None, path)
        except Exception:
            value = None
    if value is None or not isinstance(value, unreal.ScriptStruct):
        raise ValueError("Data Table row ScriptStruct was not found: " + path)
    return value


def inspect_data_table(asset_path, include_rows=False, max_rows=200):
    """
        Inspects a Data Table's row struct, columns, rows, and JSON export.

    :param asset_path: Unreal Data Table content path
    :param include_rows: whether to include exported row payloads
    :param max_rows: maximum exported rows returned in the receipt
    :return: JSON Data Table readback receipt
    """
    import unreal

    table = unreal.EditorAssetLibrary.load_asset(str(asset_path or ""))
    if table is None or not isinstance(table, unreal.DataTable):
        return json.dumps({
            "ok": False,
            "status": "data_table_not_found",
            "asset_path": asset_path,
        }, indent=2)
    library = unreal.DataTableFunctionLibrary
    row_struct = library.get_data_table_row_struct(table)
    row_names = [str(value) for value in list(library.get_data_table_row_names(table) or [])]
    column_names = [str(value) for value in list(library.get_data_table_column_names(table) or [])]
    rows = []
    rows_truncated = False
    if include_rows:
        exported = str(library.export_data_table_to_json_string(table) or "[]")
        try:
            all_rows = json.loads(exported)
        except (TypeError, ValueError):
            all_rows = []
        limit = max(0, int(max_rows))
        rows = list(all_rows[:limit])
        rows_truncated = len(all_rows) > len(rows)
    return json.dumps({
        "ok": row_struct is not None,
        "status": "inspected",
        "asset_path": asset_path,
        "row_struct_path": str(row_struct.get_path_name()) if row_struct else "",
        "row_count": len(row_names),
        "row_names": row_names,
        "column_count": len(column_names),
        "column_names": column_names,
        "rows": rows,
        "rows_included": bool(include_rows),
        "rows_truncated": rows_truncated,
    }, indent=2, default=str)


def create_from_rows(
    asset_path,
    row_struct_path,
    rows,
    overwrite=False,
    dry_run=False,
    cleanup_on_failure=True,
):
    """
        Creates, fills, saves, and verifies a Data Table from JSON-compatible rows.

    :param asset_path: destination Unreal Data Table content path
    :param row_struct_path: native or asset-backed row ScriptStruct path
    :param rows: row dictionaries containing unique Name values
    :param overwrite: whether to replace the exact existing asset
    :param dry_run: whether to validate inputs without mutation
    :param cleanup_on_failure: whether to delete a newly created failed asset
    :return: JSON creation, fill, save, and row readback receipt
    """
    import unreal

    package_path, asset_name = _asset_parts(asset_path)
    row_struct = _load_row_struct(unreal, row_struct_path)
    normalized_rows = []
    row_names = set()
    for index, raw_row in enumerate(list(rows or [])):
        if not isinstance(raw_row, dict):
            raise ValueError("Data Table rows must be objects")
        row = dict(raw_row)
        name = str(row.get("Name") or row.get("name") or "").strip()
        if not name:
            raise ValueError(f"Data Table row {index} requires Name")
        if name.casefold() in row_names:
            raise ValueError("Data Table row names must be unique: " + name)
        row_names.add(name.casefold())
        row.pop("name", None)
        row["Name"] = name
        normalized_rows.append(row)
    if not normalized_rows:
        raise ValueError("Data Table requires at least one row")
    exists_before = bool(unreal.EditorAssetLibrary.does_asset_exist(asset_path))
    if dry_run:
        return json.dumps({
            "ok": True,
            "status": "dry_run",
            "asset_path": asset_path,
            "row_struct_path": str(row_struct.get_path_name()),
            "row_count": len(normalized_rows),
            "exists_before": exists_before,
            "would_overwrite": bool(exists_before and overwrite),
        }, indent=2)
    if exists_before and not overwrite:
        raise ValueError("Data Table already exists; set overwrite=True to replace it: " + asset_path)
    if exists_before and overwrite and not unreal.EditorAssetLibrary.delete_asset(asset_path):
        raise RuntimeError("Could not delete exact existing Data Table: " + asset_path)

    factory = unreal.DataTableFactory()
    factory.set_editor_property("struct", row_struct)
    table = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
        asset_name,
        package_path,
        unreal.DataTable,
        factory,
    )
    if table is None:
        raise RuntimeError("Unreal failed to create Data Table: " + asset_path)
    try:
        filled = bool(unreal.DataTableFunctionLibrary.fill_data_table_from_json_string(
            table,
            json.dumps(normalized_rows),
        ))
        if not filled:
            raise RuntimeError("Unreal rejected the Data Table rows for the requested row struct")
        saved = bool(unreal.EditorAssetLibrary.save_loaded_asset(table, False))
        inspection = json.loads(inspect_data_table(asset_path, include_rows=False))
        expected_names = {str(row["Name"]).casefold() for row in normalized_rows}
        actual_names = {str(name).casefold() for name in inspection.get("row_names") or []}
        verified = saved and expected_names == actual_names
        if not verified:
            raise RuntimeError("Data Table save/row readback failed")
        return json.dumps({
            "ok": True,
            "status": "data_table_created_filled_saved",
            "asset_path": asset_path,
            "row_struct_path": str(row_struct.get_path_name()),
            "saved": saved,
            "inspection": inspection,
            "postconditions": {
                "row_names_match": True,
                "saved": True,
            },
        }, indent=2, default=str)
    except Exception:
        if cleanup_on_failure and unreal.EditorAssetLibrary.does_asset_exist(asset_path):
            unreal.EditorAssetLibrary.delete_asset(asset_path)
        raise
