from __future__ import annotations

import json
from types import SimpleNamespace

from tech_connector.game_engine.integration.dcc_production_workflow_service import PRODUCTION_WORKFLOWS
from unreal_tools import assets, blueprint, runtime


def test_unreal_workflow_compiles_saves_runs_pie_and_reads_the_uasset() -> None:
    operations = [step.operation for step in PRODUCTION_WORKFLOWS["unreal.gameplay_vertical_slice"].steps]

    assert operations == [
        "blueprint.create_from_template", "blueprint.compile_and_save", "runtime.pie_begin",
        "runtime.pie_validate", "runtime.pie_end", "assets.inspect",
    ]
    inspect = PRODUCTION_WORKFLOWS["unreal.gameplay_vertical_slice"].steps[-1]
    assert inspect.readback
    assert inspect.output_artifact_keys == ("absolute_path",)


def test_unreal_asset_inspection_returns_saved_file_and_parity(monkeypatch, tmp_path) -> None:
    content = tmp_path / "Content"
    artifact = content / "TC" / "BP_Workflow.uasset"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"uasset")

    class EditorAssetLibrary:
        @staticmethod
        def does_asset_exist(_path):
            return True

        @staticmethod
        def load_asset(_path):
            return SimpleNamespace(
                get_name=lambda: "BP_Workflow",
                get_class=lambda: SimpleNamespace(get_name=lambda: "Blueprint"),
            )

    data = SimpleNamespace(package_name="/Game/TC/BP_Workflow", tags_and_values={})
    registry = SimpleNamespace(
        get_asset_by_object_path=lambda _path: data,
        get_dependencies=lambda *_args: [],
        get_referencers=lambda *_args: [],
    )
    fake_unreal = SimpleNamespace(
        EditorAssetLibrary=EditorAssetLibrary,
        AssetRegistryHelpers=SimpleNamespace(get_asset_registry=lambda: registry),
        AssetRegistryDependencyOptions=lambda: object(),
        Paths=SimpleNamespace(
            project_content_dir=lambda: str(content),
            convert_relative_path_to_full=lambda value: value,
        ),
    )
    monkeypatch.setitem(__import__("sys").modules, "unreal", fake_unreal)

    result = json.loads(assets.inspect_asset("/Game/TC/BP_Workflow"))

    assert result["absolute_path"] == str(artifact)
    assert result["parity_checks"] == {
        "asset registry readback": True,
        "references and save state": True,
    }


def test_unreal_compile_and_pie_emit_named_parity_evidence(monkeypatch) -> None:
    fake_blueprint = object()
    editor = SimpleNamespace(
        compile_blueprint=lambda _bp: None,
        get_compiler_results=lambda _bp: [],
    )
    library = SimpleNamespace(save_asset=lambda *_args, **_kwargs: True)
    fake_unreal = SimpleNamespace(BlueprintEditorLibrary=editor, EditorAssetLibrary=library)
    monkeypatch.setitem(__import__("sys").modules, "unreal", fake_unreal)
    monkeypatch.setattr(blueprint, "_load_blueprint", lambda _unreal, _path: fake_blueprint)

    compiled = json.loads(blueprint.compile_and_save_blueprint("/Game/TC/BP_Workflow"))
    assert compiled["parity_checks"]["Blueprint compile"] is True

    subsystem = SimpleNamespace(is_in_play_in_editor=lambda: True)
    runtime_unreal = SimpleNamespace(
        get_editor_subsystem=lambda _kind: subsystem,
        LevelEditorSubsystem=object(),
        EditorAssetLibrary=SimpleNamespace(does_asset_exist=lambda _path: True),
    )
    monkeypatch.setitem(__import__("sys").modules, "unreal", runtime_unreal)
    monkeypatch.setattr(runtime, "_level_editor", lambda _unreal: subsystem)
    validated = json.loads(runtime.pie_validate(target_assets=["/Game/TC/BP_Workflow"]))

    assert validated["parity_checks"] == {
        "PIE behavior": True,
        "asset registry readback": True,
    }
