from __future__ import annotations

import unittest

from reasoning_runtime import CodeContext, CodeUnderstandingProvider, ContextAdapter, ReasoningKernel
from reasoning_runtime.engine.request_context import RequestContext
from reasoning_runtime.engine.runtime_request_engine import RuntimeRequestPreparation


class ExampleContext(ContextAdapter):
    name = "example"

    def get_active_context(self):
        return {"ok": True}


class ExampleCodeProvider(CodeUnderstandingProvider):
    def understand(self, request):
        return CodeContext(summary=f"code:{request.active_file or request.query}")


class RuntimeRequestEngineTests(unittest.TestCase):
    def test_prepare_attaches_runtime_snapshot(self):
        kernel = ReasoningKernel()
        kernel.register_context_adapter(ExampleContext())
        preparation = RuntimeRequestPreparation(kernel)

        context, result = preparation.prepare(
            RequestContext(text="hello", extras={"api_key": "secret", "safe": "ok"})
        )

        self.assertTrue(result.ok)
        self.assertEqual(context.extras["safe"], "ok")
        self.assertNotIn("api_key", context.extras)
        self.assertTrue(context.extras["reasoning_runtime"]["ok"])
        self.assertEqual(
            context.extras["reasoning_runtime"]["adapter_counts"]["context"],
            1,
        )

    def test_prepare_attaches_code_understanding_summary(self):
        kernel = ReasoningKernel()
        kernel.register_code_understanding_provider(ExampleCodeProvider())
        preparation = RuntimeRequestPreparation(kernel)

        context, _result = preparation.prepare(
            RequestContext(text="hello", current_file_path="C:/tmp/example.py")
        )

        code_summary = context.extras["reasoning_runtime"]["code_understanding"]
        self.assertEqual(code_summary["provider_count"], 1)
        self.assertEqual(code_summary["summaries"], ["code:C:/tmp/example.py"])


if __name__ == "__main__":
    unittest.main()
