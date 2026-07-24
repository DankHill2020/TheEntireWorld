from __future__ import annotations

import unittest

from tech_connector.services.capability_availability_service import (
    build_capability_availability,
    warning_for_decision,
)


class TestCapabilityAvailabilityService(unittest.TestCase):
    def test_status_cards_normalize_to_planner_host_contract(self) -> None:
        availability = build_capability_availability(
            status_cards={
                "unreal": {"status": "off", "detail": "Not connected"},
                "maya": {"status": "ok", "detail": "bridge:7001"},
            },
            settings={},
        )

        self.assertFalse(availability["hosts"]["unreal"]["connected"])
        self.assertEqual("red", availability["hosts"]["unreal"]["light"])
        self.assertTrue(availability["hosts"]["maya"]["connected"])
        self.assertEqual("green", availability["hosts"]["maya"]["light"])

    def test_warning_for_disconnected_dcc_decision(self) -> None:
        availability = build_capability_availability(
            status_cards={"unreal": {"status": "off", "detail": "Bridge not detected"}},
            settings={},
        )
        warning = warning_for_decision(
            {"host": "unreal", "requires_dcc_connection": True},
            availability,
        )

        self.assertIn("Unreal", warning)
        self.assertIn("direct execution is disabled", warning)


if __name__ == "__main__":
    unittest.main()
