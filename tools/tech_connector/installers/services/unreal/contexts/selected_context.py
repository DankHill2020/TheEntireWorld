from __future__ import annotations

from typing import Any, Dict

from tech_connector.services.unreal.capability_registry import (
    get_unreal_capability_pack,
    list_unreal_capabilities,
)
from tech_connector.services.unreal.contexts.common import basic_asset_context, infer_asset_category


class UnrealSelectedContextService:
    """Build compact structured context for the current Unreal selection.

    This starts with lightweight selected asset/actor queries, then dispatches to a
    domain-specific context builder when the selected asset type warrants richer
    context for reliable planning.
    """

    def __init__(self, scanner):
        self.scanner = scanner

    @staticmethod
    def selected_context_focus(task_text: str) -> str:
        lower = (task_text or "").lower()
        if any(
            term in lower
            for term in ("retarget", "ik rig", "ikrig", "ik retargeter", "ikretargeter")
        ):
            return "retarget"
        if any(
            term in lower
            for term in (
                "motion matching",
                "pose search",
                "motionmatching",
                "posesearch",
            )
        ):
            return "motion_matching"
        if any(term in lower for term in ("control rig", "controlrig", "rig graph")):
            return "control_rig"
        if any(
            term in lower
            for term in (
                "physics",
                "ragdoll",
                "constraint",
                "damping",
                "cloth",
                "chaos",
                "physical animation",
            )
        ):
            return "physics"
        if any(term in lower for term in ("niagara", "emitter", "particle", "vfx")):
            return "niagara"
        if any(
            term in lower
            for term in (
                "anim bp",
                "animation blueprint",
                "animblueprint",
                "animgraph",
                "state machine",
            )
        ):
            return "anim_blueprint"
        if any(
            term in lower
            for term in (
                "blueprint",
                "graph",
                "function",
                "functions",
                "node",
                "nodes",
                "inside",
                "connected",
            )
        ):
            return "blueprint"
        return "selection"

    def _builder_for_category(self, category: str):
        """Lazily import Unreal domain builders only when that asset family is used.

        This keeps startup and simple-query paths lighter by avoiding eager imports of
        every Unreal context module when only one domain is needed.
        """
        if category == "blueprint":
            from tech_connector.services.unreal.contexts.blueprint_context import (
                BlueprintContextBuilder,
            )

            return BlueprintContextBuilder(self.scanner)
        if category == "anim_blueprint":
            from tech_connector.services.unreal.contexts.anim_blueprint_context import (
                AnimBlueprintContextBuilder,
            )

            return AnimBlueprintContextBuilder(self.scanner)
        if category == "control_rig":
            from tech_connector.services.unreal.contexts.control_rig_context import (
                ControlRigContextBuilder,
            )

            return ControlRigContextBuilder(self.scanner)
        if category == "physics":
            from tech_connector.services.unreal.contexts.physics_context import PhysicsContextBuilder

            return PhysicsContextBuilder(self.scanner)
        if category == "niagara":
            from tech_connector.services.unreal.contexts.niagara_context import NiagaraContextBuilder

            return NiagaraContextBuilder(self.scanner)
        if category == "motion_matching":
            from tech_connector.services.unreal.contexts.motion_matching_context import (
                MotionMatchingContextBuilder,
            )

            return MotionMatchingContextBuilder(self.scanner)
        if category == "retarget":
            from tech_connector.services.unreal.contexts.retarget_context import RetargetContextBuilder

            return RetargetContextBuilder(self.scanner)
        if category == "skeletal_mesh":
            from tech_connector.services.unreal.contexts.skeletal_mesh_context import (
                SkeletalMeshContextBuilder,
            )

            return SkeletalMeshContextBuilder(self.scanner)
        if category == "anim_sequence":
            from tech_connector.services.unreal.contexts.animation_asset_context import (
                AnimationAssetContextBuilder,
            )

            return AnimationAssetContextBuilder(
                self.scanner, category="anim_sequence", label="Animation Sequence"
            )
        if category == "blend_space":
            from tech_connector.services.unreal.contexts.animation_asset_context import (
                AnimationAssetContextBuilder,
            )

            return AnimationAssetContextBuilder(
                self.scanner, category="blend_space", label="Blend Space"
            )
        if category == "montage":
            from tech_connector.services.unreal.contexts.animation_asset_context import (
                AnimationAssetContextBuilder,
            )

            return AnimationAssetContextBuilder(
                self.scanner, category="montage", label="Animation Montage"
            )
        if category == "level":
            from tech_connector.services.unreal.contexts.level_context import LevelContextBuilder

            return LevelContextBuilder(self.scanner)
        return None

    def _get_live_selection(self) -> tuple[list[str], list[str], list[str]]:
        """Return current selection using the shared DCC context-call registry first.

        Falls back to scanner helpers so older bridge installs still work.
        """
        warnings: list[str] = []
        try:
            from tech_connector.services.dcc.context_call_registry import execute_context_call
        except Exception:
            try:
                from context_call_registry import execute_context_call
            except Exception:
                execute_context_call = None

        if execute_context_call is not None:
            try:
                response = execute_context_call(
                    "unreal",
                    "selection.current",
                    self.scanner.bridge,
                    timeout=2.0,
                )
                data = response.get("data") if isinstance(response, dict) else {}
                if isinstance(data, dict):
                    raw_assets = data.get("selected_assets") or []
                    raw_actors = data.get("selected_actors") or []

                    def _paths(items):
                        out = []
                        for item in items:
                            if isinstance(item, dict):
                                out.append(str(item.get("path") or item.get("name") or item))
                            else:
                                out.append(str(item))
                        return [x for x in out if x]

                    return _paths(raw_assets), _paths(raw_actors), [
                        str(x) for x in (data.get("warnings") or [])
                    ]
                if isinstance(response, dict) and response.get("error"):
                    warnings.append(str(response.get("error")))
            except Exception as exc:
                warnings.append(str(exc))

        try:
            selected_assets = self.scanner.get_selected_assets()
        except Exception as exc:
            selected_assets = []
            warnings.append("selected_assets:" + str(exc))
        try:
            selected_actors = self.scanner.get_selected_actors()
        except Exception as exc:
            selected_actors = []
            warnings.append("selected_actors:" + str(exc))
        return selected_assets, selected_actors, warnings

    def build_selected_context(self, task_text: str = "") -> Dict[str, Any]:
        selected_assets, selected_actors, selection_warnings = self._get_live_selection()
        focus = self.selected_context_focus(task_text)
        result: Dict[str, Any] = {
            "focus": focus,
            "selected_assets": selected_assets[:20],
            "selected_actors": selected_actors[:20],
            "selected_asset_count": len(selected_assets),
            "selected_actor_count": len(selected_actors),
            "primary_asset": selected_assets[0] if selected_assets else None,
            "primary_asset_category": None,
            "selection_context": {},
            "warnings": list(selection_warnings),
        }
        if not selected_assets:
            return result

        primary_asset = str(selected_assets[0])
        category = infer_asset_category(primary_asset)
        result["primary_asset_category"] = category
        capability_pack = get_unreal_capability_pack(category)
        result["available_capabilities"] = list_unreal_capabilities(category)
        result["capability_pack"] = capability_pack
        builder = self._builder_for_category(category)
        if builder is None:
            result["selection_context"] = basic_asset_context(
                primary_asset, category, focus=focus
            )
            result["selection_context"]["available_capabilities"] = result[
                "available_capabilities"
            ]
            result["selection_context"]["recommended_model"] = capability_pack.get(
                "recommended_model"
            )
            result["selection_context"]["risk_level"] = capability_pack.get("risk")
            return result

        try:
            result["selection_context"] = builder.build(primary_asset, focus=focus)
        except Exception as exc:
            result["selection_context"] = basic_asset_context(
                primary_asset, category, focus=focus
            )
            result["warnings"].append(str(exc))
        result["selection_context"]["available_capabilities"] = result[
            "available_capabilities"
        ]
        result["selection_context"]["recommended_model"] = capability_pack.get(
            "recommended_model"
        )
        result["selection_context"]["risk_level"] = capability_pack.get("risk")
        return result
