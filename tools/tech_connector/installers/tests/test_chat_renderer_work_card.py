import unittest
from types import SimpleNamespace

from tech_connector.ui.chat_renderer import render_thread


class ChatRendererWorkCardTests(unittest.TestCase):
    def test_process_status_lines_render_as_work_card(self):
        owner = SimpleNamespace(code_snippets=[], chat_copy_blocks=[])
        html = render_thread(
            owner,
            "\n[Process +0s] Accepted request - routing\n"
            "[Request] Accepted. Routing and preparing context...\n"
            "[Process +4s] Preparing prompt for LLM\n",
        )

        self.assertIn("class='work-card'", html)
        self.assertIn("Worked for 4s", html)
        self.assertIn("Preparing prompt for LLM", html)
        self.assertNotIn("class='status-chip'>[Process", html)

    def test_assistant_cards_register_copyable_response_anchors(self):
        owner = SimpleNamespace(code_snippets=[], chat_copy_blocks=[])
        html = render_thread(
            owner,
            "ASSISTANT:\nFirst answer\n\nASSISTANT [dcc]:\nSecond answer\n",
        )

        self.assertIn("name='response_0'", html)
        self.assertIn("name='response_1'", html)
        self.assertEqual(["First answer", "Second answer"], owner.chat_copy_blocks)
        self.assertEqual(
            [
                {"anchor": "response_0", "copy_index": 0},
                {"anchor": "response_1", "copy_index": 1},
            ],
            owner.chat_response_anchors,
        )


if __name__ == "__main__":
    unittest.main()
