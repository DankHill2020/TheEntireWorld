from __future__ import annotations

import unittest

from reasoning_runtime import (
    CapabilityBridge,
    CapabilityResult,
    ContextAdapter,
    ReasoningAdapter,
    ReasoningKernel,
    ToolSpec,
    ValidationContract,
    ValidationReport,
)


class ExampleContext(ContextAdapter):
    name = "example"

    def get_active_context(self):
        return {"value": 1}


class ExampleReasoning(ReasoningAdapter):
    def get_system_instructions(self):
        return "Example instructions."


class ExampleBridge(CapabilityBridge):
    def get_tools(self):
        return [ToolSpec(name="example.echo", input_schema={"type": "object"})]

    def execute_tool(self, tool_name, arguments):
        return CapabilityResult(ok=True, output=arguments)


class ExampleValidation(ValidationContract):
    def validate_preconditions(self, request):
        return ValidationReport(ok=bool(request.get("request")), summary="checked")


class AdapterContractTests(unittest.TestCase):
    def test_kernel_loads_basic_adapters(self):
        kernel = ReasoningKernel()
        kernel.register_context_adapter(ExampleContext())
        kernel.register_reasoning_adapter(ExampleReasoning())
        kernel.register_capability_bridge(ExampleBridge())
        kernel.register_validation_contract(ExampleValidation())

        result = kernel.run("hello")

        self.assertTrue(result.ok)
        self.assertEqual(result.context["example"]["value"], 1)
        self.assertEqual(result.tools[0].name, "example.echo")
        self.assertEqual(result.system_instructions, ("Example instructions.",))

    def test_validation_failure_marks_run_not_ok(self):
        kernel = ReasoningKernel()
        kernel.register_validation_contract(ExampleValidation())

        result = kernel.run("")

        self.assertFalse(result.ok)
        self.assertEqual(result.validation[0].summary, "checked")


if __name__ == "__main__":
    unittest.main()
