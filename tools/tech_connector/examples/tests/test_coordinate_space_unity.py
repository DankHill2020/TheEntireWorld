import unittest

from tech_connector.services.dcc.coordinate_space_service import (
    provider_default_unit,
    provider_native_to_shared,
    shared_to_provider_native,
)


class UnityCoordinateSpaceTests(unittest.TestCase):
    def test_unity_defaults_to_meter_y_up_space(self):
        self.assertEqual(provider_default_unit("unity"), "meters")
        self.assertEqual(provider_native_to_shared("unity", (1.0, 2.0, 3.0)), (100.0, 200.0, 300.0))

    def test_unity_camera_points_round_trip_without_axis_swizzle(self):
        native = (1.25, -2.5, 3.75)
        shared = provider_native_to_shared("unity", native)

        self.assertEqual(shared_to_provider_native("unity", shared), native)


if __name__ == "__main__":
    unittest.main()
