"""Generate reflected C++ bridge wrappers callable from Unreal Python."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from pathlib import Path
from typing import Any


PLUGIN_NAME = "AIStudioBridge"
MODULE_NAME = "AIStudioBridge"
LIBRARY_CLASS = "UAIStudioBridgeLibrary"


def _canonical_plugin_root() -> Path:
    return Path(__file__).resolve().parents[3] / "plugins" / PLUGIN_NAME


def _canonical_plugin_text(relative_path: str) -> str:
    path = _canonical_plugin_root() / relative_path
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


@dataclass
class WrapperPlan:
    ok: bool
    message: str
    project_root: str
    plugin_root: str
    capability: str
    function_name: str
    python_call: str
    files: list[dict[str, str]]
    next_steps: list[str]
    warnings: list[str]
    progress_phases: list[dict[str, Any]]
    functional_body_contract: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "message": self.message,
            "project_root": self.project_root,
            "plugin_root": self.plugin_root,
            "capability": self.capability,
            "function_name": self.function_name,
            "python_call": self.python_call,
            "files": self.files,
            "next_steps": self.next_steps,
            "warnings": self.warnings,
            "progress_phases": self.progress_phases,
            "functional_body_contract": self.functional_body_contract,
        }


def _slug(text: str, fallback: str = "unreal_capability") -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "_", text or "").strip("_").lower()
    return text or fallback


def _pascal(text: str, fallback: str = "UnrealCapability") -> str:
    words = re.findall(r"[A-Za-z0-9]+", text or "")
    if not words:
        words = re.findall(r"[A-Za-z0-9]+", fallback)
    return "".join(word[:1].upper() + word[1:] for word in words)


def _find_project_root(path: str | Path) -> Path:
    root = Path(path or "").expanduser()
    if root.is_file() and root.suffix.lower() == ".uproject":
        return root.parent.resolve()
    for candidate in [root, *root.parents]:
        if any(candidate.glob("*.uproject")):
            return candidate.resolve()
    return root.resolve()


def _infer_capability(text: str) -> dict[str, str]:
    q = (text or "").lower()
    if "add" in q and "state" in q and any(term in q for term in ("anim", "animation", "state machine")):
        return {
            "capability": "add_anim_graph_state",
            "label": "Add Anim Graph State",
            "function": "AddAnimGraphState",
            "category": "Tech Connector|Animation",
            "argument_type": "UAnimBlueprint*",
            "argument_name": "AnimBlueprint",
            "python_argument_hint": "anim_bp, state_machine, state_name, animation_asset",
            "summary": "Create or update a state inside an AnimBlueprint state machine using editor-only C++ APIs.",
        }
    if "transition" in q and any(term in q for term in ("anim", "animation", "state machine")):
        return {
            "capability": "add_anim_graph_transition_rule",
            "label": "Add Anim Graph Transition Rule",
            "function": "AddAnimGraphTransitionRule",
            "category": "Tech Connector|Animation",
            "argument_type": "UAnimBlueprint*",
            "argument_name": "AnimBlueprint",
            "python_argument_hint": "anim_bp, state_machine, from_state, to_state, rule_expression",
            "summary": "Create an AnimBlueprint state-machine transition and attach a guard expression using editor-only C++ APIs.",
        }
    if "wire" in q and any(term in q for term in ("output pose", "state machine")):
        return {
            "capability": "wire_anim_graph_output_pose",
            "label": "Wire Anim Graph Output Pose",
            "function": "WireAnimGraphOutputPose",
            "category": "Tech Connector|Animation",
            "argument_type": "UAnimBlueprint*",
            "argument_name": "AnimBlueprint",
            "python_argument_hint": "anim_bp, state_machine",
            "summary": "Wire an AnimBlueprint state machine result into the AnimGraph output pose using editor-only C++ APIs.",
        }
    if "compile" in q and any(term in q for term in ("anim", "blueprint")):
        return {
            "capability": "compile_and_save_anim_blueprint",
            "label": "Compile And Save Anim Blueprint",
            "function": "CompileAndSaveAnimBlueprint",
            "category": "Tech Connector|Animation",
            "argument_type": "UAnimBlueprint*",
            "argument_name": "AnimBlueprint",
            "python_argument_hint": "anim_bp",
            "summary": "Compile and save an AnimBlueprint, returning compiler status and asset-save evidence.",
        }
    if "pie" in q and any(term in q for term in ("montage", "animation", "anim ")):
        return {
            "capability": "validate_character_montages_in_pie",
            "label": "Validate Character Montages In PIE",
            "function": "ValidateCharacterMontagesInPIE",
            "category": "Tech Connector|Runtime",
            "argument_type": "UClass*",
            "argument_name": "CharacterClass",
            "python_argument_hint": "character_class, montages, expected_anim_class_contains",
            "summary": "Play and observe character montages in PIE, returning runtime evidence instead of compile-only claims.",
        }
    if any(term in q for term in ("animgraph", "anim graph", "animation graph", "anim blueprint")):
        return {
            "capability": "inspect_anim_blueprint_graph",
            "label": "Inspect Anim Blueprint Graph",
            "function": "InspectAnimBlueprintGraph",
            "category": "Tech Connector|Animation",
            "argument_type": "UAnimBlueprint*",
            "argument_name": "AnimBlueprint",
            "python_argument_hint": "anim_bp",
            "summary": "Inspect Animation Blueprint graph containers, graph names, node classes, pins, and links.",
        }
    return {
        "capability": _slug(text),
        "label": _pascal(text),
        "function": _pascal(text),
        "category": "Tech Connector|Editor",
        "argument_type": "UObject*",
        "argument_name": "Target",
        "python_argument_hint": "target",
        "summary": "Bridge a missing Unreal editor capability into Python through reflected C++.",
    }


def _uplugin_text() -> str:
    canonical = _canonical_plugin_text(f"{PLUGIN_NAME}.uplugin")
    if canonical:
        return canonical
    data = {
        "FileVersion": 3,
        "Version": 1,
        "VersionName": "0.1.0",
        "FriendlyName": "Tech Connector Bridge",
        "Description": "Reflected C++ bridge functions generated by The Entire World Tech Connector.",
        "Category": "Editor",
        "CreatedBy": "The Entire World Tech Connector",
        "EnabledByDefault": False,
        "CanContainContent": False,
        "Modules": [
            {
                "Name": MODULE_NAME,
                "Type": "Editor",
                "LoadingPhase": "Default",
            }
        ],
    }
    return json.dumps(data, indent=2) + "\n"


def _build_cs_text() -> str:
    canonical = _canonical_plugin_text(f"Source/{MODULE_NAME}/{MODULE_NAME}.Build.cs")
    if canonical:
        return canonical
    return """using UnrealBuildTool;

public class AIStudioBridge : ModuleRules
{
    public AIStudioBridge(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

        PublicDependencyModuleNames.AddRange(new string[]
        {
            "Core",
            "CoreUObject",
            "Engine"
        });

        PrivateDependencyModuleNames.AddRange(new string[]
        {
            "UnrealEd",
            "BlueprintGraph",
            "AnimGraph",
            "AnimGraphRuntime",
            "Json"
        });
    }
}
"""


def _module_header_text() -> str:
    canonical = _canonical_plugin_text(f"Source/{MODULE_NAME}/Public/{MODULE_NAME}.h")
    if canonical:
        return canonical
    return """#pragma once

#include "Modules/ModuleManager.h"

class FAIStudioBridgeModule : public IModuleInterface
{
public:
    virtual void StartupModule() override;
    virtual void ShutdownModule() override;
};
"""


def _module_cpp_text() -> str:
    canonical = _canonical_plugin_text(f"Source/{MODULE_NAME}/Private/{MODULE_NAME}.cpp")
    if canonical:
        return canonical
    return """#include "AIStudioBridge.h"

#define LOCTEXT_NAMESPACE "FAIStudioBridgeModule"

void FAIStudioBridgeModule::StartupModule()
{
}

void FAIStudioBridgeModule::ShutdownModule()
{
}

#undef LOCTEXT_NAMESPACE

IMPLEMENT_MODULE(FAIStudioBridgeModule, AIStudioBridge)
"""


def _library_header_text() -> str:
    canonical = _canonical_plugin_text(f"Source/{MODULE_NAME}/Public/AIStudioBridgeLibrary.h")
    if canonical:
        return canonical
    return """#pragma once

#include "Kismet/BlueprintFunctionLibrary.h"
#include "Animation/AnimBlueprint.h"
#include "AIStudioBridgeLibrary.generated.h"

UCLASS()
class AISTUDIOBRIDGE_API UAIStudioBridgeLibrary : public UBlueprintFunctionLibrary
{
    GENERATED_BODY()

public:
    UFUNCTION(BlueprintCallable, CallInEditor, Category="Tech Connector|Animation")
    static FString InspectAnimBlueprintGraph(UAnimBlueprint* AnimBlueprint);
};
"""


def _library_cpp_text() -> str:
    canonical = _canonical_plugin_text(f"Source/{MODULE_NAME}/Private/AIStudioBridgeLibrary.cpp")
    if canonical:
        return canonical
    return """#include "AIStudioBridgeLibrary.h"

#if WITH_EDITOR
#include "EdGraph/EdGraph.h"
#include "EdGraph/EdGraphNode.h"
#include "EdGraph/EdGraphPin.h"
#include "Dom/JsonObject.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#endif

static FString AIStudioJsonString(const TSharedRef<FJsonObject>& Object)
{
    FString Output;
    const TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Output);
    FJsonSerializer::Serialize(Object, Writer);
    return Output;
}

FString UAIStudioBridgeLibrary::InspectAnimBlueprintGraph(UAnimBlueprint* AnimBlueprint)
{
    const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("capability"), TEXT("inspect_anim_blueprint_graph"));
    Root->SetBoolField(TEXT("ok"), false);

#if WITH_EDITOR
    if (!AnimBlueprint)
    {
        Root->SetStringField(TEXT("error"), TEXT("AnimBlueprint was null."));
        return AIStudioJsonString(Root);
    }

    Root->SetBoolField(TEXT("ok"), true);
    Root->SetStringField(TEXT("asset_name"), AnimBlueprint->GetName());
    Root->SetStringField(TEXT("asset_path"), AnimBlueprint->GetPathName());

    TArray<UEdGraph*> Graphs;
    Graphs.Append(AnimBlueprint->UbergraphPages);
    Graphs.Append(AnimBlueprint->FunctionGraphs);
    Graphs.Append(AnimBlueprint->MacroGraphs);
    Graphs.Append(AnimBlueprint->DelegateSignatureGraphs);

    TArray<TSharedPtr<FJsonValue>> GraphValues;
    for (UEdGraph* Graph : Graphs)
    {
        if (!Graph)
        {
            continue;
        }

        const TSharedRef<FJsonObject> GraphObject = MakeShared<FJsonObject>();
        GraphObject->SetStringField(TEXT("name"), Graph->GetName());
        GraphObject->SetStringField(TEXT("class"), Graph->GetClass()->GetName());

        TArray<TSharedPtr<FJsonValue>> NodeValues;
        for (UEdGraphNode* Node : Graph->Nodes)
        {
            if (!Node)
            {
                continue;
            }

            const TSharedRef<FJsonObject> NodeObject = MakeShared<FJsonObject>();
            NodeObject->SetStringField(TEXT("name"), Node->GetName());
            NodeObject->SetStringField(TEXT("title"), Node->GetNodeTitle(ENodeTitleType::ListView).ToString());
            NodeObject->SetStringField(TEXT("class"), Node->GetClass()->GetName());
            NodeObject->SetNumberField(TEXT("pin_count"), Node->Pins.Num());

            TArray<TSharedPtr<FJsonValue>> PinValues;
            for (UEdGraphPin* Pin : Node->Pins)
            {
                if (!Pin)
                {
                    continue;
                }
                const TSharedRef<FJsonObject> PinObject = MakeShared<FJsonObject>();
                PinObject->SetStringField(TEXT("name"), Pin->PinName.ToString());
                PinObject->SetStringField(TEXT("direction"), Pin->Direction == EGPD_Input ? TEXT("input") : TEXT("output"));
                PinObject->SetStringField(TEXT("category"), Pin->PinType.PinCategory.ToString());
                PinObject->SetNumberField(TEXT("linked_to_count"), Pin->LinkedTo.Num());
                PinValues.Add(MakeShared<FJsonValueObject>(PinObject));
            }
            NodeObject->SetArrayField(TEXT("pins"), PinValues);
            NodeValues.Add(MakeShared<FJsonValueObject>(NodeObject));
        }

        GraphObject->SetNumberField(TEXT("node_count"), Graph->Nodes.Num());
        GraphObject->SetArrayField(TEXT("nodes"), NodeValues);
        GraphValues.Add(MakeShared<FJsonValueObject>(GraphObject));
    }

    Root->SetArrayField(TEXT("graphs"), GraphValues);
    Root->SetStringField(TEXT("python_call"), TEXT("unreal.AIStudioBridgeLibrary.inspect_anim_blueprint_graph(anim_bp)"));
#else
    Root->SetStringField(TEXT("error"), TEXT("Tech Connector bridge wrappers are editor-only."));
#endif

    return AIStudioJsonString(Root);
}
"""


def _function_body_contract(cpp_text: str, spec: dict[str, str], python_call: str) -> dict[str, Any]:
    function = spec.get("function") or ""
    match = re.search(rf"FString\s+UAIStudioBridgeLibrary::{re.escape(function)}\s*\(", cpp_text)
    if not match:
        return {
            "ok": False,
            "status": "missing_cpp_body",
            "function": function,
            "required": [
                "Define the reflected C++ function body.",
                "Return structured JSON with ok/status/evidence fields.",
                "Include the exact reflected Python call in the response.",
                "Validate the function in live Unreal before registration.",
            ],
        }
    next_match = re.search(r"\nFString\s+UAIStudioBridgeLibrary::\w+\s*\(", cpp_text[match.end():])
    body_end = match.end() + next_match.start() if next_match else len(cpp_text)
    body = cpp_text[match.start():body_end]
    failures = []
    if "cpp_body_required" in body:
        failures.append("body_still_returns_cpp_body_required")
    if "SetBoolField(TEXT(\"ok\")," not in body:
        failures.append("does_not_set_ok_result")
    expected_method = python_call.split("(", 1)[0]
    if expected_method not in body:
        failures.append("does_not_report_reflected_python_call")
    if "implementation_hint" in body and "cpp_body_required" in body:
        failures.append("placeholder_implementation_hint_present")
    return {
        "ok": not failures,
        "status": "functional" if not failures else "non_functional_body",
        "function": function,
        "failures": failures,
        "required": [
            "No cpp_body_required placeholder status.",
            "Sets ok from real editor/API work or readback evidence.",
            "Returns structured JSON evidence.",
            "Reports the exact reflected Python call.",
            "Has a live Unreal validation phase before capability registration.",
        ],
    }


def _manifest_text(spec: dict[str, str], python_call: str) -> str:
    canonical = _canonical_plugin_text("AIStudioBridgeCapabilities.json")
    if canonical:
        return canonical
    data = {
        "plugin": PLUGIN_NAME,
        "module": MODULE_NAME,
        "library_class": "AIStudioBridgeLibrary",
        "capabilities": [
            {
                "name": spec["capability"],
                "label": spec["label"],
                "function": spec["function"],
                "python_call": python_call,
                "summary": spec["summary"],
            }
        ],
    }
    return json.dumps(data, indent=2) + "\n"


def create_unreal_cpp_wrapper_plan(
    project_root: str | Path,
    request_text: str,
    apply: bool = False,
) -> WrapperPlan:
    root = _find_project_root(project_root)
    spec = _infer_capability(request_text)
    domain_coverage = _domain_operation_coverage_for_request(request_text)
    plugin_root = root / "Plugins" / PLUGIN_NAME
    source_root = plugin_root / "Source" / MODULE_NAME
    public_root = source_root / "Public"
    private_root = source_root / "Private"
    python_call = f"unreal.AIStudioBridgeLibrary.{_python_method_name(spec['function'])}({spec['python_argument_hint']})"

    file_map = {
        plugin_root / f"{PLUGIN_NAME}.uplugin": _uplugin_text(),
        source_root / f"{MODULE_NAME}.Build.cs": _build_cs_text(),
        public_root / f"{MODULE_NAME}.h": _module_header_text(),
        private_root / f"{MODULE_NAME}.cpp": _module_cpp_text(),
        public_root / "AIStudioBridgeLibrary.h": _library_header_text(),
        private_root / "AIStudioBridgeLibrary.cpp": _library_cpp_text(),
        plugin_root / "AIStudioBridgeCapabilities.json": _manifest_text(spec, python_call),
    }
    body_contract = _function_body_contract(
        file_map[private_root / "AIStudioBridgeLibrary.cpp"],
        spec,
        python_call,
    )

    blocked = not body_contract["ok"]
    files = [
        {
            "path": str(path),
            "action": "blocked" if apply and blocked else "write" if apply else "preview",
        }
        for path in file_map
    ]
    warnings: list[str] = []
    if domain_coverage and domain_coverage.get("decision") == "implement_python_first":
        warnings.append(
            f"{domain_coverage['operation']} has an existing Python wrapper "
            f"({domain_coverage['python_implementation']}) and reflected Unreal API evidence; "
            "implement and live-validate that Python wrapper before adding a redundant C++ bridge body."
        )
    elif domain_coverage and domain_coverage.get("decision") == "python_native":
        warnings.append(
            f"{domain_coverage['operation']} is already covered by a functional Python implementation "
            f"({domain_coverage['python_implementation']}); do not generate C++ unless live validation proves Python is insufficient."
        )
    if not root.exists():
        warnings.append(f"Project root does not exist yet: {root}")
    if not any(root.glob("*.uproject")):
        warnings.append("No .uproject file found at project root; select the Unreal project folder before applying.")
    existing_plugin_status = _existing_plugin_function_status(spec["function"])
    if existing_plugin_status == "cpp_body_required":
        warnings.append(
            f"{spec['function']} is already reflected in AIStudioBridge, but its C++ body still returns cpp_body_required; implement and live-validate the body instead of adding another wrapper."
        )
    elif existing_plugin_status == "implemented":
        warnings.append(
            f"{spec['function']} is already implemented in AIStudioBridge; validate the reflected Python call before treating it as a capability gap."
        )
    if blocked:
        warnings.append(
            f"{spec['function']} does not satisfy the functional body contract: "
            + ", ".join(body_contract.get("failures") or [body_contract.get("status", "unknown")])
        )

    if apply and not blocked:
        for path, content in file_map.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and path.read_text(encoding="utf-8", errors="replace") == content:
                continue
            path.write_text(content, encoding="utf-8")

    return WrapperPlan(
        ok=not blocked,
        message=(
            "Generated Unreal reflected C++ bridge wrapper files."
            if apply and not blocked
            else "Blocked Unreal C++ wrapper write because the target body is not functional."
            if apply and blocked
            else "Prepared Unreal reflected C++ bridge wrapper plan."
        ),
        project_root=str(root),
        plugin_root=str(plugin_root),
        capability=spec["capability"],
        function_name=spec["function"],
        python_call=python_call,
        files=files,
        next_steps=[
            *(
                [
                    f"Implement the Python-first wrapper: {domain_coverage['python_implementation']}.",
                    "Validate it against a disposable asset fixture and read back the mutation result.",
                    "Only promote to AIStudioBridge C++ if Python validation cannot meet the minimum contract.",
                ]
                if domain_coverage and domain_coverage.get("decision") == "implement_python_first"
                else []
            ),
            "Enable/keep enabled the AIStudioBridge plugin in Unreal.",
            "Compile the project or use Live Coding from Unreal.",
            "Restart the editor if Unreal requests it.",
            f"Validate from Python: {python_call}",
            "Register the capability so future prompts call the wrapper directly.",
        ],
        warnings=warnings,
        progress_phases=_plugin_build_progress_phases(spec, python_call),
        functional_body_contract=body_contract,
)


def _domain_operation_coverage_for_request(request_text: str) -> dict[str, Any] | None:
    try:
        from tech_connector.services.unreal.domain_operation_coverage_service import (
            classify_domain_operation,
        )
        from tech_connector.services.unreal.unreal_operation_service import (
            unreal_prompt_to_operation,
        )
    except Exception:
        return None
    text = request_text or ""
    operation = unreal_prompt_to_operation(text) or ""
    fallback = _fallback_domain_operation(text)
    if fallback:
        try:
            from tech_connector.services.unreal.domain_operation_coverage_service import (
                PYTHON_IMPLEMENTATIONS,
            )
            if operation not in PYTHON_IMPLEMENTATIONS:
                operation = fallback
        except Exception:
            operation = operation or fallback
    if not operation:
        return None
    coverage = classify_domain_operation(operation)
    if coverage.get("decision") in {"python_native", "implement_python_first", "cpp_preferred", "cpp_required"}:
        return coverage
    return None


def _fallback_domain_operation(request_text: str) -> str:
    q = (request_text or "").lower()
    if "niagara" in q or "niagra" in q or "emitter" in q:
        if "delete" in q or "remove" in q:
            return "niagara.delete_emitter"
        if "module" in q and "input" in q:
            return "niagara.set_module_input" if any(term in q for term in ("set", "write", "change")) else "niagara.list_module_inputs"
        if "renderer" in q:
            return "niagara.set_renderer_property"
        if "user" in q and "parameter" in q:
            return "niagara.set_user_parameter"
        if "property" in q:
            return "niagara.set_emitter_property"
        if any(term in q for term in ("create", "make", "new", "spawn")):
            return "niagara.create_emitter"
    if "pose search" in q or "motion matching" in q:
        if "schema" in q and "channel" in q:
            return "motion_matching.add_schema_channel"
        if "schema" in q:
            return "motion_matching.create_schema"
        if "remove" in q and "animation" in q:
            return "motion_matching.remove_animation"
        if "animation" in q and any(term in q for term in ("add", "insert")):
            return "motion_matching.add_animation"
        if "property" in q:
            return "motion_matching.set_database_property"
        return "motion_matching.create_database"
    if "retarget" in q or "ik rig" in q or "ikrig" in q:
        if "chain" in q and any(term in q for term in ("map", "mapping")):
            return "retarget.set_chain_mapping"
        if "chain" in q:
            return "retarget.add_ik_chain"
        if "root" in q:
            return "retarget.set_root_settings"
        if "profile" in q:
            return "retarget.set_profile_property"
        if "retargeter" in q:
            return "retarget.create_ik_retargeter"
        return "retarget.create_ik_rig"
    if "physics" in q and "profile" in q:
        return "physics.set_profile_property"
    return ""


def _plugin_build_progress_phases(spec: dict[str, str], python_call: str) -> list[dict[str, Any]]:
    capability = spec.get("capability") or "unreal_cpp_wrapper"
    return [
        {
            "id": "prepare_plugin_source",
            "phase": "planning",
            "status": "pending",
            "progress": 5,
            "percent": 5,
            "label": "Prepare plugin source",
            "message": f"Preparing AIStudioBridge source for {capability}.",
            "evidence": ["wrapper spec", "target plugin paths"],
        },
        {
            "id": "write_plugin_files",
            "phase": "executing",
            "status": "pending",
            "progress": 20,
            "percent": 20,
            "label": "Write plugin files",
            "message": "Writing or updating plugin source, Build.cs, descriptor, and capability manifest.",
            "evidence": ["AIStudioBridge.uplugin", "AIStudioBridgeLibrary.h", "AIStudioBridgeLibrary.cpp"],
        },
        {
            "id": "build_cpp_plugin",
            "phase": "executing",
            "status": "pending",
            "progress": 45,
            "percent": 45,
            "label": "Build C++ plugin",
            "message": "Building the C++ plugin with UnrealBuildTool or Live Coding.",
            "evidence": ["compiled editor binary", "build log"],
        },
        {
            "id": "enable_plugin",
            "phase": "executing",
            "status": "pending",
            "progress": 60,
            "percent": 60,
            "label": "Enable plugin",
            "message": "Enabling AIStudioBridge only after a compiled editor binary is present.",
            "evidence": [".uproject Plugins entry", "build-environment diagnostic"],
        },
        {
            "id": "restart_unreal_if_needed",
            "phase": "executing",
            "status": "pending",
            "progress": 75,
            "percent": 75,
            "label": "Restart Unreal if needed",
            "message": "Restarting or prompting for an Unreal restart if the editor cannot load the new module live.",
            "evidence": ["editor module load status"],
        },
        {
            "id": "validate_reflected_python_call",
            "phase": "validating",
            "status": "pending",
            "progress": 90,
            "percent": 90,
            "label": "Validate reflected Python call",
            "message": f"Validating reflected Python call: {python_call}",
            "evidence": ["Unreal Python result JSON", "capability ok/status field"],
        },
        {
            "id": "register_validated_capability",
            "phase": "validating",
            "status": "pending",
            "progress": 100,
            "percent": 100,
            "label": "Register validated capability",
            "message": "Registering the wrapper as a reusable capability after validation passes.",
            "evidence": ["capability registry entry", "future route can resolve the operation"],
        },
    ]


def _existing_plugin_function_status(function_name: str) -> str:
    try:
        from tech_connector.services.unreal.unreal_capability_audit_service import audit_unreal_capability_catalogs

        audit = audit_unreal_capability_catalogs()
    except Exception:
        return ""
    for row in audit.get("plugin_capabilities") or []:
        if row.get("function") == function_name:
            return str(row.get("cpp_status") or "")
    return ""


def _project_descriptor(root: Path) -> Path | None:
    return next(iter(sorted(root.glob("*.uproject"))), None)


def diagnose_unreal_cpp_build_environment(
    project_root: str | Path,
    engine_root: str | Path | None = None,
    plugin_name: str = PLUGIN_NAME,
) -> dict[str, Any]:
    """Report whether a generated source plugin is compiled and safe to enable."""

    root = _find_project_root(project_root)
    project_file = _project_descriptor(root)
    plugin_root = root / "Plugins" / plugin_name
    plugin_descriptor = plugin_root / f"{plugin_name}.uplugin"
    source_root = plugin_root / "Source"
    binaries_root = plugin_root / "Binaries"
    engine = Path(engine_root).expanduser().resolve() if engine_root else None
    build_tool = engine / "Engine" / "Build" / "BatchFiles" / "Build.bat" if engine else None
    binaries = []
    if binaries_root.is_dir():
        binaries = [
            str(path)
            for path in binaries_root.rglob(f"*{plugin_name}*")
            if path.is_file() and path.suffix.lower() in {".dll", ".lib", ".modules"}
        ]

    has_source = source_root.is_dir() and any(source_root.rglob("*.Build.cs"))
    has_compiled_binary = bool(binaries)
    gates = {
        "project_descriptor_found": bool(project_file),
        "plugin_descriptor_found": plugin_descriptor.is_file(),
        "plugin_source_found": has_source,
        "compiled_binary_found": has_compiled_binary,
        "engine_build_tool_found": bool(build_tool and build_tool.is_file()),
    }
    gates["safe_to_enable"] = bool(
        gates["project_descriptor_found"]
        and gates["plugin_descriptor_found"]
        and gates["compiled_binary_found"]
    )
    return {
        "ok": True,
        "project_root": str(root),
        "project_file": str(project_file or ""),
        "plugin_root": str(plugin_root),
        "plugin_descriptor": str(plugin_descriptor),
        "engine_root": str(engine or ""),
        "build_tool": str(build_tool or ""),
        "binaries": binaries,
        "gates": gates,
        "recommended_action": (
            "enable_plugin"
            if gates["safe_to_enable"]
            else "build_plugin_before_enabling"
            if gates["plugin_descriptor_found"] and gates["plugin_source_found"]
            else "generate_plugin_source"
        ),
    }


def set_unreal_plugin_enabled_transactionally(
    project_root: str | Path,
    *,
    enabled: bool,
    engine_root: str | Path | None = None,
    apply: bool = False,
    plugin_name: str = PLUGIN_NAME,
) -> dict[str, Any]:
    """Update the project descriptor only after all enablement gates pass."""

    root = _find_project_root(project_root)
    project_file = _project_descriptor(root)
    diagnostic = diagnose_unreal_cpp_build_environment(
        root,
        engine_root=engine_root,
        plugin_name=plugin_name,
    )
    if not project_file:
        return {"ok": False, "changed": False, "error": "No .uproject descriptor was found.", "diagnostic": diagnostic}
    if enabled and not diagnostic["gates"]["safe_to_enable"]:
        return {
            "ok": False,
            "changed": False,
            "error": "The plugin is source-only or missing a compiled editor binary; build it before enabling.",
            "diagnostic": diagnostic,
        }

    try:
        data = json.loads(project_file.read_text(encoding="utf-8") or "{}")
    except (OSError, ValueError) as exc:
        return {"ok": False, "changed": False, "error": f"Could not read project descriptor: {exc}", "diagnostic": diagnostic}

    plugins = list(data.get("Plugins") or [])
    existing = next((item for item in plugins if str(item.get("Name") or "") == plugin_name), None)
    previous = bool(existing.get("Enabled")) if existing else False
    if existing is None:
        existing = {"Name": plugin_name, "Enabled": enabled}
        plugins.append(existing)
    else:
        existing["Enabled"] = enabled
    changed = previous != enabled
    if not apply:
        return {"ok": True, "changed": changed, "applied": False, "diagnostic": diagnostic}

    data["Plugins"] = plugins
    temporary = project_file.with_suffix(project_file.suffix + ".aistudio.tmp")
    try:
        temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        temporary.replace(project_file)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        return {"ok": False, "changed": False, "error": f"Could not update project descriptor: {exc}", "diagnostic": diagnostic}
    return {"ok": True, "changed": changed, "applied": True, "diagnostic": diagnostic}


def _python_method_name(cpp_name: str) -> str:
    value = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", cpp_name)
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    return value.lower()

