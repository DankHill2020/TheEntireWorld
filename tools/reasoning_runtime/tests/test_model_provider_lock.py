from __future__ import annotations

import unittest

from reasoning_runtime import (
    ModelProviderLockError,
    ModelProviderRoute,
    assert_model_provider_healthy,
    current_model_calls,
    current_model_provider_route,
    locked_model_provider_route,
    mark_model_provider_failed,
    model_provider_integrity,
    public_provider_route,
)


class ModelProviderLockTests(unittest.TestCase):
    def test_lock_collects_calls_and_integrity(self):
        route = ModelProviderRoute("openai", "gpt-test", cloud_active=True, transport="account")

        with locked_model_provider_route(route) as calls:
            self.assertEqual(current_model_provider_route(), route)
            current_model_calls().append({"provider": "openai", "model": "gpt-test"})
            self.assertTrue(model_provider_integrity(route, calls)["valid"])

        self.assertIsNone(current_model_provider_route())

    def test_failure_blocks_locked_provider(self):
        route = ModelProviderRoute("openai", "gpt-test", cloud_active=True)

        with locked_model_provider_route(route):
            mark_model_provider_failed("provider failed")
            with self.assertRaises(ModelProviderLockError):
                assert_model_provider_healthy()

    def test_public_route_hides_api_key(self):
        route = ModelProviderRoute("openai", "gpt-test", api_key="secret", cloud_active=True)

        self.assertNotIn("api_key", public_provider_route(route))


if __name__ == "__main__":
    unittest.main()
