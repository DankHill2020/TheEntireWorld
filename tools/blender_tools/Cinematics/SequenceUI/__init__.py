"""Blender-native Sequence Workspace with lazy host imports."""


def register():
    from .sequence_ui import register as _register
    return _register()


def unregister():
    from .sequence_ui import unregister as _unregister
    return _unregister()


def show_sequence_manager():
    from .sequence_ui import show_sequence_manager as _show
    return _show()


__all__ = ("register", "show_sequence_manager", "unregister")

