"""Isolated OpenUSD composition worker executed by Blender's Python runtime."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


def _value_type(Sdf, name):
    key = str(name or "").strip().lower()
    return {
        "bool": Sdf.ValueTypeNames.Bool,
        "int": Sdf.ValueTypeNames.Int,
        "float": Sdf.ValueTypeNames.Float,
        "double": Sdf.ValueTypeNames.Double,
        "string": Sdf.ValueTypeNames.String,
        "token": Sdf.ValueTypeNames.Token,
        "float2": Sdf.ValueTypeNames.Float2,
        "float3": Sdf.ValueTypeNames.Float3,
        "float4": Sdf.ValueTypeNames.Float4,
        "color3f": Sdf.ValueTypeNames.Color3f,
        "color4f": Sdf.ValueTypeNames.Color4f,
        "matrix4d": Sdf.ValueTypeNames.Matrix4d,
    }.get(key, Sdf.ValueTypeNames.String)


def _coerce_value(Gf, value, type_name):
    key = str(type_name or "").strip().lower()
    values = list(value) if isinstance(value, (list, tuple)) else []
    if key == "float2" and len(values) >= 2:
        return Gf.Vec2f(*map(float, values[:2]))
    if key in {"float3", "color3f"} and len(values) >= 3:
        return Gf.Vec3f(*map(float, values[:3]))
    if key in {"float4", "color4f"} and len(values) >= 4:
        return Gf.Vec4f(*map(float, values[:4]))
    if key == "matrix4d" and len(values) >= 16:
        return Gf.Matrix4d(*map(float, values[:16]))
    if key == "bool":
        return bool(value)
    if key == "int":
        return int(value)
    if key in {"float", "double"}:
        return float(value)
    return str(value) if key in {"string", "token"} else value


def compose(request_path: str, result_path: str) -> None:
    from pxr import Gf, Sdf, Tf, Usd, UsdUtils

    request = json.loads(Path(request_path).read_text(encoding="utf-8"))
    output_path = Path(request["output_path"]).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    root = Sdf.Layer.CreateAnonymous("tech_connector_composition.usda")
    layer_specs = [item for item in request.get("layers") or [] if not item.get("muted")]
    for item in layer_specs:
        path = str(Path(item["path"]).resolve())
        mark = Tf.Error.Mark()
        mark.SetMark()
        layer = None
        caught_error = ""
        try:
            layer = Sdf.Layer.FindOrOpen(path)
        except Exception as exc:
            caught_error = str(exc)
        errors = [str(error) for error in mark.GetErrors()]
        if caught_error:
            errors.append(caught_error)
        mark.Clear()
        if layer is None or errors:
            detail = "; ".join(errors) or "OpenUSD returned no layer."
            raise RuntimeError(f"Invalid OpenUSD source layer {path}: {detail}")
    root.subLayerPaths = [str(Path(item["path"]).resolve()).replace("\\", "/") for item in layer_specs]
    offsets = []
    for item in layer_specs:
        offsets.append(Sdf.LayerOffset(float(item.get("offset", 0.0)), float(item.get("scale", 1.0))))
    try:
        root.subLayerOffsets = offsets
    except Exception:
        pass
    load_policy = str(request.get("load_policy") or "all").lower()
    stage = Usd.Stage.Open(root, load=Usd.Stage.LoadNone if load_policy == "none" else Usd.Stage.LoadAll)
    if stage is None:
        raise RuntimeError("OpenUSD could not open the composed stage.")
    stage.SetEditTarget(root)

    diagnostics = []
    for item in request.get("variants") or []:
        prim = stage.GetPrimAtPath(str(item.get("prim_path") or ""))
        if not prim:
            diagnostics.append({"severity": "warning", "message": "Variant prim was not found.", **item})
            continue
        set_name = str(item.get("variant_set") or "")
        if set_name not in prim.GetVariantSets().GetNames():
            diagnostics.append({"severity": "warning", "message": "Variant set was not found.", **item})
            continue
        variant_set = prim.GetVariantSets().GetVariantSet(set_name)
        selection = str(item.get("selection") or "")
        if selection not in variant_set.GetVariantNames():
            diagnostics.append({"severity": "warning", "message": "Variant selection is unavailable.", **item})
            continue
        variant_set.SetVariantSelection(selection)

    for item in request.get("payload_rules") or []:
        prim_path = str(item.get("prim_path") or "")
        if bool(item.get("loaded", True)):
            stage.Load(prim_path)
        else:
            stage.Unload(prim_path)

    for item in request.get("overrides") or []:
        prim_path = str(item.get("prim_path") or "")
        property_name = str(item.get("property_name") or "")
        prim = stage.OverridePrim(prim_path)
        attribute = prim.GetAttribute(property_name)
        type_name = str(item.get("value_type") or "string")
        if not attribute:
            attribute = prim.CreateAttribute(property_name, _value_type(Sdf, type_name), custom=True)
        value = _coerce_value(Gf, item.get("value"), type_name)
        time_code = item.get("time_code")
        attribute.Set(value, Usd.TimeCode(float(time_code))) if time_code is not None else attribute.Set(value)

    flatten = bool(request.get("flatten", False))
    if flatten:
        stage.Flatten().Export(str(output_path))
    else:
        root.Export(str(output_path))

    prims = []
    type_counts = {}
    limit = max(1, min(100000, int(request.get("prim_limit", 10000))))
    for prim in stage.TraverseAll():
        type_name = str(prim.GetTypeName() or "untyped")
        type_counts[type_name] = type_counts.get(type_name, 0) + 1
        if len(prims) < limit:
            variants = {}
            for name in prim.GetVariantSets().GetNames():
                variant_set = prim.GetVariantSets().GetVariantSet(name)
                variants[name] = {
                    "selection": variant_set.GetVariantSelection(),
                    "options": list(variant_set.GetVariantNames()),
                }
            prims.append({
                "path": str(prim.GetPath()),
                "name": str(prim.GetName()),
                "type": type_name,
                "active": bool(prim.IsActive()),
                "loaded": bool(prim.IsLoaded()),
                "instance": bool(prim.IsInstance()),
                "has_payload": bool(prim.HasPayload()),
                "variants": variants,
            })
    dependencies = []
    try:
        _layers, assets, unresolved = UsdUtils.ComputeAllDependencies(str(output_path))
        dependencies = sorted({str(path) for path in list(assets) + list(unresolved) if str(path)})
    except Exception as exc:
        diagnostics.append({"severity": "info", "message": f"Dependency scan unavailable: {exc}"})
    result = {
        "schema": "tech_connector.usd_composition_result.v1",
        "ok": True,
        "usd_version": list(Usd.GetVersion()),
        "output_path": str(output_path),
        "flattened": flatten,
        "layer_count": len(layer_specs),
        "prim_count": sum(type_counts.values()),
        "type_counts": type_counts,
        "prims": prims,
        "prim_inventory_truncated": sum(type_counts.values()) > len(prims),
        "dependencies": dependencies,
        "diagnostics": diagnostics,
    }
    Path(result_path).write_text(json.dumps(result, separators=(",", ":")), encoding="utf-8")


def main() -> None:
    arguments = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    parser.add_argument("--result", required=True)
    options = parser.parse_args(arguments)
    compose(options.request, options.result)


if __name__ == "__main__":
    main()
