"""Check that the packaged SKM_Test control card keeps every text row visible."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path


ROWS = {
    "title": (36, 32, 420, 68),
    "movement": (36, 75, 420, 105),
    "stance": (36, 108, 420, 139),
}
MIN_WHITE_PIXELS = {"title": 750, "movement": 1000, "stance": 850}


def blue_character_bounds(path: Path, box: tuple[int, int, int, int]) -> dict[str, object]:
    """Locate the demo's blue skinned actor inside its central gameplay region."""
    data = path.read_bytes()
    if len(data) < 54 or data[:2] != b"BM":
        raise ValueError(f"Expected a 24-bit BMP: {path}")
    offset = struct.unpack_from("<I", data, 10)[0]
    width, height = struct.unpack_from("<ii", data, 18)
    depth = struct.unpack_from("<H", data, 28)[0]
    x0, y0, x1, y1 = box
    if depth != 24 or not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
        raise ValueError(f"Unsupported character screenshot size or format: {path}")
    stride = (width * 3 + 3) & ~3
    if offset + stride * height > len(data):
        raise ValueError(f"Truncated character screenshot: {path}")
    count = 0
    bounds = [x1, y1, x0, y0]
    for y in range(y0, y1):
        row = offset + (height - 1 - y) * stride
        for x in range(x0, x1):
            blue, green, red = data[row + x * 3:row + x * 3 + 3]
            if red < 100 and green < 160 and blue > 140 and \
                    blue > red + 60 and green > red + 30:
                count += 1
                bounds = [min(bounds[0], x), min(bounds[1], y),
                          max(bounds[2], x), max(bounds[3], y)]
    return {"pixels": count, "bounds": bounds if count else None}


def _text_mask(path: Path, box: tuple[int, int, int, int]) -> tuple[int, str]:
    data = path.read_bytes()
    if len(data) < 54 or data[:2] != b"BM":
        raise ValueError(f"Expected a 24-bit BMP: {path}")
    offset = struct.unpack_from("<I", data, 10)[0]
    width, height = struct.unpack_from("<ii", data, 18)
    depth = struct.unpack_from("<H", data, 28)[0]
    if depth != 24 or width < box[2] or height < box[3] or offset < 54:
        raise ValueError(f"Unsupported UI screenshot size or format: {path}")
    stride = (width * 3 + 3) & ~3
    if offset + stride * height > len(data):
        raise ValueError(f"Truncated UI screenshot: {path}")
    mask = bytearray()
    for y in range(box[1], box[3]):
        row = offset + (height - 1 - y) * stride
        for x in range(box[0], box[2]):
            blue, green, red = data[row + x * 3:row + x * 3 + 3]
            mask.append(red >= 215 and green >= 215 and blue >= 215)
    return sum(mask), hashlib.sha256(mask).hexdigest()


def verify_control_card(
    screenshots: list[Path], *, offset: tuple[int, int] = (0, 0)
) -> dict[str, object]:
    if len(screenshots) < 2:
        raise ValueError("At least two independent UI captures are required.")
    rows: dict[str, list[dict[str, object]]] = {}
    for name, original_box in ROWS.items():
        box = (original_box[0] + offset[0], original_box[1] + offset[1],
               original_box[2] + offset[0], original_box[3] + offset[1])
        rows[name] = [
            {"screenshot": str(path), "white_pixels": count, "text_mask_sha256": digest}
            for path in screenshots
            for count, digest in [_text_mask(path, box)]
        ]
    checks = {
        "all_text_rows_visible": all(
            result["white_pixels"] >= MIN_WHITE_PIXELS[name]
            for name, captures in rows.items() for result in captures
        ),
        "text_stable_across_captures": all(
            len({result["text_mask_sha256"] for result in captures}) == 1
            for captures in rows.values()
        ),
    }
    return {"schema": "tech_connector.skm_ui_capture.v1",
            "status": "passed" if all(checks.values()) else "blocked",
            "checks": checks, "rows": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("screenshots", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = verify_control_card(args.screenshots)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "checks": result["checks"]}))
    if result["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
