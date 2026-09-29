"""Regression coverage for the one-shot desktop startup prompt sequence."""

from __future__ import annotations

from tech_connector.app.main_window_core import MainWindowCoreMixin


class _PromptHarness:
    def __init__(self) -> None:
        self._startup_prompts_started = False
        self._deferred_terms_prompt = False
        self._deferred_first_run_prompt = False
        self.entitlement_checks = 0

    def show_entitlement_if_needed(self) -> bool:
        self.entitlement_checks += 1
        # Reproduce a second queued callback becoming runnable inside a modal
        # dialog's nested event loop.
        MainWindowCoreMixin.run_deferred_startup_prompts(self)
        return False


def test_startup_prompts_ignore_reentrant_activation_callback() -> None:
    harness = _PromptHarness()

    MainWindowCoreMixin.run_deferred_startup_prompts(harness)

    assert harness.entitlement_checks == 1
    assert harness._startup_prompts_started
