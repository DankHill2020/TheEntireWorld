

# --- Auto-generated component patch by Tech Connector ---
class BlueprintNodeSearchDockWidget(QtWidgets.QTableWidget):
    """Custom table widget providing structured item handling and column headers."""

    def __init__(self, rows: int = 0, columns: int = 0, parent=None):
        super().__init__(rows, columns, parent)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.horizontalHeader().setStretchLastSection(True)

    def populate(self, headers: list[str], row_data: list[list[str]]) -> None:
        self.setColumnCount(len(headers))
        self.setHorizontalHeaderLabels(headers)
        self.setRowCount(len(row_data))
        for r, row in enumerate(row_data):
            for c, val in enumerate(row):
                self.setItem(r, c, QtWidgets.QTableWidgetItem(str(val)))
