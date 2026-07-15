"""Project tree UI helpers."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QStyle, QTreeWidgetItem

from services.project_service import build_full_project_tree


def filter_tree_items(tree, text: str) -> None:
    text = (text or "").lower().strip()

    def visit(item):
        own_match = not text or text in item.text(0).lower() or text in item.text(1).lower()
        child_match = False
        for i in range(item.childCount()):
            if visit(item.child(i)):
                child_match = True
        visible = own_match or child_match
        item.setHidden(not visible)
        if text and child_match:
            item.setExpanded(True)
        return visible

    for i in range(tree.topLevelItemCount()):
        visit(tree.topLevelItem(i))


def load_lazy_roots(tree, roots: list[str], style) -> None:
    tree.clear()
    folder_icon = style.standardIcon(QStyle.StandardPixmap.SP_DirIcon)
    for root_path in roots:
        root_p = Path(root_path)
        root_item = QTreeWidgetItem([root_p.name or str(root_p), str(root_p)])
        root_item.setIcon(0, folder_icon)
        root_item.setData(0, Qt.UserRole, "folder")
        tree.addTopLevelItem(root_item)
        if root_p.exists():
            root_item.addChild(QTreeWidgetItem(["Loading...", ""]))
        else:
            root_item.addChild(QTreeWidgetItem(["[missing]", str(root_p)]))


def populate_folder_item(parent_item, folder_path: Path, style, is_supported_fn, folder_has_children_fn, list_entries_fn) -> None:
    parent_item.takeChildren()
    folder_icon = style.standardIcon(QStyle.StandardPixmap.SP_DirIcon)
    file_icon = style.standardIcon(QStyle.StandardPixmap.SP_FileIcon)

    for name, path, kind in list_entries_fn(folder_path):
        if kind == "error":
            parent_item.addChild(QTreeWidgetItem([name, path]))
            continue
        item = QTreeWidgetItem([name, path])
        if kind == "folder":
            item.setIcon(0, folder_icon)
            item.setData(0, Qt.UserRole, "folder")
            if folder_has_children_fn(Path(path)):
                item.addChild(QTreeWidgetItem(["Loading...", ""]))
        else:
            item.setIcon(0, file_icon)
            item.setData(0, Qt.UserRole, "file")
        parent_item.addChild(item)


def load_full_project_tree(tree, roots: list[str], style) -> None:
    """Build an actual IDE-style folder hierarchy (non-lazy)."""
    tree.clear()
    folder_icon = style.standardIcon(QStyle.StandardPixmap.SP_DirIcon)
    file_icon = style.standardIcon(QStyle.StandardPixmap.SP_FileIcon)

    for root_node in build_full_project_tree(roots):
        root_item = _add_node(tree, None, root_node, folder_icon, file_icon)
        root_item.setExpanded(False)

    tree.resizeColumnToContents(0)


def _add_node(parent_widget, parent_item, node: dict, folder_icon, file_icon):
    if parent_item is None:
        item = QTreeWidgetItem([node["name"], node["path"]])
        parent_widget.addTopLevelItem(item)
    else:
        item = QTreeWidgetItem([node["name"], node["path"]])
        parent_item.addChild(item)

    if node["kind"] == "folder":
        item.setIcon(0, folder_icon)
    else:
        item.setIcon(0, file_icon)

    for child in node.get("children", []):
        _add_node(parent_widget, item, child, folder_icon, file_icon)

    return item
