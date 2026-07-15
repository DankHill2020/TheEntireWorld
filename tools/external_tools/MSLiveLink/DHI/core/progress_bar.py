import maya.cmds as cmds


class ProgressBar:
    @staticmethod
    def start_progress_bar(status, max_value):
        cmds.progressWindow(
            title="Please wait...",
            status=status,
            maxValue=max_value,
            isInterruptable=False,
        )

    @staticmethod
    def step_progress_bar(status=""):
        cmds.progressWindow(edit=True, step=1, status=status)

    @staticmethod
    def end_progress_bar():
        cmds.progressWindow(endProgress=True)
