import maya.cmds as cmds

def disable_evaluation():
    """Equivalent to Evaluation > Evaluation Mode > Off"""
    try:
        cmds.evaluationManager(mode="off")
    except Exception:
        pass


def enable_evaluation():
    """Restore normal evaluation (Parallel)."""
    try:
        cmds.evaluationManager(mode="parallel")
    except Exception:
        try:
            cmds.evaluationManager(mode="serial")
        except Exception:
            pass