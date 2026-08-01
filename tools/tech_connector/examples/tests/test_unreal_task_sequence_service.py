from __future__ import annotations

import unittest

from tech_connector.services.unreal.unreal_task_sequence_service import (
    _parse_verdict_rows,
)


class TestUnrealTaskSequenceService(unittest.TestCase):
    def test_recovers_complete_verdict_from_truncated_model_envelope(self) -> None:
        raw = (
            '{"verdicts":[{"id":"clause_09","match":true,'
            '"missing_terms":["extra diagnostic"],"confidence":4},'
            '{"id":"clause_09","match":true'
        )

        rows = _parse_verdict_rows(raw)

        self.assertEqual(1, len(rows))
        self.assertTrue(rows[0]["match"])
        self.assertEqual(1.0, rows[0]["confidence"])
        self.assertEqual([], rows[0]["missing_terms"])
        self.assertEqual(["extra diagnostic"], rows[0]["dismissed_missing_terms"])


if __name__ == "__main__":
    unittest.main()
