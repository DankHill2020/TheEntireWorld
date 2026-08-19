from __future__ import annotations

import json
import sys
from types import ModuleType, SimpleNamespace

from tech_connector.bridges.gimp.gimp_bridge import GimpBridge
from tech_connector.game_engine.integration.dcc_production_workflow_service import PRODUCTION_WORKFLOWS


class _Region:
    def __init__(self, data: bytes):
        self.data = bytes(data)

    def __getitem__(self, _key):
        return self.data

    def __setitem__(self, _key, value):
        self.data = bytes(value)


class _Drawable:
    def __init__(self, width: int, height: int, data: bytes, bpp: int):
        self.width, self.height, self.bpp = width, height, bpp
        self.region = _Region(data)

    def get_pixel_rgn(self, *_args):
        return self.region

    def flush(self):
        pass

    def merge_shadow(self, _undo):
        pass

    def update(self, *_args):
        pass


def test_gimp_pack_pbr_executes_real_rgb_channel_composition(monkeypatch, tmp_path) -> None:
    roughness = tmp_path / "roughness.png"
    metallic = tmp_path / "metallic.png"
    ao = tmp_path / "ao.png"
    output = tmp_path / "orm.png"
    for path in (roughness, metallic, ao):
        path.write_bytes(b"source")
    values = {
        str(roughness): bytes([10, 20]),
        str(metallic): bytes([30, 40]),
        str(ao): bytes([50, 60]),
    }

    class Pdb:
        def gimp_file_load(self, path, _raw):
            return SimpleNamespace(active_layer=_Drawable(2, 1, values[path], 1))

        def gimp_image_new(self, width, height, _kind):
            return SimpleNamespace(width=width, height=height, active_layer=None)

        def gimp_layer_new(self, _image, width, height, _kind, _name, _opacity, _mode):
            return _Drawable(width, height, bytes(width * height * 3), 3)

        def gimp_image_insert_layer(self, image, layer, _parent, _index):
            image.active_layer = layer

        def gimp_file_save(self, _image, drawable, path, _raw):
            __import__("pathlib").Path(path).write_bytes(drawable.region.data)

        def gimp_image_delete(self, _image):
            pass

    gimpfu = ModuleType("gimpfu")
    gimpfu.pdb = Pdb()
    gimpfu.RGB = 0
    gimpfu.RGB_IMAGE = 0
    gimpfu.NORMAL_MODE = 0
    monkeypatch.setitem(sys.modules, "gimpfu", gimpfu)

    def execute(_self, code, host="127.0.0.1", port=None):
        namespace = {}
        exec(code, namespace, namespace)
        return {"ok": True, "result": namespace["result"]}

    monkeypatch.setattr(GimpBridge, "execute_python_fu", execute)
    response = GimpBridge().pack_pbr_channels(
        str(roughness), str(metallic), str(ao), str(output), port=7082,
    )
    result = json.loads(response["result"])

    assert output.read_bytes() == bytes([10, 30, 50, 20, 40, 60])
    assert result["parity_checks"] == {
        "dimensions": True,
        "channel packing": True,
        "color space": True,
    }
    assert len(result["head_sha256"]) == 64


def test_gimp_workflow_uses_pixel_pack_as_readback_and_checksum_artifact() -> None:
    pack = next(
        step for step in PRODUCTION_WORKFLOWS["gimp.pbr_texture_pack"].steps
        if step.operation == "texture.pack_pbr"
    )

    assert pack.readback
    assert pack.artifact_parity_checks == {"output pixel checksum": "output_path"}
