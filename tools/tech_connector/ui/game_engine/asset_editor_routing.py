"""Registry-driven routing from asset descriptors to contextual editor handlers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from tech_connector.game_engine.assets import AssetTypeDescriptor


@dataclass(frozen=True)
class AssetEditorOpenReceipt:
    opened: bool
    editor_id: str
    workspace: str
    path: str
    message: str


class AssetEditorRouter:
    def __init__(self) -> None:
        self._handlers: dict[str, tuple[str, Callable[[str, AssetTypeDescriptor, str], bool]]] = {}

    def register(
        self,
        editor_id: str,
        workspace: str,
        handler: Callable[[str, AssetTypeDescriptor, str], bool],
        *,
        replace: bool = False,
    ) -> None:
        key = str(editor_id).casefold()
        if key in self._handlers and not replace:
            raise KeyError(f"Asset editor route is already registered: {editor_id}")
        if not callable(handler):
            raise TypeError("Asset editor route handlers must be callable.")
        self._handlers[key] = (str(workspace), handler)

    def open(self, path: str, descriptor: AssetTypeDescriptor, asset_id: str = "") -> AssetEditorOpenReceipt:
        route = self._handlers.get(descriptor.editor_id.casefold())
        if route is None:
            return AssetEditorOpenReceipt(
                False,
                descriptor.editor_id,
                "Assets",
                str(path),
                f"{descriptor.display_name} is registered, but its dedicated editor is not available yet.",
            )
        workspace, handler = route
        try:
            opened = bool(handler(str(path), descriptor, str(asset_id)))
        except Exception as exc:
            return AssetEditorOpenReceipt(False, descriptor.editor_id, workspace, str(path), str(exc))
        return AssetEditorOpenReceipt(
            opened,
            descriptor.editor_id,
            workspace,
            str(path),
            f"Opened {descriptor.display_name} in {workspace}." if opened else f"{workspace} could not open this {descriptor.display_name}.",
        )

    def registered_editor_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._handlers))

