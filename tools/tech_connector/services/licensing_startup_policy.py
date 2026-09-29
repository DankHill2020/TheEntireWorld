"""Small, dependency-free policies used before the desktop UI is unlocked."""

from __future__ import annotations

import os
import sys


def development_entitlement_bypass_allowed() -> bool:
    """Permit explicit source development, never an official frozen build."""
    return (
        not bool(getattr(sys, "frozen", False))
        and os.environ.get("TECH_CONNECTOR_DEV_LICENSE_BYPASS", "").strip() == "1"
    )


def legacy_entitlement_allowed() -> bool:
    """Keep tc1 shared-secret tokens available only to explicit source tests."""
    return (
        not bool(getattr(sys, "frozen", False))
        and os.environ.get("TECH_CONNECTOR_ALLOW_LEGACY_ENTITLEMENT", "").strip() == "1"
    )
