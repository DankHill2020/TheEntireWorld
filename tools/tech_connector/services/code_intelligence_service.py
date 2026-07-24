"""IDE-style code intelligence facade for project prompts.

This service is the deterministic front door before model synthesis. It gathers
symbol facts, usages, repo-map context, validation candidates, and sufficiency
signals from existing Tech Connector services.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_FIRST_PARTY_PACKAGES = (
    "agents",
    "app",
    "bridges",
    "dcc_intelligence",
    "editor",
    "engine",
    "knowledge",
    "models",
    "project_analysis",
    "router",
    "services",
    "ui",
)


def _top_level_import_targets(tree: ast.Module, current_module: str) -> set[str]:
    """Return imports that execute while a module is being initialized."""

    targets: set[str] = set()

    def is_main_guard(test: ast.expr) -> bool:
        return (
            isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name)
            and test.left.id == "__name__"
            and len(test.ops) == 1
            and isinstance(test.ops[0], ast.Eq)
            and len(test.comparators) == 1
            and isinstance(test.comparators[0], ast.Constant)
            and test.comparators[0].value == "__main__"
        )

    def visit(statements: list[ast.stmt]) -> None:
        for statement in statements:
            if isinstance(statement, ast.Import):
                targets.update(alias.name for alias in statement.names)
            elif isinstance(statement, ast.ImportFrom):
                if statement.level:
                    parts = current_module.split(".")
                    base = parts[: max(0, len(parts) - statement.level)]
                    module = ".".join([*base, statement.module or ""]).strip(".")
                else:
                    module = statement.module or ""
                if module:
                    targets.add(module)
                    targets.update(
                        f"{module}.{alias.name}"
                        for alias in statement.names
                        if alias.name != "*"
                    )
            elif isinstance(statement, ast.If):
                is_type_checking = (
                    isinstance(statement.test, ast.Name)
                    and statement.test.id == "TYPE_CHECKING"
                ) or (
                    isinstance(statement.test, ast.Attribute)
                    and statement.test.attr == "TYPE_CHECKING"
                )
                if not is_type_checking and not is_main_guard(statement.test):
                    visit(statement.body)
                    visit(statement.orelse)
            elif isinstance(statement, (ast.Try, ast.TryStar)):
                visit(statement.body)
                for handler in statement.handlers:
                    visit(handler.body)
                visit(statement.orelse)
                visit(statement.finalbody)

    visit(tree.body)
    return targets


def _build_import_graph(module_trees: dict[str, ast.Module]) -> dict[str, set[str]]:
    """Build first-party import edges, resolving symbols to owning modules."""

    known_modules = set(module_trees)
    graph: dict[str, set[str]] = {module: set() for module in known_modules}
    for module, tree in module_trees.items():
        for imported in _top_level_import_targets(tree, module):
            candidate = imported
            while candidate and candidate not in known_modules:
                candidate = candidate.rsplit(".", 1)[0] if "." in candidate else ""
            if candidate and candidate != module:
                graph[module].add(candidate)
    return graph


def _find_import_cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    """Find deterministic directed cycles in a module import graph."""

    state: dict[str, int] = {}
    stack: list[str] = []
    positions: dict[str, int] = {}
    cycles: dict[tuple[str, ...], list[str]] = {}

    def canonical(nodes: list[str]) -> tuple[str, ...]:
        rotations = [tuple(nodes[index:] + nodes[:index]) for index in range(len(nodes))]
        return min(rotations)

    def visit(module: str) -> None:
        state[module] = 1
        positions[module] = len(stack)
        stack.append(module)
        for imported in sorted(graph.get(module, ())):
            if state.get(imported, 0) == 0:
                visit(imported)
            elif state.get(imported) == 1:
                nodes = stack[positions[imported]:]
                if nodes:
                    cycles.setdefault(canonical(nodes), nodes)
        stack.pop()
        positions.pop(module, None)
        state[module] = 2

    for module in sorted(graph):
        if state.get(module, 0) == 0:
            visit(module)
    return [cycles[key] for key in sorted(cycles)]


def audit_python_package_layout(
    project_root: str | Path,
    *,
    package_name: str = "tech_connector",
    first_party_packages: tuple[str, ...] = DEFAULT_FIRST_PARTY_PACKAGES,
) -> dict[str, Any]:
    """Audit first-party imports and stale paths for a relocatable package.

    This is the reusable project-intelligence form of the checks used during a
    package move. It parses imports with the AST and reports source files that
    cannot be parsed instead of silently skipping them.
    """
    root = Path(project_root).expanduser().resolve()
    package_root = root / package_name if (root / package_name).is_dir() else root
    ignored_dirs = {
        ".ai_studio",
        ".git",
        ".index_backups",
        ".pytest_cache",
        ".venv",
        "__pycache__",
        "data",
        "installers",
        "node_modules",
    }
    unqualified_imports: list[dict[str, Any]] = []
    stale_paths: list[dict[str, Any]] = []
    legacy_compatibility_refs: list[dict[str, Any]] = []
    parse_errors: list[dict[str, Any]] = []
    module_trees: dict[str, ast.Module] = {}
    module_paths: dict[str, str] = {}
    personal_references: list[dict[str, Any]] = []
    hardcoded_user_paths: list[dict[str, Any]] = []
    legacy_marker = "/the_entire_world_ai_studio"

    for path in package_root.rglob("*.py"):
        if any(part in ignored_dirs for part in path.parts):
            continue
        if "tests" in path.relative_to(package_root).parts:
            continue
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(path))
        except (OSError, SyntaxError) as exc:
            parse_errors.append({"path": str(path), "error": str(exc)})
            continue
        relative_path = path.relative_to(package_root)
        relative = str(relative_path)
        module_parts = list(relative_path.with_suffix("").parts)
        if module_parts and module_parts[-1] == "__init__":
            module_parts.pop()
        module_name = ".".join((package_name, *module_parts))
        module_trees[module_name] = tree
        module_paths[module_name] = str(path)
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules.append(node.module)
            elif isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            for module in modules:
                root_name = module.split(".", 1)[0]
                if root_name in first_party_packages:
                    unqualified_imports.append(
                        {"path": str(path), "relative_path": relative, "line": node.lineno, "module": module}
                    )
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                normalized = node.value.replace("\\", "/").lower()
                if legacy_marker in normalized:
                    finding = {
                        "path": str(path),
                        "relative_path": relative,
                        "line": node.lineno,
                        "value": node.value,
                    }
                    if normalized == legacy_marker:
                        legacy_compatibility_refs.append(finding)
                    else:
                        stale_paths.append(finding)

    import_graph = _build_import_graph(module_trees)
    circular_imports = [
        {"modules": cycle, "paths": [module_paths[module] for module in cycle]}
        for cycle in _find_import_cycles(import_graph)
    ]

    text_extensions = {".bat", ".cfg", ".ini", ".json", ".jsonl", ".md", ".py", ".toml", ".txt", ".yaml", ".yml"}
    current_user = Path.home().name.lower()
    user_home_segment = ":/" + "users/"
    for path in package_root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in text_extensions:
            continue
        if any(part in ignored_dirs for part in path.parts):
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        relative = str(path.relative_to(package_root))
        for line_number, line in enumerate(lines, start=1):
            normalized = line.replace("\\", "/").lower()
            finding = {"path": str(path), "relative_path": relative, "line": line_number}
            if current_user and current_user in normalized:
                personal_references.append(finding)
            if user_home_segment in normalized:
                hardcoded_user_paths.append(finding)

    return {
        "ok": not unqualified_imports and not stale_paths and not parse_errors and not circular_imports and not personal_references and not hardcoded_user_paths,
        "project_root": str(root),
        "package_root": str(package_root),
        "package_name": package_name,
        "unqualified_imports": unqualified_imports,
        "stale_paths": stale_paths,
        "legacy_compatibility_refs": legacy_compatibility_refs,
        "parse_errors": parse_errors,
        "circular_imports": circular_imports,
        "module_count": len(module_trees),
        "import_edge_count": sum(len(edges) for edges in import_graph.values()),
        "personal_references": personal_references,
        "hardcoded_user_paths": hardcoded_user_paths,
    }


def analyze_service_cleanup_candidates(
    project_root: str | Path,
    *,
    package_name: str = "tech_connector",
    service_package: str = "services",
    oversized_line_count: int = 1200,
) -> dict[str, Any]:
    """Find evidence-backed service cleanup and consolidation candidates.

    Results are advisory. A module is a dead-code review candidate only when no
    runtime service imports it and no Python source or test contains its full
    module path. Callers must still check entry points, generated configs, and
    external consumers before deletion. Consolidation candidates are ranked by
    direct dependency, shared callers, naming, documentation, and combined size.
    """

    root = Path(project_root).expanduser().resolve()
    package_root = root / package_name if (root / package_name).is_dir() else root
    services_root = package_root / service_package
    ignored_dirs = {".ai_studio", ".git", ".index_backups", ".pytest_cache", ".venv", "__pycache__", "data", "node_modules"}
    if not services_root.is_dir():
        return {
            "ok": False,
            "project_root": str(root),
            "services_root": str(services_root),
            "error": "Service package was not found.",
            "modules": [],
            "dead_code_candidates": [],
            "consolidation_candidates": [],
            "related_groups": [],
            "folder_candidates": [],
            "existing_folder_moves": [],
            "oversized_modules": [],
            "circular_imports": [],
            "parse_errors": [],
        }

    all_sources: dict[Path, str] = {}
    for path in package_root.rglob("*.py"):
        if any(part in ignored_dirs for part in path.parts):
            continue
        try:
            all_sources[path] = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

    module_trees: dict[str, ast.Module] = {}
    module_paths: dict[str, Path] = {}
    module_sources: dict[str, str] = {}
    parse_errors: list[dict[str, str]] = []
    for path in sorted(services_root.glob("*.py")):
        if path.name == "__init__.py":
            continue
        module_name = f"{package_name}.{service_package}.{path.stem}"
        source = all_sources.get(path, "")
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            parse_errors.append({"path": str(path), "error": str(exc)})
            continue
        module_trees[module_name] = tree
        module_paths[module_name] = path
        module_sources[module_name] = source

    graph = _build_import_graph(module_trees)
    inbound: dict[str, set[str]] = {module: set() for module in module_trees}
    for caller, imports in graph.items():
        for imported in imports:
            if imported in inbound:
                inbound[imported].add(caller)

    stop_terms = {
        "and", "for", "from", "into", "module", "service", "services", "that",
        "the", "this", "with", "tech", "connector", "user", "users",
    }

    def words(value: str) -> set[str]:
        return {
            token for token in re.findall(r"[a-z][a-z0-9]+", value.lower())
            if len(token) >= 3 and token not in stop_terms
        }

    records: dict[str, dict[str, Any]] = {}
    for module, tree in module_trees.items():
        path = module_paths[module]
        source = module_sources[module]
        public_symbols = [
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and not node.name.startswith("_")
        ]
        external_references = [
            str(candidate)
            for candidate, candidate_source in all_sources.items()
            if candidate != path and module in candidate_source
        ]
        records[module] = {
            "module": module,
            "path": str(path),
            "line_count": len(source.splitlines()),
            "public_symbols": public_symbols,
            "imports": sorted(graph.get(module, ())),
            "inbound_modules": sorted(inbound.get(module, ())),
            "external_references": external_references,
            "test_references": [value for value in external_references if "tests" in Path(value).parts],
            "name_terms": sorted(words(path.stem.replace("_", " "))),
            "doc_terms": sorted(words(ast.get_docstring(tree) or "")),
        }

    dead_code_candidates = [
        {
            **record,
            "reasons": [
                "No inbound imports from another service module.",
                "No full module-path references in runtime source or tests.",
                "Confirm external entry points and generated configuration before deletion.",
            ],
        }
        for record in records.values()
        if not record["inbound_modules"] and not record["external_references"]
    ]

    modules = sorted(records)
    consolidation_candidates: list[dict[str, Any]] = []
    for index, left in enumerate(modules):
        for right in modules[index + 1:]:
            left_record = records[left]
            right_record = records[right]
            score = 0.0
            reasons: list[str] = []
            direct_dependency = right in graph.get(left, set()) or left in graph.get(right, set())
            if direct_dependency:
                score += 4.0
                reasons.append("One module imports the other during initialization.")
            shared_name = sorted(set(left_record["name_terms"]) & set(right_record["name_terms"]))
            if shared_name:
                score += min(3.0, 1.5 * len(shared_name))
                reasons.append("Shared module concepts: " + ", ".join(shared_name) + ".")
            shared_callers = sorted(set(left_record["inbound_modules"]) & set(right_record["inbound_modules"]))
            if shared_callers:
                score += min(3.0, float(len(shared_callers)))
                reasons.append(f"Shared service callers: {len(shared_callers)}.")
            shared_docs = sorted(set(left_record["doc_terms"]) & set(right_record["doc_terms"]))
            if len(shared_docs) >= 2:
                score += min(2.0, len(shared_docs) * 0.4)
                reasons.append("Shared responsibility language: " + ", ".join(shared_docs[:5]) + ".")
            combined_lines = left_record["line_count"] + right_record["line_count"]
            if combined_lines <= oversized_line_count:
                score += 1.0
                reasons.append(f"Combined size remains reviewable ({combined_lines} lines).")
            if min(left_record["line_count"], right_record["line_count"]) <= 200:
                score += 0.5
            if score >= 3.0:
                consolidation_candidates.append(
                    {
                        "modules": [left, right],
                        "paths": [left_record["path"], right_record["path"]],
                        "score": round(score, 3),
                        "combined_line_count": combined_lines,
                        "direct_dependency": direct_dependency,
                        "shared_callers": shared_callers,
                        "reasons": reasons,
                    }
                )

    token_groups: dict[str, list[str]] = {}
    for module, record in records.items():
        for token in record["name_terms"]:
            token_groups.setdefault(token, []).append(module)
    related_groups = [
        {"concept": token, "modules": sorted(group), "module_count": len(group)}
        for token, group in token_groups.items()
        if len(group) >= 2
    ]
    related_groups.sort(key=lambda item: (-item["module_count"], item["concept"]))
    existing_subpackages = {
        path.name
        for path in services_root.iterdir()
        if path.is_dir() and path.name not in ignored_dirs
    }
    existing_folder_moves = [
        {
            **group,
            "target_package": f"{package_name}.{service_package}.{group['concept']}",
            "target_path": str(services_root / group["concept"]),
            "reason": "Related top-level modules match an existing service subpackage.",
        }
        for group in related_groups
        if group["concept"] in existing_subpackages
    ]

    circular_imports = [
        {"modules": cycle, "paths": [str(module_paths[module]) for module in cycle]}
        for cycle in _find_import_cycles(graph)
    ]
    consolidation_candidates.sort(key=lambda item: (-item["score"], item["modules"]))
    dead_code_candidates.sort(key=lambda item: item["module"])
    oversized_modules = sorted(
        [record for record in records.values() if record["line_count"] >= oversized_line_count],
        key=lambda item: (-item["line_count"], item["module"]),
    )
    return {
        "ok": not parse_errors and not circular_imports,
        "project_root": str(root),
        "services_root": str(services_root),
        "module_count": len(records),
        "import_edge_count": sum(len(edges) for edges in graph.values()),
        "modules": [records[module] for module in sorted(records)],
        "dead_code_candidates": dead_code_candidates,
        "consolidation_candidates": consolidation_candidates,
        "related_groups": related_groups,
        "folder_candidates": [group for group in related_groups if group["module_count"] >= 8],
        "existing_folder_moves": existing_folder_moves,
        "oversized_modules": oversized_modules,
        "circular_imports": circular_imports,
        "parse_errors": parse_errors,
    }


@dataclass(frozen=True)
class CodeIntelligencePacket:
    objective: str
    mode: str
    scope: str
    active_path: str = ""
    terms: tuple[str, ...] = field(default_factory=tuple)
    repo_map: dict[str, Any] = field(default_factory=dict)
    symbols: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    usages: dict[str, Any] = field(default_factory=dict)
    project_context: str = ""
    sufficiency: dict[str, Any] = field(default_factory=dict)
    validation_plan: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    deterministic_answer: str = ""

    @property
    def can_answer_without_model(self) -> bool:
        return bool(self.sufficiency.get("answerable")) and bool(self.deterministic_answer)

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective": self.objective,
            "mode": self.mode,
            "scope": self.scope,
            "active_path": self.active_path,
            "terms": list(self.terms),
            "repo_map": self.repo_map,
            "symbols": list(self.symbols),
            "usages": self.usages,
            "project_context": self.project_context,
            "sufficiency": self.sufficiency,
            "validation_plan": list(self.validation_plan),
            "deterministic_answer": self.deterministic_answer,
            "can_answer_without_model": self.can_answer_without_model,
        }


def build_code_intelligence_packet(
    objective: str,
    *,
    active_path: str | None = None,
    limit: int = 20,
    include_repo_map: bool = True,
) -> dict[str, Any]:
    try:
        from tech_connector.services.settings_service import load_settings
        settings = load_settings()
        custom_module = settings.get("code_intel_provider_module")
        if custom_module and custom_module != "default":
            from tech_connector.services.modular_provider_utils import invoke_custom_provider
            return invoke_custom_provider(
                f"{custom_module}.build_code_intelligence_packet",
                _build_code_intelligence_packet_impl,
                objective,
                active_path=active_path,
                limit=limit,
                include_repo_map=include_repo_map
            )
    except Exception as e:
        print(f"Error calling custom build_code_intelligence_packet: {e}", flush=True)
    return _build_code_intelligence_packet_impl(objective, active_path=active_path, limit=limit, include_repo_map=include_repo_map)

def _build_code_intelligence_packet_impl(
    objective: str,
    *,
    active_path: str | None = None,
    limit: int = 20,
    include_repo_map: bool = True,
) -> dict[str, Any]:
    """Gather deterministic IDE-agent context for code/search/edit prompts."""

    from tech_connector.knowledge.search import extract_code_search_terms, search_index_symbols, search_index_usages
    from tech_connector.services.project_search_service import (
        build_deterministic_project_search_answer,
        detect_project_search_mode,
        detect_search_scope,
        gather_project_search_context,
    )
    from tech_connector.services.reasoning.rag_sufficiency_service import evaluate_project_rag_sufficiency
    from tech_connector.services.validation_planner_service import plan_validation_for_paths

    text = objective or ""
    scope = detect_search_scope(text)
    mode = detect_project_search_mode(text)
    terms = tuple(extract_code_search_terms(text)[:12])
    project_context = gather_project_search_context(text, active_path=active_path, limit=limit, scope=scope)
    sufficiency = evaluate_project_rag_sufficiency(
        text,
        project_context,
        intent="project_edit" if mode == "target_edit" else "project_search",
    )
    deterministic_answer = ""
    if sufficiency.answerable:
        deterministic_answer = build_deterministic_project_search_answer(text, active_path, project_context)
    project_roots = _project_roots_from_context(project_context)
    symbols = tuple(
        search_index_symbols(
            list(terms),
            limit=min(limit, 20),
            active_path=active_path,
            scope=scope,
            project_roots=project_roots,
        )
        if terms
        else []
    )
    usages = search_index_usages(
        text,
        limit=min(max(limit, 10), 50),
        active_path=active_path,
        scope=scope,
        project_roots=project_roots,
    )
    repo_map = {}
    if include_repo_map:
        from tech_connector.services.repo_map_service import build_repo_map

        repo_map = build_repo_map(
            project_root=project_roots[0] if project_roots else None,
            scope=scope,
            max_dirs=12,
            max_files=16,
        )
    validation_paths = _candidate_paths(symbols, usages, active_path=active_path)
    validation_plan = tuple(
        plan_validation_for_paths(
            validation_paths,
            project_root=project_roots[0] if project_roots else None,
        )
    )
    return CodeIntelligencePacket(
        objective=text.strip(),
        mode=str(mode),
        scope=scope,
        active_path=str(active_path or ""),
        terms=terms,
        repo_map=repo_map,
        symbols=symbols,
        usages=usages,
        project_context=project_context,
        sufficiency=sufficiency.to_dict(),
        validation_plan=validation_plan,
        deterministic_answer=deterministic_answer,
    ).to_dict()


def render_code_intelligence_packet(packet: dict[str, Any] | None, *, max_context_chars: int = 5000) -> str:
    try:
        from tech_connector.services.settings_service import load_settings
        settings = load_settings()
        custom_module = settings.get("code_intel_provider_module")
        if custom_module and custom_module != "default":
            from tech_connector.services.modular_provider_utils import invoke_custom_provider
            return invoke_custom_provider(
                f"{custom_module}.render_code_intelligence_packet",
                _render_code_intelligence_packet_impl,
                packet,
                max_context_chars=max_context_chars
            )
    except Exception as e:
        print(f"Error calling custom render_code_intelligence_packet: {e}", flush=True)
    return _render_code_intelligence_packet_impl(packet, max_context_chars=max_context_chars)

def _render_code_intelligence_packet_impl(packet: dict[str, Any] | None, *, max_context_chars: int = 5000) -> str:
    packet = dict(packet or {})
    if not packet:
        return ""
    lines = [
        "Code intelligence packet:",
        f"Mode: {packet.get('mode') or 'unknown'}",
        f"Scope: {packet.get('scope') or 'project'}",
        f"Can answer without model: {bool(packet.get('can_answer_without_model'))}",
    ]
    terms = packet.get("terms") or []
    if terms:
        lines.append("Terms: " + ", ".join(str(term) for term in terms[:12]))
    suff = dict(packet.get("sufficiency") or {})
    if suff:
        lines.append(
            "RAG sufficiency: "
            f"{'answerable' if suff.get('answerable') else 'needs synthesis'} "
            f"(confidence {suff.get('confidence')})"
        )
        if suff.get("recommended_next_stage"):
            lines.append(f"Next stage: {suff.get('recommended_next_stage')}")
    repo = dict(packet.get("repo_map") or {})
    if repo:
        lines.extend(
            [
                f"Repo map: {repo.get('file_count', 0)} files, {repo.get('symbol_count', 0)} symbols",
                "Top areas: "
                + ", ".join(str(item.get("path")) for item in list(repo.get("directories") or [])[:6]),
            ]
        )
    symbols = list(packet.get("symbols") or [])
    if symbols:
        lines.append("Top symbol evidence:")
        for item in symbols[:8]:
            lines.append(
                f"- {item.get('kind')} {item.get('qualname') or item.get('name')} "
                f"at {item.get('path')}:{item.get('start_line')}"
            )
    validation = list(packet.get("validation_plan") or [])
    if validation:
        lines.append("Validation candidates:")
        for item in validation[:8]:
            lines.append(f"- {item.get('command')}: {item.get('reason')}")
    context = str(packet.get("project_context") or "").strip()
    if context:
        lines.extend(["", "Indexed project evidence excerpt:", context[:max_context_chars]])
    return "\n".join(lines)


def deterministic_code_answer(packet: dict[str, Any] | None) -> str | None:
    packet = dict(packet or {})
    answer = str(packet.get("deterministic_answer") or "").strip()
    return answer if packet.get("can_answer_without_model") and answer else None


def _project_roots_from_context(context: str) -> list[str]:
    for line in (context or "").splitlines():
        if line.startswith("Project roots:"):
            raw = line.split(":", 1)[1].strip()
            if not raw or raw == "(none)":
                return []
            return [part.strip() for part in raw.split(",") if part.strip()]
    return []


def _candidate_paths(
    symbols: tuple[dict[str, Any], ...],
    usages: dict[str, Any],
    *,
    active_path: str | None = None,
) -> list[str]:
    paths: list[str] = []
    if active_path:
        paths.append(str(active_path))
    for item in symbols:
        path = item.get("path")
        if path:
            paths.append(str(path))
    for key in ("exact_symbols", "exact_calls", "exact_chunks", "related_symbols"):
        for item in usages.get(key) or []:
            path = item.get("path")
            if path:
                paths.append(str(path))
    out: list[str] = []
    seen: set[str] = set()
    for path in paths:
        try:
            normalized = str(Path(path).expanduser().resolve())
        except Exception:
            normalized = path
        if normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out[:12]
