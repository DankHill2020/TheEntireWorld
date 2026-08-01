from __future__ import annotations

import unittest

from reasoning_runtime import (
    IndexProvider,
    IndexQuery,
    IndexRecord,
    IndexRegistry,
    IndexSearchResult,
    ReasoningKernel,
)


class ExampleIndexProvider(IndexProvider):
    name = "example_index"

    def search(self, query: IndexQuery):
        return [
            IndexSearchResult(
                record=IndexRecord(
                    record_id="example:1",
                    title="Example",
                    text=query.query,
                    source=self.name,
                ),
                score=0.9,
            )
        ]


class IndexingContractTests(unittest.TestCase):
    def test_index_registry_searches_registered_providers(self):
        registry = IndexRegistry([ExampleIndexProvider()])

        results = registry.search(IndexQuery("find code"))

        self.assertEqual(results[0].record.text, "find code")
        self.assertEqual(results[0].record.source, "example_index")

    def test_kernel_exposes_index_providers(self):
        kernel = ReasoningKernel()
        kernel.register_index_provider(ExampleIndexProvider())

        result = kernel.run("hello")

        self.assertEqual(result.metadata["adapter_counts"]["index_providers"], 1)
        self.assertEqual(len(kernel.index_registry().providers), 1)


if __name__ == "__main__":
    unittest.main()
