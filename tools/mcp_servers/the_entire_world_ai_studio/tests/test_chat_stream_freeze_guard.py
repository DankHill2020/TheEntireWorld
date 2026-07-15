import unittest

from app.main_window_chat_runtime import MainWindowChatRuntimeMixin


class _FakeCursor:
    def __init__(self):
        self.inserted = []

    def movePosition(self, *_args, **_kwargs):
        return True

    def insertBlock(self):
        self.inserted.append("\n")

    def insertText(self, text):
        self.inserted.append(text)


class _FakeDocument:
    def characterCount(self):
        return 1


class _FakeLog:
    def __init__(self):
        self.cursor = _FakeCursor()
        self.html_updates = 0
        self.moved_to_end = 0
        self.scroll = _FakeScrollBar()

    def textCursor(self):
        return self.cursor

    def setTextCursor(self, cursor):
        self.cursor = cursor

    def document(self):
        return _FakeDocument()

    def moveCursor(self, *_args, **_kwargs):
        self.moved_to_end += 1

    def setHtml(self, _html):
        self.html_updates += 1

    def verticalScrollBar(self):
        return self.scroll


class _FakeScrollBar:
    def __init__(self):
        self._value = 0
        self._maximum = 100

    def value(self):
        return self._value

    def maximum(self):
        return self._maximum

    def setValue(self, value):
        self._value = value


class ChatStreamFreezeGuardTests(unittest.TestCase):
    def test_stream_preview_appends_plain_text_without_full_html_render(self):
        window = MainWindowChatRuntimeMixin()
        window.log = _FakeLog()
        window._stream_preview_render_pending = {"main"}
        window._stream_preview_content_by_role = {
            "main": {
                "header": "ASSISTANT",
                "content": "hello from a slow local stream",
                "rendered": 0,
            }
        }
        window._stream_plain_started_roles = set()
        window._chat_render_pending_bottom = True

        window._render_stream_preview("main")

        self.assertEqual(window.log.html_updates, 0)
        self.assertIn("ASSISTANT:\n", window.log.cursor.inserted)
        self.assertIn("hello from a slow local stream", window.log.cursor.inserted)
        self.assertEqual(
            window._stream_preview_content_by_role["main"]["rendered"],
            len("hello from a slow local stream"),
        )

    def test_visible_prompt_text_truncates_chat_only(self):
        window = MainWindowChatRuntimeMixin()
        window.settings = {"chat_visible_prompt_char_limit": 10}

        visible = window._visible_prompt_text("0123456789abcdef")

        self.assertTrue(visible.startswith("0123456789"))
        self.assertIn("kept in the request/session", visible)

    def test_full_render_preserves_scroll_when_user_is_not_at_bottom(self):
        window = MainWindowChatRuntimeMixin()
        window.log = _FakeLog()
        window.settings = {}
        window.chat_history_raw = "ASSISTANT:\nHello\n"
        window._chat_render_pending_bottom = False
        window._chat_render_previous_scroll = 37

        window.render_chat_history()

        self.assertEqual(1, window.log.html_updates)
        self.assertEqual(0, window.log.moved_to_end)
        self.assertEqual(37, window.log.scroll.value())


if __name__ == "__main__":
    unittest.main()
