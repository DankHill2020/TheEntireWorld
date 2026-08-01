from __future__ import annotations

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
import json
import tempfile
import unittest

from tech_connector.services.action_execution_engine import (
    ExecutionContext,
    default_action_handler_registry,
)
from tech_connector.services.external_asset_acquisition_service import (
    active_external_asset_sources,
    candidate_auth_status,
    download_asset_candidate,
    search_asset_candidates,
)


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        pass


class _HttpAssetProvider:
    def __init__(self, root: Path):
        self.root = root
        handler = partial(_QuietHandler, directory=str(root))
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return f"http://127.0.0.1:{self.server.server_port}"

    def __exit__(self, exc_type, exc, tb):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


class TestExternalAssetAcquisitionService(unittest.TestCase):
    def test_search_download_and_manifest_pipeline(self) -> None:
        """Verify direct asset acquisition searches, downloads, and records provenance."""
        with tempfile.TemporaryDirectory(dir=Path.cwd() / ".ai_studio") as temp_root:
            root = Path(temp_root)
            provider_root = root / "provider"
            cache_root = root / "cache"
            provider_root.mkdir()
            source_file = provider_root / "proof.wav"
            source_file.write_bytes(b"RIFF----WAVEfmt proof asset bytes")
            with _HttpAssetProvider(provider_root) as base_url:
                providers = [
                    {
                        "name": "Proof Footstep WAV",
                        "provider": "Local Test Provider",
                        "url": f"{base_url}/proof.wav",
                        "download_url": f"{base_url}/proof.wav",
                        "asset_type": "audio",
                        "license": "Test fixture license",
                        "formats": ["wav"],
                        "target_hosts": ["unreal", "maya"],
                        "description": "A footstep sound effect for import testing.",
                    }
                ]
                candidates = search_asset_candidates(
                    "footstep sound effect",
                    asset_type="audio",
                    target_host="unreal",
                    providers=providers,
                )
                result = download_asset_candidate(
                    candidates[0],
                    cache_root,
                    approved=True,
                    target_host="unreal",
                    destination="Audio/Footsteps",
                )

            self.assertTrue(result["ok"], result)
            self.assertEqual(result["bytes"], source_file.stat().st_size)
            self.assertTrue(Path(result["local_path"]).exists())
            self.assertTrue(Path(result["manifest_path"]).exists())
            manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
            self.assertEqual(manifest["provider"], "Local Test Provider")
            self.assertEqual(manifest["license"], "Test fixture license")
            self.assertEqual(manifest["destination"], "/Game/Audio/Footsteps")
            self.assertEqual(manifest["sha256"], result["sha256"])

    def test_download_requires_approval(self) -> None:
        """Verify asset downloads stop before mutation without approval."""
        result = download_asset_candidate(
            {"name": "Blocked", "download_url": "http://127.0.0.1/blocked.wav"},
            Path.cwd() / ".ai_studio" / "blocked_cache",
            approved=False,
        )

        self.assertFalse(result["ok"])
        self.assertTrue(result["requires_approval"])
        self.assertIn("requires approval", result["errors"][0])

    def test_direct_url_search_returns_downloadable_candidate(self) -> None:
        """Verify pasted asset URLs become reviewable table candidates."""
        candidates = search_asset_candidates(
            "Use https://assets.example.com/audio/impact.wav for the impact sound.",
            asset_type="audio",
            target_host="unreal",
        )

        self.assertTrue(candidates)
        self.assertEqual(candidates[0]["download_url"], "https://assets.example.com/audio/impact.wav")
        self.assertEqual(candidates[0]["asset_type"], "audio")
        self.assertTrue(candidates[0]["download_available"])

    def test_listing_page_is_not_mislabeled_as_downloadable_asset(self) -> None:
        candidates = search_asset_candidates(
            "Review https://www.fab.com/listings/example for a ledge animation.",
            asset_type="animation",
            target_host="unreal",
        )

        direct = next(row for row in candidates if row.get("url", "").startswith("https://www.fab.com/listings/"))
        self.assertFalse(direct["download_available"])
        self.assertEqual(
            "listing_or_page_requires_resolved_download_url",
            direct["candidate_status"],
        )

    def test_provider_auth_status_blocks_download_until_connected(self) -> None:
        """Verify authenticated providers require login before direct download."""
        candidate = {
            "name": "Fab Asset",
            "provider": "Fab Marketplace",
            "url": "https://www.fab.com/listings/proof",
            "download_url": "https://www.fab.com/download/proof.uasset",
            "auth_required": True,
            "account_id": "fab",
        }

        status = candidate_auth_status(candidate, {})
        self.assertTrue(status["requires_auth"])
        self.assertFalse(status["connected"])
        blocked = download_asset_candidate(
            candidate,
            Path.cwd() / ".ai_studio" / "blocked_fab_cache",
            approved=True,
            settings={},
        )
        self.assertFalse(blocked["ok"])
        self.assertTrue(blocked["requires_login"])

        connected = candidate_auth_status(candidate, {"fab_login_confirmed": "true"})
        self.assertTrue(connected["connected"])

    def test_active_provider_search_filters_login_required_sources(self) -> None:
        """Verify contextual search only includes public or connected providers."""
        public_sources = active_external_asset_sources({})
        public_names = {str(item.get("provider") or item.get("name") or "") for item in public_sources}
        self.assertIn("Poly Haven", public_names)
        self.assertNotIn("Mixamo", public_names)

        texture_candidates = search_asset_candidates(
            "find texture material hdri for unreal",
            asset_type="texture",
            target_host="unreal",
            settings={},
            active_only=True,
            limit=10,
        )
        texture_providers = {str(item.get("provider") or "") for item in texture_candidates}
        self.assertIn("Poly Haven", texture_providers)
        self.assertNotIn("Fab Marketplace", texture_providers)

        animation_candidates = search_asset_candidates(
            "download mixamo animation fbx for unreal",
            asset_type="animation",
            target_host="unreal",
            settings={"mixamo_login_confirmed": "true"},
            active_only=True,
            limit=10,
        )
        animation_providers = {str(item.get("provider") or "") for item in animation_candidates}
        self.assertIn("Mixamo", animation_providers)

    def test_animation_search_surfaces_login_required_provider_choices(self) -> None:
        """Verify animation searches show login-gated services instead of hiding them."""
        candidates = search_asset_candidates(
            "find Mixamo climbing animation for Manny retarget in Unreal",
            asset_type="animation",
            target_host="unreal",
            settings={},
            active_only=True,
            limit=10,
        )

        by_provider = {str(item.get("provider") or ""): item for item in candidates}
        self.assertIn("Mixamo", by_provider)
        self.assertTrue(by_provider["Mixamo"].get("login_required_for_search"))
        self.assertTrue(by_provider["Mixamo"]["auth_status"]["requires_auth"])
        self.assertFalse(by_provider["Mixamo"]["auth_status"]["connected"])
        self.assertTrue(by_provider["Mixamo"].get("login_url"))

    def test_animation_search_ranks_role_match_and_marks_wrong_motion_unusable(self) -> None:
        providers = [
            {
                "name": "Samba Dancing",
                "provider": "Fixture",
                "download_url": "https://example.invalid/samba.fbx",
                "asset_type": "animation",
                "formats": ["fbx"],
                "target_hosts": ["unreal"],
                "description": "Looping dance performance.",
            },
            {
                "name": "Wall Climb Loop",
                "provider": "Fixture",
                "download_url": "https://example.invalid/wall-climb-loop.fbx",
                "asset_type": "animation",
                "formats": ["fbx"],
                "target_hosts": ["unreal"],
                "description": "In-place vertical wall climbing locomotion.",
            },
        ]
        candidates = search_asset_candidates(
            "find a wall climb loop animation for Unreal",
            asset_type="animation",
            target_host="unreal",
            providers=providers,
            limit=10,
        )
        by_name = {item["name"]: item for item in candidates}

        self.assertEqual(candidates[0]["name"], "Wall Climb Loop")
        self.assertTrue(by_name["Wall Climb Loop"]["contextually_usable"])
        self.assertFalse(by_name["Samba Dancing"]["contextually_usable"])

        with tempfile.TemporaryDirectory(dir=Path.cwd() / ".ai_studio") as temp_root:
            blocked = download_asset_candidate(
                by_name["Samba Dancing"],
                temp_root,
                approved=True,
                target_host="unreal",
            )
        self.assertFalse(blocked["ok"])
        self.assertIn("semantic contract", blocked["errors"][0])

    def test_action_handlers_search_and_download_asset(self) -> None:
        """Verify action graph/API callers can search and download assets."""
        with tempfile.TemporaryDirectory(dir=Path.cwd() / ".ai_studio") as temp_root:
            root = Path(temp_root)
            provider_root = root / "provider"
            cache_root = root / "cache"
            provider_root.mkdir()
            (provider_root / "spark.wav").write_bytes(b"RIFF----WAVEfmt spark")
            with _HttpAssetProvider(provider_root) as base_url:
                providers = [
                    {
                        "name": "Spark WAV",
                        "provider": "Local Test Provider",
                        "url": f"{base_url}/spark.wav",
                        "download_url": f"{base_url}/spark.wav",
                        "asset_type": "audio",
                        "license": "Test fixture license",
                        "formats": ["wav"],
                        "target_hosts": ["unreal"],
                        "description": "A spark sound effect.",
                    }
                ]
                registry = default_action_handler_registry()
                search = registry.get("asset_source_search").execute_fn(
                    {
                        "type": "asset_source_search",
                        "args": {
                            "query": "spark sound",
                            "asset_type": "audio",
                            "target_host": "unreal",
                            "providers": providers,
                        },
                    },
                    ExecutionContext(project_root=str(root)),
                )
                download = registry.get("download_or_ingest_asset").execute_fn(
                    {
                        "type": "download_or_ingest_asset",
                        "args": {
                            "candidate_assets": search["candidate_assets"],
                            "selected_index": 0,
                            "cache_root": str(cache_root),
                            "approved": True,
                            "target_host": "unreal",
                            "destination": "/Game/Audio/Sparks",
                        },
                    },
                    ExecutionContext(project_root=str(root), approved=True),
                )

            self.assertTrue(search["ok"], search)
            self.assertTrue(download["ok"], download)
            self.assertTrue(Path(download["local_path"]).exists())
            self.assertEqual(download["manifest"]["destination"], "/Game/Audio/Sparks")

    def test_action_handler_uses_active_sources_without_explicit_providers(self) -> None:
        """Verify API/action graph search falls back to active provider catalog."""
        registry = default_action_handler_registry()
        search = registry.get("asset_source_search").execute_fn(
            {
                "type": "asset_source_search",
                "args": {
                    "query": "find texture material hdri for unreal",
                    "asset_type": "texture",
                    "target_host": "unreal",
                    "settings": {},
                    "limit": 10,
                },
            },
            ExecutionContext(project_root=str(Path.cwd())),
        )

        self.assertTrue(search["ok"], search)
        providers = {str(item.get("provider") or "") for item in search["candidate_assets"]}
        self.assertIn("Poly Haven", providers)
        self.assertNotIn("Fab Marketplace", providers)


if __name__ == "__main__":
    unittest.main()
