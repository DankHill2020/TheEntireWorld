from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from tech_connector.knowledge.search import query_ollama_text


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


if __name__ == "__main__":
    unittest.main()
