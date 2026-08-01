from __future__ import annotations

import unittest

from reasoning_runtime import SymbolHit, SymbolLookupBroker, SymbolLookupProvider, SymbolQuery


class ExampleSymbolLookupProvider(SymbolLookupProvider):
    name = "example_symbols"

    def find_symbols(self, query: SymbolQuery) -> list[SymbolHit]:
        if query.query.lower() not in {"thing", "examplething"}:
            return []
        return [
            SymbolHit(
                symbol_id=1,
                name="ExampleThing",
                qualname="pkg.module.ExampleThing",
                kind="class",
                path="/tmp/pkg/module.py",
                score=10.0,
            )
        ]


class SymbolLookupContractTests(unittest.TestCase):
    def test_symbol_lookup_broker_returns_registered_provider_hits(self):
        broker = SymbolLookupBroker([ExampleSymbolLookupProvider()])
        hits = broker.find_symbols(SymbolQuery("ExampleThing"))
        self.assertEqual(1, len(hits))
        self.assertEqual("ExampleThing", hits[0].name)
        self.assertEqual("pkg.module.ExampleThing", hits[0].qualname)


if __name__ == "__main__":
    unittest.main()
