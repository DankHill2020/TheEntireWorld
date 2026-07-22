import unittest

from tech_connector.bridges.error_detection import bridge_output_has_error


class BridgeErrorDetectionTests(unittest.TestCase):
    def test_traceback_text_counts_as_error(self):
        raw = "STDOUT:\nbefore\n\nSTDERR:\nTraceback (most recent call last):\nRuntimeError: boom"

        self.assertTrue(bridge_output_has_error(raw))

    def test_json_result_traceback_text_counts_as_error(self):
        raw = "{'ok': True, 'result': 'Traceback (most recent call last): RuntimeError: boom'}"

        self.assertTrue(bridge_output_has_error(raw))

    def test_clean_host_output_is_not_error(self):
        self.assertFalse(bridge_output_has_error("Cube.001\nCamera\nLight"))


if __name__ == "__main__":
    unittest.main()
