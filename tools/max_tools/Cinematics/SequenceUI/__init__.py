"""3ds Max Sequence Workspace with lazy host/UI imports."""


def show_sequence_manager():
    from .sequence_ui import show_sequence_manager as _show
    return _show()


__all__ = ("show_sequence_manager",)

