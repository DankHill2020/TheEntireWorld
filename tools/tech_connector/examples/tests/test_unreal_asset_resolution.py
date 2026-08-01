from __future__ import annotations

from unreal_tools.assets import load_asset, load_blueprint_class, object_path


class _EditorAssetLibrary:
    @staticmethod
    def load_asset(_path):
        return None

    @staticmethod
    def load_blueprint_class(_path):
        return None


class _Asset:
    pass


class _GeneratedClass:
    pass


class _Unreal:
    EditorAssetLibrary = _EditorAssetLibrary

    def __init__(self):
        self.asset = _Asset()
        self.generated_class = _GeneratedClass()
        self.loaded_objects = []
        self.loaded_classes = []

    def load_object(self, _outer, path):
        self.loaded_objects.append(path)
        return self.asset

    def load_class(self, _outer, path):
        self.loaded_classes.append(path)
        return self.generated_class


def test_package_path_is_converted_to_object_path():
    assert object_path("/Game/Folder/Asset") == "/Game/Folder/Asset.Asset"
    assert object_path("/Game/Folder/Asset.Asset") == "/Game/Folder/Asset.Asset"


def test_asset_loader_falls_back_to_unreal_object_path():
    unreal = _Unreal()

    assert load_asset(unreal, "/Game/Folder/Asset") is unreal.asset
    assert unreal.loaded_objects == ["/Game/Folder/Asset.Asset"]


def test_blueprint_class_loader_falls_back_to_generated_class_path():
    unreal = _Unreal()

    assert load_blueprint_class(unreal, "/Game/Folder/BP_Player") is unreal.generated_class
    assert unreal.loaded_classes == ["/Game/Folder/BP_Player.BP_Player_C"]
