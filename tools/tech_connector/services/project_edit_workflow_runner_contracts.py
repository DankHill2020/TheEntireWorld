"""Project-edit workflow phase: _run_contract_phase."""

from __future__ import annotations
from tech_connector.services import project_edit_workflow_runner_dependencies as _deps
from tech_connector.services.project_edit_workflow_runner_control import _WorkflowReturn


class _ProjectEditContractPhase:
    """Provide the contract workflow phase."""

    def _run_contract_phase(self) -> None:
        """Run the contract phase.

        :return: None.
        """
        for self.plan_chunk in (
            []
            if self.early_cached_approval
            else self.implementation_plan.get("chunks") or []
        ):
            self.requirement_rows = [
                item
                for item in self.plan_chunk.get("requirements") or []
                if isinstance(item, _deps.Mapping)
                and str(item.get("text") or "").strip()
            ]
            self.evidence_query = ".\n".join(
                (str(item.get("text") or "") for item in self.requirement_rows)
            )
            self.chunk_requires_qt_worker = any(
                (
                    _deps.re.search(
                        "\\b(?:Qt|PySide|PyQt)\\b[^.!?\\n]{0,120}\\b(?:worker|thread|threadpool|runnable)\\b|\\b(?:worker|thread|threadpool|runnable)\\b[^.!?\\n]{0,120}\\b(?:Qt|PySide|PyQt)\\b",
                        str(item.get("text") or ""),
                        flags=_deps.re.IGNORECASE,
                    )
                    for item in self.requirement_rows
                )
            )
            self.merged_evidence: dict[tuple[str, str, str], dict[str, _deps.Any]] = {}
            self.merged_queries: list[str] = []
            self.merged_unresolved: list[str] = []
            self.merged_hosts: list[str] = []
            self.merged_provider_errors: list[dict[str, str]] = []
            self.merged_acquisition_requests: list[dict[str, _deps.Any]] = []
            self.merged_unresolved_capability_intents: list[dict[str, _deps.Any]] = []
            self.requirement_query_map: dict[str, list[str]] = {}
            self.capability_requirements: list[_deps.Mapping[str, _deps.Any]] = []
            for self.requirement in self.requirement_rows:
                self.requirement_id = str(self.requirement.get("id") or "")
                self.requirement_text = str(self.requirement.get("text") or "")
                self.extracted_queries = self.extract_symbol_evidence_queries(
                    self.requirement_text, limit=24
                )
                if self.chunk_requires_qt_worker:
                    if _deps.re.search(
                        "\\b(?:worker|thread|threadpool|runnable)\\b",
                        self.requirement_text,
                        flags=_deps.re.IGNORECASE,
                    ):
                        self.extracted_queries = list(
                            dict.fromkeys(
                                [
                                    *self.extracted_queries,
                                    "PySide6.QtCore.QRunnable.run",
                                    "PySide6.QtCore.QThreadPool.globalInstance",
                                    "PySide6.QtCore.QThreadPool.start",
                                ]
                            )
                        )
                    if _deps.re.search(
                        "\\b(?:signal|completion|error|result)\\b",
                        self.requirement_text,
                        flags=_deps.re.IGNORECASE,
                    ):
                        self.extracted_queries = list(
                            dict.fromkeys(
                                [*self.extracted_queries, "PySide6.QtCore.Signal"]
                            )
                        )
                self.requires_capability = bool(
                    self.extracted_queries
                    or _deps.re.search(
                        "\\b(?:API|adapter|bridge|service|transport|worker|thread|callback|signal|import|export|load|save|create|execute|query|read|write|connect)\\b",
                        self.requirement_text,
                        flags=_deps.re.IGNORECASE,
                    )
                )
                if not self.requires_capability:
                    continue
                self.requirement_query_map[self.requirement_id] = self.extracted_queries
                self.capability_requirements.append(self.requirement)
            if self.capability_requirements:
                self.exact_query_lines = [
                    f"{requirement_id}: {query}"
                    for requirement_id, values in self.requirement_query_map.items()
                    for query in values
                ]
                self.chunk_evidence_query = self.evidence_query
                if self.exact_query_lines:
                    self.chunk_evidence_query += (
                        "\n\nExact capability queries by requirement:\n"
                        + "\n".join(self.exact_query_lines)
                    )
                self.requirement_packet = self.preplan_grounding
                self.merged_queries.extend(
                    (
                        str(value)
                        for value in self.requirement_packet.get("queries") or []
                    )
                )
                self.merged_unresolved.extend(
                    (
                        str(value)
                        for value in self.requirement_packet.get(
                            "unresolved_host_api_queries"
                        )
                        or []
                    )
                )
                self.merged_hosts.extend(
                    (str(value) for value in self.requirement_packet.get("hosts") or [])
                )
                self.merged_provider_errors.extend(
                    (
                        dict(value)
                        for value in self.requirement_packet.get("provider_errors")
                        or []
                        if isinstance(value, _deps.Mapping)
                    )
                )
                self.merged_acquisition_requests.extend(
                    (
                        dict(value)
                        for value in self.requirement_packet.get(
                            "capability_acquisition_requests"
                        )
                        or []
                        if isinstance(value, _deps.Mapping)
                    )
                )
                self.merged_unresolved_capability_intents.extend(
                    (
                        dict(value)
                        for value in self.requirement_packet.get(
                            "unresolved_capability_intents"
                        )
                        or []
                        if isinstance(value, _deps.Mapping)
                    )
                )
                for self.raw_item in self.requirement_packet.get("evidence") or []:
                    if not isinstance(self.raw_item, _deps.Mapping):
                        continue
                    self.item = dict(self.raw_item)
                    self.item_links = {
                        str(value).casefold()
                        for value in self.item.get("query_links") or []
                        if str(value)
                    }
                    self.item_name_terms = {
                        token.casefold()
                        for token in _deps.re.findall(
                            "[A-Za-z_][A-Za-z0-9_]{2,}",
                            " ".join(
                                (
                                    str(self.item.get(field) or "")
                                    for field in ("qualified_name", "signature")
                                )
                            ),
                        )
                    }
                    self.mapped_requirement_ids = {
                        str(value)
                        for value in self.item.get("requirement_ids") or []
                        if str(value)
                    }
                    for self.requirement in self.capability_requirements:
                        self.requirement_id = str(self.requirement.get("id") or "")
                        self.requirement_text = str(self.requirement.get("text") or "")
                        self.exact_links = {
                            query.casefold()
                            for query in self.requirement_query_map.get(
                                self.requirement_id, []
                            )
                        }
                        self.requirement_terms = {
                            token.casefold()
                            for token in _deps.re.findall(
                                "[A-Za-z_][A-Za-z0-9_]{2,}", self.requirement_text
                            )
                            if token.casefold()
                            not in {
                                "adapter",
                                "and",
                                "api",
                                "bridge",
                                "class",
                                "code",
                                "file",
                                "from",
                                "function",
                                "method",
                                "must",
                                "that",
                                "the",
                                "this",
                                "through",
                                "using",
                                "with",
                            }
                        }
                        if (
                            self.exact_links & self.item_links
                            or len(self.requirement_terms & self.item_name_terms) >= 2
                        ):
                            self.mapped_requirement_ids.add(self.requirement_id)
                    if (
                        not self.mapped_requirement_ids
                        and len(self.capability_requirements) == 1
                    ):
                        self.mapped_requirement_ids.add(
                            str(self.capability_requirements[0].get("id") or "")
                        )
                    self.item["requirement_ids"] = sorted(
                        (value for value in self.mapped_requirement_ids if value)
                    )
                    self.key = (
                        str(self.item.get("qualified_name") or "").casefold(),
                        str(self.item.get("signature") or ""),
                        str(self.item.get("path") or "").replace("\\", "/").casefold(),
                    )
                    self.existing = self.merged_evidence.get(self.key)
                    if self.existing is None:
                        self.existing = self.item
                        self.existing["requirement_ids"] = list(
                            self.item.get("requirement_ids") or []
                        )
                        self.raw_item_supports = self.item.get("supports") or []
                        self.existing["supports"] = (
                            list(self.raw_item_supports)
                            if isinstance(self.raw_item_supports, (list, tuple, set))
                            else (
                                [str(self.raw_item_supports)]
                                if str(self.raw_item_supports)
                                else []
                            )
                        )
                        self.raw_item_links = self.item.get("query_links") or []
                        self.existing["query_links"] = (
                            list(self.raw_item_links)
                            if isinstance(self.raw_item_links, (list, tuple, set))
                            else (
                                [str(self.raw_item_links)]
                                if str(self.raw_item_links)
                                else []
                            )
                        )
                        self.merged_evidence[self.key] = self.existing
                    self.existing["requirement_ids"] = list(
                        dict.fromkeys(
                            [
                                *list(self.existing.get("requirement_ids") or []),
                                *list(self.item.get("requirement_ids") or []),
                            ]
                        )
                    )
                    self.raw_supports = self.existing.get("supports") or []
                    self.supports = (
                        list(self.raw_supports)
                        if isinstance(self.raw_supports, list)
                        else [str(self.raw_supports)]
                    )
                    self.supported_requirement_texts = [
                        str(requirement.get("text") or "")
                        for requirement in self.capability_requirements
                        if str(requirement.get("id") or "")
                        in self.existing["requirement_ids"]
                    ]
                    self.existing["supports"] = list(
                        dict.fromkeys(
                            [*self.supports, *self.supported_requirement_texts]
                        )
                    )
                    self.raw_links = self.existing.get("query_links") or []
                    self.links = (
                        list(self.raw_links)
                        if isinstance(self.raw_links, list)
                        else [str(self.raw_links)]
                    )
                    self.linked_exact_queries = [
                        query
                        for requirement_id in self.existing["requirement_ids"]
                        for query in self.requirement_query_map.get(requirement_id, [])
                    ]
                    self.existing["query_links"] = list(
                        dict.fromkeys([*self.links, *self.linked_exact_queries])
                    )
            self.evidence_packet = {
                "evidence": sorted(
                    self.merged_evidence.values(), key=self._evidence_strength_rank
                ),
                "queries": list(dict.fromkeys(self.merged_queries)),
                "unresolved_host_api_queries": list(
                    dict.fromkeys(self.merged_unresolved)
                ),
                "hosts": list(dict.fromkeys(self.merged_hosts)),
                "provider_errors": list(
                    {
                        (
                            str(item.get("provider") or ""),
                            str(item.get("error") or ""),
                        ): item
                        for item in self.merged_provider_errors
                    }.values()
                ),
                "capability_acquisition_requests": self.merged_acquisition_requests,
                "unresolved_capability_intents": self.merged_unresolved_capability_intents,
            }
            if self.status_callback and self.evidence_packet["provider_errors"]:
                self.status_callback(
                    "Evidence provider warnings: "
                    + "; ".join(
                        (
                            f"{item.get('provider')}: {item.get('error')}"
                            for item in self.evidence_packet["provider_errors"][:4]
                        )
                    )
                )
            if self.internal_adapter_evidence_required:
                self.direct_host_prefixes = (
                    "unreal.",
                    "maya.cmds.",
                    "maya.api.",
                    "maya.openmaya.",
                    "bpy.",
                    "pyfbsdk.",
                )
                self.evidence_packet["evidence"] = [
                    item
                    for item in self.evidence_packet.get("evidence") or []
                    if not str(item.get("qualified_name") or "")
                    .casefold()
                    .startswith(self.direct_host_prefixes)
                ]
            self.evidence_terms = {
                token.casefold()
                for query in self.evidence_packet.get("queries") or []
                for token in _deps.re.findall("[A-Za-z_][A-Za-z0-9_]{3,}", str(query))
                if token.casefold()
                not in {
                    "add",
                    "build",
                    "class",
                    "connect",
                    "create",
                    "file",
                    "from",
                    "implement",
                    "module",
                    "must",
                    "python",
                    "that",
                    "this",
                    "using",
                    "with",
                }
            }
            self.exact_host_queries = {
                str(query).casefold()
                for query in self.evidence_packet.get("queries") or []
                if str(query).startswith(
                    ("unreal.", "maya.", "cmds.", "bpy.", "pyfbsdk.")
                )
            }
            self.derived_host_members = {
                member.casefold()
                for _owner, member in _deps.re.findall(
                    "\\b((?:unreal|maya\\.cmds|maya\\.api\\.OpenMaya|maya\\.OpenMaya|cmds|bpy|pyfbsdk)(?:\\.[A-Za-z_][A-Za-z0-9_]*)+)\\s*\\([^)]*\\)\\s*\\.\\s*([A-Za-z_][A-Za-z0-9_]*)",
                    self.evidence_query,
                )
            }
            self.normalized_evidence: list[dict[str, _deps.Any]] = []
            self.normalized_evidence_names: set[str] = set()
            for self.row in self.evidence_packet.get("evidence") or []:
                self.provider = str(self.row.get("provider") or "")
                self.provenance = str(self.row.get("provenance") or "")
                self.raw_supports = self.row.get("supports") or []
                self.supports = (
                    [str(value) for value in self.raw_supports if str(value)]
                    if isinstance(self.raw_supports, (list, tuple, set))
                    else [str(self.raw_supports)] if str(self.raw_supports) else []
                )
                self.raw_query_links = self.row.get("query_links") or []
                self.query_links = (
                    [str(value) for value in self.raw_query_links if str(value)]
                    if isinstance(self.raw_query_links, (list, tuple, set))
                    else (
                        [str(self.raw_query_links)] if str(self.raw_query_links) else []
                    )
                )
                self.supports_text = " ".join(self.supports)
                self.authoritative = bool(
                    self.row.get("authoritative_signature")
                    and self._complete_callable_evidence(self.row)
                )
                self.row_name = str(self.row.get("qualified_name") or "")
                self.row_path = str(self.row.get("path") or "")
                self.target_path = str(self.plan_chunk.get("path") or "")
                self.row_name_parts = set(
                    _deps.re.findall("[A-Za-z_][A-Za-z0-9_]*", self.row_name)
                )
                self.external_planned_owner_collision = bool(
                    self.row_name_parts & self.planned_owner_names
                    and self.row_path.casefold() != self.target_path.casefold()
                )
                self.indexed_third_party = bool(
                    self.provider.startswith("project_index")
                    and "third_party" in self.provenance.casefold()
                    and (self.row_path.casefold() != self.target_path.casefold())
                )
                if self.external_planned_owner_collision or self.indexed_third_party:
                    continue
                if (
                    self.provider.startswith("unreal_capability_graph")
                    and (not self.supports_text)
                    and (self.row_name.casefold() not in self.exact_host_queries)
                    and (
                        self.row_name.rsplit(".", 1)[-1].casefold()
                        not in self.derived_host_members
                    )
                ):
                    continue
                self.normalized_name = self.row_name.casefold()
                if self.normalized_name in self.normalized_evidence_names:
                    continue
                self.evidence_haystack = " ".join(
                    (
                        str(self.row.get(field) or "")
                        for field in ("qualified_name", "signature", "path")
                    )
                ).casefold()
                self.related_usage = any(
                    (term in self.evidence_haystack for term in self.evidence_terms)
                )
                if (
                    not self.authoritative
                    and self.provider != "official_public_api_research"
                    and (not self.related_usage)
                ):
                    continue
                if self.authoritative:
                    self.strength = "authoritative_signature"
                elif (
                    self.provider == "official_public_api_research"
                    and self.authoritative
                ):
                    self.strength = "official_api_research"
                elif str(self.row.get("confidence") or "") == "exact":
                    self.strength = "exact_indexed_definition"
                else:
                    self.strength = "indexed_usage_example"
                self.normalized_evidence.append(
                    {
                        "name": str(self.row.get("qualified_name") or ""),
                        "signature": str(self.row.get("signature") or ""),
                        "source_excerpt": str(self.row.get("source_excerpt") or ""),
                        "path": str(self.row.get("path") or ""),
                        "provider": self.provider,
                        "provenance": self.provenance,
                        "strength": self.strength,
                        "supports": self.supports,
                        "query_links": self.query_links,
                        "kind": str(self.row.get("kind") or ""),
                        "access_kind": str(self.row.get("access_kind") or ""),
                        "decorators": list(self.row.get("decorators") or []),
                        "usage_role": str(self.row.get("usage_role") or ""),
                        "owner_qualname": str(self.row.get("owner_qualname") or ""),
                        "owner_member": bool(self.row.get("owner_member")),
                        "selected_for_generation": bool(
                            self.row.get("selected_for_generation")
                        ),
                        "dependency_for_selected": bool(
                            self.row.get("dependency_for_selected")
                        ),
                        "capability_relationships": dict(
                            self.row.get("capability_relationships") or {}
                        ),
                        "intent_indexes": list(self.row.get("intent_indexes") or []),
                        "requirement_ids": list(self.row.get("requirement_ids") or []),
                        "evidence_rank": self._evidence_strength_rank(self.row)[0],
                    }
                )
                self.normalized_evidence_names.add(self.normalized_name)
            self.strong_evidence = [
                item
                for item in self.normalized_evidence
                if item.get("strength")
                in {
                    "authoritative_signature",
                    "official_api_research",
                    "exact_indexed_definition",
                }
            ]
            self.required_base_names = set(
                _deps.re.findall(
                    "\\b(?:inheriting\\s+from|subclassing|extends)\\s+([A-Z][A-Za-z0-9_.]*)\\b",
                    self.evidence_query,
                    flags=_deps.re.IGNORECASE,
                )
            )
            self.declared_base = str(
                (self.plan_chunk.get("declaration_contract") or {}).get("base") or ""
            ).rsplit(".", 1)[-1]
            if self.declared_base:
                self.required_base_names.add(self.declared_base)
            for self.required_base in sorted(
                (base_name.rsplit(".", 1)[-1] for base_name in self.required_base_names)
            ):
                self.base_requirement_ids = sorted(
                    {
                        str(requirement.get("id") or "")
                        for requirement in self.requirement_rows
                        if self.required_base.casefold()
                        in str(requirement.get("text") or "").casefold()
                    }
                )
                for self.base_record in self.indexed_requested_base_records:
                    if (
                        str(self.base_record.get("name") or "").rsplit(".", 1)[-1]
                        != self.required_base
                    ):
                        continue
                    self.selected_base_record = {
                        **self.base_record,
                        "requirement_ids": self.base_requirement_ids,
                    }
                    if not any(
                        (
                            str(item.get("name") or "")
                            == str(self.selected_base_record.get("name") or "")
                            for item in self.strong_evidence
                        )
                    ):
                        self.strong_evidence.append(self.selected_base_record)
            self.capability_candidates = list(self.strong_evidence)

            def _normalized_capability_terms(value: str) -> set[str]:
                expanded = _deps.re.sub(
                    "(?<=[a-z0-9])(?=[A-Z])", " ", str(value or "").replace("_", " ")
                )
                result: set[str] = set()
                for raw_token in _deps.re.findall("[A-Za-z][A-Za-z0-9]*", expanded):
                    token = raw_token.casefold()
                    result.add(token)
                    if token.endswith("ies") and len(token) > 5:
                        result.add(token[:-3] + "y")
                    elif token.endswith("s") and len(token) > 4:
                        result.add(token[:-1])
                return result

            self._normalized_capability_terms = _normalized_capability_terms

            def _capability_term_overlap(left: set[str], right: set[str]) -> set[str]:
                """Match exact terms plus unambiguous four-character word prefixes."""
                overlap = set(left & right)
                for left_term in left - overlap:
                    if len(left_term) < 4:
                        continue
                    if any(
                        (
                            min(len(left_term), len(right_term)) >= 5
                            and min(len(left_term), len(right_term))
                            / max(len(left_term), len(right_term))
                            >= 0.6
                            and (
                                left_term.startswith(right_term)
                                or right_term.startswith(left_term)
                            )
                            for right_term in right - overlap
                        )
                    ):
                        overlap.add(left_term)
                return overlap

            self._capability_term_overlap = _capability_term_overlap
            self.raw_query_terms = self._normalized_capability_terms(
                self.evidence_query
            )
            self.query_action_terms = {
                "apply",
                "build",
                "connect",
                "convert",
                "copy",
                "create",
                "delete",
                "export",
                "find",
                "generate",
                "get",
                "import",
                "load",
                "normalize",
                "read",
                "report",
                "return",
                "save",
                "set",
                "update",
                "validate",
                "write",
            } & self.raw_query_terms
            self.capability_relevance_terms = (
                self.evidence_terms | self.query_action_terms
            )

            def _deterministic_capability_score(item: dict[str, _deps.Any]) -> int:
                name = str(item.get("name") or "")
                name_tokens = self._normalized_capability_terms(name)
                supports_tokens = self._normalized_capability_terms(
                    str(item.get("supports") or "")
                )
                score = len(supports_tokens & self.capability_relevance_terms) * 6
                score += len(name_tokens & self.query_action_terms) * 25
                score += len(name_tokens & self.capability_relevance_terms) * 6
                short_name = name.rsplit(".", 1)[-1]
                short_name_tokens = self._normalized_capability_terms(short_name)
                if (
                    len(short_name_tokens) >= 2
                    and short_name_tokens <= self.raw_query_terms
                ):
                    score += 60
                owner_short_name = (
                    name.rsplit(".", 1)[0].rsplit(".", 1)[-1]
                    if name.count(".") >= 2
                    else ""
                )
                owner_tokens = self._normalized_capability_terms(owner_short_name)
                if (
                    len(owner_tokens) >= 2
                    and owner_tokens <= self.raw_query_terms
                    and (
                        not owner_tokens
                        & {
                            "editor",
                            "factory",
                            "helper",
                            "helpers",
                            "library",
                            "service",
                            "subsystem",
                            "tool",
                            "tools",
                            "utility",
                        }
                    )
                ):
                    score += 100
                if name.casefold() in self.evidence_query.casefold() or _deps.re.search(
                    f"\\b{_deps.re.escape(short_name)}\\b",
                    self.evidence_query,
                    flags=_deps.re.IGNORECASE,
                ):
                    score += 100
                if self.internal_adapter_evidence_required:
                    lowered_name = name.casefold()
                    provider = str(item.get("provider") or "").casefold()
                    if "adapter" in lowered_name or "bridge" in lowered_name:
                        score += 240
                    if any(
                        (
                            marker in provider
                            for marker in (
                                "project",
                                "intelligence",
                                "internal",
                                "source",
                            )
                        )
                    ):
                        score += 80
                for convenience_term in ("accessibility", "async", "dialog", "style"):
                    if (
                        convenience_term in name.casefold()
                        and convenience_term not in self.evidence_query.casefold()
                    ):
                        score -= 30
                return score

            self._deterministic_capability_score = _deterministic_capability_score
            self.deterministic_ranked = sorted(
                self.capability_candidates,
                key=lambda item: (
                    -self._deterministic_capability_score(item),
                    str(item.get("name") or "").casefold(),
                ),
            )
            self.deterministic_supported = [
                item
                for item in self.deterministic_ranked
                if self._deterministic_capability_score(item) >= 25
            ]
            if (
                len(self.deterministic_supported) >= 4
                and (not self.internal_adapter_evidence_required)
                and (not self.requirement_rows)
            ):
                self.strong_evidence = [
                    *self.deterministic_supported,
                    *[
                        item
                        for item in self.deterministic_ranked
                        if item not in self.deterministic_supported
                    ],
                ]
                self.capability_candidates = []
                if self.status_callback:
                    self.status_callback(
                        f"Selected authoritative APIs deterministically for {self.plan_chunk.get('owner')}: "
                        + ", ".join(
                            (
                                str(item.get("name") or "")
                                for item in self.strong_evidence[:36]
                            )
                        )
                    )
            self.callable_capability_candidates = [
                item
                for item in self.capability_candidates
                if (
                    str(item.get("kind") or "").casefold()
                    not in {"class", "module", "property", "attribute"}
                    and (
                        not str(item.get("signature") or "")
                        .lstrip()
                        .casefold()
                        .startswith("class ")
                    )
                    and (
                        str(item.get("kind") or "").casefold()
                        in {"function", "method", "async_function", "async_method"}
                        or "(" in str(item.get("signature") or "")
                    )
                )
                and str(item.get("name") or "").count(".") >= 2
            ]
            if self.callable_capability_candidates:
                self.capability_candidates = self.callable_capability_candidates
            self.qt_worker_required = any(
                (
                    _deps.re.search(
                        "\\b(?:Qt|PySide|PyQt)\\b[^.!?\\n]{0,120}\\b(?:worker|thread|threadpool|runnable)\\b|\\b(?:worker|thread|threadpool|runnable)\\b[^.!?\\n]{0,120}\\b(?:Qt|PySide|PyQt)\\b",
                        str(requirement.get("text") or ""),
                        flags=_deps.re.IGNORECASE,
                    )
                    for requirement in self.requirement_rows
                )
            )
            if self.qt_worker_required:
                self.qt_candidates = [
                    item
                    for item in self.strong_evidence
                    if _deps.re.search(
                        "(?:^|\\.)(?:PySide[26]|PyQt[56]|QtCore|QtWidgets|QThread|QRunnable|QThreadPool|Signal)(?:\\.|$)",
                        str(item.get("name") or ""),
                        flags=_deps.re.IGNORECASE,
                    )
                ]
                if self.qt_candidates:
                    self.capability_candidates = self.qt_candidates
                self.qt_names = {
                    str(item.get("name") or "").casefold(): item
                    for item in self.qt_candidates
                    if str(item.get("name") or "")
                }
                self.pool_dispatch = next(
                    (
                        item
                        for name, item in self.qt_names.items()
                        if name.endswith(".qthreadpool.start")
                    ),
                    None,
                )
                self.runnable_entry = next(
                    (
                        item
                        for name, item in self.qt_names.items()
                        if name.endswith(".qrunnable.run")
                    ),
                    None,
                )
                self.thread_dispatch = next(
                    (
                        item
                        for name, item in self.qt_names.items()
                        if name.endswith(".qthread.start")
                    ),
                    None,
                )
                self.concurrent_dispatch = next(
                    (
                        item
                        for name, item in self.qt_names.items()
                        if name.endswith(".qtconcurrent.run")
                    ),
                    None,
                )
                self.signal_evidence_required = any(
                    (
                        _deps.re.search(
                            "\\b(?:signal|completion|error|result)\\b",
                            str(requirement.get("text") or ""),
                            flags=_deps.re.IGNORECASE,
                        )
                        for requirement in self.requirement_rows
                    )
                )
                self.signal_record = next(
                    (
                        item
                        for name, item in self.qt_names.items()
                        if name.endswith(".signal")
                    ),
                    None,
                )
                self.worker_bundle: list[dict[str, _deps.Any]] = []
                if self.pool_dispatch and self.runnable_entry:
                    self.worker_bundle.extend([self.pool_dispatch, self.runnable_entry])
                    self.pool_factory = next(
                        (
                            item
                            for name, item in self.qt_names.items()
                            if name.endswith(".qthreadpool.globalinstance")
                        ),
                        None,
                    )
                    if self.pool_factory:
                        self.worker_bundle.insert(0, self.pool_factory)
                elif self.thread_dispatch:
                    self.worker_bundle.append(self.thread_dispatch)
                elif self.concurrent_dispatch:
                    self.worker_bundle.append(self.concurrent_dispatch)
                if self.signal_record:
                    self.worker_bundle.append(self.signal_record)
                self.complete_worker_bundle = (
                    bool(self.worker_bundle)
                    and bool(
                        self.pool_dispatch
                        or self.thread_dispatch
                        or self.concurrent_dispatch
                    )
                    and (
                        not self.signal_evidence_required
                        or self.signal_record is not None
                    )
                )
                if self.complete_worker_bundle:
                    self.requested_base_names = set(
                        _deps.re.findall(
                            "\\b(?:inheriting\\s+from|subclassing|extends)\\s+([A-Z][A-Za-z0-9_.]*)\\b",
                            self.evidence_query,
                            flags=_deps.re.IGNORECASE,
                        )
                    )
                    self.base_dependency_records = [
                        {**item, "dependency_for_selected": True}
                        for item in self.strong_evidence
                        if any(
                            (
                                str(item.get("name") or "").endswith("." + base_name)
                                or str(item.get("name") or "") == base_name
                                for base_name in self.requested_base_names
                            )
                        )
                    ]
                    self.worker_requirement_ids = {
                        str(requirement.get("id") or "")
                        for requirement in self.requirement_rows
                        if _deps.re.search(
                            "\\b(?:worker|thread|threadpool|runnable|blocking)\\b",
                            str(requirement.get("text") or ""),
                            flags=_deps.re.IGNORECASE,
                        )
                    }
                    self.signal_requirement_ids = {
                        str(requirement.get("id") or "")
                        for requirement in self.requirement_rows
                        if _deps.re.search(
                            "\\b(?:signal|completion|error|result)\\b",
                            str(requirement.get("text") or ""),
                            flags=_deps.re.IGNORECASE,
                        )
                    }
                    self.selected_worker_records = []
                    for self.item in {
                        str(value.get("name") or ""): value
                        for value in self.worker_bundle
                        if str(value.get("name") or "")
                    }.values():
                        self.evidence_name = str(self.item.get("name") or "").casefold()
                        self.is_signal = self.evidence_name.endswith(".signal")
                        self.usage_role = (
                            "declaration"
                            if self.is_signal
                            else (
                                "override"
                                if self.evidence_name.endswith(
                                    (".qrunnable.run", ".qthread.run")
                                )
                                else "invoke"
                            )
                        )
                        self.selected_worker_records.append(
                            {
                                **self.item,
                                "selected_for_generation": True,
                                "usage_role": self.usage_role,
                                "requirement_ids": sorted(
                                    self.signal_requirement_ids
                                    if self.is_signal
                                    else self.worker_requirement_ids
                                ),
                            }
                        )
                    self.strong_evidence = [
                        *self.base_dependency_records,
                        *self.selected_worker_records,
                    ]
                    self.capability_candidates = []
                    if self.status_callback:
                        self.status_callback(
                            f"Selected complete verified Qt worker bundle deterministically for {self.plan_chunk.get('owner')}: "
                            + ", ".join(
                                (
                                    str(item.get("name") or "")
                                    for item in self.selected_worker_records
                                )
                            )
                        )
                else:
                    self.missing_worker_evidence = []
                    if not (
                        self.pool_dispatch
                        and self.runnable_entry
                        or self.thread_dispatch
                        or self.concurrent_dispatch
                    ):
                        self.missing_worker_evidence.append("dispatch callable")
                    if self.signal_evidence_required and self.signal_record is None:
                        self.missing_worker_evidence.append("signal declaration")
                    self.unresolved_plan_evidence.append(
                        f"Verified Qt worker evidence is incomplete for {self.plan_chunk.get('owner')}: missing "
                        + ", ".join(self.missing_worker_evidence)
                    )
                    self.capability_candidates = []
            self.explicit_dependency_owners = {
                value
                for value in _deps.re.findall(
                    "\\b([A-Z][A-Za-z0-9_]*?(?:Adapter|Bridge))\\b", self.evidence_query
                )
            }
            self.grounded_owner_evidence = False
            if self.explicit_dependency_owners:
                self.grounded_candidates = [
                    item
                    for item in self.capability_candidates
                    if any(
                        (
                            owner in str(item.get("name") or "").split(".")
                            for owner in self.explicit_dependency_owners
                        )
                    )
                ]
                if self.grounded_candidates:
                    self.capability_candidates = self.grounded_candidates
                    self.grounded_owner_evidence = True
                else:
                    self.capability_candidates = []
                    self.unresolved_plan_evidence.append(
                        "No authoritative callable evidence was found for explicit dependency owners: "
                        + ", ".join(sorted(self.explicit_dependency_owners))
                    )
                if self.status_callback:
                    self.status_callback(
                        "Explicit dependency evidence for "
                        + ", ".join(sorted(self.explicit_dependency_owners))
                        + ": "
                        + (
                            ", ".join(
                                (
                                    str(item.get("name") or "")
                                    for item in self.grounded_candidates
                                )
                            )
                            if self.grounded_candidates
                            else "(none)"
                        )
                    )
            self.deterministic_selected_names: list[str] = []
            self.deterministic_selected_requirements: dict[str, set[str]] = {}
            self.required_callable_ids = {
                str(requirement.get("id") or "")
                for requirement in self.requirement_rows
                if self._requires_callable_evidence(str(requirement.get("text") or ""))
                and str(requirement.get("semantic_role") or "behavior").casefold()
                not in {
                    "constant",
                    "constraint",
                    "documentation",
                    "entry_point",
                    "export",
                    "import",
                    "module_wiring",
                    "package_wiring",
                    "quality",
                    "structure",
                }
            }
            if not self.required_callable_ids:
                self.capability_candidates = []
            self.owner_requires_host_api = any(
                _deps.re.search(
                    r"\b(?:unreal|maya|blender|motionbuilder|bpy|pyfbsdk|"
                    r"PySide|PyQt|Qt|adapter|bridge|API)\b",
                    str(requirement.get("text") or ""),
                    flags=_deps.re.IGNORECASE,
                )
                for requirement in self.requirement_rows
                if str(requirement.get("id") or "")
                in self.required_callable_ids
            )
            if not self.owner_requires_host_api:
                self.capability_candidates = []
            if (
                self.explicit_dependency_owners
                and self.grounded_owner_evidence
                and self.capability_candidates
            ):
                for self.requirement in self.requirement_rows:
                    self.requirement_id = str(self.requirement.get("id") or "")
                    self.requirement_text = str(self.requirement.get("text") or "")
                    if self.requirement_id not in self.required_callable_ids:
                        continue
                    self.requested_members = set(
                        _deps.re.findall(
                            "\\b([A-Z][A-Za-z0-9_]*\\.[a-z_][A-Za-z0-9_]*)\\b",
                            self.requirement_text,
                        )
                    )
                    self.requirement_terms = self._normalized_capability_terms(
                        self.requirement_text
                    )
                    self.linked_candidates = [
                        item
                        for item in self.capability_candidates
                        if self.requirement_id in item.get("requirement_ids", [])
                        or self.requirement_text in item.get("supports", [])
                    ]
                    self.exact_candidates = [
                        item
                        for item in self.linked_candidates
                        if any(
                            (
                                str(item.get("name") or "").endswith("." + member)
                                for member in self.requested_members
                            )
                        )
                    ]
                    self.semantic_stop_terms = {
                        "a",
                        "an",
                        "api",
                        "adapter",
                        "and",
                        "as",
                        "at",
                        "be",
                        "bridge",
                        "by",
                        "call",
                        "do",
                        "for",
                        "from",
                        "get",
                        "in",
                        "is",
                        "it",
                        "method",
                        "of",
                        "on",
                        "or",
                        "set",
                        "that",
                        "the",
                        "then",
                        "this",
                        "through",
                        "to",
                        "use",
                        "using",
                        "via",
                        "with",
                    }

                    def _requirement_member_score(
                        candidate: _deps.Mapping[str, _deps.Any],
                    ) -> int:
                        candidate_name = str(candidate.get("name") or "")
                        member_terms = (
                            self._normalized_capability_terms(
                                candidate_name.rsplit(".", 1)[-1]
                            )
                            - self.semantic_stop_terms
                        )
                        score = (
                            len(
                                self._capability_term_overlap(
                                    member_terms, self.requirement_terms
                                )
                            )
                            * 10
                        )
                        owner_name = candidate_name.rsplit(".", 1)[0].rsplit(".", 1)[-1]
                        owner_terms = (
                            self._normalized_capability_terms(owner_name)
                            - self.semantic_stop_terms
                        )
                        score += (
                            len(
                                self._capability_term_overlap(
                                    owner_terms, self.requirement_terms
                                )
                            )
                            * 3
                        )
                        return score

                    self._requirement_member_score = _requirement_member_score
                    self.semantic_candidates: list[dict[str, _deps.Any]] = []
                    if not self.exact_candidates:
                        self.scored_candidates = [
                            (self._requirement_member_score(item), item)
                            for item in self.linked_candidates
                        ]
                        self.best_score = max(
                            (score for score, _item in self.scored_candidates),
                            default=0,
                        )
                        if self.best_score > 0:
                            self.semantic_candidates = [
                                item
                                for score, item in sorted(
                                    self.scored_candidates,
                                    key=lambda pair: (
                                        -pair[0],
                                        str(pair[1].get("name") or "").casefold(),
                                    ),
                                )
                                if score == self.best_score
                            ][:4]
                        self.universal_match = _deps.re.search(
                            "\\b(?:both|all)\\b[^,.;]{0,80}",
                            self.requirement_text,
                            flags=_deps.re.IGNORECASE,
                        )
                        self.universal_terms = (
                            self._normalized_capability_terms(
                                self.universal_match.group(0)
                            )
                            - self.semantic_stop_terms
                            if self.universal_match
                            else set()
                        )
                        self.universal_members = {
                            str(item.get("name") or "").rsplit(".", 1)[-1]
                            for item in self.semantic_candidates
                            if self._normalized_capability_terms(
                                str(item.get("name") or "").rsplit(".", 1)[-1]
                            )
                            - self.semantic_stop_terms
                            & self.universal_terms
                        }
                        if self.universal_members:
                            self.expanded_semantic_candidates = [
                                *self.semantic_candidates,
                                *[
                                    item
                                    for item in self.capability_candidates
                                    if str(item.get("name") or "").rsplit(".", 1)[-1]
                                    in self.universal_members
                                    and any(
                                        (
                                            owner
                                            in str(item.get("name") or "").split(".")
                                            for owner in self.explicit_dependency_owners
                                        )
                                    )
                                ],
                            ]
                            self.semantic_candidates = list(
                                {
                                    str(item.get("name") or ""): item
                                    for item in self.expanded_semantic_candidates
                                    if str(item.get("name") or "")
                                }.values()
                            )
                    self.selected_requirement_candidates = [
                        *self.exact_candidates,
                        *self.semantic_candidates,
                    ]
                    self.deterministic_selected_names.extend(
                        (
                            str(item.get("name") or "")
                            for item in self.selected_requirement_candidates
                            if str(item.get("name") or "")
                        )
                    )
                    for self.item in self.selected_requirement_candidates:
                        self.selected_name = str(self.item.get("name") or "")
                        if self.selected_name:
                            self.deterministic_selected_requirements.setdefault(
                                self.selected_name, set()
                            ).add(self.requirement_id)
                self.deterministic_selected_names = list(
                    dict.fromkeys(self.deterministic_selected_names)
                )
                self.covered_callable_ids = {
                    requirement_id
                    for name in self.deterministic_selected_names
                    for item in self.capability_candidates
                    if str(item.get("name") or "") == name
                    for requirement_id in item.get("requirement_ids", [])
                }
                if self.required_callable_ids <= self.covered_callable_ids:
                    self.selected_owner_names = {
                        name.rsplit(".", 1)[0]
                        for name in self.deterministic_selected_names
                    }
                    self.selected_records = [
                        {
                            **item,
                            "selected_for_generation": True,
                            "usage_role": (
                                "access"
                                if item.get("access_kind") == "property"
                                else "invoke"
                            ),
                            "requirement_ids": sorted(
                                self.deterministic_selected_requirements.get(
                                    str(item.get("name") or ""), set()
                                )
                            ),
                        }
                        for item in self.capability_candidates
                        if str(item.get("name") or "")
                        in self.deterministic_selected_names
                    ]
                    self.dependency_records = [
                        {**item, "dependency_for_selected": True}
                        for item in self.strong_evidence
                        if str(item.get("name") or "") in self.selected_owner_names
                    ]
                    self.strong_evidence = [
                        *[
                            item
                            for item in self.strong_evidence
                            if item.get("dependency_for_selected")
                            or str(item.get("usage_role") or "") == "inheritance"
                        ],
                        *self.dependency_records,
                        *self.selected_records,
                    ]
                    self.capability_candidates = []
                    if self.status_callback:
                        self.status_callback(
                            f"Selected explicitly owned verified APIs deterministically for {self.plan_chunk.get('owner')}: "
                            + ", ".join(self.deterministic_selected_names)
                        )
            if self.capability_candidates:
                self.behavior_clauses = list(
                    dict.fromkeys(
                        (
                            str(requirement.get("text") or "").strip()
                            for requirement in self.requirement_rows
                            if self._requires_callable_evidence(
                                str(requirement.get("text") or "")
                            )
                        )
                    )
                )
                self.selection_stop_terms = {
                    "a",
                    "an",
                    "and",
                    "api",
                    "as",
                    "at",
                    "be",
                    "both",
                    "by",
                    "call",
                    "class",
                    "code",
                    "during",
                    "each",
                    "existing",
                    "file",
                    "for",
                    "from",
                    "function",
                    "in",
                    "internal",
                    "into",
                    "is",
                    "it",
                    "method",
                    "module",
                    "must",
                    "of",
                    "on",
                    "or",
                    "our",
                    "project",
                    "requested",
                    "that",
                    "the",
                    "their",
                    "then",
                    "this",
                    "through",
                    "to",
                    "use",
                    "using",
                    "via",
                    "when",
                    "which",
                    "with",
                }
                self.deterministic_matches: dict[str, dict[str, _deps.Any]] = {}
                for self.clause in self.behavior_clauses:
                    self.clause_requirement_ids = {
                        str(
                            requirement.get("id")
                            or requirement.get("requirement_id")
                            or ""
                        ).strip()
                        for requirement in self.requirement_rows
                        if str(requirement.get("text") or "").strip() == self.clause
                    }
                    self.clause_requirement_ids.discard("")
                    self.clause_terms = (
                        self._normalized_capability_terms(self.clause)
                        - self.selection_stop_terms
                    )
                    self.ranked_candidates: list[
                        tuple[int, int, dict[str, _deps.Any]]
                    ] = []
                    for self.candidate in self.capability_candidates:
                        self.candidate_name = str(
                            self.candidate.get("name") or ""
                        )
                        self.explicit_support_match = bool(
                            self.candidate_name.casefold() in self.clause.casefold()
                            or any(
                                str(support).casefold() in self.clause.casefold()
                                for support in self.candidate.get("supports") or []
                                if str(support).strip()
                            )
                        )
                        self.candidate_text = " ".join(
                            (
                                str(self.candidate.get(field) or "")
                                for field in (
                                    "name",
                                    "signature",
                                    "supports",
                                    "query_links",
                                )
                            )
                        )
                        self.candidate_terms = (
                            self._normalized_capability_terms(self.candidate_text)
                            - self.selection_stop_terms
                        )
                        self.overlap = self._capability_term_overlap(
                            self.clause_terms, self.candidate_terms
                        )
                        if not self.overlap:
                            continue
                        self.leaf_terms = self._normalized_capability_terms(
                            str(self.candidate.get("name") or "").rsplit(".", 1)[-1]
                        )
                        self.leaf_overlap_count = len(
                            self._capability_term_overlap(
                                self.clause_terms, self.leaf_terms
                            )
                        )
                        self.score = (
                            len(self.overlap) * 5
                            + self.leaf_overlap_count * 8
                            + (
                                4
                                if bool(self.candidate.get("authoritative_signature"))
                                else 0
                            )
                        )
                        if self.explicit_support_match:
                            self.score += 1000
                        if (
                            str(self.candidate.get("provider") or "")
                            == "host_adapter_capability_index"
                        ):
                            self.support_capability_terms = {
                                token.casefold()
                                for support in self.candidate.get("supports") or []
                                for token in _deps.re.findall(
                                    "[A-Za-z_][A-Za-z0-9_]{2,}",
                                    str(support).partition("=")[2] or str(support),
                                )
                                if token.casefold() not in {"capability_terms", "host"}
                            }
                            self.support_hosts = {
                                str(support).partition("=")[2].casefold()
                                for support in self.candidate.get("supports") or []
                                if str(support).startswith("host=")
                            }
                            if self._capability_term_overlap(
                                self.clause_terms, self.support_capability_terms
                            ) and (
                                not self.support_hosts
                                or self.support_hosts & self.clause_terms
                            ):
                                self.score += 100
                        self.ranked_candidates.append(
                            (self.score, self.leaf_overlap_count, self.candidate)
                        )
                    self.explicit_ranked_candidates = [
                        pair for pair in self.ranked_candidates
                        if pair[0] >= 1000
                    ]
                    self.maximum_leaf_overlap = max(
                        (pair[1] for pair in self.ranked_candidates), default=0
                    )
                    if self.explicit_ranked_candidates:
                        self.ranked_candidates = self.explicit_ranked_candidates
                    elif self.maximum_leaf_overlap:
                        self.ranked_candidates = [
                            pair
                            for pair in self.ranked_candidates
                            if pair[1] == self.maximum_leaf_overlap
                        ]
                    self.ordered_ranked_candidates = sorted(
                        self.ranked_candidates,
                        key=lambda pair: (
                            -pair[0],
                            str(pair[2].get("name") or "").casefold(),
                        ),
                    )
                    self.admissible_ranked_candidates = [
                        pair
                        for pair in self.ordered_ranked_candidates
                        if _deps._production_evidence_candidate_is_admissible(
                            pair[2], self.requirement_rows
                        )
                    ]
                    self.best_ranked_score = (
                        self.admissible_ranked_candidates[0][0]
                        if self.admissible_ranked_candidates
                        else 0
                    )
                    self.selected_ranked_candidates = (
                        [
                            pair
                            for pair in self.admissible_ranked_candidates
                            if pair[0] >= 1000
                        ]
                        or [
                            pair
                            for pair in self.admissible_ranked_candidates
                            if pair[0] == self.best_ranked_score
                        ][:3]
                    )
                    for self._score, self._leaf_overlap, self.candidate in (
                        self.selected_ranked_candidates
                    ):
                        self.candidate_name = str(self.candidate.get("name") or "")
                        if self.candidate_name:
                            self.candidate_signature = str(
                                self.candidate.get("signature") or ""
                            )
                            self.candidate_import_statement = str(
                                self.candidate.get("import_statement") or ""
                            )
                            if not self.candidate_import_statement and (
                                not _deps.re.search(
                                    "\\(\\s*(?:self|cls)\\b", self.candidate_signature
                                )
                            ):
                                self.module_path, self.separator, self.binding_name = (
                                    self.candidate_name.rpartition(".")
                                )
                                if (
                                    self.separator
                                    and self.module_path
                                    and _deps.re.fullmatch(
                                        "[A-Za-z_][A-Za-z0-9_]*", self.binding_name
                                    )
                                ):
                                    self.candidate_import_statement = f"from {self.module_path} import {self.binding_name}"
                            self.selected = self.deterministic_matches.setdefault(
                                self.candidate_name,
                                {
                                    **self.candidate,
                                    "import_statement": self.candidate_import_statement,
                                    "selected_for_generation": True,
                                    "usage_role": (
                                        "access"
                                        if self.candidate.get("access_kind")
                                        == "property"
                                        else "invoke"
                                    ),
                                    "requirement_ids": [],
                                },
                            )
                            self.selected["requirement_ids"] = sorted(
                                {
                                    *[
                                        str(value)
                                        for value in self.selected.get(
                                            "requirement_ids", []
                                        )
                                        if str(value)
                                    ],
                                    *self.clause_requirement_ids,
                                }
                            )
                if self.deterministic_matches:
                    self.strong_evidence = [
                        *self.strong_evidence,
                        *self.deterministic_matches.values(),
                    ]
                    self.capability_candidates = []
                    if self.status_callback:
                        self.status_callback(
                            f"Selected verified APIs by deterministic owner-clause ranking for {self.plan_chunk.get('owner')}: "
                            + ", ".join(self.deterministic_matches)
                        )
            if self.capability_candidates:
                self.behavior_clauses = list(
                    dict.fromkeys(
                        (
                            str(requirement.get("text") or "").strip()
                            for requirement in self.requirement_rows
                            if self._requires_callable_evidence(
                                str(requirement.get("text") or "")
                            )
                        )
                    )
                )
                self.dependency_requirement_rows = [
                    row
                    for row in self.requirement_rows
                    if _deps.re.search(
                        "\\b(?:use|using|through|via|call|invoke)\\b.*\\b(?:internal|api|adapter|bridge|capability|callable|service|sdk)\\b|\\b(?:internal|api|adapter|bridge|capability|callable|service|sdk)\\b.*\\b(?:use|using|through|via|call|invoke)\\b|\\brather\\s+than\\s+import(?:ing)?\\b",
                        str(row.get("text") or row.get("requirement") or ""),
                        flags=_deps.re.IGNORECASE,
                    )
                ]
                self.capability_requirement_rows = (
                    self.dependency_requirement_rows or self.requirement_rows
                )
                self.capability_requirement_ids = {
                    str(row.get("id") or row.get("requirement_id") or "")
                    for row in self.capability_requirement_rows
                    if str(row.get("id") or row.get("requirement_id") or "")
                }
                self.capability_requirement_texts = {
                    str(row.get("text") or row.get("requirement") or "")
                    for row in self.capability_requirement_rows
                    if str(row.get("text") or row.get("requirement") or "")
                }
                self.capability_candidates = [
                    item
                    for item in self.capability_candidates
                    if _deps._production_evidence_candidate_is_admissible(
                        item, self.capability_requirement_rows
                    )
                    and (
                        not self.capability_requirement_ids
                        or self.capability_requirement_ids.intersection(
                            (str(value) for value in item.get("requirement_ids") or [])
                        )
                        or self.capability_requirement_texts.intersection(
                            (str(value) for value in item.get("supports") or [])
                        )
                    )
                ]
                self.minimum_api_selections = 1 if self.capability_candidates else 0
                self.diverse_capability_candidates: list[dict[str, _deps.Any]] = []
                self.capability_owner_counts: dict[str, int] = {}
                for self.owner_round in range(1, 4):
                    for self.item in self.capability_candidates:
                        self.owner_name = str(self.item.get("name") or "").rsplit(
                            ".", 1
                        )[0]
                        if (
                            self.capability_owner_counts.get(self.owner_name, 0)
                            >= self.owner_round
                        ):
                            continue
                        self.diverse_capability_candidates.append(self.item)
                        self.capability_owner_counts[self.owner_name] = (
                            self.capability_owner_counts.get(self.owner_name, 0) + 1
                        )
                        if len(self.diverse_capability_candidates) >= 64:
                            break
                    if len(self.diverse_capability_candidates) >= 64:
                        break
                self.candidate_ids = {
                    f"A{index:03d}": item
                    for index, item in enumerate(
                        self.diverse_capability_candidates, start=1
                    )
                }
                self.capability_stage = _deps.ProjectEditPromptStage(
                    key="capability_api_selection",
                    label="Selecting relevant verified APIs",
                    system_prompt="You select APIs only from an authoritative, production-admissible candidate set that has already been filtered for the requirement's provider and ownership constraints. Return JSON only. Never add, rename, infer, or substitute an API. Existence is not applicability: select a candidate only when its callable semantics directly perform a required operation. Return no selection when none applies. Tests, examples, fixtures, and broad keyword neighbors cannot authorize production code. Select candidate IDs, not API names. Each ID is an opaque exact reference to one verified callable member.",
                    user_prompt=_deps.json.dumps(
                        {
                            "requirement": "\n".join(
                                sorted(self.capability_requirement_texts)
                            ),
                            "required_behavior_clauses": [
                                clause
                                for clause in self.behavior_clauses
                                if any(
                                    (
                                        requirement_text in clause
                                        or clause in requirement_text
                                        for requirement_text in self.capability_requirement_texts
                                    )
                                )
                            ],
                            "minimum_selected_ids": self.minimum_api_selections,
                            "candidates": [
                                {
                                    "id": candidate_id,
                                    "name": item.get("name"),
                                    "signature": item.get("signature"),
                                    "supports": item.get("supports"),
                                }
                                for candidate_id, item in self.candidate_ids.items()
                            ],
                            "output": {
                                "selections": [
                                    {
                                        "id": "candidate ID",
                                        "supports": ["exact required behavior clause"],
                                    }
                                ]
                            },
                        },
                        ensure_ascii=True,
                        separators=(",", ":"),
                    ),
                    model_tier="local_reasoning",
                    num_ctx=4096,
                    num_predict=500,
                    timeout=45,
                    no_progress_seconds=20,
                    prefer_coder=False,
                    coder_preference="fast",
                    response_format="json",
                )
                self.capability_response, self.capability_timing = _deps._query_stage(
                    self.capability_stage,
                    selected_model=_deps._causal_repair_escalation_model(
                        self.settings, self.selected_model
                    ),
                    settings=self.settings,
                    timeout=self.timeout,
                )
                self.capability_timing["owner"] = str(
                    self.plan_chunk.get("owner") or ""
                )
                self.timings.append(self.capability_timing)
                try:
                    self.capability_payload = _deps.json.loads(self.capability_response)
                except (TypeError, ValueError, _deps.json.JSONDecodeError):
                    self.capability_payload = {}
                self.candidate_by_name = {
                    str(item.get("name") or ""): item
                    for item in self.capability_candidates
                    if str(item.get("name") or "")
                }
                self.selected_supports: dict[str, list[str]] = {}

                def _selected_api_values(payload: _deps.Any) -> list[str]:
                    if not isinstance(payload, dict):
                        return []
                    direct = (
                        payload.get("selections")
                        or payload.get("selected_ids")
                        or payload.get("ids")
                        or payload.get("selected")
                        or payload.get("selected_apis")
                        or payload.get("apis")
                        or []
                    )
                    if isinstance(direct, list) and direct:
                        selected_values: list[str] = []
                        for item in direct:
                            if isinstance(item, _deps.Mapping):
                                selected_id = str(
                                    item.get("id")
                                    or item.get("candidate_id")
                                    or item.get("name")
                                    or ""
                                )
                                if selected_id:
                                    selected_values.append(selected_id)
                                    supports = [
                                        str(clause)
                                        for clause in item.get("supports") or []
                                        if str(clause) in self.behavior_clauses
                                    ]
                                    if supports:
                                        self.selected_supports[selected_id] = supports
                            else:
                                selected_values.append(str(item))
                        return selected_values
                    recovered: list[str] = []

                    def visit(value: _deps.Any, *, key: str = "") -> None:
                        if key.casefold() in {
                            "candidates",
                            "requirement",
                            "required_behavior_clauses",
                            "output",
                        }:
                            return
                        if isinstance(value, dict):
                            for child_key, child_value in value.items():
                                visit(child_value, key=str(child_key))
                        elif isinstance(value, list):
                            for child in value:
                                visit(child, key=key)
                        elif isinstance(value, str):
                            recovered.extend(_deps.re.findall("\\bA\\d{3}\\b", value))
                            if value in self.candidate_by_name:
                                recovered.append(value)

                    visit(payload)
                    return list(dict.fromkeys(recovered))

                self._selected_api_values = _selected_api_values
                self.raw_selected_capabilities = self._selected_api_values(
                    self.capability_payload
                )
                self.selected_capability_names = list(
                    dict.fromkeys(
                        (
                            str(
                                self.candidate_ids[str(item)].get("name")
                                if str(item) in self.candidate_ids
                                else item
                            )
                            for item in self.raw_selected_capabilities
                            if str(item) in self.candidate_ids
                            or str(item) in self.candidate_by_name
                        )
                    )
                )
                self.selected_capability_owners = {
                    name.rsplit(".", 1)[0] for name in self.selected_capability_names
                }
                self.required_owner_count = min(2, self.minimum_api_selections)
                if (
                    len(self.selected_capability_names) < self.minimum_api_selections
                    or len(self.selected_capability_owners) < self.required_owner_count
                ):
                    if self.status_callback:
                        self.status_callback(
                            f"Semantic API selection did not cover enough behavior clauses and distinct capability owners ({len(self.selected_capability_names)}/{self.minimum_api_selections}); escalating the same verified candidate set to the coding model. Response: "
                            + str(self.capability_response or "")[:1200]
                        )
                    self.capability_response, self.capability_timing = (
                        _deps._query_stage(
                            self.capability_stage,
                            selected_model=self.selected_model,
                            settings=self.settings,
                            timeout=self.timeout,
                            suffix=f'\n\nCORRECTION: Return exactly {{"selections":[{{"id":"A001","supports":["an exact supplied behavior clause"]}}]}}, with at least {self.minimum_api_selections} distinct IDs. Select only IDs present in the candidates and map every required behavior clause to supporting IDs. Do not repeat the requirement, candidates, or output schema.',
                        )
                    )
                    self.capability_timing.update(
                        {
                            "owner": str(self.plan_chunk.get("owner") or ""),
                            "reason": "capability_selection_escalation",
                        }
                    )
                    self.timings.append(self.capability_timing)
                    try:
                        self.capability_payload = _deps.json.loads(
                            self.capability_response
                        )
                    except (TypeError, ValueError, _deps.json.JSONDecodeError):
                        self.capability_payload = {}
                    self.raw_selected_capabilities = self._selected_api_values(
                        self.capability_payload
                    )
                    self.selected_capability_names = list(
                        dict.fromkeys(
                            (
                                str(
                                    self.candidate_ids[str(item)].get("name")
                                    if str(item) in self.candidate_ids
                                    else item
                                )
                                for item in self.raw_selected_capabilities
                                if str(item) in self.candidate_ids
                                or str(item) in self.candidate_by_name
                            )
                        )
                    )
                    self.selected_capability_owners = {
                        name.rsplit(".", 1)[0]
                        for name in self.selected_capability_names
                    }
                    if (
                        len(self.selected_capability_names)
                        < self.minimum_api_selections
                        or len(self.selected_capability_owners)
                        < self.required_owner_count
                    ):
                        self.selected_capability_names = []
                if self.selected_capability_names:
                    self.selected_records: list[dict[str, _deps.Any]] = []
                    self.selected_owner_names = {
                        name.rsplit(".", 1)[0]
                        for name in self.selected_capability_names
                    }
                    for self.name in self.selected_capability_names:
                        self.selected = dict(self.candidate_by_name[self.name])
                        self.candidate_id = next(
                            (
                                candidate_id
                                for candidate_id, candidate in self.candidate_ids.items()
                                if candidate is self.candidate_by_name[self.name]
                            ),
                            "",
                        )
                        self.semantic_supports = self.selected_supports.get(
                            self.candidate_id, self.selected_supports.get(self.name, [])
                        )
                        self.semantic_requirement_ids = [
                            str(requirement.get("id") or "")
                            for requirement in self.requirement_rows
                            if any(
                                (
                                    support in str(requirement.get("text") or "")
                                    or str(requirement.get("text") or "") in support
                                    for support in self.semantic_supports
                                )
                            )
                        ]
                        if self.semantic_requirement_ids:
                            self.selected["requirement_ids"] = list(
                                dict.fromkeys(self.semantic_requirement_ids)
                            )
                            self.selected["supports"] = list(
                                dict.fromkeys(self.semantic_supports)
                            )
                        else:
                            self.selected["supports"] = list(
                                dict.fromkeys(
                                    [
                                        *list(self.selected.get("supports") or []),
                                        *self.semantic_supports,
                                    ]
                                )
                            )
                        self.selected["query_links"] = list(
                            dict.fromkeys(
                                [
                                    *list(self.selected.get("query_links") or []),
                                    *self.semantic_supports,
                                ]
                            )
                        )
                        self.selected["selected_for_generation"] = True
                        self.selected["usage_role"] = (
                            "access"
                            if self.selected.get("access_kind") == "property"
                            else "invoke"
                        )
                        self.selected_records.append(self.selected)
                    self.dependency_records = [
                        {**item, "dependency_for_selected": True}
                        for item in self.strong_evidence
                        if str(item.get("name") or "") in self.selected_owner_names
                    ]
                    self.strong_evidence = [
                        *self.dependency_records,
                        *self.selected_records,
                    ]
                    if self.status_callback:
                        self.status_callback(
                            f"Verified API selection for {self.plan_chunk.get('owner')}: "
                            + ", ".join(self.selected_capability_names)
                        )
                elif self.status_callback:
                    self.status_callback(
                        "Rejected API selector response; no exact verified candidate names were returned: "
                        + str(self.capability_response or "")[:1200]
                    )
            self.plan_chunk["evidence"] = list(self.strong_evidence)
            self.plan_chunk["requirement_evidence"] = []
            for self.requirement in self.requirement_rows:
                self.requirement_id = str(self.requirement.get("id") or "")
                self.requirement_text = str(self.requirement.get("text") or "")
                self.owned_evidence = [
                    item
                    for item in self.strong_evidence
                    if self.requirement_id in item.get("requirement_ids", [])
                    or self.requirement_text in item.get("supports", [])
                ]
                self.plan_chunk["requirement_evidence"].append(
                    {
                        "requirement_id": self.requirement_id,
                        "requires_callable_evidence": self._requires_callable_evidence(
                            self.requirement_text
                        ),
                        "evidence": sorted(
                            self.owned_evidence,
                            key=lambda item: (
                                int(
                                    item.get("evidence_rank")
                                    if item.get("evidence_rank") is not None
                                    else 99
                                ),
                                str(item.get("name") or "").casefold(),
                            ),
                        ),
                    }
                )
            self.plan_chunk["evidence_queries"] = list(
                self.evidence_packet.get("queries") or []
            )
            self.plan_chunk["unresolved_host_api_queries"] = list(
                self.evidence_packet.get("unresolved_host_api_queries") or []
            )
            self.plan_chunk["capability_acquisition_requests"] = list(
                self.evidence_packet.get("capability_acquisition_requests") or []
            )
            self.plan_chunk["unresolved_capability_intents"] = list(
                self.evidence_packet.get("unresolved_capability_intents") or []
            )
            self.implementation_plan.setdefault(
                "capability_acquisition_requests", []
            ).extend(self.plan_chunk["capability_acquisition_requests"])
            self.unresolved_plan_evidence.extend(
                (
                    f"{self.plan_chunk.get('path')}:{self.plan_chunk.get('owner')} -> {query}"
                    for query in self.plan_chunk["unresolved_host_api_queries"]
                )
            )
            self.unresolved_plan_evidence.extend(
                (
                    f"{self.plan_chunk.get('path')}:{self.plan_chunk.get('owner')} -> {intent.get('source_clause') or intent.get('query')}"
                    for intent in self.plan_chunk["unresolved_capability_intents"]
                )
            )
        from tech_connector.services.plan_data_flow_contract_service import (
            materialize_plan_data_flow_contracts,
        )

        self.materialize_plan_data_flow_contracts = materialize_plan_data_flow_contracts
        self.data_flow_contracts = self.materialize_plan_data_flow_contracts(
            self.implementation_plan
        )
        self.implementation_plan["data_flow_contracts"] = self.data_flow_contracts
        for self.contract_chunk in self.implementation_plan.get("chunks") or []:
            if not isinstance(self.contract_chunk, dict):
                continue
            self.contract_path = str(self.contract_chunk.get("path") or "")
            self.contract_owner = str(self.contract_chunk.get("owner") or "<module>")
            self.contract_chunk["callable_surface_contracts"] = [
                item
                for item in self.data_flow_contracts.get("callable_surfaces") or []
                if str(item.get("path") or "") == self.contract_path
                and str(item.get("owner") or "<module>") == self.contract_owner
            ]
            self.contract_chunk["data_flow_binding_obligations"] = [
                item
                for item in self.data_flow_contracts.get("binding_obligations") or []
                if str(item.get("path") or "") == self.contract_path
                and str(item.get("owner") or "<module>") == self.contract_owner
            ]
            self.contract_chunk["evidence_reuse_policy"] = {
                "evidence_is_immutable_for_owner": True,
                "repair_must_reuse_evidence_ids": [
                    str(item.get("evidence_id") or "")
                    for item in self.contract_chunk["callable_surface_contracts"]
                    if str(item.get("evidence_id") or "")
                ],
                "refresh_only_when": [
                    "index revision changed",
                    "validator disproved the stored signature or access kind",
                    "generation reports an exact unanswered evidence question",
                ],
            }
            from tech_connector.services.generation_evidence_request_service import (
                evidence_request_protocol,
            )

            self.evidence_request_protocol = evidence_request_protocol
            self.contract_chunk["generation_evidence_request_protocol"] = (
                self.evidence_request_protocol()
            )
        self.unresolved_plan_evidence.extend(
            (str(value) for value in self.data_flow_contracts.get("hard_errors") or [])
        )
        if self.status_callback:
            self.data_flow_summary = self.data_flow_contracts.get("summary") or {}
            self.status_callback(
                f"Plan data-flow contracts: {self.data_flow_summary.get('selected_callable_count', 0)} callables, {self.data_flow_summary.get('binding_obligation_count', 0)} bindings, {self.data_flow_summary.get('hard_error_count', 0)} hard errors"
            )
        if self.internal_adapter_evidence_required and (
            not any(
                (
                    bool(item.get("selected_for_generation"))
                    for chunk in self.implementation_plan.get("chunks") or []
                    if isinstance(chunk, _deps.Mapping)
                    for item in chunk.get("evidence") or []
                    if isinstance(item, _deps.Mapping)
                )
            )
        ):
            self.method_contract_errors.append(
                "Exclusive internal dependency ownership was requested, but no exact indexed callable was selected for generation. Generation is blocked rather than substituting a direct host API or unrelated usage example."
            )
        for self.module_chunk in (
            chunk
            for chunk in self.implementation_plan.get("chunks") or []
            if isinstance(chunk, _deps.Mapping)
            and str(chunk.get("kind") or "") == "module"
        ):
            self.module_path = str(self.module_chunk.get("path") or "")
            self.unowned_behavior_ids = [
                str(requirement.get("id") or "")
                for requirement in self.module_chunk.get("requirements") or []
                if isinstance(requirement, _deps.Mapping)
                and str(requirement.get("semantic_role") or "behavior")
                in {"behavior", "integration", "interaction"}
                and (
                    not _deps.re.search(
                        "\\b(?:__main__|entry\\s+point|module\\s+docstring|imports?|constants?|exports?|package\\s+wiring)\\b",
                        str(requirement.get("text") or ""),
                        flags=_deps.re.IGNORECASE,
                    )
                )
            ]
            if self.unowned_behavior_ids:
                self.method_contract_errors.append(
                    f"{self.module_path}: executable requirements "
                    + ", ".join(self.unowned_behavior_ids)
                    + " remain owned only by <module>. Assign each behavior to an exact class or function declaration before generation; module ownership is valid only for imports, constants, exports, package wiring, and entry points."
                )
        self.timings.append(
            {
                "stage": "plan_symbol_evidence",
                "label": "Resolving chunk symbol and API evidence",
                "model": "deterministic_federated_evidence",
                "elapsed_ms": (_deps.time.perf_counter() - self.evidence_started)
                * 1000.0,
            }
        )
        from tech_connector.services.implementation_plan_quality_service import (
            apply_deterministic_implementation_plan_repairs,
            enrich_implementation_plan,
            implementation_plan_approval_id,
            load_approved_plan_candidate,
            materialize_threaded_progress_declarations,
            persist_approved_plan_candidate,
            validate_generated_files_against_implementation_plan,
            validate_implementation_plan_completeness,
        )

        self.apply_deterministic_implementation_plan_repairs = (
            apply_deterministic_implementation_plan_repairs
        )
        self.enrich_implementation_plan = enrich_implementation_plan
        self.implementation_plan_approval_id = implementation_plan_approval_id
        self.load_approved_plan_candidate = load_approved_plan_candidate
        self.materialize_threaded_progress_declarations = (
            materialize_threaded_progress_declarations
        )
        self.persist_approved_plan_candidate = persist_approved_plan_candidate
        self.validate_generated_files_against_implementation_plan = (
            validate_generated_files_against_implementation_plan
        )
        self.validate_implementation_plan_completeness = (
            validate_implementation_plan_completeness
        )
        if not self.early_cached_approval:
            self.implementation_plan = self.enrich_implementation_plan(
                self.implementation_plan,
                original_prompt=self.user_prompt,
                manifest=self.manifest,
            )
            self.data_flow_contracts = self.materialize_plan_data_flow_contracts(
                self.implementation_plan
            )
            self.implementation_plan["data_flow_contracts"] = self.data_flow_contracts
            for self.contract_chunk in self.implementation_plan.get("chunks") or []:
                if not isinstance(self.contract_chunk, dict):
                    continue
                self.contract_path = str(self.contract_chunk.get("path") or "")
                self.contract_owner = str(
                    self.contract_chunk.get("owner") or "<module>"
                )
                self.contract_chunk["callable_surface_contracts"] = [
                    item
                    for item in self.data_flow_contracts.get("callable_surfaces", [])
                    if str(item.get("path") or "") == self.contract_path
                    and str(item.get("owner") or "<module>") == self.contract_owner
                ]
                self.contract_chunk["data_flow_binding_obligations"] = [
                    item
                    for item in self.data_flow_contracts.get("binding_obligations", [])
                    if str(item.get("path") or "") == self.contract_path
                    and str(item.get("owner") or "<module>") == self.contract_owner
                ]
            if self.status_callback:
                self.refreshed_summary = self.data_flow_contracts.get("summary") or {}
                self.status_callback(
                    f"Refreshed enriched plan data-flow contracts: {self.refreshed_summary.get('selected_callable_count', 0)} callables, {self.refreshed_summary.get('binding_obligation_count', 0)} bindings, {self.refreshed_summary.get('hard_error_count', 0)} hard errors"
                )
        self.plan_chunks = [
            chunk
            for chunk in self.implementation_plan.get("chunks") or []
            if isinstance(chunk, dict)
        ]
        self.injected_time_chunk_ids = {
            str(chunk.get("chunk_id") or "")
            for chunk in self.plan_chunks
            if any(
                (
                    _deps.re.search(
                        "\\b(?:clock|time_source|monotonic_clock)\\s*:\\s*Callable\\[\\[\\],\\s*float\\]",
                        str(signature),
                    )
                    for signature in (chunk.get("declaration_contract") or {}).get(
                        "callable_signatures"
                    )
                    or []
                )
            )
            or any(
                (
                    "stored injected monotonic" in str(step).casefold()
                    for mechanic in chunk.get("implementation_mechanics") or []
                    if isinstance(mechanic, dict)
                    for step in mechanic.get("steps") or []
                )
            )
        }
        if self.injected_time_chunk_ids:
            for self.plan_chunk in self.plan_chunks:
                if str(self.plan_chunk.get("kind") or "") != "module":
                    continue
                self.module_requirements = " ".join(
                    (
                        str(requirement.get("text") or "")
                        for requirement in self.plan_chunk.get("requirements") or []
                        if isinstance(requirement, dict)
                    )
                )
                if not _deps.re.search(
                    "\\b(?:demonstrat|example|expir|deadline|timeout)\\w*\\b",
                    self.module_requirements,
                    flags=_deps.re.IGNORECASE,
                ):
                    continue
                self.plan_chunk.setdefault("implementation_mechanics", []).append(
                    {
                        "requirement_id": ",".join(
                            (
                                str(requirement.get("id") or "")
                                for requirement in self.plan_chunk.get("requirements")
                                or []
                                if isinstance(requirement, dict)
                            )
                        ),
                        "steps": [
                            "Demonstrate time-dependent behavior with a mutable fake injected clock/time source and advance its returned value directly. Never sleep or call a host clock in the runnable example."
                        ],
                    }
                )
        for self.plan_chunk in self.implementation_plan.get("chunks") or []:
            if (
                not isinstance(self.plan_chunk, dict)
                or str(self.plan_chunk.get("kind") or "") != "class"
            ):
                continue
            self.declaration_contract = (
                self.plan_chunk.get("declaration_contract") or {}
            )
            self.owner_name = str(self.plan_chunk.get("owner") or "")
            self.owner_is_error = self.owner_name.endswith(("Error", "Exception"))
            self.owner_is_data = "dataclass" in {
                str(value).rsplit(".", 1)[-1]
                for value in self.declaration_contract.get("decorators") or []
            }
            self.required_data_methods = {
                str(value)
                for value in self.declaration_contract.get("required_methods") or []
                if str(value) and str(value) != "__init__"
            }
            if self.owner_is_error or (
                self.owner_is_data and (not self.required_data_methods)
            ):
                self.plan_chunk["method_tasks"] = []
                continue
            self.method_requirement_text = ".\n".join(
                (
                    str(requirement.get("text") or "")
                    for requirement in self.plan_chunk.get("requirements") or []
                    if isinstance(requirement, dict)
                )
            )
            self.existing_callable_signatures = [
                str(signature)
                for signature in self.declaration_contract.get("callable_signatures")
                or []
            ]
            self.existing_callable_names = {
                match.group(1)
                for signature in self.existing_callable_signatures
                for match in [
                    _deps.re.search("\\bdef\\s+([a-z_][A-Za-z0-9_]*)\\s*\\(", signature)
                ]
                if match
            }
            self.prompt_callable_signatures = [
                "def "
                + method_name
                + (
                    arguments
                    if _deps.re.match("\\(\\s*(?:self|cls)\\b", arguments)
                    else "(self"
                    + (
                        ", " + arguments[1:-1].strip()
                        if arguments[1:-1].strip()
                        else ""
                    )
                    + ")"
                )
                + (f" -> {return_type.strip()}" if return_type.strip() else "")
                for method_name, arguments, return_type in _deps.re.findall(
                    "\\b([a-z_][A-Za-z0-9_]*)(\\((?:[^()]|\\([^()]*\\))*\\))\\s*(?:->\\s*([^.;\\n]+))?",
                    self.method_requirement_text,
                )
                if method_name.casefold()
                not in {"callable", "sequence", "tuple", "dict", "list", "set"}
                and method_name not in self.existing_callable_names
                and (
                    not (
                        method_name.casefold().endswith("_callback")
                        and (
                            not _deps.re.search(
                                f"\\b{_deps.re.escape(self.owner_name)}\\.{_deps.re.escape(method_name)}\\s*\\(|\\b(?:method|function|callable)\\s+(?:named\\s+)?{_deps.re.escape(method_name)}\\b|\\b(?:implement|define|add)\\s+{_deps.re.escape(method_name)}\\s+method\\b",
                                self.method_requirement_text,
                                flags=_deps.re.IGNORECASE,
                            )
                        )
                    )
                )
            ]
            if self.prompt_callable_signatures:
                self.existing_callable_signatures = list(
                    dict.fromkeys(
                        [
                            *self.existing_callable_signatures,
                            *self.prompt_callable_signatures,
                        ]
                    )
                )
                self.declaration_contract["callable_signatures"] = (
                    self.existing_callable_signatures
                )
                self.declaration_contract["required_methods"] = list(
                    dict.fromkeys(
                        [
                            *[
                                str(value)
                                for value in self.declaration_contract.get(
                                    "required_methods", []
                                )
                            ],
                            *[
                                match.group(1)
                                for signature in self.prompt_callable_signatures
                                for match in [
                                    _deps.re.search(
                                        "\\bdef\\s+([a-z_][A-Za-z0-9_]*)\\s*\\(",
                                        signature,
                                    )
                                ]
                                if match
                            ],
                        ]
                    )
                )
                self.plan_chunk["declaration_contract"] = self.declaration_contract
                self.existing_method_tasks = {
                    str(item.get("name") or ""): dict(item)
                    for item in self.plan_chunk.get("method_tasks") or []
                    if isinstance(item, _deps.Mapping) and str(item.get("name") or "")
                }
                self.requirement_rows = [
                    item
                    for item in self.plan_chunk.get("requirements") or []
                    if isinstance(item, _deps.Mapping)
                ]
                self.mechanics_by_requirement = {
                    str(item.get("requirement_id") or ""): list(item.get("steps") or [])
                    for item in self.plan_chunk.get("implementation_mechanics") or []
                    if isinstance(item, _deps.Mapping)
                }
                self.validations_by_requirement = {
                    str(item.get("requirement_id") or ""): list(
                        item.get("checks") or []
                    )
                    for item in self.plan_chunk.get("validation_cases") or []
                    if isinstance(item, _deps.Mapping)
                }
                for self.signature in self.prompt_callable_signatures:
                    self.method_match = _deps.re.search(
                        "\\bdef\\s+([a-z_][A-Za-z0-9_]*)\\s*\\(", self.signature
                    )
                    if not self.method_match:
                        continue
                    self.method_name = self.method_match.group(1)
                    if self.method_name in self.existing_method_tasks:
                        continue
                    self.behavior_ids = [
                        str(item.get("id") or item.get("requirement_id") or "")
                        for item in self.requirement_rows
                        if _deps.re.search(
                            f"(?<![.\\w]){_deps.re.escape(self.method_name)}\\s*\\(",
                            str(item.get("text") or ""),
                        )
                    ]
                    self.existing_method_tasks[self.method_name] = {
                        "name": self.method_name,
                        "signature": self.signature,
                        "behavior_ids": self.behavior_ids,
                        "requirement_ids": self.behavior_ids,
                        "responsibility": f"Implement the exact requested behavior assigned to {self.method_name} without placeholders.",
                        "implementation_mechanics": list(
                            dict.fromkeys(
                                (
                                    step
                                    for requirement_id in self.behavior_ids
                                    for step in self.mechanics_by_requirement.get(
                                        requirement_id, []
                                    )
                                )
                            )
                        ),
                        "validation_cases": list(
                            dict.fromkeys(
                                (
                                    check
                                    for requirement_id in self.behavior_ids
                                    for check in self.validations_by_requirement.get(
                                        requirement_id, []
                                    )
                                )
                            )
                        ),
                    }
                self.plan_chunk["method_tasks"] = list(
                    self.existing_method_tasks.values()
                )
            self.plan_chunk["method_tasks"] = [
                {
                    **dict(task),
                    "behavior_ids": [
                        str(value)
                        for value in task.get("requirement_ids") or []
                        if str(value)
                    ],
                }
                for task in self.plan_chunk.get("method_tasks") or []
                if isinstance(task, _deps.Mapping)
            ]
            if self.declaration_contract.get("required_methods") or any(
                (
                    not _deps.re.search("\\b__init__\\s*\\(", signature)
                    for signature in self.existing_callable_signatures
                )
            ):
                continue
            if "dataclass" in {
                str(value).casefold()
                for value in self.declaration_contract.get("decorators") or []
            } and (not self.declaration_contract.get("required_methods")):
                continue
            self.behavior_clauses = list(
                dict.fromkeys(
                    (
                        text
                        for requirement in self.plan_chunk.get("requirements") or []
                        if isinstance(requirement, dict)
                        for text in [str(requirement.get("text") or "").strip()]
                        if len(text) >= 12
                        and (
                            not _deps.re.search(
                                "\\b[A-Za-z_][A-Za-z0-9_]*\\.py\\s+(?:define|defines|defining|contain|contains|containing|implement|implements|provide|provides|with)\\b|\\b(?:docstrings?|documentation)\\b|^\\s*(?:do\\s+not|don't|never|must\\s+not|without)\\b|\\b__main__\\b|\\bentry\\s+point\\b",
                                text,
                                flags=_deps.re.IGNORECASE,
                            )
                        )
                    )
                )
            )
            if len(self.behavior_clauses) < 4:
                continue
            self.behavior_rows = [
                {"id": f"B{index:02d}", "text": clause}
                for index, clause in enumerate(self.behavior_clauses, start=1)
            ]
            self.connected_handler_groups = _deps.re.findall(
                "\\bto\\s+(?:self\\.)?([a-z_][A-Za-z0-9_]*)(?:\\s+and\\s+(?:self\\.)?([a-z_][A-Za-z0-9_]*))?",
                self.method_requirement_text,
                flags=_deps.re.IGNORECASE,
            )
            self.explicit_method_names = list(
                dict.fromkeys(
                    [
                        *_deps.re.findall(
                            "\\b(?:implement|define|add|create|expose)\\s+(?:the\\s+)?([a-z_][A-Za-z0-9_]*)(?=\\s*(?:\\(|method\\b|with\\b|during\\b|that\\b))",
                            self.method_requirement_text,
                            flags=_deps.re.IGNORECASE,
                        ),
                        *_deps.re.findall(
                            "\\b(?:connect|wire)\\b[^\\n.;]{0,160}?\\bto\\s+(?:self\\.)?([a-z_][A-Za-z0-9_]*)\\b",
                            self.method_requirement_text,
                            flags=_deps.re.IGNORECASE,
                        ),
                        *_deps.re.findall(
                            "\\b(?:method|function|callable)\\s+(?:named\\s+)?([a-z_][A-Za-z0-9_]*)\\b",
                            self.method_requirement_text,
                            flags=_deps.re.IGNORECASE,
                        ),
                        *[
                            handler
                            for handler_group in self.connected_handler_groups
                            for handler in handler_group
                            if handler
                        ],
                    ]
                )
            )
            self.explicit_method_names = [
                name
                for name in self.explicit_method_names
                if name.casefold()
                not in {"a", "an", "asset", "class", "code", "module", "the", "widget"}
            ]
            self.approved_attributes = {
                str(attribute.get("name") or "")
                for attribute in self.declaration_contract.get("attributes") or []
                if isinstance(attribute, dict) and str(attribute.get("name") or "")
            }
            self.ui_suffixes = (
                "_push_button",
                "_tool_button",
                "_check_box",
                "_radio_button",
                "_button",
                "_checkbox",
                "_combobox",
                "_spinbox",
                "_action",
                "_combo",
                "_btn",
            )
            self.derived_handler_names: list[str] = []
            self.connection_pattern = _deps.re.compile(
                "\\b(?:connect|wire)\\s+(?:self\\.)?(?P<widget>[a-z_][A-Za-z0-9_]*)\\b(?P<body>.*?)(?=\\b(?:and\\s+)?(?:connect|wire)\\b|[.;]|$)",
                flags=_deps.re.IGNORECASE | _deps.re.DOTALL,
            )
            for self.connection_match in self.connection_pattern.finditer(
                self.method_requirement_text
            ):
                self.widget_name = self.connection_match.group("widget")
                if self.widget_name not in self.approved_attributes:
                    continue
                self.connection_body = self.connection_match.group("body")
                if _deps.re.search(
                    "\\bto\\s+(?:(?:the|a|an)\\s+)?(?:self\\.)?[a-z_][A-Za-z0-9_]*\\s*(?:\\(|method\\b)",
                    self.connection_body,
                    flags=_deps.re.IGNORECASE,
                ):
                    continue
                self.stem = self.widget_name
                for self.suffix in self.ui_suffixes:
                    if self.stem.casefold().endswith(self.suffix):
                        self.stem = self.stem[: -len(self.suffix)]
                        break
                self.stem = _deps.re.sub("[^A-Za-z0-9_]+", "_", self.stem).strip("_")
                if self.stem:
                    self.derived_handler_names.append(f"_on_{self.stem}")
            self.explicit_method_names = list(
                dict.fromkeys(
                    [*self.explicit_method_names, *self.derived_handler_names]
                )
            )
            if (
                not self.explicit_method_names
                and self.approved_attributes
                and _deps.re.search(
                    "\\b(?:connect|wire)\\b",
                    self.method_requirement_text,
                    flags=_deps.re.IGNORECASE,
                )
            ):
                self.explicit_method_names = [
                    f"_on_{stem}"
                    for attribute_name in sorted(self.approved_attributes)
                    for stem in [
                        next(
                            (
                                attribute_name[: -len(suffix)]
                                for suffix in self.ui_suffixes
                                if attribute_name.casefold().endswith(suffix)
                            ),
                            "",
                        )
                    ]
                    if stem
                ]
            if self.explicit_method_names:
                self.constructor_markers = _deps.re.compile(
                    "\\b(?:add|connect|construct|construction|dialog|layout|qcheckbox|qcombobox|qdialog|qdouble?spinbox|qlabel|qlineedit|qpushbutton|qwidget|signal|spinbox|widget)\\b",
                    flags=_deps.re.IGNORECASE,
                )
                self.method_tasks: list[dict[str, _deps.Any]] = []
                self.signature_by_name = {
                    match.group(1): str(signature)
                    for signature in self.declaration_contract.get(
                        "callable_signatures", []
                    )
                    for match in [
                        _deps.re.search(
                            "\\bdef\\s+([a-z_][A-Za-z0-9_]*)\\s*\\(", str(signature)
                        )
                    ]
                    if match
                }
                self.constructor_ids = [
                    row["id"]
                    for row in self.behavior_rows
                    if self.constructor_markers.search(row["text"])
                    and (
                        not any(
                            (
                                name.casefold() in row["text"].casefold()
                                and _deps.re.search(
                                    f"\\b(?:implement|define)\\s+{_deps.re.escape(name)}\\b",
                                    row["text"],
                                    flags=_deps.re.IGNORECASE,
                                )
                                for name in self.explicit_method_names
                            )
                        )
                    )
                ]
                if self.constructor_ids:
                    self.method_tasks.append(
                        {
                            "name": "__init__",
                            "signature": self.signature_by_name.get(
                                "__init__", "def __init__(self, parent=None)"
                            ),
                            "behavior_ids": self.constructor_ids,
                            "responsibility": "Construct the requested owner, widgets, layout, defaults, and signal connections.",
                        }
                    )
                self.non_constructor_ids = [
                    row["id"]
                    for row in self.behavior_rows
                    if row["id"] not in set(self.constructor_ids)
                ]
                self.method_tokens = {
                    method_name: {
                        token
                        for token in _deps.re.findall(
                            "[a-z0-9]+", method_name.removeprefix("_on_").casefold()
                        )
                        if len(token) >= 3
                    }
                    for method_name in self.explicit_method_names
                }
                self.semantic_non_constructor_owners: dict[str, list[str]] = {
                    method_name: [] for method_name in self.explicit_method_names
                }
                for self.behavior_id in self.non_constructor_ids:
                    self.behavior_text = next(
                        (
                            row["text"]
                            for row in self.behavior_rows
                            if row["id"] == self.behavior_id
                        )
                    )
                    self.behavior_tokens = set(
                        _deps.re.findall("[a-z0-9]+", self.behavior_text.casefold())
                    )
                    self.ranked_methods = sorted(
                        self.explicit_method_names,
                        key=lambda method_name: (
                            len(self.method_tokens[method_name] & self.behavior_tokens),
                            -self.explicit_method_names.index(method_name),
                        ),
                        reverse=True,
                    )
                    self.semantic_non_constructor_owners[self.ranked_methods[0]].append(
                        self.behavior_id
                    )
                for self.index, self.method_name in enumerate(
                    self.explicit_method_names
                ):
                    self.owned_ids = [
                        row["id"]
                        for row in self.behavior_rows
                        if self.method_name.casefold() in row["text"].casefold()
                    ]
                    self.owned_ids = list(
                        dict.fromkeys(
                            [
                                *self.owned_ids,
                                *self.semantic_non_constructor_owners.get(
                                    self.method_name, []
                                ),
                            ]
                        )
                    )
                    if not self.owned_ids:
                        self.owned_ids = self.constructor_ids[:1]
                    self.method_tasks.append(
                        {
                            "name": self.method_name,
                            "signature": self.signature_by_name.get(
                                self.method_name, f"def {self.method_name}(self)"
                            ),
                            "behavior_ids": self.owned_ids,
                            "responsibility": f"Implement every explicitly requested behavior assigned to {self.method_name} without placeholders.",
                        }
                    )
                self.covered_ids = {
                    behavior_id
                    for method in self.method_tasks
                    for behavior_id in method["behavior_ids"]
                }
                self.missing_ids = [
                    row["id"]
                    for row in self.behavior_rows
                    if row["id"] not in self.covered_ids
                ]
                if self.missing_ids and self.method_tasks:
                    self.method_tasks[-1]["behavior_ids"] = list(
                        dict.fromkeys(
                            [*self.method_tasks[-1]["behavior_ids"], *self.missing_ids]
                        )
                    )
                self.declaration_contract["required_methods"] = list(
                    dict.fromkeys(
                        [
                            *[
                                str(value)
                                for value in self.declaration_contract.get(
                                    "required_methods", []
                                )
                            ],
                            *self.explicit_method_names,
                        ]
                    )
                )
                self.declaration_contract["callable_signatures"] = list(
                    dict.fromkeys(
                        [
                            *[
                                str(value)
                                for value in self.declaration_contract.get(
                                    "callable_signatures", []
                                )
                            ],
                            *[method["signature"] for method in self.method_tasks],
                        ]
                    )
                )
                self.plan_chunk["declaration_contract"] = self.declaration_contract
                self.plan_chunk["method_tasks"] = self.method_tasks
                if self.status_callback:
                    self.status_callback(
                        f"Resolved explicit method contract deterministically for {self.plan_chunk.get('owner')}: "
                        + ", ".join(
                            (method["signature"] for method in self.method_tasks)
                        )
                    )
                continue
            self.method_plan_stage = _deps.ProjectEditPromptStage(
                key="class_method_contract",
                label="Designing method contract for "
                + str(self.plan_chunk.get("owner") or "class"),
                system_prompt="Design a concise internal Python class method contract, not code. Return JSON only. Assign every behavior ID to one or more exact method signatures. Use __init__ for construction, event handlers for event input, focused helpers for reusable operations, and cleanup methods for lifecycle restoration. Do not invent external APIs or omit any behavior ID. Worker-helper constructor parameters are infrastructure, not domain method parameters: never copy operation, *args, or **kwargs into the owning UI class operation. Derive that operation's inputs from the approved dependency callable contracts. Give each worker signal a distinct UI handler unless two signals have exactly the same payload contract.",
                user_prompt=_deps.json.dumps(
                    {
                        "owner": str(self.plan_chunk.get("owner") or ""),
                        "base": str(self.declaration_contract.get("base") or ""),
                        "behaviors": self.behavior_rows,
                        "declaration_contract": self.declaration_contract,
                        "approved_dependency_contracts": [
                            {
                                "owner": str(dependency_chunk.get("owner") or ""),
                                "callable_signatures": list(
                                    (
                                        dependency_chunk.get("declaration_contract")
                                        or {}
                                    ).get("callable_signatures")
                                    or []
                                ),
                                "required_methods": list(
                                    (
                                        dependency_chunk.get("declaration_contract")
                                        or {}
                                    ).get("required_methods")
                                    or []
                                ),
                            }
                            for dependency_id in self.plan_chunk.get("depends_on") or []
                            for dependency_chunk in self.implementation_plan.get(
                                "chunks", []
                            )
                            if isinstance(dependency_chunk, dict)
                            and str(dependency_chunk.get("chunk_id") or "")
                            == str(dependency_id)
                        ],
                        "verified_api_evidence": [
                            {
                                "name": str(item.get("name") or ""),
                                "signature": str(item.get("signature") or ""),
                            }
                            for item in self.plan_chunk.get("evidence") or []
                            if isinstance(item, dict)
                        ],
                        "output": {
                            "methods": [],
                            "method_fields": {
                                "name": "a concrete valid Python method identifier",
                                "signature": "a matching Python def signature",
                                "behavior_ids": "one or more IDs from behaviors",
                                "responsibility": "one concise executable responsibility",
                            },
                        },
                    },
                    ensure_ascii=True,
                    separators=(",", ":"),
                ),
                model_tier="local_reasoning",
                num_ctx=4096,
                num_predict=-1,
                timeout=60,
                no_progress_seconds=25,
                prefer_coder=True,
                coder_preference="standard",
                response_format="json",
            )
            self.method_response, self.method_timing = _deps._query_stage(
                self.method_plan_stage,
                selected_model=_deps._causal_repair_escalation_model(
                    self.settings, self.selected_model
                ),
                settings=self.settings,
                timeout=self.timeout,
            )
            self.method_timing["owner"] = str(self.plan_chunk.get("owner") or "")
            self.timings.append(self.method_timing)
            try:
                self.method_payload = _deps.json.loads(self.method_response)
            except (TypeError, ValueError, _deps.json.JSONDecodeError):
                self.method_payload = {}
            self.method_rows = []
            if isinstance(self.method_payload, dict):
                self.method_rows = self.method_payload.get("methods") or []
                if not self.method_rows:
                    for self.container_key in ("output", "plan", "contract", "result"):
                        self.container = self.method_payload.get(self.container_key)
                        if isinstance(self.container, dict) and self.container.get(
                            "methods"
                        ):
                            self.method_rows = self.container.get("methods") or []
                            break
            elif isinstance(self.method_payload, list):
                self.method_rows = self.method_payload
            self.accepted_methods: list[dict[str, _deps.Any]] = []
            self.covered_behavior_ids: set[str] = set()
            self.valid_behavior_ids = {row["id"] for row in self.behavior_rows}
            for self.method in self.method_rows or []:
                if not isinstance(self.method, dict):
                    continue
                self.method_name = str(self.method.get("name") or "").strip()
                self.signature = (
                    str(self.method.get("signature") or "")
                    .replace("\\n", "\n")
                    .splitlines()[0]
                    .strip()
                    .rstrip(":")
                )
                self.raw_behavior_ids = self.method.get("behavior_ids") or []
                if isinstance(self.raw_behavior_ids, str):
                    self.raw_behavior_ids = _deps.re.findall(
                        "B\\d{2}", self.raw_behavior_ids
                    )
                self.behavior_ids = [
                    str(value)
                    for value in self.raw_behavior_ids
                    if str(value) in self.valid_behavior_ids
                ]
                if (
                    not _deps.re.fullmatch("[A-Za-z_][A-Za-z0-9_]*", self.method_name)
                    or not _deps.re.match(
                        f"^def\\s+{_deps.re.escape(self.method_name)}\\s*\\(",
                        self.signature,
                    )
                    or (not self.behavior_ids)
                ):
                    continue
                self.accepted_methods.append(
                    {
                        "name": self.method_name,
                        "signature": self.signature,
                        "behavior_ids": list(dict.fromkeys(self.behavior_ids)),
                        "responsibility": str(
                            self.method.get("responsibility") or ""
                        ).strip(),
                    }
                )
                self.covered_behavior_ids.update(self.behavior_ids)
            self.worker_helpers = [
                helper
                for helper in self.declaration_contract.get("helper_declarations") or []
                if isinstance(helper, dict)
                and isinstance(helper.get("operation_protocol"), dict)
            ]
            self.worker_contract: dict[str, _deps.Any] = {}
            if self.worker_helpers and self.accepted_methods:
                self.worker_helper = self.worker_helpers[0]
                self.helper_signal_rows = [
                    signal
                    for signal in self.worker_helper.get("signals") or []
                    if isinstance(signal, dict)
                    and str(signal.get("name") or "").strip()
                ]

                def signal_terms(signal_name: str) -> set[str]:
                    normalized = signal_name.casefold()
                    if normalized in {
                        "completion",
                        "complete",
                        "completed",
                        "result",
                        "success",
                    }:
                        return {
                            "completion",
                            "complete",
                            "completed",
                            "result",
                            "success",
                        }
                    if normalized in {"error", "failed", "failure", "exception"}:
                        return {"error", "failed", "failure", "exception"}
                    return {normalized}

                self.signal_terms = signal_terms
                self.ambiguous_signal_methods: list[dict[str, _deps.Any]] = []
                self.owner_signal_names = {
                    str(signal.get("name") or "").casefold()
                    for signal in self.declaration_contract.get("signals") or []
                    if isinstance(signal, dict) and str(signal.get("name") or "")
                }
                for self.method in self.accepted_methods:
                    self.matched_signal_groups = sum(
                        (
                            any(
                                (
                                    term in self.method["name"].casefold()
                                    for term in self.signal_terms(
                                        str(signal.get("name") or "")
                                    )
                                )
                            )
                            for signal in self.helper_signal_rows
                        )
                    )
                    self.emit_without_owner_signal = self.method[
                        "name"
                    ].casefold().startswith("emit_") and (
                        not any(
                            (
                                signal_name in self.method["name"].casefold()
                                for signal_name in self.owner_signal_names
                            )
                        )
                    )
                    if self.matched_signal_groups > 1 or self.emit_without_owner_signal:
                        self.ambiguous_signal_methods.append(self.method)
                self.ambiguous_behavior_ids = list(
                    dict.fromkeys(
                        (
                            behavior_id
                            for method in self.ambiguous_signal_methods
                            for behavior_id in method.get("behavior_ids") or []
                        )
                    )
                )
                if self.ambiguous_signal_methods:
                    self.accepted_methods = [
                        method
                        for method in self.accepted_methods
                        if method not in self.ambiguous_signal_methods
                    ]
                self.operation_candidates = [
                    method
                    for method in self.accepted_methods
                    if method["name"] not in {"__init__"}
                    and _deps.re.search(
                        "(?:execute|run|perform|process|work|operation|background|worker)",
                        method["name"],
                        flags=_deps.re.IGNORECASE,
                    )
                    and (
                        not _deps.re.search(
                            "(?:complete|result|success|error|fail|finish|handle|emit)",
                            method["name"],
                            flags=_deps.re.IGNORECASE,
                        )
                    )
                    and (not method["name"].casefold().startswith(("on_", "handle_")))
                    and (
                        not _deps.re.search(
                            "(?:clicked|triggered|pressed|released|toggled|create.*worker|worker.*create)",
                            method["name"],
                            flags=_deps.re.IGNORECASE,
                        )
                    )
                ]
                if self.operation_candidates:
                    self.operation_method = self.operation_candidates[0]
                    self.operation_method["signature"] = (
                        _deps.re.sub(
                            "\\s*->\\s*[^:]+$", "", self.operation_method["signature"]
                        )
                        + " -> object"
                    )
                    self.operation_method["responsibility"] = (
                        "Execute only the approved blocking operation in the worker thread, return its result payload, never mutate UI-owned widgets, and let exceptions propagate to the worker error boundary."
                    )
                    self.worker_contract["operation_method"] = self.operation_method[
                        "name"
                    ]
                    self.worker_contract["operation_source"] = "owner_method"
                else:
                    self.worker_contract["operation_source"] = (
                        "approved_dependency_callable"
                    )
                self.signal_handlers: list[dict[str, _deps.Any]] = []
                self.assigned_handler_names: set[str] = set()
                self.behavior_text_by_id = {
                    row["id"]: str(row.get("text") or "") for row in self.behavior_rows
                }
                for self.signal in self.helper_signal_rows:
                    if not isinstance(self.signal, dict):
                        continue
                    self.signal_name = str(self.signal.get("name") or "").strip()
                    self.argument_types = [
                        str(value or "object")
                        for value in self.signal.get("arguments") or []
                    ]
                    if not self.signal_name:
                        continue
                    self.current_signal_terms = self.signal_terms(self.signal_name)
                    self.handler = next(
                        (
                            method
                            for method in self.accepted_methods
                            if any(
                                (
                                    term in method["name"].casefold()
                                    for term in self.current_signal_terms
                                )
                            )
                            and method["name"] not in self.assigned_handler_names
                            and (
                                method["name"]
                                != self.worker_contract.get("operation_method")
                            )
                        ),
                        None,
                    )
                    self.relevant_behavior_ids = [
                        behavior_id
                        for behavior_id, behavior_text in self.behavior_text_by_id.items()
                        if any(
                            (
                                _deps.re.search(
                                    f"\\b{_deps.re.escape(term)}\\w*\\b",
                                    behavior_text,
                                    flags=_deps.re.IGNORECASE,
                                )
                                for term in self.current_signal_terms
                            )
                        )
                    ]
                    if self.handler is None:
                        self.handler_name = f"handle_{self.signal_name}"
                        self.existing_names = {
                            method["name"] for method in self.accepted_methods
                        }
                        self.suffix = 2
                        while self.handler_name in self.existing_names:
                            self.handler_name = (
                                f"handle_{self.signal_name}_{self.suffix}"
                            )
                            self.suffix += 1
                        self.handler = {
                            "name": self.handler_name,
                            "signature": "",
                            "behavior_ids": self.relevant_behavior_ids
                            or [self.behavior_rows[0]["id"]],
                            "responsibility": "",
                        }
                        self.accepted_methods.append(self.handler)
                    self.parameter_names = []
                    for self.argument_index, self.argument_type in enumerate(
                        self.argument_types
                    ):
                        if (
                            self.signal_name.casefold()
                            in {"error", "failed", "failure", "exception"}
                            and self.argument_index == 0
                        ):
                            self.parameter_name = "message"
                        elif self.argument_index == 0:
                            self.parameter_name = "result"
                        else:
                            self.parameter_name = f"value_{self.argument_index + 1}"
                        self.parameter_names.append(
                            f"{self.parameter_name}: {self.argument_type}"
                        )
                    self.parameters = ", ".join(["self", *self.parameter_names])
                    self.handler["signature"] = (
                        f"def {self.handler['name']}({self.parameters}) -> None"
                    )
                    self.handler["responsibility"] = (
                        f"Handle the worker `{self.signal_name}` payload on the UI thread and update only UI-owned presentation state."
                    )
                    self.handler["behavior_ids"] = list(
                        dict.fromkeys(
                            [
                                *self.handler.get("behavior_ids", []),
                                *self.relevant_behavior_ids,
                                *self.ambiguous_behavior_ids,
                            ]
                        )
                    )
                    self.covered_behavior_ids.update(self.handler["behavior_ids"])
                    self.assigned_handler_names.add(self.handler["name"])
                    self.signal_handlers.append(
                        {
                            "signal": self.signal_name,
                            "handler": self.handler["name"],
                            "argument_types": self.argument_types,
                        }
                    )
                self.worker_contract.update(
                    {
                        "helper_owner": str(self.worker_helper.get("owner") or ""),
                        "signal_handlers": self.signal_handlers,
                        "ui_updates_only_in_handlers": True,
                    }
                )
                self.declaration_contract["worker_contract"] = self.worker_contract
            if (
                self.accepted_methods
                and self.covered_behavior_ids == self.valid_behavior_ids
            ):
                self.required_methods = list(
                    dict.fromkeys((method["name"] for method in self.accepted_methods))
                )
                self.signatures = list(
                    dict.fromkeys(
                        [
                            *[
                                str(value)
                                for value in self.declaration_contract.get(
                                    "callable_signatures", []
                                )
                            ],
                            *[method["signature"] for method in self.accepted_methods],
                        ]
                    )
                )
                self.declaration_contract["required_methods"] = self.required_methods
                self.declaration_contract["callable_signatures"] = self.signatures
                self.plan_chunk["declaration_contract"] = self.declaration_contract
                self.plan_chunk["method_tasks"] = self.accepted_methods
                self.plan_chunk.setdefault("implementation_mechanics", []).extend(
                    (
                        {
                            "requirement_id": ",".join(method["behavior_ids"]),
                            "steps": [
                                f"{method['signature']}: {method['responsibility'] or 'implement the assigned behavior IDs'}"
                            ],
                        }
                        for method in self.accepted_methods
                    )
                )
                if self.status_callback:
                    self.status_callback(
                        f"Accepted method contract for {self.plan_chunk.get('owner')}: "
                        + ", ".join(
                            (method["signature"] for method in self.accepted_methods)
                        )
                    )
            elif self.status_callback:
                self.rejection_message = (
                    f"Rejected incomplete method contract for {self.plan_chunk.get('owner')}; covered {len(self.covered_behavior_ids)}/{len(self.valid_behavior_ids)} behavior clauses. Response: "
                    + str(self.method_response or "")[:3000]
                )
                self.status_callback(self.rejection_message)
                self.method_contract_errors.append(self.rejection_message)
        if self.method_contract_errors:
            raise _WorkflowReturn(
                _deps.ProjectEditWorkflowResult(
                    ok=False,
                    status="method_contract_incomplete",
                    errors=self.method_contract_errors,
                    timings=self.timings,
                    implementation_plan=self.implementation_plan,
                    approval_id="",
                )
            )
        self.approved_test_surfaces = [
            f"{chunk.get('owner')}: methods="
            + ", ".join(
                sorted(
                    {
                        match.group(1)
                        for signature in (chunk.get("declaration_contract") or {}).get(
                            "callable_signatures"
                        )
                        or []
                        for match in [
                            _deps.re.search(
                                "\\bdef\\s+([A-Za-z_][A-Za-z0-9_]*)\\s*\\(",
                                str(signature),
                            )
                        ]
                        if match
                    }
                )
            )
            + "; attributes="
            + ", ".join(
                (
                    str(attribute.get("name") or "")
                    for attribute in (chunk.get("declaration_contract") or {}).get(
                        "attributes"
                    )
                    or []
                    if isinstance(attribute, dict) and str(attribute.get("name") or "")
                )
            )
            for chunk in self.implementation_plan.get("chunks") or []
            if isinstance(chunk, dict) and str(chunk.get("kind") or "") == "class"
        ]
        self.approved_test_mechanics = [
            str(step)
            for chunk in self.implementation_plan.get("chunks") or []
            if isinstance(chunk, dict)
            for mechanic in chunk.get("implementation_mechanics") or []
            if isinstance(mechanic, dict)
            for step in mechanic.get("steps") or []
            if str(step)
        ]
        self.injected_time_source = any(
            (
                _deps.re.search(
                    "\\b(?:clock|time_source|monotonic_clock)\\s*:\\s*Callable\\b",
                    str(signature),
                    flags=_deps.re.IGNORECASE,
                )
                for chunk in self.implementation_plan.get("chunks") or []
                if isinstance(chunk, dict)
                for signature in (chunk.get("declaration_contract") or {}).get(
                    "callable_signatures"
                )
                or []
            )
        )
        for self.manifest_item in self.manifest:
            if not bool(self.manifest_item.get("is_test")):
                continue
            self.manifest_item.setdefault("contracts", []).append(
                "Tests may use only these approved production surfaces: "
                + " | ".join(self.approved_test_surfaces)
            )
            self.manifest_item.setdefault("algorithm_steps", []).append(
                "Trigger connected UI actions through approved widget attributes, such as button.click(); never call implementation slots directly."
            )
            self.manifest_item.setdefault("algorithm_steps", []).append(
                "Assert production state only through approved query methods; never read or assume production storage attributes or element representations."
            )
            self.manifest_item.setdefault("algorithm_steps", []).extend(
                (
                    "Prove this approved implementation mechanic: " + mechanic
                    for mechanic in self.approved_test_mechanics
                )
            )
            if self.injected_time_source:
                self.manifest_item.setdefault("algorithm_steps", []).append(
                    "For an injected clock/time source, use a mutable deterministic fake clock and advance its returned value directly. Never call sleep(), patch wall-clock time, or mutate production timestamp fields."
                )
            if any(
                ("status_label" in surface for surface in self.approved_test_surfaces)
            ):
                self.manifest_item.setdefault("algorithm_steps", []).append(
                    "For UI domain errors, click the connected widget and assert the approved status label; do not expect a Qt signal dispatch to propagate the slot's handled exception."
                )
        self.generic_mechanic_patterns = (
            _deps.re.compile(
                "^Implement the requirement inside its approved owner\\b",
                flags=_deps.re.IGNORECASE,
            ),
            _deps.re.compile(
                "^Implement (?:this|the) requirement\\b", flags=_deps.re.IGNORECASE
            ),
            _deps.re.compile(
                "^Apply [A-Za-z0-9_ ]+ and update only its documented state\\.?$",
                flags=_deps.re.IGNORECASE,
            ),
        )
        for self.chunk in self.implementation_plan.get("chunks") or []:
            if not isinstance(self.chunk, _deps.Mapping):
                continue
            for self.mechanic_row in self.chunk.get("implementation_mechanics") or []:
                if not isinstance(self.mechanic_row, dict):
                    continue
                self.steps = [
                    str(step).strip()
                    for step in self.mechanic_row.get("steps") or []
                    if str(step).strip()
                ]
                self.concrete_steps = [
                    step
                    for step in self.steps
                    if not any(
                        (
                            pattern.search(step)
                            for pattern in self.generic_mechanic_patterns
                        )
                    )
                ]
                if self.concrete_steps:
                    self.mechanic_row["steps"] = list(
                        dict.fromkeys(self.concrete_steps)
                    )
        self.completeness_errors = self.validate_implementation_plan_completeness(
            self.implementation_plan, original_prompt=self.user_prompt
        )
        self.incomplete_requirement_ids = set(
            _deps.re.findall(
                "(?:mechanics|contract) for `([^`]+)`",
                "\n".join(self.completeness_errors),
            )
        )
