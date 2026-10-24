"""Identify animator-facing rig controls without treating deform nodes as controls."""

from __future__ import annotations

from collections.abc import Iterable


def is_animator_control_identity(node: str, object_sets: Iterable[str] = ()) -> bool:
    """Use a naming contract or an explicit Maya control set membership."""
    name = str(node).split("|")[-1].split(":")[-1].casefold()
    if name.endswith("_switch_ctrl"):
        return False
    if name.endswith("_ctrl"):
        return True
    return any(
        "control" in str(group).split("|")[-1].split(":")[-1].casefold()
        for group in object_sets
    )
