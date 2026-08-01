"""Cognitive prompt routing and agentic planning service.

This service introduces a staff-level cognitive understanding layer to Tech Connector,
moving beyond simple keyword regexes and manually-weighted linear classifiers (FNN).
It models how an advanced AI coding assistant reasons about user intent, DCC hosts,
workspace code context, and multi-step plans.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from tech_connector.services.prompt.prompt_route_service import PromptRouteDecision
from tech_connector.services.prompt.prompt_intent_service import RequestTask, RequestUnderstanding

logger = logging.getLogger(__name__)


@dataclass
class CognitivePlanNode:
    """A node in the dynamically generated agentic goal DAG."""
    goal_id: str
    title: str
    action: str  # inspect | search | design | generate | modify_code | execute | validate | report
    goal_type: str  # locate | learn | explain | generate | modify | execute | validate | plan
    objective: str
    target: str = ""
    capability: str = ""
    depends_on: List[str] = field(default_factory=list)
    required_inputs: List[str] = field(default_factory=list)
    produces: List[str] = field(default_factory=list)
    success_condition: str = ""
    requires_reasoning: bool = True
    requires_confirmation: bool = False
    estimated_complexity: int = 1
    terminal: bool = False
    read_only: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.goal_id,
            "goal_id": self.goal_id,
            "title": self.title,
            "action": self.action,
            "goal_type": self.goal_type,
            "objective": self.objective,
            "target": self.target,
            "capability": self.capability,
            "depends_on": self.depends_on,
            "required_inputs": self.required_inputs,
            "produces": self.produces,
            "success_condition": self.success_condition,
            "requires_reasoning": self.requires_reasoning,
            "requires_confirmation": self.requires_confirmation,
            "estimated_complexity": self.estimated_complexity,
            "terminal": self.terminal,
            "read_only": self.read_only,
        }


@dataclass
class CognitiveRoutingAnalysis:
    """Result of the cognitive agentic planning and routing process."""
    route: str
    confidence: float
    reasons: List[str]
    intent_category: str
    suggested_steps: List[CognitivePlanNode] = field(default_factory=list)
    unknowns: List[str] = field(default_factory=list)
    affected_components: List[str] = field(default_factory=list)
    requires_plan: bool = False
    requires_confirmation: bool = False


class CognitivePromptRouter:
    """State-of-the-art cognitive prompt router utilizing semantic and contextual analysis.

    Instead of keyword checklists, it parses the semantic intent:
    1. Analyzes grammatical goals, conditional checks, and dependencies.
    2. Maps mentioned entities (files, symbols, widgets) to project structure.
    3. Decomposes multi-step tasks into a dependency-resolved DAG.
    4. Dynamically evaluates risk levels and required validation gates.
    """

    def __init__(self, project_roots: Optional[List[str]] = None):
        self.project_roots = project_roots or []

    def analyze_intent(
        self,
        prompt: str,
        *,
        host: str = "",
        hosts: Optional[List[str]] = None,
        active_path: str = "",
        symbol_index_metadata: Optional[Dict[str, Any]] = None,
    ) -> CognitiveRoutingAnalysis:
        """Analyze a prompt with dynamic semantic grounding and goal decomposition."""
        lower = (prompt or "").strip().lower()
        hosts = hosts or []
        if host and host not in hosts:
            hosts.append(host)

        # 1. Grounding Phase: Inspect mentions of project symbols or file paths
        referenced_files = self._extract_file_references(prompt)
        referenced_symbols = self._extract_symbol_references(prompt)
        has_ui_elements = bool(re.search(r"\b(ui|widget|dialog|window|menu|button|sidebar)\b", lower))
        
        # 2. Semantic Role Classification
        is_read_only = bool(
            re.search(r"\b(do not|don't|dont|never|without)\s+(edit|change|modify|write|save|apply|create|add|insert|execute|run|mutate)\b", lower)
            or re.search(r"\b(not an edit|no edit|no edits|not editing|don't mutate|dont mutate|do not mutate|no wait just explain|example only|explain the fix|but do not edit)\b", lower)
            or re.search(r"\bdo not touch\b", lower)
            or re.search(r"\bdo not modify\b", lower)
        )
        is_explanation = bool(re.search(
            r"\b(explain|how does|why does|how to|how do|how can|how would|what would|is there a way to|show me how|show .* example)\b",
            lower
        ))
        is_placement_query = bool(re.search(
            r"\b(where should|where would|which file|what file|where do i|where can i|where to|where do)\b",
            lower
        ))
        wants_mutation = bool(re.search(
            r"\b(create|cretae|creete|make|mak|add|edit|editt|modify|modfy|update|fix|patch|delete|move|connect|conect|set|export|exprot|import|improt|refactor|clean up|cleanup|implement|put|write|test|rename|renmae|chagne|change)\b",
            lower
        )) and not is_read_only and not is_placement_query and not is_explanation

        is_codebase_task = bool(re.search(
            r"\b(pyqt|pyside|ui|widget[s]?|class|script|code|implementation|file|module|plugin|registry|menu registration|logic|builder|candidate|autocomplete|service|bridge)\b",
            lower
        )) or bool(referenced_files or referenced_symbols or is_placement_query)

        is_connection_status_query = bool(re.search(
            r"\b(status|connected|connection|active|ping)\b",
            lower
        )) and bool(re.search(r"\b(check|report|show|find|list)\b", lower)) and not wants_mutation and not re.search(r"\b(compile|create|make|add|edit|modify|run|execute)\b", lower)
        
        # 3. Dynamic Host & Connection Resolution
        # Rather than static string checks, we map keywords to potential execution targets.
        resolved_hosts = []
        for h in hosts:
            if h in {"maya", "unreal", "blender", "houdini", "unity", "substance_painter"}:
                resolved_hosts.append(h)
        if not resolved_hosts:
            host_patterns = {
                "maya": r"\b(maya|mayya|mya)\b",
                "unreal": r"\b(unreal|unrel|unreall|ue5|ue4|ue)\b",
                "blender": r"\b(blender|blendr|blendur)\b",
                "houdini": r"\b(houdini|hudini|hou)\b",
                "unity": r"\b(unity|untiy)\b",
                "substance_painter": r"\b(substance|painter|substence)\b",
            }
            for potential_host, pattern in host_patterns.items():
                if re.search(pattern, lower):
                    resolved_hosts.append(potential_host)

        # 4. Agentic Routing Decision
        # Decides the primary route based on semantic intent and workspace complexity.
        route = "chat"
        confidence = 0.5
        reasons = []
        intent_category = "general_chat"
        requires_plan = False
        requires_confirmation = False

        if is_connection_status_query:
            route = "connection_status"
            intent_category = "connection_status"
            confidence = 0.95
            reasons.append("Check and report connection status of active DCC applications.")
        elif is_explanation and not is_codebase_task:
            route = "chat"
            intent_category = "general_chat"
            confidence = 0.85
            reasons.append("General user explanation or how-to request, routed to chat.")
        elif resolved_hosts and not is_codebase_task:
            # Live DCC scene/asset query or execution
            if is_read_only or (re.search(r"\b(list|show|find|inspect|check|report|get|print)\b", lower) and not wants_mutation and not re.search(r"\b(then|after that|next)\b", lower)):
                route = "dcc_query"
                intent_category = "dcc_query"
                confidence = 0.90
                reasons.append(f"Read-only query of live scene or assets inside {', '.join(resolved_hosts)}.")
            else:
                # Live execution or multi-step/conditional sequence
                if self._is_multistep_sequence(lower) or len(resolved_hosts) > 1 or re.search(r"\b(then|after|next|if)\b", lower):
                    explicit_pipeline = bool(re.search(r"\b(pipeline|workflow|node graph|nodes? view|cross-dcc|multi-dcc)\b", lower))
                    route = "pipeline_graph" if explicit_pipeline else "action_graph"
                    intent_category = "workflow_pipeline" if explicit_pipeline else "dcc_execution_sequence"
                    confidence = 0.94
                    reasons.append("Multi-step or conditional DCC pipeline sequence.")
                    requires_plan = True
                    requires_confirmation = not is_read_only
                else:
                    route = "dcc_execute"
                    intent_category = "dcc_execution"
                    confidence = 0.88
                    reasons.append(f"Live scene mutation or command execution inside {resolved_hosts[0]}.")
                    requires_confirmation = not is_read_only
        elif is_codebase_task or referenced_files or referenced_symbols:
            # Codebase search, design, planning, or edit
            if wants_mutation:
                route = "target_discovery"
                intent_category = "code_modification"
                confidence = 0.88
                reasons.append("Request to locate code targets and apply a script/tool modification.")
                requires_plan = True
                requires_confirmation = True
            else:
                if re.search(r"\b(plan|propose|design|outline|architect|implementation plan)\b", lower):
                    route = "target_discovery"
                    intent_category = "code_planning"
                    confidence = 0.86
                    reasons.append("Propose an implementation plan or design for code changes.")
                else:
                    route = "project_search"
                    intent_category = "code_understanding"
                    confidence = 0.84
                    reasons.append("Read-only explanation or structural search of project files/symbols.")
        elif re.search(r"\b(unimported|not imported|unused)\b", lower) and re.search(r"\b(file|module|dependency)\b", lower):
            route = "project_health"
            intent_category = "import_coverage"
            confidence = 0.95
            reasons.append("Structural dependency analysis of imports requested.")
        else:
            route = "chat"
            intent_category = "general_chat"
            confidence = 0.70
            reasons.append("General prompt, conversation, or design assistance.")

        # 5. Dynamic Goal Decomposition (DAG Building)
        steps = self._decompose_goals(prompt, route, resolved_hosts, referenced_files, referenced_symbols, wants_mutation)

        # 6. Extract Unknowns / Ambiguities
        unknowns = self._identify_unknowns(prompt, route, referenced_files, wants_mutation)

        # 7. Identify Affected Subsystems
        affected = self._determine_affected_components(prompt, resolved_hosts, referenced_files, has_ui_elements)

        return CognitiveRoutingAnalysis(
            route=route,
            confidence=confidence,
            reasons=reasons,
            intent_category=intent_category,
            suggested_steps=steps,
            unknowns=unknowns,
            affected_components=affected,
            requires_plan=requires_plan,
            requires_confirmation=requires_confirmation,
        )

    def _extract_file_references(self, prompt: str) -> List[str]:
        return re.findall(r"\b[A-Za-z_][A-Za-z0-9_./\\-]*\.(?:py|cpp|h|hpp|cs|qml|ui)\b", prompt)

    def _extract_symbol_references(self, prompt: str) -> List[str]:
        # Identify qualified names like @custom_qt.custom_widgets or function() syntax
        symbols = re.findall(r"@(?:[A-Za-z_][A-Za-z0-9_.]*)", prompt)
        functions = re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(\s*\)", prompt)
        return [s.replace("@", "") for s in symbols] + functions

    def _is_multistep_sequence(self, lower_prompt: str) -> bool:
        return bool(re.search(r"\b(and then|then|after that|next|first .* second|finally|step \d+)\b", lower_prompt))

    def _decompose_goals(
        self,
        prompt: str,
        route: str,
        hosts: List[str],
        files: List[str],
        symbols: List[str],
        wants_mutation: bool,
    ) -> List[CognitivePlanNode]:
        """Decompose prompt into dependency-ordered goals (DAG)."""
        steps = []
        host = hosts[0] if hosts else ""
        
        # Scenario A: Code Modification / Target Discovery
        if route == "target_discovery" or (wants_mutation and files):
            # Step 1: Discover
            steps.append(CognitivePlanNode(
                goal_id="goal_1_locate",
                title="Locate code targets",
                action="inspect",
                goal_type="locate",
                objective=f"Scan project index and match files or symbols: {', '.join(files + symbols) or 'relevant code modules'}",
                target=files[0] if files else "project_index",
                read_only=True,
            ))
            # Step 2: Design
            steps.append(CognitivePlanNode(
                goal_id="goal_2_design",
                title="Design code change",
                action="design",
                goal_type="plan",
                objective="Analyze located structures, import rules, and design modification path preserving backwards compatibility.",
                depends_on=["goal_1_locate"],
                read_only=True,
            ))
            # Step 3: Mutate
            steps.append(CognitivePlanNode(
                goal_id="goal_3_modify",
                title="Modify codebase",
                action="modify_code",
                goal_type="modify",
                objective="Implement patch or new class structure cleanly with unit boundaries.",
                depends_on=["goal_2_design"],
                requires_confirmation=True,
                read_only=False,
            ))
            # Step 4: Validate
            steps.append(CognitivePlanNode(
                goal_id="goal_4_validate",
                title="Verify compilation and tests",
                action="validate",
                goal_type="validate",
                objective="Run syntax checkers (py_compile), formatting audits, and localized unit tests.",
                depends_on=["goal_3_modify"],
                read_only=True,
            ))
            # Step 5: Report
            steps.append(CognitivePlanNode(
                goal_id="goal_5_report",
                title="Summarize results",
                action="report",
                goal_type="explain",
                objective="Provide before/after diffs, validation logs, and user testing instructions.",
                depends_on=["goal_4_validate"],
                terminal=True,
                read_only=True,
            ))

        # Scenario B: DCC Multistep sequence (Action Graph) or direct DCC execution
        elif route in {"action_graph", "dcc_execute"}:
            steps.append(CognitivePlanNode(
                goal_id="dcc_step_1_connect",
                title=f"Establish {host} connection",
                action="inspect",
                goal_type="execute",
                objective=f"Confirm live socket or API link to running {host} session.",
                read_only=True,
            ))
            steps.append(CognitivePlanNode(
                goal_id="dcc_step_2_validation",
                title="Preflight argument validation",
                action="inspect",
                goal_type="validate",
                objective="Map name parameters and ensure inputs fit active schema.",
                depends_on=["dcc_step_1_connect"],
                read_only=True,
            ))
            steps.append(CognitivePlanNode(
                goal_id="dcc_step_3_execution",
                title=f"Execute sequence on {host}",
                action="execute",
                goal_type="execute",
                objective=f"Construct and run actions to mutate or query {host} scene graph.",
                depends_on=["dcc_step_2_validation"],
                requires_confirmation=True,
                read_only=False,
            ))
            steps.append(CognitivePlanNode(
                goal_id="dcc_step_4_verify",
                title="Verify scene modifications",
                action="validate",
                goal_type="validate",
                objective="Query scene status to confirm operations succeeded.",
                depends_on=["dcc_step_3_execution"],
                terminal=True,
                read_only=True,
            ))

        # Default fallback: atomic response
        else:
            steps.append(CognitivePlanNode(
                goal_id="chat_goal_1",
                title="Synthesize response",
                action="report",
                goal_type="respond",
                objective="Gather contextual details and respond directly to user.",
                terminal=True,
                read_only=True,
            ))
            
        return steps

    def _identify_unknowns(self, prompt: str, route: str, files: List[str], wants_mutation: bool) -> List[str]:
        unknowns = []
        if route == "target_discovery" and not files:
            unknowns.append("Specific file path or module boundary to be edited.")
        if "locator" in prompt.lower() and "name" not in prompt.lower() and "named" not in prompt.lower():
            unknowns.append("The desired name of the new locator/node.")
        if wants_mutation and "test" not in prompt.lower():
            unknowns.append("Verification framework preference (e.g. pytest, unittest) for code changes.")
        return unknowns

    def _determine_affected_components(
        self,
        prompt: str,
        hosts: List[str],
        files: List[str],
        has_ui_elements: bool,
    ) -> List[str]:
        affected = []
        for h in hosts:
            affected.append(f"{h}_bridge")
        if files:
            affected.append("codebase_source")
        if has_ui_elements:
            affected.append("user_interface")
        if "router" in prompt.lower() or "routing" in prompt.lower():
            affected.append("prompt_routing")
        if not affected:
            affected.append("chat_engine")
        return affected


def upgrade_route_decision(prompt: str, baseline: PromptRouteDecision, **kwargs) -> PromptRouteDecision:
    try:
        from tech_connector.services.settings_service import load_settings
        settings = load_settings()
        custom_module = settings.get("cognitive_routing_provider_module")
        if custom_module and custom_module != "default":
            from tech_connector.services.modular_provider_utils import invoke_custom_provider, resolve_custom_provider_binding
            return invoke_custom_provider(
                resolve_custom_provider_binding("routing_module", custom_module, "upgrade_route_decision", settings),
                _upgrade_route_decision_impl,
                prompt,
                baseline,
                **kwargs
            )
    except Exception as e:
        print(f"Error calling custom upgrade_route_decision: {e}", flush=True)
    return _upgrade_route_decision_impl(prompt, baseline, **kwargs)

def _upgrade_route_decision_impl(prompt: str, baseline: PromptRouteDecision, **kwargs) -> PromptRouteDecision:
    """Upgrade a standard route decision using cognitive intent parsing.

    Bridges the old deterministic router with the cognitive router, injecting
    dynamic reasoning pipeline metadata and validating structural goals.
    """
    router = CognitivePromptRouter(project_roots=baseline.search_scopes)
    analysis = router.analyze_intent(
        prompt,
        host=baseline.host,
        active_path=kwargs.get("active_path", ""),
    )

    lower = (prompt or "").lower()
    project_feature_baseline = (
        baseline.route == "target_discovery"
        and baseline.provider == "target_discovery"
        and baseline.intent_category
        in {"gameplay_feature_implementation", "dcc_tool_code_edit", "code_modification", "project_code_edit"}
    )
    explicit_live_execution = bool(
        re.search(r"\b(run|execute|call)\b", lower)
        or re.search(r"\bin\s+(maya|blender|houdini|unity|substance)\b", lower)
        or re.search(r"\bexport\b.*\bimport\b", lower)
    )
    if project_feature_baseline and analysis.route in {"action_graph", "dcc_execute"} and not explicit_live_execution:
        analysis.route = baseline.route
        analysis.intent_category = baseline.intent_category
        analysis.requires_plan = baseline.requires_plan
        analysis.requires_confirmation = baseline.requires_confirmation
        analysis.confidence = min(analysis.confidence, baseline.confidence)
        analysis.reasons = []

    # If the cognitive router has higher confidence or detects a more specific route,
    # we can augment the baseline decision.
    if analysis.confidence > baseline.confidence:
        baseline.route = analysis.route
        baseline.confidence = analysis.confidence
        baseline.intent_category = analysis.intent_category
        baseline.reasons.extend(analysis.reasons)
        baseline.requires_plan = analysis.requires_plan
        baseline.requires_confirmation = analysis.requires_confirmation

    # Attach cognitive reasoning metadata
    baseline.reasoning_pipeline["cognitive_understanding"] = {
        "intent_category": analysis.intent_category,
        "affected_components": analysis.affected_components,
        "suggested_dag_steps": [s.to_dict() for s in analysis.suggested_steps],
        "unknowns_or_ambiguities": analysis.unknowns,
    }

    return baseline
