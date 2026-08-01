from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from tech_connector.knowledge.search import query_ollama_json_until_complete, query_ollama_text


class TestOllamaQueryOptions(unittest.TestCase):
    def test_query_can_disable_separate_model_thinking(self) -> None:
        response = MagicMock()
        response.read.return_value = json.dumps({"message": {"content": "READY"}}).encode("utf-8")
        response.__enter__.return_value = response
        opener = MagicMock()
        opener.open.return_value = response

        with (
            patch("tech_connector.knowledge.search.get_installed_ollama_models", return_value=["qwen3:8b"]),
            patch("urllib.request.build_opener", return_value=opener),
        ):
            result = query_ollama_text(
                model="qwen3:8b",
                system_prompt="Plan carefully.",
                user_prompt="Return a concise plan.",
                num_predict=64,
                think=False,
                response_format="json",
            )

        request = opener.open.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual("READY", result)
        self.assertIs(payload["think"], False)
        self.assertEqual("json", payload["format"])

    def test_streaming_query_emits_progress_without_losing_output(self) -> None:
        events = [
            {"message": {"content": "HELLO "}, "done": False},
            {"message": {"content": "WORLD"}, "done": True, "eval_count": 2},
        ]
        response = MagicMock()
        response.__iter__.return_value = iter(
            [json.dumps(event).encode("utf-8") + b"\n" for event in events]
        )
        response.__enter__.return_value = response
        opener = MagicMock()
        opener.open.return_value = response
        progress = []

        with (
            patch("tech_connector.knowledge.search.get_installed_ollama_models", return_value=["qwen3:8b"]),
            patch("urllib.request.build_opener", return_value=opener),
        ):
            result = query_ollama_text(
                model="qwen3:8b",
                system_prompt="Implement.",
                user_prompt="Return source.",
                progress_callback=progress.append,
                progress_interval_seconds=0,
            )

        request = opener.open.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual("HELLO WORLD", result)
        self.assertTrue(payload["stream"])
        self.assertTrue(progress)
        self.assertTrue(progress[-1]["done"])
        self.assertEqual(11, progress[-1]["characters_received"])

    def test_json_until_complete_uses_completion_not_a_token_budget(self) -> None:
        schema = {"type": "object", "properties": {"files": {"type": "array"}}}
        response = MagicMock()
        response.__iter__.return_value = iter([
            b'{"message":{"content":"{\\\"files\\\":[]}"},"done":false}\n',
        ])
        response.__enter__.return_value = response
        opener = MagicMock()
        opener.open.return_value = response

        with (
            patch("tech_connector.knowledge.search.get_installed_ollama_models", return_value=["qwen3:8b"]),
            patch("urllib.request.build_opener", return_value=opener),
        ):
            result = query_ollama_json_until_complete(
                model="qwen3:8b",
                system_prompt="Architect.",
                user_prompt="Return the manifest.",
                response_format=schema,
                prefer_coder=False,
                max_wall_seconds=20,
            )

        request = opener.open.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual('{"files":[]}', result)
        self.assertEqual(-1, payload["options"]["num_predict"])
        self.assertEqual(schema, payload["format"])
        self.assertEqual(20, opener.open.call_args.kwargs["timeout"])


if __name__ == "__main__":
    unittest.main()
