"""Interactive Educational Guide and Tutorial Mode Service for Tech Connector.

Allows users to switch from default automated execution to tutorial mode.
Tutorial mode breaks 3D tasks into learn-by-doing walkthroughs with actions,
concepts, verification checks, and optional learning resources.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class WalkthroughStep:
    """A single actionable step in an educational walkthrough."""

    step_number: int
    title: str
    action_instruction: str
    educational_concept: str
    dcc_target: str
    verification_check_code: str = ""
    completed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_number": self.step_number,
            "title": self.title,
            "action_instruction": self.action_instruction,
            "educational_concept": self.educational_concept,
            "dcc_target": self.dcc_target,
            "verification_check_code": self.verification_check_code,
            "completed": self.completed,
        }


@dataclass
class TutorialWalkthroughPlan:
    """Actionable step-by-step educational walkthrough plan for the user."""

    task_name: str
    mode: str = "interactive_guide"
    overview: str = ""
    target_dcc: str = "Unreal Engine 5"
    steps: list[WalkthroughStep] = field(default_factory=list)
    current_step_index: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_name": self.task_name,
            "mode": self.mode,
            "overview": self.overview,
            "target_dcc": self.target_dcc,
            "steps": [s.to_dict() for s in self.steps],
            "current_step_index": self.current_step_index,
        }


@dataclass
class EducationalResourceLink:
    """An optional educational resource link for a walkthrough topic."""

    title: str
    url_or_ref: str
    resource_type: str
    description: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url_or_ref": self.url_or_ref,
            "resource_type": self.resource_type,
            "description": self.description,
        }


class TutorialModeService:
    """Manages automation vs interactive tutorial mode and plan generation."""

    def __init__(self):
        self._mode = "automation"

    @property
    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str):
        if mode in ("automation", "interactive_guide"):
            self._mode = mode

    def is_tutorial_mode(self) -> bool:
        return self._mode == "interactive_guide"

    def build_educational_walkthrough(self, task_prompt: str, active_dcc: str = "") -> TutorialWalkthroughPlan:
        """Convert a prompt into a step-by-step interactive educational guide."""
        clean_prompt = strip_tutorial_directive(task_prompt)
        dcc = detect_target_dcc(clean_prompt, active_dcc)
        category = classify_3d_task(clean_prompt)
        steps = _build_steps_for_category(category, clean_prompt, dcc)

        return TutorialWalkthroughPlan(
            task_name=clean_prompt,
            mode="interactive_guide",
            overview=f"Educational walkthrough: learn the workflow for '{clean_prompt}' in {dcc}.",
            target_dcc=dcc,
            steps=steps,
            current_step_index=0,
        )


_TUTORIAL_DIRECTIVE_RE = re.compile(
    r"(^|\s)(/tutorial|/guide|\+tutorial|tutorial mode|teach me)(?=\s|:|$)",
    re.IGNORECASE,
)


def strip_tutorial_directive(task_prompt: str) -> str:
    """Remove tutorial activation text before showing the task back to the user."""
    cleaned = _TUTORIAL_DIRECTIVE_RE.sub(" ", str(task_prompt or "")).strip()
    return re.sub(r"\s+", " ", cleaned) or "3D workflow"


def has_tutorial_directive(task_prompt: str) -> bool:
    """Return True only when the user explicitly opted into guide mode."""
    return bool(_TUTORIAL_DIRECTIVE_RE.search(str(task_prompt or "")))


def detect_target_dcc(task_prompt: str, active_dcc: str = "") -> str:
    """Infer the target DCC from the prompt, falling back to the active app."""
    lower = str(task_prompt or "").lower()
    explicit = [
        (("maya", "arnold"), "Autodesk Maya"),
        (("unreal", "ue5", "metahuman", "level sequence", "control rig"), "Unreal Engine 5"),
        (("blender", "geometry nodes", "cycles", "eevee"), "Blender"),
        (("houdini", "vex", "sop", "hda", "karma"), "Houdini"),
        (("substance", "painter", "designer", "pbr"), "Substance 3D Painter"),
        (("photoshop", "psd"), "Adobe Photoshop"),
        (("gimp",), "GIMP"),
        (("zbrush", "sculpt"), "ZBrush"),
    ]
    for terms, label in explicit:
        if any(term in lower for term in terms):
            return label
    return active_dcc or "Unreal Engine 5"


def classify_3d_task(task_prompt: str) -> str:
    """Map a broad 3D prompt to a teachable workflow category."""
    lower = str(task_prompt or "").lower()
    categories = [
        ("camera_settings", ("camera", "lens", "focal length", "fov", "field of view", "aperture", "depth of field", "dof", "focus distance", "shutter", "iso", "filmback", "safe frame", "matchmove", "camera track", "lens distortion")),
        ("lighting", ("light", "shadow", "lumen", "hdr", "exposure", "rim light", "key light", "fill light")),
        ("mocap", ("metahuman", "mocap", "motion capture", "facial", "face tracking", "live link", "video")),
        ("uv_texturing", ("uv", "unwrap", "texture", "texel", "pbr", "substance", "material", "bake", "normal map")),
        ("modeling", ("model", "mesh", "topology", "retopo", "bevel", "extrude", "sculpt", "edge loop")),
        ("rigging_animation", ("rig", "skin", "weight", "animation", "keyframe", "control rig", "ik", "fk")),
        ("procedural", ("geometry node", "procedural", "houdini", "vex", "sop", "hda", "node graph")),
        ("rendering", ("render", "camera", "composition", "depth of field", "focal length", "cinematic", "viewport")),
    ]
    for category, terms in categories:
        if any(term in lower for term in terms):
            return category
    return "general_3d"


def _build_steps_for_category(category: str, task_prompt: str, dcc: str) -> list[WalkthroughStep]:
    if category == "camera_settings":
        return [
            WalkthroughStep(1, "Lock Output and Framing", f"In {dcc}, set the delivery resolution/aspect, enable safe frame or film gate overlays, and frame the subject before changing lens settings.", "Camera work starts from the final crop because every lens, focus, and exposure choice is judged through that frame.", dcc),
            WalkthroughStep(2, "Choose Lens and Filmback", "Set focal length or FOV, then choose filmback/sensor size if the tool exposes it. Compare wide, normal, and longer lens reads before committing.", "Focal length and filmback control perspective distortion, lens compression, and how much environment context the viewer sees.", dcc),
            WalkthroughStep(3, "Set Focus, Aperture, and Exposure", "Set focus distance on the subject, tune aperture/depth of field, then adjust exposure, ISO, shutter, or motion blur only after the composition is readable.", "Focus and exposure settings guide attention, but they can also hide important forms or break tracking if pushed too far.", dcc),
            WalkthroughStep(4, "Validate the Shot or Plate", "Scrub or preview the camera view and check crop, clipping, jitter, motion blur, highlight clipping, shadow crushing, and whether the settings are recorded for later matchmove or render work.", "A camera setup is finished when it is reproducible, readable, and stable in the final shot context.", dcc),
        ]
    if category == "lighting":
        return [
            WalkthroughStep(1, "Define the Shot Goal", f"In {dcc}, frame the subject and decide where the main light should appear to come from.", "Lighting choices should support form, mood, and readability before you start changing intensities.", dcc),
            WalkthroughStep(2, "Place the Key Light", "Add the primary light and rotate it about 30-45 degrees off the camera axis, then tune intensity until the subject reads clearly.", "The key light establishes the dominant shadow direction and the viewer's first read of the form.", dcc, "cmds.ls(type='light')" if "maya" in dcc.lower() else ""),
            WalkthroughStep(3, "Balance Fill and Rim", "Add a weaker fill light on the shadow side, then add a back or rim light only if the silhouette needs separation.", "Fill controls contrast, while rim light separates the subject from the background without flattening the setup.", dcc),
            WalkthroughStep(4, "Check the Render", "Preview the shot in the viewport or renderer and compare shadow softness, exposure, and silhouette clarity.", "A lighting pass is only successful when the final camera view communicates the intended shape and mood.", dcc),
        ]
    if category == "mocap":
        return [
            WalkthroughStep(1, "Prepare Clean Source Footage", "Collect the source video or capture take, confirm frame rate, and remove unusable sections before solving.", "Tracking quality depends heavily on stable, well-lit footage with visible facial or body landmarks.", dcc),
            WalkthroughStep(2, "Create the Tracking Asset", f"In {dcc}, create the appropriate identity, capture, or tracking asset and assign the target character or rig.", "The solver needs a mapping between source movement and the destination rig controls.", dcc),
            WalkthroughStep(3, "Solve and Review the Motion", "Run the solve, scrub the result, and mark frames where the expression, head pose, or body contact slips.", "Reviewing before export helps catch drift while it is still easy to correct.", dcc),
            WalkthroughStep(4, "Bake to Editable Animation", "Export or bake the solved result to a sequence, control rig, or animation clip, then save a named version.", "Baking turns solver output into animator-editable data that can be polished and reused.", dcc),
        ]
    if category == "uv_texturing":
        return [
            WalkthroughStep(1, "Inspect UVs and Scale", "Open the UV view and look for stretching, overlapping islands, inconsistent texel density, or tiny hidden shells.", "Texture quality starts with predictable UV space and even pixel distribution.", dcc),
            WalkthroughStep(2, "Fix Problem Islands", "Relax or unfold stretched islands, straighten hard-surface edges where useful, and add padding between shells.", "Clean UVs prevent smears, seams, and mipmap bleeding in the final material.", dcc),
            WalkthroughStep(3, "Bake or Rebuild Maps", "Bake normal, ambient occlusion, curvature, or ID maps after the UV changes, then inspect them at full resolution.", "Many PBR workflows depend on baked support maps that must match the final UV layout.", dcc),
            WalkthroughStep(4, "Validate in the Target Renderer", "Apply the material in the destination app and check the asset under neutral lighting.", "A texture pass should be judged in the same lighting and renderer where the asset will ship.", dcc),
        ]
    if category == "modeling":
        return [
            WalkthroughStep(1, "Block Out the Primary Forms", f"In {dcc}, create or isolate the base mesh and match the main proportions before adding detail.", "Strong primary forms make later topology and detail work easier to control.", dcc),
            WalkthroughStep(2, "Build Clean Supporting Topology", "Add loops, bevels, or retopology around deformation areas, silhouette edges, and material breaks.", "Topology should support shape, shading, deformation, and future editing.", dcc),
            WalkthroughStep(3, "Add Secondary Detail", "Layer in bevels, sculpt detail, trims, or surface variation after the broad forms are stable.", "Detail works best when it reinforces the readable forms instead of hiding weak structure.", dcc),
            WalkthroughStep(4, "Run a Shading and Scale Check", "Apply a neutral material, check normals, freeze transforms if appropriate, and compare scale against a known reference.", "Scale, normals, and shading errors are easiest to catch before rigging or texturing starts.", dcc),
        ]
    if category == "rigging_animation":
        return [
            WalkthroughStep(1, "Identify the Motion Requirement", "List the controls, bones, or deforming regions involved and test the current neutral pose.", "Good rigging and animation starts from the specific deformation or motion the shot needs.", dcc),
            WalkthroughStep(2, "Set Up Controls or Key Poses", "Create the required controls or keyframes, then pose the main extremes before polishing in-betweens.", "Extremes define the readable intent of an animation or rig behavior.", dcc),
            WalkthroughStep(3, "Check Deformation and Timing", "Scrub the timeline and inspect joints, skin weights, arcs, contact points, and interpolation.", "Most animation issues reveal themselves in motion, not in a single static frame.", dcc),
            WalkthroughStep(4, "Bake or Publish a Clean Version", "Save a versioned clip, control rig change, or exported animation after the validation pass.", "Versioned output makes the work reviewable and recoverable.", dcc),
        ]
    if category == "procedural":
        return [
            WalkthroughStep(1, "Define Inputs and Outputs", "Write down the parameters the procedural setup should expose and the geometry or material it should produce.", "Procedural systems are easier to learn when each control has a clear purpose.", dcc),
            WalkthroughStep(2, "Build the Minimal Node Chain", "Create the smallest node graph that produces the core result before adding variation or polish.", "A simple working graph gives you a stable mental model of data flow.", dcc),
            WalkthroughStep(3, "Add Controls and Constraints", "Expose useful parameters, clamp dangerous values, and name nodes or groups by their job.", "Good controls make procedural tools reusable instead of mysterious.", dcc),
            WalkthroughStep(4, "Test Edge Cases", "Try small, large, empty, and oddly shaped inputs, then fix graph assumptions that break.", "Procedural work needs validation across input ranges, not just the happy path.", dcc),
        ]
    if category == "rendering":
        return [
            WalkthroughStep(1, "Lock the Camera Read", "Set the camera, focal length, composition, and output aspect before judging materials or lighting.", "The final camera controls what the viewer actually sees.", dcc),
            WalkthroughStep(2, "Set Baseline Render Settings", "Choose renderer, resolution, samples, exposure, color management, and anti-aliasing settings.", "Stable render settings make visual comparisons meaningful.", dcc),
            WalkthroughStep(3, "Preview and Diagnose", "Render a small preview and inspect noise, clipping, material response, silhouettes, and depth cues.", "A diagnostic preview helps you improve the image without waiting for full-quality renders.", dcc),
            WalkthroughStep(4, "Render and Compare", "Render the final view and compare it against the goal or reference before publishing.", "The final pass should be evaluated against the original visual intention.", dcc),
        ]
    return [
        WalkthroughStep(1, "Clarify the 3D Goal", f"In {dcc}, identify the target asset, scene, shot, or tool output involved in the request.", "A clear target prevents accidental changes and helps you choose the right workflow.", dcc),
        WalkthroughStep(2, "Break the Work into a Small Test", "Create a low-risk duplicate, sandbox scene, or isolated selection where you can try the first operation.", "Learning is faster when experiments are reversible and scoped.", dcc),
        WalkthroughStep(3, "Apply the Core Operation", "Perform the main workflow step manually, watching which parameters change and what the viewport result looks like.", "The important learning comes from connecting controls to visible results.", dcc),
        WalkthroughStep(4, "Verify and Save a Version", "Check the result from the final camera or target app, then save a named version before continuing.", "Verification and versioning turn a one-off attempt into a repeatable workflow.", dcc),
    ]


def get_educational_resources_for_task(task_prompt: str, target_dcc: str = "") -> list[EducationalResourceLink]:
    """Return optional learning resources for a 3D task."""
    clean_prompt = strip_tutorial_directive(task_prompt)
    dcc = detect_target_dcc(clean_prompt, target_dcc)
    category = classify_3d_task(clean_prompt)
    resources: list[EducationalResourceLink] = []

    app_resources = {
        "Unreal Engine 5": EducationalResourceLink("Unreal Engine Documentation", "https://dev.epicgames.com/documentation/en-us/unreal-engine", "Official Docs", "Core editor, rendering, animation, and asset workflows."),
        "Autodesk Maya": EducationalResourceLink("Autodesk Maya Help", "https://help.autodesk.com/view/MAYAUL/2026/ENU/", "Official Docs", "Modeling, animation, rigging, lighting, and rendering reference."),
        "Blender": EducationalResourceLink("Blender Manual", "https://docs.blender.org/manual/en/latest/", "Official Docs", "Modeling, geometry nodes, animation, materials, and rendering reference."),
        "Houdini": EducationalResourceLink("SideFX Houdini Documentation", "https://www.sidefx.com/docs/houdini/", "Official Docs", "SOPs, VEX, HDAs, simulation, and rendering reference."),
        "Substance 3D Painter": EducationalResourceLink("Substance 3D Painter Documentation", "https://helpx.adobe.com/substance-3d-painter/home.html", "Official Docs", "Painting, baking, materials, and export workflows."),
        "Adobe Photoshop": EducationalResourceLink("Adobe Photoshop User Guide", "https://helpx.adobe.com/photoshop/user-guide.html", "Official Docs", "Layer, mask, color, and texture editing workflows."),
        "GIMP": EducationalResourceLink("GIMP Documentation", "https://docs.gimp.org/", "Official Docs", "Image editing, masks, channels, and texture preparation."),
        "ZBrush": EducationalResourceLink("Maxon ZBrush Documentation", "https://help.maxon.net/zbr/en-us/", "Official Docs", "Digital sculpting, brushes, subdivision, and export workflows."),
    }
    if dcc in app_resources:
        resources.append(app_resources[dcc])

    topic_resources = {
        "lighting": [
            EducationalResourceLink("Unreal Engine Lighting the Environment", "https://dev.epicgames.com/documentation/en-us/unreal-engine/lighting-the-environment-in-unreal-engine", "Official Docs", "Light types, exposure, shadows, and environment lighting."),
            EducationalResourceLink("Confluence Maya and UE Light Rig Spec", "@confluence.DOC-102", "Confluence Page", "Studio lighting standards and key-to-fill ratios."),
        ],
        "camera_settings": [
            EducationalResourceLink("Unreal Engine Cameras Documentation", "https://dev.epicgames.com/documentation/en-us/unreal-engine/cameras-in-unreal-engine", "Official Docs", "Cine cameras, camera actors, lens settings, and camera workflows."),
            EducationalResourceLink("Blender Camera Manual", "https://docs.blender.org/manual/en/latest/render/cameras.html", "Official Docs", "Lens, sensor, depth of field, clipping, safe areas, and camera display settings."),
            EducationalResourceLink("Confluence Camera and Matchmove Checklist", "@confluence.DOC-112", "Confluence Page", "Studio shot camera settings, plate validation, lens notes, and matchmove handoff checks."),
        ],
        "mocap": [
            EducationalResourceLink("MetaHuman Animator Documentation", "https://dev.epicgames.com/documentation/en-us/metahuman/metahuman-animator", "Official Docs", "Capture sources, identity setup, solving, and animation export."),
            EducationalResourceLink("Unreal Live Link Documentation", "https://dev.epicgames.com/documentation/en-us/unreal-engine/live-link-in-unreal-engine", "Official Docs", "Streaming animation data into Unreal Engine."),
            EducationalResourceLink("Confluence Video Mocap Guide", "@confluence.DOC-111", "Confluence Page", "Video ingestion, facial blendshape extraction, Live Link, FBX, and BVH notes."),
        ],
        "uv_texturing": [
            EducationalResourceLink("Substance 3D Painter Baking", "https://helpx.adobe.com/substance-3d-painter/baking.html", "Official Docs", "Mesh maps, bake settings, and common texture troubleshooting."),
            EducationalResourceLink("Confluence Substance and PBR Export Guide", "@confluence.DOC-108", "Confluence Page", "Layer stack automation and channel packing for game engines."),
        ],
        "modeling": [
            EducationalResourceLink("Blender Modeling Manual", "https://docs.blender.org/manual/en/latest/modeling/index.html", "Official Docs", "Mesh editing, modifiers, curves, and topology workflows."),
            EducationalResourceLink("Autodesk Maya Modeling Help", "https://help.autodesk.com/view/MAYAUL/2026/ENU/?guid=GUID-7941F97A-36E8-47FE-95D1-71412A3B3017", "Official Docs", "Polygon modeling, topology, and mesh cleanup reference."),
        ],
        "rigging_animation": [
            EducationalResourceLink("Unreal Engine Animation Documentation", "https://dev.epicgames.com/documentation/en-us/unreal-engine/animating-characters-and-objects-in-unreal-engine", "Official Docs", "Sequencer, Control Rig, animation Blueprints, and retargeting."),
            EducationalResourceLink("Autodesk Maya Animation Help", "https://help.autodesk.com/view/MAYAUL/2026/ENU/?guid=GUID-Animation", "Official Docs", "Keyframing, graph editing, constraints, and rigging workflows."),
        ],
        "procedural": [
            EducationalResourceLink("Blender Geometry Nodes Manual", "https://docs.blender.org/manual/en/latest/modeling/geometry_nodes/index.html", "Official Docs", "Procedural node graphs, fields, and attributes."),
            EducationalResourceLink("SideFX VEX Documentation", "https://www.sidefx.com/docs/houdini/vex/", "Official Docs", "VEX language and wrangle workflows."),
            EducationalResourceLink("Confluence Houdini Guide", "@confluence.DOC-106", "Confluence Page", "HDA parameter binding and Karma rendering."),
        ],
        "rendering": [
            EducationalResourceLink("Unreal Engine Rendering Documentation", "https://dev.epicgames.com/documentation/en-us/unreal-engine/rendering-and-graphics-in-unreal-engine", "Official Docs", "Rendering, graphics features, post processing, and debugging."),
            EducationalResourceLink("Blender Rendering Manual", "https://docs.blender.org/manual/en/latest/render/index.html", "Official Docs", "Cycles, Eevee, cameras, lighting, and render settings."),
        ],
        "general_3d": [
            EducationalResourceLink("Confluence Technical Architecture Spec", "@confluence.DOC-101", "Confluence Page", "Studio pipeline standards and tool integration."),
        ],
    }
    resources.extend(topic_resources.get(category, topic_resources["general_3d"]))
    return _dedupe_resources(resources)


def _dedupe_resources(resources: list[EducationalResourceLink]) -> list[EducationalResourceLink]:
    seen = set()
    unique = []
    for resource in resources:
        key = resource.url_or_ref.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(resource)
    return unique[:4]


tutorial_service = TutorialModeService()
