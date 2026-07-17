"""In-file editor search helpers."""

from PySide6.QtGui import QTextCursor, QTextDocument


def find_in_editor(editor, query: str) -> bool:
    if not query:
        return False

    flags = QTextDocument.FindFlags()
    found = editor.find(query, flags)
    if not found:
        cursor = editor.textCursor()
        cursor.movePosition(QTextCursor.Start)
        editor.setTextCursor(cursor)
        found = editor.find(query, flags)
    return found


def duplicate_line(editor) -> None:
    cursor = editor.textCursor()
    cursor.select(QTextCursor.LineUnderCursor)
    line = cursor.selectedText()
    cursor.movePosition(QTextCursor.EndOfLine)
    cursor.insertText("\n" + line)


def comment_selection_python_style(editor) -> None:
    cursor = editor.textCursor()
    if not cursor.hasSelection():
        cursor.select(QTextCursor.LineUnderCursor)

    start = cursor.selectionStart()
    end = cursor.selectionEnd()
    cursor.setPosition(start)
    start_block = cursor.blockNumber()
    cursor.setPosition(end)
    end_block = cursor.blockNumber()

    cursor.beginEditBlock()
    for block_no in range(start_block, end_block + 1):
        block = editor.document().findBlockByNumber(block_no)
        c = QTextCursor(block)
        text = block.text()
        stripped = text.lstrip()
        indent_len = len(text) - len(stripped)
        c.setPosition(block.position() + indent_len)
        if stripped.startswith("#"):
            c.deleteChar()
            if c.block().text()[indent_len:indent_len + 1] == " ":
                c.deleteChar()
        else:
            c.insertText("# ")
    cursor.endEditBlock()


def trim_trailing_whitespace(editor) -> str:
    text = editor.toPlainText()
    lines = [line.rstrip() for line in text.splitlines()]
    new_text = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    editor.setPlainText(new_text)
    return new_text
