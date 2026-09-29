"""Shared onboarding, discoverability, and control-guidance polish."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractButton, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QPushButton, QTabWidget, QTreeWidget, QVBoxLayout, QWidget,
)

from tech_connector.ui.design_system import set_ui_role
from tech_connector.ui.icons import configure_button


@dataclass(frozen=True)
class ToolGuidance:
    summary: str
    requires: str = ""
    result: str = ""
    shortcut: str = ""
    note: str = ""


@dataclass(frozen=True)
class WorkflowRecipe:
    """A compact, reusable explanation for a specialist workflow."""

    title: str
    steps: tuple[str, ...]
    requires: str = ""
    preview: str = ""
    output: str = ""
    tip: str = ""


def guidance_tooltip(guidance: ToolGuidance) -> str:
    """Return a predictable, quickly scannable tooltip."""
    lines = [guidance.summary.strip()]
    if guidance.requires:
        lines.extend(("", f"Before you start: {guidance.requires.strip()}"))
    if guidance.result:
        lines.append(f"Result: {guidance.result.strip()}")
    if guidance.shortcut:
        lines.append(f"Shortcut: {guidance.shortcut.strip()}")
    if guidance.note:
        lines.extend(("", guidance.note.strip()))
    return "\n".join(lines)


MAJOR_ACTION_GUIDANCE = {
    "Load Project": ToolGuidance(
        "Open a project workspace so files, symbols, and tools have a clear scope.",
        result="The project tree and recent-project list update; nothing is modified.",
    ),
    "Update Project": ToolGuidance(
        "Refresh the visible project tree from disk.",
        requires="Load a project first.", result="New and removed files appear in the sidebar.",
    ),
    "Quick index": ToolGuidance(
        "Index new and changed project files for search and grounded answers.",
        requires="Choose the project and any extra knowledge directories.",
        result="Search, symbols, and project-aware prompts become more accurate.",
    ),
    "Graph": ToolGuidance(
        "Rebuild the dependency and dead-code graph from the current index.",
        requires="Build the knowledge index first.",
        result="Dependency-aware search and impact analysis are refreshed.",
    ),
    "Install": ToolGuidance(
        "Open component installation and update tools.",
        result="You can review components before any installation begins.",
    ),
    "Send": ToolGuidance(
        "Send the request using the project, open-file, selection, and tab context shown below.",
        shortcut="Enter to send; Shift+Enter for a new line.",
    ),
    "New": ToolGuidance("Start a new conversation.", result="The current conversation remains in history."),
    "Save": ToolGuidance("Save the current conversation to history."),
    "Open in Editor": ToolGuidance(
        "Open the selected saved code snippet in an editor tab.", requires="Select or double-click a snippet first.",
    ),
}


class GettingStartedCard(QFrame):
    dismissed = Signal()

    def __init__(self, window: QWidget):
        super().__init__(window)
        self.window_ref = window
        self.setObjectName("uxGettingStartedCard")
        self.setAccessibleName("Getting started guide")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 11, 14, 11)
        outer.setSpacing(8)

        heading = QHBoxLayout()
        title_column = QVBoxLayout()
        title_column.setSpacing(1)
        title = QLabel("Start here")
        set_ui_role(title, "sectionTitle")
        title_column.addWidget(title)
        subtitle = QLabel("Three steps are enough. You can discover advanced tools as you need them.")
        subtitle.setWordWrap(True)
        set_ui_role(subtitle, "muted")
        title_column.addWidget(subtitle)
        heading.addLayout(title_column, 1)
        dismiss = QPushButton()
        configure_button(dismiss, "close", tooltip="Dismiss this guide. Reopen it with the Guide button.",
                         role="quiet", icon_only=True)
        dismiss.clicked.connect(self._dismiss)
        heading.addWidget(dismiss)
        outer.addLayout(heading)

        steps = QHBoxLayout()
        steps.setSpacing(8)
        steps.addWidget(self._step("1", "Choose a project", "Sets the scope for files and search.",
                                   "Choose project", self._choose_project), 1)
        steps.addWidget(self._step("2", "Build knowledge", "Indexes changed files for grounded help.",
                                   "Quick index", self._build_index), 1)
        steps.addWidget(self._step("3", "Ask naturally", "Describe the result you want; context is inferred.",
                                   "Try an example", self._try_example), 1)
        outer.addLayout(steps)

        tip = QLabel("Tip: Hover any control to see what it does, what it needs, and what will change.")
        tip.setWordWrap(True)
        set_ui_role(tip, "muted")
        outer.addWidget(tip)

    def _step(self, number: str, title: str, detail: str, action: str,
              callback: Callable[[], None]) -> QWidget:
        card = QFrame(self)
        card.setProperty("uiRole", "onboardingStep")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)
        label = QLabel(f"{number}  {title}")
        set_ui_role(label, "sectionTitle")
        layout.addWidget(label)
        explanation = QLabel(detail)
        explanation.setWordWrap(True)
        set_ui_role(explanation, "muted")
        layout.addWidget(explanation, 1)
        button = QPushButton(action)
        configure_button(button, "arrow_right", text=action,
                         role="primary" if number == "1" else "secondary")
        button.clicked.connect(callback)
        layout.addWidget(button, 0, Qt.AlignLeft)
        return card

    def _choose_project(self) -> None:
        callback = getattr(self.window_ref, "load_project", None)
        if callable(callback):
            callback()

    def _build_index(self) -> None:
        callback = getattr(self.window_ref, "build_index", None)
        if callable(callback):
            callback()

    def _try_example(self) -> None:
        prompt = getattr(self.window_ref, "input", None)
        if prompt is not None and hasattr(prompt, "setText"):
            prompt.setText("Show me what I can do in this project, then suggest one safe first task.")
            prompt.setFocus(Qt.OtherFocusReason)

    def _dismiss(self) -> None:
        self.hide()
        self.dismissed.emit()


class ContextRecipeCard(QFrame):
    """Collapsible in-context instructions that keep advanced surfaces approachable."""

    def __init__(self, recipe: WorkflowRecipe, parent: QWidget | None = None, *, expanded: bool = True):
        super().__init__(parent)
        self.recipe = recipe
        self.setObjectName("uxContextRecipe")
        self.setAccessibleName(f"{recipe.title} workflow guide")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(11, 8, 11, 8)
        outer.setSpacing(6)

        heading = QHBoxLayout()
        self.toggle = QPushButton()
        self.toggle.setCheckable(True)
        self.toggle.setChecked(bool(expanded))
        configure_button(self.toggle, "sparkles", text=recipe.title,
                         tooltip="Show or hide this workflow guide.", role="quiet")
        self.toggle.toggled.connect(self._set_expanded)
        heading.addWidget(self.toggle, 0, Qt.AlignLeft)
        heading.addStretch(1)
        outer.addLayout(heading)

        self.detail = QWidget(self)
        detail_layout = QVBoxLayout(self.detail)
        detail_layout.setContentsMargins(2, 0, 2, 2)
        detail_layout.setSpacing(4)
        if recipe.requires:
            detail_layout.addWidget(self._line("Before you start", recipe.requires))
        steps = "  →  ".join(f"{index}. {step}" for index, step in enumerate(recipe.steps, 1))
        detail_layout.addWidget(self._line("Workflow", steps))
        if recipe.preview:
            detail_layout.addWidget(self._line("Preview", recipe.preview))
        if recipe.output:
            detail_layout.addWidget(self._line("Output", recipe.output))
        if recipe.tip:
            detail_layout.addWidget(self._line("Good first move", recipe.tip))
        outer.addWidget(self.detail)
        self._set_expanded(bool(expanded))

    def _line(self, label: str, value: str) -> QLabel:
        widget = QLabel(f"<b>{label}:</b> {value}", self)
        widget.setWordWrap(True)
        set_ui_role(widget, "muted")
        return widget

    def _set_expanded(self, expanded: bool) -> None:
        self.detail.setVisible(bool(expanded))
        self.toggle.setAccessibleDescription(
            ("Hide" if expanded else "Show") + f" the {self.recipe.title.lower()} instructions."
        )


def apply_property_guidance(control: QWidget, summary: str, *, safe_start: str = "",
                            consequence: str = "") -> None:
    """Explain an expert property in artist language, including a safe starting point."""
    parts = [str(summary).strip()]
    if safe_start:
        parts.extend(("", f"Safe start: {str(safe_start).strip()}"))
    if consequence:
        parts.append(f"Watch for: {str(consequence).strip()}")
    tooltip = "\n".join(parts)
    control.setToolTip(tooltip)
    control.setAccessibleDescription(tooltip)


def apply_action_guidance(action: object, summary: str, *, requires: str = "", result: str = "") -> None:
    """Add tooltip and status guidance to QAction-like objects without importing QtGui here."""
    guidance = guidance_tooltip(ToolGuidance(summary, requires=requires, result=result))
    if hasattr(action, "setToolTip"):
        action.setToolTip(guidance)
    if hasattr(action, "setStatusTip"):
        action.setStatusTip(summary)


def apply_main_window_ux_polish(window: QWidget) -> None:
    """Install novice orientation and normalize discoverability metadata."""
    _install_getting_started(window)
    apply_widget_discoverability(window)
    _polish_primary_workspace_controls(window)


def apply_widget_discoverability(root: QWidget) -> None:
    """Fill accessibility gaps and explain unavailable controls consistently."""
    for control in root.findChildren(QWidget):
        label = _control_label(control)
        if label and not control.accessibleName():
            control.setAccessibleName(label)
        guidance = MAJOR_ACTION_GUIDANCE.get(label)
        if guidance is not None:
            tooltip = guidance_tooltip(guidance)
            control.setToolTip(tooltip)
            control.setAccessibleDescription(tooltip)
            control.setStatusTip(guidance.summary)
        elif control.toolTip() and not control.accessibleDescription():
            control.setAccessibleDescription(control.toolTip())
        if isinstance(control, (QComboBox, QLineEdit)) and not control.toolTip():
            description = label or "this value"
            control.setToolTip(f"Choose or enter {description.lower()}. Changes apply to the current workspace context.")


def apply_3d_viewer_ux_polish(viewer: QWidget) -> None:
    """Orient first-time 3D users without covering the viewport."""
    apply_widget_discoverability(viewer)
    if getattr(viewer, "viewer_getting_started_hint", None) is not None:
        return
    root = viewer.layout()
    splitter = getattr(viewer, "scene_splitter", None)
    if root is None or splitter is None:
        return
    banner = QFrame(viewer)
    banner.setObjectName("uxContextGuide")
    row = QHBoxLayout(banner)
    row.setContentsMargins(10, 5, 7, 5)
    row.setSpacing(8)
    label = QLabel(
        "3D workflow:  1 Load or sync a scene  →  2 Select an object in the Outliner  →  "
        "3 Choose a tool  →  4 Preview, tune, then export"
    )
    label.setWordWrap(True)
    set_ui_role(label, "muted")
    row.addWidget(label, 1)
    close = QPushButton("Got it")
    configure_button(close, "check", text="Got it", tooltip="Hide this workflow reminder.", role="quiet")
    close.clicked.connect(banner.hide)
    row.addWidget(close)
    root.insertWidget(max(0, root.indexOf(splitter)), banner)
    viewer.viewer_getting_started_hint = banner
    outliner = getattr(viewer, "scene_outliner", None)
    if isinstance(outliner, QTreeWidget):
        outliner.setToolTip(
            "Scene Outliner\n\nSelect an object, joint, skin, or deformer here before using context-sensitive tools. "
            "Right-click a selection for relevant actions."
        )
    status = getattr(viewer, "viewport_status_label", None)
    if status is not None:
        status.setToolTip("Shows what the last tool did, what is currently running, or why an action could not start.")


def explain_disabled(control: QWidget, reason: str) -> None:
    """Disable a control without leaving users to guess why."""
    control.setEnabled(False)
    current = control.toolTip().strip()
    message = f"Unavailable: {str(reason).strip()}"
    control.setToolTip((current + "\n\n" if current else "") + message)
    control.setAccessibleDescription(control.toolTip())


def _install_getting_started(window: QWidget) -> None:
    if getattr(window, "getting_started_card", None) is not None:
        return
    root = window.layout()
    top = getattr(window, "top_section_widget", None)
    if root is None or top is None:
        return
    card = GettingStartedCard(window)
    card.setVisible(not bool(getattr(window, "settings", {}).get("getting_started_dismissed", False)))

    def persist_dismissal():
        settings = getattr(window, "settings", None)
        if isinstance(settings, dict):
            settings["getting_started_dismissed"] = True
            try:
                window.service.save_settings(settings)
            except Exception:
                pass

    card.dismissed.connect(persist_dismissal)
    root.insertWidget(max(0, root.indexOf(top) + 1), card)
    window.getting_started_card = card

    controls_widget = getattr(window, "menu_bar_controls_widget", None)
    controls = controls_widget.layout() if controls_widget is not None else None
    if controls is not None:
        guide = QPushButton()
        configure_button(guide, "sparkles", text="Guide",
                         tooltip="Show or hide the getting-started guide.", role="quiet")
        guide.clicked.connect(lambda: card.setVisible(not card.isVisible()))
        controls.insertWidget(max(0, controls.count() - 1), guide)
        window.getting_started_toggle_btn = guide


def _polish_primary_workspace_controls(window: QWidget) -> None:
    project_tree = getattr(window, "project_tree", None)
    if isinstance(project_tree, QTreeWidget):
        project_tree.setToolTip("Project files. Double-click a file to open it; right-click for file actions.")
        project_tree.setAccessibleDescription(project_tree.toolTip())
    history = getattr(window, "history", None)
    if isinstance(history, QListWidget):
        history.setToolTip("Saved conversations. Select one to restore it; right-click for history actions.")
    snippets = getattr(window, "code_list", None)
    if isinstance(snippets, QListWidget):
        snippets.setToolTip("Saved code snippets. Double-click one to open it in the editor.")
    tabs = getattr(window, "workspace_tabs", None)
    if isinstance(tabs, QTabWidget):
        tabs.setToolTip("Choose a workspace. Tabs can be reordered, detached, hidden, or anchored side by side.")
    prompt = getattr(window, "input", None)
    if prompt is not None:
        prompt.setToolTip(guidance_tooltip(ToolGuidance(
            "Describe the outcome you want in ordinary language.",
            "Load a project for project-aware answers; select an object or open a file for focused context.",
            "The context strip below previews what will be used.",
            "Enter to send; Shift+Enter for a new line.",
            "You do not need to know command names—ask what is possible or request a guided workflow.",
        )))


def _control_label(control: QWidget) -> str:
    if isinstance(control, QAbstractButton):
        return str(control.text() or control.accessibleName()).replace("&", "").strip()
    if isinstance(control, QComboBox):
        return str(control.accessibleName() or control.objectName()).replace("_", " ").strip()
    if isinstance(control, QLineEdit):
        return str(control.placeholderText() or control.accessibleName()).strip(" .")
    name = str(control.accessibleName() or "").strip()
    return re.sub(r"\s+", " ", name)


__all__ = ["ContextRecipeCard", "GettingStartedCard", "ToolGuidance", "WorkflowRecipe",
           "apply_3d_viewer_ux_polish", "apply_action_guidance", "apply_main_window_ux_polish",
           "apply_property_guidance", "apply_widget_discoverability", "explain_disabled", "guidance_tooltip"]
