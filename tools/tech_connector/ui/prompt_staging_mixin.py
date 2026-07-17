from __future__ import annotations

"""MainWindow mixin for staging prompt context before Send.

Add this mixin to MainWindow or copy these methods into the existing
MainWindowChatRuntimeMixin/MainWindowUiMixin.
"""


class PromptStagingUiMixin:
    def _current_prompt_text(self) -> str:
        widget = getattr(self, "input", None)
        if widget is None:
            return ""
        return widget.text() if hasattr(widget, "text") else ""

    def _set_prompt_text(self, text: str) -> None:
        widget = getattr(self, "input", None)
        if widget is None:
            return
        if hasattr(widget, "setText"):
            # QLineEdit cannot comfortably show multi-line staged context.
            # Prefer replacing the input with a QTextEdit later. For now,
            # compact to a single line if needed.
            compact = " ".join((text or "").splitlines())
            widget.setText(compact[:32000])
        elif hasattr(widget, "setPlainText"):
            widget.setPlainText(text or "")

    def stage_project_context_to_prompt(self) -> None:
        """Tools menu action: gather context and insert into composer only."""
        text = self._current_prompt_text()
        try:
            from tech_connector.services.prompt_dispatch_service import PromptStagingService
            draft = PromptStagingService().build_draft(
                text,
                project_root=str(getattr(self, "project_root", "") or "") or None,
                include_unreal=True,
                include_code=True,
                include_cpp_wrappers=True,
            )
            self._pending_prompt_draft = draft
            self._set_prompt_text(draft.render_for_composer())
            label = getattr(self, "prompt_context_label", None)
            if label is not None:
                label.setText(draft.context_badge())
            if hasattr(self, "set_live_process"):
                self.set_live_process("Context staged. Review prompt, then press Send.")
        except Exception as exc:
            if hasattr(self, "append"):
                self.append(f"\n[PromptStaging] Failed to stage context: {exc}\n")

    def stage_unreal_context_to_prompt(self) -> None:
        text = self._current_prompt_text()
        try:
            from tech_connector.services.prompt_dispatch_service import PromptStagingService
            draft = PromptStagingService().build_draft(
                text,
                project_root=str(getattr(self, "project_root", "") or "") or None,
                include_unreal=True,
                include_code=False,
                include_cpp_wrappers=False,
            )
            self._pending_prompt_draft = draft
            self._set_prompt_text(draft.render_for_composer())
            label = getattr(self, "prompt_context_label", None)
            if label is not None:
                label.setText(draft.context_badge())
            if hasattr(self, "set_live_process"):
                self.set_live_process("Unreal context staged. Review prompt, then press Send.")
        except Exception as exc:
            if hasattr(self, "append"):
                self.append(f"\n[PromptStaging] Failed to stage Unreal context: {exc}\n")

    def stage_cpp_wrapper_context_to_prompt(self) -> None:
        text = self._current_prompt_text()
        try:
            from tech_connector.services.prompt_dispatch_service import PromptStagingService
            draft = PromptStagingService().build_draft(
                text,
                project_root=str(getattr(self, "project_root", "") or "") or None,
                include_unreal=False,
                include_code=True,
                include_cpp_wrappers=True,
            )
            self._pending_prompt_draft = draft
            self._set_prompt_text(draft.render_for_composer())
            label = getattr(self, "prompt_context_label", None)
            if label is not None:
                label.setText(draft.context_badge())
            if hasattr(self, "set_live_process"):
                self.set_live_process("C++/wrapper context staged. Review prompt, then press Send.")
        except Exception as exc:
            if hasattr(self, "append"):
                self.append(f"\n[PromptStaging] Failed to stage C++ wrapper context: {exc}\n")
