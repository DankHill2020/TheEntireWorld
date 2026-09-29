from __future__ import annotations

"""Headless authoring, validation, and deterministic flattening for Ophanim projects."""

from copy import deepcopy
from dataclasses import asdict, dataclass
import base64
from io import BytesIO
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from PIL import Image, ImageChops

from .asset_database_service import AssetDatabase, DerivedArtifact
from .asset_operations_service import AssetOperationsService


IMAGE_PROJECT_SCHEMA = "tech_connector_image_project_v1"


@dataclass(frozen=True)
class ImageProjectIssue:
    severity: str
    code: str
    message: str
    subject: str = ""

    def to_dict(self) -> dict[str, str]: return asdict(self)


class ImageProjectAssetService:
    def __init__(self, project_root: str | Path, database: AssetDatabase) -> None:
        self.project_root = Path(project_root).expanduser().resolve(); self.database = database
        self.operations = AssetOperationsService(self.project_root, database)

    def create(self, name: str, *, width: int = 1024, height: int = 1024,
               layers: Sequence[Mapping[str, Any]] = (), folder: str | Path = "Assets/Images"):
        width, height = max(1, int(width)), max(1, int(height))
        authored = [self._normalize_layer(row, width, height, index) for index, row in enumerate(layers)]
        if not authored: authored = [self._normalize_layer({"name": "Background", "color": [24, 28, 36, 255]}, width, height, 0)]
        document = {"schema": IMAGE_PROJECT_SCHEMA, "width": width, "height": height, "image_path": "",
                    "active_index": len(authored) - 1, "grid_enabled": False, "grid_size": 32,
                    "perspective_mode": "Off", "perspective_ray_density": 12,
                    "atmos_haze_color": "#9bb7d4", "active_atmos_level": 1, "vp_positions": {}, "layers": authored}
        receipt = self.operations.create_asset("tc.image_project", name, folder=folder)
        record = self.database.asset(receipt.asset_id); assert record is not None
        self._write(record.source_path, document)
        self.database.register_asset(record.source_path, record.asset_type, asset_id=record.asset_id, metadata=record.metadata)
        return receipt

    def properties(self, asset_id: str) -> dict[str, Any]: return deepcopy(self._load(asset_id)[1])

    def update(self, asset_id: str, values: Mapping[str, Any]) -> dict[str, Any]:
        record, document = self._load(asset_id); document.update(deepcopy(dict(values)))
        width, height = max(1, int(document.get("width") or 1)), max(1, int(document.get("height") or 1))
        document["layers"] = [self._normalize_layer(row, width, height, index) for index, row in enumerate(document.get("layers") or ())]
        self._write(record.source_path, document)
        self.database.register_asset(record.source_path, record.asset_type, asset_id=record.asset_id, metadata=record.metadata)
        return self.properties(asset_id)

    def validate(self, asset_id: str) -> list[ImageProjectIssue]:
        _record, value = self._load(asset_id); issues: list[ImageProjectIssue] = []
        if value.get("schema") != IMAGE_PROJECT_SCHEMA: issues.append(ImageProjectIssue("error", "schema", "Unsupported Ophanim project schema."))
        width, height = int(value.get("width") or 0), int(value.get("height") or 0)
        if width <= 0 or height <= 0 or width > 32768 or height > 32768: issues.append(ImageProjectIssue("error", "dimensions", "Image dimensions must be between 1 and 32768 pixels."))
        layers = value.get("layers") or []
        if not layers: issues.append(ImageProjectIssue("error", "layers", "Image Project requires at least one layer."))
        for index, layer in enumerate(layers):
            try:
                image = self._decode_layer(dict(layer));
                if image.size != (width, height): issues.append(ImageProjectIssue("error", "layer_dimensions", "Layer dimensions do not match the project.", str(index)))
            except (ValueError, OSError) as exc: issues.append(ImageProjectIssue("error", "layer_data", str(exc), str(index)))
        return issues

    def flatten(self, asset_id: str) -> bytes:
        _record, value = self._load(asset_id); errors = [row.message for row in self.validate(asset_id) if row.severity == "error"]
        if errors: raise ValueError("Image Project is not flattenable: " + "; ".join(errors))
        size = (int(value["width"]), int(value["height"])); result = Image.new("RGBA", size, (0, 0, 0, 0))
        for row in value.get("layers") or ():
            layer = dict(row)
            if not bool(layer.get("visible", True)): continue
            image = self._decode_layer(layer)
            opacity = max(0.0, min(1.0, float(layer.get("opacity", 1.0))))
            if opacity < 1.0:
                alpha = image.getchannel("A").point(lambda value: round(value * opacity)); image.putalpha(alpha)
            mode = str(layer.get("blend_mode") or "Normal").casefold()
            if mode == "multiply": image = ImageChops.multiply(result, image)
            elif mode == "screen": image = ImageChops.screen(result, image)
            result = Image.alpha_composite(result, image)
        output = BytesIO(); result.save(output, format="PNG", optimize=False, compress_level=9); return output.getvalue()

    def cook(self, asset_id: str, *, platform: str = "desktop", quality: str = "high") -> DerivedArtifact:
        return self.database.store_derived(asset_id, f"image_project:{platform}:{quality}", self.flatten(asset_id),
            metadata={"platform": platform, "quality": quality, "format": "png"}, extension=".png")

    def _normalize_layer(self, value: Mapping[str, Any], width: int, height: int, index: int) -> dict[str, Any]:
        row = dict(value); encoded = str(row.get("png_base64") or "")
        if not encoded:
            color = tuple(int(max(0, min(255, channel))) for channel in (list(row.get("color") or [0, 0, 0, 0]) + [255] * 4)[:4])
            image = Image.new("RGBA", (width, height), color); stream = BytesIO(); image.save(stream, format="PNG", compress_level=9)
            encoded = base64.b64encode(stream.getvalue()).decode("ascii")
        return {"name": str(row.get("name") or f"Layer {index + 1}"), "visible": bool(row.get("visible", True)),
                "locked": bool(row.get("locked", False)), "opacity": max(0.0, min(1.0, float(row.get("opacity", 1.0)))),
                "blend_mode": str(row.get("blend_mode") or "Normal"), "png_base64": encoded}

    @staticmethod
    def _decode_layer(value: Mapping[str, Any]) -> Image.Image:
        try: raw = base64.b64decode(str(value.get("png_base64") or ""), validate=True)
        except Exception as exc: raise ValueError("Layer PNG is not valid base64.") from exc
        try:
            image = Image.open(BytesIO(raw)); image.load(); return image.convert("RGBA")
        except OSError as exc: raise ValueError("Layer payload is not a readable PNG.") from exc

    def _load(self, asset_id: str):
        record = self.database.asset(asset_id)
        if record is None: raise KeyError(f"Unknown Image Project: {asset_id}")
        if record.asset_type != "tc.image_project": raise ValueError(f"Asset is not an Image Project: {asset_id}")
        try: value = json.loads(record.source_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc: raise ValueError(f"Unreadable Image Project: {record.source_path}") from exc
        return record, value

    @staticmethod
    def _write(path: Path, value: Mapping[str, Any]) -> None:
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp"); temporary.write_text(json.dumps(dict(value), indent=2, sort_keys=True) + "\n", encoding="utf-8"); os.replace(temporary, path)


__all__ = ["IMAGE_PROJECT_SCHEMA", "ImageProjectAssetService", "ImageProjectIssue"]
