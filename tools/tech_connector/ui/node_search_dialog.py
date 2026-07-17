from PySide6.QtWidgets import QDialog, QVBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QHBoxLayout, QPushButton
from tech_connector.services.project_search_service import _active_project_roots
from tech_connector.services.tool_discovery_service import list_internal_functions

class ToolSearchDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Search and Add Tool Node")
        self.resize(500, 400)
        
        layout = QVBoxLayout(self)
        
        self.search_bar = QLineEdit(self)
        self.search_bar.setPlaceholderText("Filter functions...")
        self.search_bar.textChanged.connect(self.filter_list)
        layout.addWidget(self.search_bar)
        
        self.list_widget = QListWidget(self)
        layout.addWidget(self.list_widget)
        
        self.buttons = QHBoxLayout()
        self.ok_btn = QPushButton("Add Node", self)
        self.ok_btn.clicked.connect(self.accept)
        self.cancel_btn = QPushButton("Cancel", self)
        self.cancel_btn.clicked.connect(self.reject)
        self.buttons.addWidget(self.ok_btn)
        self.buttons.addWidget(self.cancel_btn)
        layout.addLayout(self.buttons)
        
        self.symbols = []
        self.load_symbols()
        
    def load_symbols(self):
        try:
            roots = _active_project_roots()
            self.symbols = list_internal_functions(roots)
        except Exception as e:
            print(f"Error loading symbols: {e}")
            self.symbols = []
        self.filter_list("")
        
    def filter_list(self, text):
        self.list_widget.clear()
        query = text.lower()
        for sym in self.symbols:
            name = sym.get("name", "")
            doc = sym.get("docstring", "") or ""
            if query and query not in name.lower() and query not in doc.lower():
                continue
            first_doc_line = doc.splitlines()[0] if doc.strip() else ""
            item = QListWidgetItem(f"{name} ({first_doc_line})" if first_doc_line else name)
            item.setData(100, sym)
            self.list_widget.addItem(item)
            
    def get_selected_symbol(self):
        item = self.list_widget.currentItem()
        if item:
            return item.data(100)
        return None
