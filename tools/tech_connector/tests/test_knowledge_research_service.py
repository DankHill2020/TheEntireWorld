from __future__ import annotations

import json
import unittest

from tech_connector.router.command_router import CommandRouter
from tech_connector.services.knowledge_research_service import (
    extract_public_source_claims,
    run_automatic_feature_research,
    sanitize_public_research_query,
    search_public_sources,
    verify_known_public_claims,
)
from tech_connector.services.open_knowledge_policy_service import (
    assess_open_knowledge_source,
)
from tech_connector.services.unreal.unreal_operation_service import UNREAL_OPERATIONS


class _Response:
    def __init__(self, payload: bytes, content_type: str) -> None:
        self.payload = payload
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _size: int = -1) -> bytes:
        return self.payload


class _Opener:
    def __init__(self, responses: list[_Response]) -> None:
        self.responses = list(responses)

    def open(self, _request, timeout: float):
        del timeout
        return self.responses.pop(0)


class TestKnowledgeResearchService(unittest.TestCase):
    def test_public_search_returns_candidates_without_adopting_claims(self) -> None:
        rss = b"""<html><body><a class="result-link"
        href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fdev.epicgames.com%2Fdocumentation%2Fen-us%2Funreal-engine%2Fanimation-blueprints-in-unreal-engine">
        Animation Blueprints</a></body></html>"""

        result = search_public_sources(
            "animation blueprint linking",
            engine_version="5.8",
            official_only=True,
            opener=_Opener([_Response(rss, "application/rss+xml")]),
        )

        self.assertTrue(result["ok"])
        self.assertFalse(result["claims_adopted"])
        self.assertEqual("official_docs", result["candidates"][0]["source_kind"])
        self.assertTrue(result["candidates"][0]["knowledge_policy"]["eligible"])

    def test_claim_extraction_requires_exact_bounded_quote(self) -> None:
        html = b"""<html><head><title>State Machines</title></head><body>
        <p>State Machines are modular systems you build in Animation Blueprints.</p>
        <p>Each state produces a final animation pose.</p></body></html>"""
        source = {
            "url": "https://dev.epicgames.com/documentation/state-machines",
            "title": "State Machines",
            "source_kind": "official_docs",
            "official_public_documentation": True,
            "public_access": True,
            "license": "Official public documentation",
        }

        result = extract_public_source_claims(
            [source],
            query="animation state machine",
            engine_version="5.8",
            opener=_Opener([_Response(html, "text/html")]),
            claim_extractor=lambda _payload: {
                "claims": [
                    {
                        "claim": "Animation Blueprint state machines are modular pose-producing graphs.",
                        "supporting_quote": "State Machines are modular systems you build in Animation Blueprints.",
                        "applies_to_version": "5.8",
                        "prerequisites": ["Animation Blueprint"],
                    },
                    {
                        "claim": "Invented claim",
                        "supporting_quote": "This quote is absent.",
                        "applies_to_version": "5.8",
                        "prerequisites": [],
                    },
                ]
            },
        )

        self.assertTrue(result["ok"])
        self.assertEqual(1, len(result["claims"]))
        self.assertEqual(1, len(result["rejected"]))
        self.assertFalse(result["knowledge_promotion_allowed"])

    def test_claim_extraction_bounds_an_exact_long_model_quote(self) -> None:
        sentence = (
            "Linked animation layers let an existing animation blueprint keep its main state machine "
            "while another animation blueprint overrides a specific layer for one gameplay context "
            "without duplicating the entire animation graph or replacing unrelated combat behavior."
        )
        html = f"<html><body><p>{sentence}</p></body></html>".encode()
        source = {
            "url": "https://dev.epicgames.com/documentation/linked-layers",
            "source_kind": "official_docs",
            "official_public_documentation": True,
            "public_access": True,
            "license": "Official public documentation",
        }

        result = extract_public_source_claims(
            [source],
            query="linked animation layers",
            opener=_Opener([_Response(html, "text/html")]),
            claim_extractor=lambda _payload: {
                "claims": [
                    {
                        "claim": "A specific linked layer can be overridden without replacing the main state machine.",
                        "supporting_quote": sentence,
                        "applies_to_version": "5.8",
                        "prerequisites": [],
                    }
                ]
            },
        )

        self.assertTrue(result["ok"])
        self.assertLessEqual(len(result["claims"][0]["supporting_quote"].split()), 25)
        self.assertTrue(result["claims"][0]["quote_bounded_by_validator"])

    def test_public_unlicensed_guide_is_task_usable_but_not_learnable(self) -> None:
        assessment = assess_open_knowledge_source(
            {
                "url": "https://example.com/public-unreal-guide",
                "public_access": True,
                "allow_task_use": True,
            }
        )

        self.assertTrue(assessment["task_use_allowed"])
        self.assertFalse(assessment["eligible"])
        self.assertFalse(assessment["community_share_allowed"])

    def test_knowledge_operations_are_registered_and_dispatch_locally(self) -> None:
        self.assertIn("knowledge.search_sources", UNREAL_OPERATIONS)
        self.assertIn("knowledge.extract_claims", UNREAL_OPERATIONS)
        router = CommandRouter()
        label, ok, result = router.execute_unreal_operation(
            "knowledge.compare_approaches",
            {"baseline": {}, "candidates": []},
        )

        self.assertTrue(ok)
        self.assertIn("Compare", label)
        self.assertEqual("unreal_technique_comparison_v1", json.loads(result)["framework"])

    def test_automatic_research_sanitizes_project_identity_and_returns_claims(self) -> None:
        queries = []

        def searcher(query, **_kwargs):
            queries.append(query)
            return {
                "ok": True,
                "candidates": [
                    {
                        "url": "https://dev.epicgames.com/documentation/state-machines",
                        "title": "State Machines",
                    }
                ],
                "errors": [],
            }

        result = run_automatic_feature_research(
            {
                "request": "Build climbing on /Game/PrivateHero/BP_SecretHero",
                "evidence_driven_synthesis": {
                    "research_queries": [
                        {
                            "query": "climbing /Game/PrivateHero/BP_SecretHero ABP_SecretCombat official docs",
                            "enabled": True,
                        }
                    ]
                },
            },
            settings={"auto_research_official_docs": True},
            searcher=searcher,
            extractor=lambda *_args, **_kwargs: {
                "claims": [{"claim": "Supported", "source": {}}],
                "rejected": [],
                "errors": [],
            },
        )

        self.assertTrue(result["ok"])
        self.assertTrue(queries)
        self.assertNotIn("PrivateHero", queries[0])
        self.assertNotIn("SecretCombat", queries[0])
        self.assertFalse(result["project_identifiers_sent"])
        self.assertNotIn("PrivateHero", sanitize_public_research_query(queries[0]))

    def test_automatic_research_refreshes_known_source_pointers_before_search(self) -> None:
        searched = []
        result = run_automatic_feature_research(
            {
                "request": "Build a novel traversal behavior on /Game/Private/BP_Hero",
                "expert_technique_selection": {
                    "techniques": [
                        {
                            "title": "Modular animation integration",
                            "operations": ["blueprint.scan"],
                            "sources": [
                                {
                                    "url": "https://dev.epicgames.com/documentation/animation-linking",
                                    "kind": "official_docs",
                                    "official_public_documentation": True,
                                    "public_access": True,
                                    "license": "Official public documentation",
                                }
                            ],
                        }
                    ]
                },
            },
            settings={"auto_research_official_docs": True},
            searcher=lambda query, **_kwargs: searched.append(query) or {"candidates": [], "errors": []},
            extractor=lambda sources, **_kwargs: {
                "claims": [{"claim": "Refreshed", "source": sources[0]}],
                "rejected": [],
                "errors": [],
            },
        )

        self.assertTrue(result["ok"])
        self.assertEqual("known_pointer_pending_live_refresh", result["sources"][0]["candidate_status"])

    def test_known_claim_refresh_uses_fetched_text_without_model_synthesis(self) -> None:
        sentence = (
            "Linked Anim Layers let a main Animation Blueprint retain its state machine "
            "while another Animation Blueprint overrides a specific animation layer."
        )
        result = verify_known_public_claims(
            [
                {
                    "url": "https://dev.epicgames.com/documentation/animation-linking",
                    "claim": "Linked animation layers preserve a main state machine while a context-specific Blueprint overrides one layer.",
                }
            ],
            opener=_Opener([_Response(f"<p>{sentence}</p>".encode(), "text/html")]),
        )

        self.assertTrue(result["ok"])
        self.assertEqual("live_refresh_of_known_public_source", result["claims"][0]["evidence_origin"])
        self.assertLessEqual(len(result["claims"][0]["supporting_quote"].split()), 25)
