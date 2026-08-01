from __future__ import annotations

import unittest

from reasoning_runtime import ResourceLane


class ResourceOrchestrationContractTests(unittest.TestCase):
    def test_resource_lane_serializes_work_tuple(self):
        lane = ResourceLane("search", "Search", 2, ("index", "ast"))

        self.assertEqual(lane.to_dict()["work"], ["index", "ast"])


if __name__ == "__main__":
    unittest.main()
