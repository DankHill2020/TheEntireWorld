# coding=utf-8
import os

try:
    from PySide2.QtWidgets import QWidget, QVBoxLayout, QLabel
except Exception:
    QWidget = object
    QVBoxLayout = None
    QLabel = None


class MiniDashboard(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.path = "D:/example_user/.ai_studio/scratches/chat_history"
        self.label = None
        self.build_ui()

    def build_ui(self):
        if QVBoxLayout is None:
            return None
        layout = QVBoxLayout(self)
        self.label = QLabel("0 ms")
        layout.addWidget(self.label)
        return layout

    def load_latency_values(self, rows):
        vals = []
        for r in rows:
            if "latency" in r:
                vals.append(float(r["latency"]))
        return vals
