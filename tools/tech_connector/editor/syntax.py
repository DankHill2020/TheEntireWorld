"""Python syntax highlighting for the code editor."""

import re

from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat


class SimpleCodeHighlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)

        self.keyword_format = QTextCharFormat()
        self.keyword_format.setForeground(QColor("#7aa2f7"))
        self.keyword_format.setFontWeight(QFont.Bold)

        self.string_format = QTextCharFormat()
        self.string_format.setForeground(QColor("#9ece6a"))

        self.comment_format = QTextCharFormat()
        self.comment_format.setForeground(QColor("#565f89"))

        self.number_format = QTextCharFormat()
        self.number_format.setForeground(QColor("#ff9e64"))

        self.function_format = QTextCharFormat()
        self.function_format.setForeground(QColor("#bb9af7"))
        self.function_format.setFontWeight(QFont.Bold)

        self.class_format = QTextCharFormat()
        self.class_format.setForeground(QColor("#2ac3de"))
        self.class_format.setFontWeight(QFont.Bold)

        self.keywords = {
            "False", "None", "True", "and", "as", "assert", "async", "await",
            "break", "class", "continue", "def", "del", "elif", "else", "except",
            "finally", "for", "from", "global", "if", "import", "in", "is",
            "lambda", "nonlocal", "not", "or", "pass", "raise", "return",
            "try", "while", "with", "yield", "self",
        }

    def highlightBlock(self, text):
        comment_index = text.find("#")
        if comment_index >= 0:
            self.setFormat(comment_index, len(text) - comment_index, self.comment_format)

        for pattern in [r'"[^"\\]*(\\.[^"\\]*)*"', r"'[^'\\]*(\\.[^'\\]*)*'"]:
            for m in re.finditer(pattern, text):
                self.setFormat(m.start(), m.end() - m.start(), self.string_format)

        for m in re.finditer(r"\b\d+(\.\d+)?\b", text):
            self.setFormat(m.start(), m.end() - m.start(), self.number_format)

        for word in self.keywords:
            for m in re.finditer(rf"\b{re.escape(word)}\b", text):
                self.setFormat(m.start(), m.end() - m.start(), self.keyword_format)

        for m in re.finditer(r"\bdef\s+([A-Za-z_][A-Za-z0-9_]*)", text):
            self.setFormat(m.start(1), len(m.group(1)), self.function_format)
        for m in re.finditer(r"\bclass\s+([A-Za-z_][A-Za-z0-9_]*)", text):
            self.setFormat(m.start(1), len(m.group(1)), self.class_format)
