import unittest

from tech_connector.ui.animation_timeline_widget import playback_frame_for_elapsed


class AnimationTimelineClockTests(unittest.TestCase):
    def test_24_fps_clock_has_no_integer_timer_drift(self):
        frame, steps = playback_frame_for_elapsed(0, 10.0, 24.0, 1000)
        self.assertEqual(steps, 240)
        self.assertEqual(frame, 240)

    def test_clock_loops_and_preserves_fractional_frame_rates(self):
        frame, steps = playback_frame_for_elapsed(8, 100.0, 29.97, 100)
        self.assertEqual(steps, 2997)
        self.assertEqual(frame, 5)

    def test_clock_never_advances_before_the_source_frame_deadline(self):
        frame, steps = playback_frame_for_elapsed(4, (1.0 / 24.0) - 1.0e-5, 24.0, 10)
        self.assertEqual(steps, 0)
        self.assertEqual(frame, 4)


if __name__ == "__main__":
    unittest.main()
