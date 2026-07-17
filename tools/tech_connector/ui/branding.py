"""Application branding stylesheet."""


def application_stylesheet() -> str:
    return """
            /* Main Application Background and Text */
            QWidget {
                background-color: #000102;
                color: #effff4;
                font-family: "Segoe UI", "Inter", sans-serif;
                font-size: 12px;
            }

            /* Text Editors, Lists, Dropdowns */
            QTextEdit, QTextBrowser, QPlainTextEdit, QLineEdit, QListWidget, QComboBox, QTableWidget, QTreeWidget {
                background-color: #000203;
                color: #effff4;
                border: 1px solid #12324a;
                border-radius: 6px;
                padding: 4px;
                selection-background-color: #5bd000;
                selection-color: #041105;
            }

            /* Chat and progress readability */
            QTextBrowser {
                background-color: #060a08;
                color: #effff4;
                border: 1px solid #173d26;
                selection-background-color: #5bd000;
                selection-color: #041105;
            }

            /* Active glowing focus effect on inputs */
            QTextEdit:focus, QPlainTextEdit:focus, QLineEdit:focus, QComboBox:focus {
                border: 1px solid #1e9bff;
                background-color: #010609;
            }

            /* Custom Dropdown ComboBox Arrow Styling */
            QComboBox {
                padding-right: 20px;
            }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 20px;
                border-left-width: 1px;
                border-left-color: #12324a;
                border-left-style: solid;
                border-top-right-radius: 6px;
                border-bottom-right-radius: 6px;
            }
            QComboBox::arrow {
                image: none;
                border: none;
                width: 0;
                height: 0;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid #1e9bff;
                margin-top: 1px;
            }
            QComboBox::arrow:hover {
                border-top: 5px solid #1e9bff;
            }
            QComboBox QAbstractItemView {
                background-color: #020304;
                color: #effff4;
                border: 1px solid #12324a;
                selection-background-color: #5bd000;
                selection-color: #041105;
            }

            /* Buttons: dark logo-blue controls; green is reserved for status/health lights. */
            QPushButton, QToolButton {
                background-color: #010304;
                color: #effff4;
                border: 1px solid #1e9bff;
                border-radius: 6px;
                padding: 6px 12px;
                font-weight: bold;
            }

            QPushButton:hover, QToolButton:hover {
                background-color: #03131e;
                border: 1px solid #4bb4ff;
                color: #ffffff;
            }

            QPushButton:pressed, QToolButton:pressed {
                background-color: #05213a;
                border: 1px solid #7bc8ff;
                color: #effff4;
            }

            QPushButton:disabled, QToolButton:disabled {
                background-color: #020506;
                border: 1px solid #12324a;
                color: #577386;
            }

            /* Progress Bar Styling: Sleek modern layout with gradients */
            QProgressBar {
                border: 1px solid #1e9bff;
                border-radius: 4px;
                text-align: center;
                background-color: #000203;
                color: #ffffff;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #5bd000, stop:1 #1e9bff);
                border-radius: 3px;
            }

            /* Splitters: thin elegant dividers */
            QSplitter::handle {
                background-color: #020506;
            }
            QSplitter::handle:horizontal {
                width: 6px;
            }
            QSplitter::handle:vertical {
                height: 6px;
            }
            QSplitter::handle:hover {
                background-color: #1e9bff;
            }

            /* Tab Panels: modern pill-like tabs */
            QTabWidget::pane {
                border: 1px solid #12324a;
                background-color: #000203;
                border-radius: 6px;
            }
            QTabWidget[validTabDrop="true"]::pane {
                border: 2px solid #1e9bff;
                background-color: #03131e;
            }

            QTabBar::tab {
                background-color: #020506;
                color: #8fb9c9;
                padding: 8px 16px;
                border: 1px solid #12324a;
                border-bottom: none;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                min-width: 100px;
                margin-right: 2px;
            }

            QTabBar::tab:selected {
                background-color: #03131e;
                color: #1e9bff;
                border: 1px solid #1e9bff;
                border-bottom: none;
                font-weight: bold;
            }

            QTabBar::tab:hover {
                background-color: #041a2a;
                color: #ffffff;
            }

            QTabBar::tab:!selected {
                margin-top: 3px;
            }

            /* Clean, modern scrollbars */
            QScrollBar:vertical {
                background-color: #000203;
                width: 10px;
                margin: 0px;
                border-radius: 5px;
            }

            QScrollBar::handle:vertical {
                background-color: #1e9bff;
                min-height: 20px;
                border-radius: 5px;
            }

            QScrollBar::handle:vertical:hover {
                background-color: #1e9bff;
            }

            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
                background: none;
            }

            QScrollBar:horizontal {
                background-color: #000203;
                height: 10px;
                margin: 0px;
                border-radius: 5px;
            }

            QScrollBar::handle:horizontal {
                background-color: #1e9bff;
                min-width: 20px;
                border-radius: 5px;
            }

            QScrollBar::handle:horizontal:hover {
                background-color: #1e9bff;
            }

            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0px;
                background: none;
            }

            /* Trees & Item Selections */
            QTreeWidget::item, QListWidget::item {
                padding: 4px;
                border-radius: 4px;
            }
            QTreeWidget::item:hover, QListWidget::item:hover {
                background-color: #061321;
            }
            QTreeWidget::item:selected, QListWidget::item:selected {
                background-color: #062b40;
                border-left: 2px solid #1e9bff;
                color: #effff4;
                font-weight: bold;
            }
            QTreeView::branch {
                background: transparent;
                min-width: 14px;
            }
            QTreeView::branch:has-children:closed,
            QTreeView::branch:closed:has-children:has-siblings,
            QTreeView::branch:closed:has-children:!has-siblings {
                border: 1px solid #1e9bff;
                background-color: #03131e;
                image: none;
                width: 9px;
                height: 9px;
                margin: 4px;
            }
            QTreeView::branch:has-children:open,
            QTreeView::branch:open:has-children:has-siblings,
            QTreeView::branch:open:has-children:!has-siblings {
                border: 1px solid #5bd000;
                background-color: #000711;
                image: none;
                width: 9px;
                height: 9px;
                margin: 4px;
            }

            /* Menu Bar & Menu Items */
            QMenuBar {
                background-color: #000102;
                color: #effff4;
                border-bottom: 1px solid #12324a;
            }
            QMenuBar::item {
                background-color: transparent;
                padding: 4px 10px;
                margin: 2px 2px;
                border-radius: 4px;
                color: #effff4;
            }
            QMenuBar::item:selected {
                background-color: #061321;
                color: #1e9bff;
            }
            QMenuBar::item:pressed {
                background-color: #05213a;
                color: #effff4;
            }

            /* Clean Context Menus & Dropdowns */
            QMenu {
                background-color: #000203;
                color: #effff4;
                border: 1px solid #1e9bff;
                border-radius: 6px;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 24px 6px 20px;
                border-radius: 4px;
                background-color: transparent;
                color: #effff4;
            }
            QMenu::item:selected {
                background-color: #061321;
                color: #1e9bff;
                font-weight: bold;
            }
            QMenu::separator {
                height: 1px;
                background-color: #12324a;
                margin: 4px 0px;
            }

            QLabel#statusBandLabel, QLabel#activeModelStatusLabel, QLabel#liveProcessStatusLabel {
                background-color: #000711;
                border: 1px solid #1e9bff;
                border-radius: 5px;
                color: #b9dcff;
                padding: 4px 8px;
            }

            QLabel#statusBandLabel[statusState="warn"], QLabel#activeModelStatusLabel[statusState="warn"],
            QLabel#liveProcessStatusLabel[statusState="warn"] {
                border-color: #ff9f1c;
                color: #ffd08a;
                background-color: #100804;
            }

            /* Tooltips */
            QToolTip {
                background-color: #020304;
                color: #effff4;
                border: 1px solid #1e9bff;
                border-radius: 4px;
                padding: 4px;
            }
        """
