from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

from motionbuilder_tools import character as character_ops
from motionbuilder_tools import io as io_ops


def _fake_sdk(tmp_path) -> ModuleType:
    sdk = ModuleType("pyfbsdk")

    class Curve:
        Keys = [1, 2, 3]

    class AnimationNode:
        FCurve = Curve()
        Nodes = []

    class AnimatedProperty:
        def GetAnimationNode(self):
            return AnimationNode()

    class ModelSkeleton:
        def __init__(self, name):
            self.Name = name
            self.LongName = name
            self.Translation = AnimatedProperty()
            self.Rotation = AnimatedProperty()
            self.Scaling = AnimatedProperty()

    class Link:
        def __init__(self):
            self.models = []

        def removeAll(self):
            self.models.clear()

        def append(self, model):
            self.models.append(model)

    class PropertyList:
        def __init__(self):
            self.links = {}

        def Find(self, name):
            return self.links.setdefault(name, Link())

    scene = SimpleNamespace(Components=[], Characters=[], Takes=[])

    class Character:
        def __init__(self, name):
            self.Name = name
            self.PropertyList = PropertyList()
            self._characterized = False
            scene.Characters.append(self)
            scene.Components.append(self)

        def GetCharacterize(self):
            return self._characterized

        def SetCharacterizeOn(self, value):
            self._characterized = bool(value)
            return True

        def PlotAnimation(self, destination, options):
            self.last_plot = (destination, options)
            return True

    class TimeValue:
        def __init__(self, frame):
            self.frame = frame

        def GetFrame(self):
            return self.frame

    class TimeSpan:
        def GetStart(self):
            return TimeValue(1)

        def GetStop(self):
            return TimeValue(24)

    take = SimpleNamespace(Name="Walk", LocalTimeSpan=TimeSpan())
    system = SimpleNamespace(Scene=scene, CurrentTake=take)
    scene.Takes.append(take)

    class Application:
        def FileMerge(self, path):
            self.last_import = (path, True)
            return True

        def FileOpen(self, path):
            self.last_import = (path, False)
            return True

        def FileSave(self, path, options):
            self.last_export = (path, options)
            with open(path, "wb") as stream:
                stream.write(b"FBX")
            return True

    application = Application()

    class FbxOptions:
        def __init__(self, _load):
            self.SaveSelectedModelsOnly = False

    class PlotOptions:
        pass

    class Time:
        def __init__(self, *_args):
            pass

    sdk.FBCharacter = Character
    sdk.FBModelSkeleton = ModelSkeleton
    sdk.FBSystem = lambda: system
    sdk.FBApplication = lambda: application
    sdk.FBFbxOptions = FbxOptions
    sdk.FBPlotOptions = PlotOptions
    sdk.FBTime = Time
    sdk.FBCharacterPlotWhere = SimpleNamespace(
        kFBCharacterPlotOnControlRig=1,
        kFBCharacterPlotOnSkeleton=2,
    )
    models = [ModelSkeleton(name) for name in ("Hips", "LeftUpLeg", "LeftLeg", "LeftFoot", "RightUpLeg", "RightLeg", "RightFoot", "Spine", "Head", "LeftArm", "LeftForeArm", "LeftHand", "RightArm", "RightForeArm", "RightHand")]
    scene.Components.extend(models)
    by_name = {model.Name: model for model in models}
    sdk.FBFindModelByLabelName = lambda name: by_name.get(name)
    return sdk


def test_motionbuilder_character_plot_export_and_parity_readback(monkeypatch, tmp_path) -> None:
    sdk = _fake_sdk(tmp_path)
    monkeypatch.setitem(sys.modules, "pyfbsdk", sdk)
    source = tmp_path / "source.fbx"
    source.write_bytes(b"FBX")
    output = tmp_path / "plotted.fbx"

    imported = io_ops.import_fbx(str(source))
    characterized = character_ops.create_character("Hero")
    plotted = character_ops.plot_animation("Hero", plot_to_rig=False, fps=24)
    exported = io_ops.export_fbx(str(output))
    inspected = io_ops.inspect_character("Hero")

    assert imported["ok"] and characterized["characterized"]
    assert len(characterized["assigned_slots"]) == 15
    assert plotted["plot_destination"] == "skeleton" and plotted["fps"] == 24
    assert exported["ok"] and output.is_file()
    assert inspected["start_frame"] == 1 and inspected["end_frame"] == 24
    assert inspected["animation_key_count"] > 0
    assert all(inspected["parity_checks"].values())
