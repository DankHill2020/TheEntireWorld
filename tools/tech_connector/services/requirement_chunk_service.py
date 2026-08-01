"""Deterministic requirement-to-symbol chunk planning for project edits.

The coding model receives a compact owner-specific envelope. The complete user
request remains authoritative in the requirement ledger and coverage matrix;
it is not repeatedly copied into every generation or repair call.
"""

from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping, Sequence


CHUNK_PLANNER_VERSION = "requirement-chunks-v1"


@dataclass(frozen=True)
class RequirementRecord:
    requirement_id: str
    text: str
    semantic_role: str = ""
    owner: str = ""
    path: str = ""
    owner_evidence: str = ""
    owner_candidates: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class SymbolDeclaration:
    path: str
    owner: str
    kind: str = "module"
    parent: str = ""
    requirement_ids: tuple[str, ...] = ()


@dataclass
class RequirementChunk:
    chunk_id: str
    path: str
    owner: str
    kind: str
    requirements: list[RequirementRecord] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    unresolved_candidates: list[str] = field(default_factory=list)

    def requirement_ids(self) -> list[str]:
        return [item.requirement_id for item in self.requirements]


@dataclass
class RequirementCoverage:
    requirement_id: str
    chunk_id: str
    path: str
    owner: str
    implemented: bool = False
    validated: bool = False
    assembled: bool = False
    failure: str = ""

    @property
    def complete(self) -> bool:
        return self.implemented and self.validated and self.assembled


def _stable_hash(value: Any) -> str:
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _normalize_requirement_rows(requirement_ledger: Any) -> list[RequirementRecord]:
    rows = requirement_ledger
    if isinstance(requirement_ledger, Mapping):
        rows = (
            requirement_ledger.get("requirements")
            or requirement_ledger.get("clauses")
            or requirement_ledger.get("items")
            or []
        )
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        return []

    normalized: list[RequirementRecord] = []
    for index, raw in enumerate(rows, start=1):
        if isinstance(raw, str):
            normalized.append(RequirementRecord(f"R{index}", raw.strip()))
            continue
        if not isinstance(raw, Mapping):
            continue
        requirement_id = str(
            raw.get("requirement_id") or raw.get("id") or raw.get("clause_id") or f"R{index}"
        ).strip()
        text = str(
            raw.get("text")
            or raw.get("requirement")
            or raw.get("description")
            or raw.get("objective")
            or ""
        ).strip()
        owner = str(raw.get("owner") or raw.get("symbol") or "").strip()
        path = str(raw.get("path") or raw.get("file") or "").strip()
        semantic_role = str(
            raw.get("semantic_role") or raw.get("role") or raw.get("requirement_type") or ""
        ).strip()
        owner_evidence = str(
            raw.get("owner_evidence") or raw.get("ownership_reason") or ""
        ).strip()
        raw_candidates = raw.get("owner_candidates") or ()
        if isinstance(raw_candidates, str):
            owner_candidates = (raw_candidates,)
        elif isinstance(raw_candidates, Iterable):
            owner_candidates = tuple(str(item) for item in raw_candidates if item)
        else:
            owner_candidates = ()
        raw_evidence = raw.get("evidence_ids") or raw.get("evidence") or ()
        if isinstance(raw_evidence, str):
            evidence_ids = (raw_evidence,)
        elif isinstance(raw_evidence, Iterable):
            evidence_ids = tuple(str(item) for item in raw_evidence if item)
        else:
            evidence_ids = ()
        if text:
            normalized.append(
                RequirementRecord(
                    requirement_id=requirement_id,
                    text=text,
                    semantic_role=semantic_role,
                    owner=owner,
                    path=path,
                    owner_evidence=owner_evidence,
                    owner_candidates=owner_candidates,
                    evidence_ids=evidence_ids,
                )
            )
    return normalized


def _normalize_manifest(manifest: Any) -> list[SymbolDeclaration]:
    rows = manifest
    if isinstance(manifest, Mapping):
        rows = manifest.get("files") or manifest.get("artifacts") or []
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        return []

    declarations: list[SymbolDeclaration] = []
    for raw_file in rows:
        if isinstance(raw_file, str):
            declarations.append(SymbolDeclaration(raw_file, "<module>", "module"))
            continue
        if not isinstance(raw_file, Mapping):
            continue
        path = str(raw_file.get("path") or raw_file.get("file") or "").strip()
        if not path:
            continue
        declarations.append(SymbolDeclaration(path, "<module>", "module"))
        symbols = (
            raw_file.get("public_symbols")
            or raw_file.get("symbols")
            or raw_file.get("declarations")
            or []
        )
        if isinstance(symbols, str):
            symbols = [symbols]
        for raw_symbol in symbols:
            if isinstance(raw_symbol, str):
                declarations.append(SymbolDeclaration(path, raw_symbol, "symbol"))
                continue
            if not isinstance(raw_symbol, Mapping):
                continue
            owner = str(
                raw_symbol.get("qualified_name")
                or raw_symbol.get("owner")
                or raw_symbol.get("name")
                or ""
            ).strip()
            if not owner:
                continue
            declarations.append(
                SymbolDeclaration(
                    path=path,
                    owner=owner,
                    kind=str(raw_symbol.get("kind") or "symbol"),
                    parent=str(raw_symbol.get("parent") or "").strip(),
                    requirement_ids=tuple(
                        str(item)
                        for item in (raw_symbol.get("requirement_ids") or ())
                        if item
                    ),
                )
            )
    return declarations


def _owner_candidates(
    requirement: RequirementRecord,
    declarations: Sequence[SymbolDeclaration],
) -> list[SymbolDeclaration]:
    """Return only ownership candidates supplied by semantic planning evidence.

    A symbol merely appearing in requirement text is never ownership evidence:
    it may be an API, dependency, base class, example, or return type.
    """

    requirement_bound = [
        item
        for item in declarations
        if requirement.requirement_id in item.requirement_ids
    ]
    if requirement_bound:
        return requirement_bound

    if requirement.owner:
        exact = [
            item
            for item in declarations
            if item.owner == requirement.owner
            or item.owner.endswith(f".{requirement.owner}")
        ]
        if requirement.path:
            exact = [item for item in exact if item.path == requirement.path]
        return exact

    allowed = set(requirement.owner_candidates)
    candidates = [
        item
        for item in declarations
        if item.owner != "<module>"
        and (
            item.owner in allowed
            or f"{item.path}:{item.owner}" in allowed
        )
    ]
    if requirement.path:
        candidates = [item for item in candidates if item.path == requirement.path]
    return candidates


def _module_declaration(
    requirement: RequirementRecord,
    declarations: Sequence[SymbolDeclaration],
) -> SymbolDeclaration | None:
    if requirement.semantic_role not in {
        "module",
        "module_behavior",
        "entry_point",
        "file_contract",
        "package_contract",
    }:
        return None
    modules = [item for item in declarations if item.owner == "<module>"]
    if requirement.path:
        modules = [item for item in modules if item.path == requirement.path]
    if len(modules) == 1:
        return modules[0]
    if len({item.path for item in modules}) == 1 and modules:
        return modules[0]
    return None


def _chunk_key(declaration: SymbolDeclaration) -> tuple[str, str]:
    # New classes are generated coherently as a class block. Existing method
    # repair can use a qualified method owner without regenerating the class.
    owner = declaration.parent or declaration.owner
    return declaration.path, owner


def build_requirement_chunks(
    requirement_ledger: Any,
    manifest: Any,
    evidence_by_id: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[list[RequirementChunk], list[RequirementCoverage]]:
    """Create deterministic owner chunks without guessing ambiguous ownership."""

    requirements = _normalize_requirement_rows(requirement_ledger)
    declarations = _normalize_manifest(manifest)
    evidence_by_id = evidence_by_id or {}
    grouped: dict[tuple[str, str], RequirementChunk] = {}

    for requirement in requirements:
        candidates = _owner_candidates(requirement, declarations)
        declaration: SymbolDeclaration | None = None
        unresolved: list[str] = []
        if len(candidates) == 1:
            declaration = candidates[0]
        elif len(candidates) > 1:
            unresolved = sorted(
                f"{candidate.path}:{candidate.owner}" for candidate in candidates
            )
        else:
            declaration = _module_declaration(requirement, declarations)

        if declaration is None:
            path = requirement.path or "<unresolved>"
            owner = "<unresolved>"
            kind = "unresolved"
            key = path, owner
        else:
            path, owner = _chunk_key(declaration)
            kind = declaration.kind
            key = path, owner

        chunk = grouped.get(key)
        if chunk is None:
            chunk_id = f"C-{_stable_hash({'path': path, 'owner': owner})[:12]}"
            chunk = RequirementChunk(chunk_id, path, owner, kind)
            grouped[key] = chunk
        chunk.requirements.append(requirement)
        chunk.unresolved_candidates.extend(
            item for item in unresolved if item not in chunk.unresolved_candidates
        )
        for evidence_id in requirement.evidence_ids:
            evidence = evidence_by_id.get(evidence_id)
            if evidence and not any(
                item.get("evidence_id") == evidence_id for item in chunk.evidence
            ):
                chunk.evidence.append({"evidence_id": evidence_id, **dict(evidence)})

    chunks = sorted(grouped.values(), key=lambda item: (item.path, item.owner))
    chunk_by_owner = {(item.path, item.owner): item.chunk_id for item in chunks}
    for chunk in chunks:
        declaration = next(
            (
                item
                for item in declarations
                if item.path == chunk.path
                and (item.owner == chunk.owner or item.parent == chunk.owner)
            ),
            None,
        )
        if declaration and declaration.parent:
            dependency = chunk_by_owner.get((declaration.path, declaration.parent))
            if dependency and dependency != chunk.chunk_id:
                chunk.dependencies.append(dependency)

    coverage = [
        RequirementCoverage(
            requirement_id=requirement.requirement_id,
            chunk_id=chunk.chunk_id,
            path=chunk.path,
            owner=chunk.owner,
        )
        for chunk in chunks
        for requirement in chunk.requirements
    ]
    return chunks, coverage


def build_chunk_generation_prompt(
    chunk: RequirementChunk,
    boundary_source: str = "",
    interface_contracts: Sequence[str] = (),
) -> str:
    """Build a compact coding-only envelope for one resolved owner."""

    if chunk.unresolved_candidates or chunk.owner == "<unresolved>":
        raise ValueError(
            f"Chunk {chunk.chunk_id} has unresolved ownership and cannot be generated."
        )
    payload = {
        "mode": "generate_exact_symbol_chunk",
        "chunk_id": chunk.chunk_id,
        "target": {"path": chunk.path, "owner": chunk.owner, "kind": chunk.kind},
        "requirements": [
            {"id": item.requirement_id, "text": item.text}
            for item in chunk.requirements
        ],
        "dependencies": chunk.dependencies,
        "interfaces": list(interface_contracts),
        "verified_evidence": chunk.evidence,
        "boundary_source": boundary_source,
        "output_contract": {
            "return": "exact replacement or insertion block only",
            "placeholders_forbidden": True,
            "unrequested_symbols_forbidden": True,
            "preserve_unrelated_code": True,
        },
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def build_owner_resolution_prompt(
    chunk: RequirementChunk,
    declarations: Sequence[Mapping[str, Any]],
    relationship_context: Sequence[Mapping[str, Any]] = (),
) -> str:
    """Build a bounded semantic-owner decision for an unresolved requirement.

    The reasoner may select only a supplied declaration ID or mark the
    requirement module-owned/unresolved. It cannot invent a target.
    """

    payload = {
        "mode": "resolve_requirement_ownership",
        "chunk_id": chunk.chunk_id,
        "requirements": [
            {
                "id": item.requirement_id,
                "text": item.text,
                "semantic_role": item.semantic_role,
                "owner_evidence": item.owner_evidence,
            }
            for item in chunk.requirements
        ],
        "candidate_declarations": list(declarations),
        "relationships": list(relationship_context),
        "decision_contract": {
            "allowed_results": [
                "one supplied declaration_id per requirement",
                "module_owned",
                "unresolved",
            ],
            "invented_targets_forbidden": True,
            "symbol_mentions_are_not_ownership_evidence": True,
            "return": "JSON only",
        },
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def validate_chunk_source(chunk: RequirementChunk, source: str) -> list[str]:
    """Run model-independent checks on a returned owner chunk."""

    failures: list[str] = []
    if not source.strip():
        return [f"[owner:{chunk.owner}] Empty chunk response."]
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f"[owner:{chunk.owner}] Syntax error: {exc.msg} at line {exc.lineno}."]
    placeholder_nodes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and (
            not node.body
            or (
                len(node.body) == 1
                and (
                    isinstance(node.body[0], ast.Pass)
                    or (
                        isinstance(node.body[0], ast.Expr)
                        and isinstance(node.body[0].value, ast.Constant)
                        and node.body[0].value.value is Ellipsis
                    )
                    or (
                        isinstance(node.body[0], ast.Raise)
                        and isinstance(node.body[0].exc, ast.Call)
                        and isinstance(node.body[0].exc.func, ast.Name)
                        and node.body[0].exc.func.id == "NotImplementedError"
                    )
                )
            )
        )
    ]
    if placeholder_nodes:
        failures.append(
            f"[owner:{chunk.owner}] Placeholder callable bodies detected: "
            + ", ".join(node.name for node in placeholder_nodes)
        )

    expected_name = chunk.owner.rsplit(".", 1)[-1]
    if expected_name != "<module>":
        declared = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        }
        if expected_name not in declared:
            failures.append(
                f"[owner:{chunk.owner}] Expected declaration {expected_name!r} is missing."
            )
    return failures


def update_coverage(
    coverage: Sequence[RequirementCoverage],
    chunk_id: str,
    *,
    implemented: bool | None = None,
    validated: bool | None = None,
    assembled: bool | None = None,
    failure: str | None = None,
) -> None:
    for item in coverage:
        if item.chunk_id != chunk_id:
            continue
        if implemented is not None:
            item.implemented = implemented
        if validated is not None:
            item.validated = validated
        if assembled is not None:
            item.assembled = assembled
        if failure is not None:
            item.failure = failure


def coverage_is_complete(coverage: Sequence[RequirementCoverage]) -> bool:
    return bool(coverage) and all(item.complete for item in coverage)


def serialize_chunk_state(
    chunks: Sequence[RequirementChunk],
    coverage: Sequence[RequirementCoverage],
) -> dict[str, Any]:
    payload = {
        "planner_version": CHUNK_PLANNER_VERSION,
        "chunks": [asdict(item) for item in chunks],
        "coverage": [asdict(item) for item in coverage],
    }
    payload["state_hash"] = _stable_hash(payload)
    return payload
