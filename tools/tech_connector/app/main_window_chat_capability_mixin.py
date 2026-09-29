"""Capability routing, clarification, and response methods for chat runtime."""

from __future__ import annotations

from __future__ import annotations

from __future__ import annotations

import sys
from pathlib import Path

from tech_connector.path_bootstrap import ensure_tools_root_on_path

ensure_tools_root_on_path(__file__)

import json
import re
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, unquote, urlparse
from PySide6.QtCore import QEvent, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QDesktopServices,
    QFont,
    QGuiApplication,
    QIcon,
    QPixmap,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QProgressDialog,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QToolButton,
    QTreeWidget,
    QVBoxLayout,
    QWidget,
)


def unreal_prompt_requires_project_selection(text: str, detected_host: str = "") -> bool:
    """Return True only for project-backed Unreal work, not general Unreal discussion."""
    value = str(text or "").strip()
    lower = value.lower()
    mentions_unreal = detected_host == "unreal" or bool(
        re.search(r"\b(?:unreal|ue5|ue4|uproject)\b", lower)
    )
    if not mentions_unreal:
        return False
    if re.match(
        r"^(?:what is|what are|why does|how does|can unreal|does unreal|explain|tell me about)\b",
        lower,
    ) and not re.search(
        r"\b(?:in my project|for my project|via my tool|do it|make it|implement it|connect|launch|open)\b",
        lower,
    ):
        return False
    return bool(
        re.search(
            r"\b(?:connect|launch|open|run|execute|import|export|create|build|implement|"
            r"make|add|modify|edit|wire|compile|save|spawn|duplicate|delete|inspect|scan|"
            r"validate|test|blueprint|niagara|anim\s*bp|asset|level|sequencer|control\s*rig|"
            r"metahuman|retarget|material|widget|replicat\w*|pie)\b",
            lower,
        )
    )

from tech_connector.models.constants import (
    ANSI_RE,
    HISTORY_DIR,
)
from tech_connector.models.files import is_supported_code_file

from tech_connector.services.model_provider_service import (
    is_credit_or_quota_failure,
    provider_for_model,
    resolve_model_for_policy,
)
from tech_connector.services.ollama_service import (
    AI_MODELS,
    as_mcphost_model
)

PROMPT_PROGRESS_QUIET_SECONDS = 10
PROMPT_PROGRESS_CHAT_INTERVAL_SECONDS = 15
DEFAULT_CHAT_VISIBLE_MAX_CHARS = 120_000


class MainWindowChatCapabilityMixin:
    def start_intelligence_engine_request(self, text: str, decision=None) -> None:
        """Run understanding, planning, routing, and retrieval in one worker."""
        try:
            from dataclasses import replace
            from tech_connector.engine import snapshot_from_window, RequestPreparationWorker

            prompt_route_decision = decision
            base_context = snapshot_from_window(self, text)
            extras = dict(base_context.extras or {})
            extras.pop("prompt_route_decision", None)
            extras.pop("prompt_execution_context", None)
            if prompt_route_decision is not None:
                extras["prompt_execution_context"] = dict(getattr(self, "_last_prompt_execution_context", {}) or {})
                extras["prompt_route_decision"] = (
                    prompt_route_decision.to_dict()
                    if hasattr(prompt_route_decision, "to_dict")
                    else dict(prompt_route_decision or {})
                )
            if getattr(self, "_active_conversation_workspace", None):
                extras["conversation_workspace"] = self._active_conversation_workspace
            if getattr(self, "_active_operation_memory", None):
                extras["operation_memory"] = self._active_operation_memory
            context = replace(base_context, extras=extras)
            self.set_live_process("Understanding your request...")
            self._log_ui_diagnostic(
                "intelligence_engine_worker_starting",
                prompt_chars=len(text or ""),
                route="",
                provider="",
            )
            self.request_preparation_worker = RequestPreparationWorker(context, self)
            self.request_preparation_worker.progress.connect(self.set_live_process)
            if hasattr(self.request_preparation_worker, "activity"):
                self.request_preparation_worker.activity.connect(self.handle_engine_activity)
            self.request_preparation_worker.finished_result.connect(self.on_intelligence_engine_result)
            self.request_preparation_worker.start()
        except Exception as exc:
            self._append_runtime_error("The intelligence engine failed", exc)
            try:
                self.set_live_process("Intelligence Engine failed to start")
                self._log_ui_diagnostic(
                    "intelligence_engine_worker_start_failed",
                    prompt_chars=len(text or ""),
                    error=str(exc),
                )
            except Exception:
                pass

    def _dispatch_prompt_route_from_chat(self, text: str, decision) -> bool:
        """Dispatch foreground routes without chat owning host-specific execution."""
        if not decision:
            return False
        execution_route = getattr(decision, "execution_route", "") or ""
        if execution_route not in {"dcc.execution_pipeline", "dcc.prototype_pipeline", "unreal.capability_pipeline"}:
            return False

        # Engineering Reasoning Phase
        # For complex engineering prompts, emit a structured reasoning card
        # before dispatching. This runs synchronously (no DCC needed) and
        # gives the user staff-level technical thinking before any code runs.
        try:
            from tech_connector.services.interaction_quality_service import is_senior_engineering_prompt

            if is_senior_engineering_prompt(text):
                self.set_live_process("Queued expert prompt analysis")
                self._log_ui_diagnostic(
                    "senior_reasoning_deferred",
                    route=execution_route,
                    prompt_chars=len(text or ""),
                )
        except Exception:
            pass
        # ------------------------------------------------------------

        try:
            from dataclasses import replace
            from tech_connector.engine import snapshot_from_window, RequestPreparationWorker

            base_context = snapshot_from_window(self, text)
            extras = dict(base_context.extras or {})
            extras["prompt_execution_context"] = dict(getattr(self, "_last_prompt_execution_context", {}) or {})
            extras["prompt_route_decision"] = decision.to_dict()
            extras["window"] = self
            if getattr(self, "_active_conversation_workspace", None):
                extras["conversation_workspace"] = self._active_conversation_workspace
            if getattr(self, "_active_operation_memory", None):
                extras["operation_memory"] = self._active_operation_memory
            context = replace(base_context, extras=extras)
            self.input.clear()
            self.append(f"\nYOU [Dispatch]:\n{self._visible_prompt_text(text)}\n")
            self._append_prompt_understanding(decision)
            self.set_live_process("Preparing dispatch in background")
            self.request_preparation_worker = RequestPreparationWorker(context, self)
            self.request_preparation_worker.progress.connect(self.set_live_process)
            if hasattr(self.request_preparation_worker, "activity"):
                self.request_preparation_worker.activity.connect(self.handle_engine_activity)
            self.request_preparation_worker.finished_result.connect(self.on_intelligence_engine_result)
            self.request_preparation_worker.start()
            return True
        except Exception as exc:
            self.input.clear()
            self._append_runtime_error("Prompt dispatch failed", exc)
            return True

        try:
            from tech_connector.engine import snapshot_from_window, RequestPreparationWorker
            context = snapshot_from_window(self, text)
            self.set_live_process("Understanding request")
            self.append(f"\nYOU [Intelligence Engine]:\n{self._visible_prompt_text(text)}\n")
            try:
                decision = self._last_prompt_route_decision or {}
                self._append_prompt_understanding(decision)
            except Exception:
                pass
            self.request_preparation_worker = RequestPreparationWorker(context, self)
            self.request_preparation_worker.progress.connect(self.set_live_process)
            if hasattr(self.request_preparation_worker, "activity"):
                self.request_preparation_worker.activity.connect(self.handle_engine_activity)
            self.request_preparation_worker.finished_result.connect(self.on_intelligence_engine_result)
            self.request_preparation_worker.start()
        except Exception as exc:
            self._append_runtime_error("The intelligence engine failed", exc)

    def on_intelligence_engine_result(self, result) -> None:
        """Handle RequestPreparationWorker results safely on the UI thread."""
        self._stop_prompt_progress_observer("main")
        action = getattr(result, "action", "error")
        label = getattr(result, "label", "Intelligence Engine")
        text = getattr(result, "text", "") or ""
        prompt = getattr(result, "prompt", "") or ""
        metadata = dict(getattr(result, "metadata", None) or {})
        self._last_engine_result_metadata = metadata
        self._update_active_operation_memory_from_result(result)

        route_decision = dict(metadata.get("route_decision") or {})
        if action != "passthrough" and route_decision:
            self._last_prompt_route_decision = route_decision
            self._last_prompt_execution_context = dict(metadata.get("prompt_execution_context") or {})
            self._append_prompt_understanding(route_decision)

        if (
            str(route_decision.get("operation_mode") or "") == "acquire_then_resume"
            and getattr(self, "_active_capability_coordinator", None) is None
        ):
            original = str(
                (metadata.get("prompt_execution_context") or {}).get("prompt")
                or metadata.get("original_query")
                or route_decision.get("user_text")
                or getattr(self, "last_user_prompt", "")
                or ""
            )
            self._begin_route_capability_acquisition(original, route_decision)
            return

        if action == "answer":
            self.set_live_process(f"{label} ready")
            self.last_assistant_output = text
            self.service.last_assistant_output = text
            self.append(f"\nASSISTANT [{label}]:\n{text}\n")
            self._append_structured_interaction_cards(result)
            self._store_pending_chat_continuation(result, text)
            return

        if action == "clarify":
            self.set_live_process(f"{label} needs input")
            self.last_assistant_output = text
            self.service.last_assistant_output = text
            self.append(f"\nASSISTANT [{label}]:\n{text}\n")
            self._append_structured_interaction_cards(result)
            self._store_pending_chat_continuation(result, text)
            return

        if action == "send_raw" and prompt:
            self.set_live_process("Sending prepared prompt to model")
            if text:
                self.append(f"\n[Intent] {text}\n")
            self.send_raw(prompt, label)
            return

        if action == "action_plan":
            self.set_live_process("Executing action graph")
            metadata = getattr(result, "metadata", None) or {}
            plan = metadata.get("plan") or {}
            try:
                from tech_connector.services.action_execution_engine import (
                    ActionExecutionEngine,
                    ExecutionContext,
                    InMemoryWorkflowRuntime,
                )
                from tech_connector.services.chat_report_service import (
                    format_action_plan_chat_report,
                    simple_chat_enabled,
                )

                roots = self.project_roots() if hasattr(self, "project_roots") else []
                workflow = InMemoryWorkflowRuntime(goal=plan.get("goal") or "")
                report = ActionExecutionEngine().execute_plan(
                    plan,
                    ExecutionContext(
                        project_root=roots[0] if roots else "",
                        project_roots=roots,
                        active_file=str(getattr(self, "current_file_path", "") or ""),
                        app_service=getattr(self, "service", None),
                        window=self,
                        workflow=workflow,
                        approved=False,
                        policy={"goal": plan.get("goal") or ""},
                    ),
                )
                self._last_action_graph = plan
                self._last_action_execution_report = report
                chat_report = format_action_plan_chat_report(
                    plan,
                    report,
                    simple=simple_chat_enabled(getattr(self, "settings", {})),
                )
                self.append(f"\nASSISTANT [Action Graph]:\n{chat_report}\n")
                return
            except Exception as exc:
                self.append(f"\n[Action Graph Error]\n{exc}\n")
                return

        if action == "passthrough":
            self.set_live_process("Understanding complete; continuing with the selected model")
            self._prepared_request_resume = {
                "text": str(
                    (metadata.get("prompt_execution_context") or {}).get("prompt")
                    or metadata.get("original_query")
                    or getattr(self, "last_user_prompt", "")
                    or ""
                ),
                "route_decision": route_decision,
                "prompt_execution_context": dict(metadata.get("prompt_execution_context") or {}),
            }
            if not self._prepared_request_resume["text"]:
                self._prepared_request_resume["text"] = str(
                    route_decision.get("user_text")
                    or route_decision.get("prompt_preview")
                    or ""
                )
            self.send_message()
            return

        self.set_live_process(f"{label} failed")
        self.append(f"\n[{label} Error]\n{text or 'Unknown request preparation error.'}\n")
        self._append_structured_interaction_cards(result)

    def _append_structured_interaction_cards(self, result) -> None:
        metadata = getattr(result, "metadata", None) or {}
        if not isinstance(metadata, dict):
            return
        try:
            from tech_connector.services.interaction_quality_service import render_structured_interaction_summary

            summary = render_structured_interaction_summary(metadata)
            if not summary:
                return
            self._last_execution_plan = metadata.get("execution_plan")
            self._last_result_card = metadata.get("result_card")
            self._last_recovery_options = metadata.get("recovery_options") or []
            self.append(f"\n[Execution Summary]\n{summary}\n")
        except Exception:
            pass

    def _store_pending_chat_continuation(self, result, message: str = "") -> None:
        metadata = getattr(result, "metadata", None) or {}
        if not metadata.get("pending_clarification"):
            return
        try:
            from tech_connector.engine import snapshot_from_window
            from tech_connector.services.chat_continuation_service import (
                continuation_view_model,
                create_pending_continuation,
            )
            from tech_connector.services.interaction_lifecycle_service import InteractionLifecycleManager

            context = snapshot_from_window(self, "")
            try:
                from dataclasses import replace

                context = replace(
                    context,
                    extras={
                        **dict(context.extras or {}),
                        "conversation_workspace": getattr(self, "_active_conversation_workspace", None) or {},
                    },
                )
            except Exception:
                pass
            pending = create_pending_continuation(metadata, context, message=message)
            if pending is None:
                return
            lifecycle = getattr(self, "_interaction_lifecycle", None)
            if lifecycle is None:
                lifecycle = InteractionLifecycleManager()
                self._interaction_lifecycle = lifecycle
            operation = lifecycle.start_operation(continuation_id=pending.continuation_id, origin_message_id=pending.origin_message_id)
            pending_dict = pending.to_dict()
            pending_dict["operation_id"] = operation.operation_id
            pending_dict["operation_revision"] = operation.revision
            self._pending_chat_continuation = pending_dict
            view_model = continuation_view_model(pending, message=message).to_dict()
            if str(view_model.get("clarification_type") or "") == "confirmation":
                self._render_chat_clarification_controls(view_model)
            else:
                self._clear_chat_clarification_controls()
            self.set_live_process("Waiting for clarification")
        except Exception as exc:
            try:
                self.append(f"\n[Clarification UI] Could not render native controls: {exc}\n")
            except Exception:
                pass

    def _clear_pending_chat_continuation(self, reason: str = "") -> None:
        try:
            pending = getattr(self, "_pending_chat_continuation", None) or {}
            operation_id = str(pending.get("operation_id") or "")
            lifecycle = getattr(self, "_interaction_lifecycle", None)
            if operation_id and lifecycle is not None:
                lifecycle.cancel_operation(operation_id, reason=reason or "cleared")
        except Exception:
            pass
        self._pending_chat_continuation = None
        self._clear_chat_clarification_controls()
        if reason and hasattr(self, "set_live_process"):
            self.set_live_process(reason)

    def _update_active_operation_memory_from_result(self, result) -> None:
        """Commit resolved result entities so follow-up references stay scoped."""
        try:
            metadata = dict(getattr(result, "metadata", None) or {})
            knowledge_update = list(metadata.get("contextual_knowledge_update") or [])
            if knowledge_update:
                try:
                    from tech_connector.services.ai_work_memory_service import record_contextual_knowledge

                    record_contextual_knowledge(
                        getattr(self, "settings", {}) or {},
                        knowledge_update,
                        request=str(
                            (metadata.get("prompt_execution_context") or {}).get("normalized_prompt")
                            or metadata.get("deep_search_query")
                            or ""
                        ),
                    )
                except Exception as knowledge_exc:
                    self._log_ui_diagnostic("contextual_knowledge_commit_failed", error=str(knowledge_exc))
            from tech_connector.services.conversation_workspace_service import (
                compatibility_snapshot,
                merge_workspace_update,
                workspace_update_from_legacy_metadata,
            )

            workspace = dict(getattr(self, "_active_conversation_workspace", None) or {})
            workspace_update = metadata.get("workspace_update") or workspace_update_from_legacy_metadata(metadata)
            if workspace_update:
                workspace = merge_workspace_update(
                    workspace,
                    workspace_update,
                    request_id=str(metadata.get("request_id") or ""),
                )
                self._active_conversation_workspace = workspace
            memory = metadata.get("operation_memory")
            if not isinstance(memory, dict):
                memory = dict(getattr(self, "_active_operation_memory", None) or {})
            if workspace:
                memory["conversation_workspace"] = workspace
            from tech_connector.services.operation_memory_service import update_operation_memory
            route_decision = dict(metadata.get("route_decision") or {})
            route_decision.setdefault("original_prompt", metadata.get("deep_search_query") or "")
            memory = update_operation_memory(memory, route_decision=route_decision, result=metadata)
            if memory.get("status") != "cleared":
                self._active_operation_memory = memory
            if memory.get("conversation_workspace"):
                self._active_conversation_workspace = memory.get("conversation_workspace")
            compat = compatibility_snapshot(getattr(self, "_active_conversation_workspace", None) or {})
            selected_file = str(compat.get("selected_file") or metadata.get("selected_file") or metadata.get("resolved_target_file") or "")
            if selected_file:
                momentum = getattr(self, "_context_momentum", None)
                if momentum is None:
                    try:
                        from tech_connector.services.context_momentum_service import ContextMomentum
                        momentum = ContextMomentum()
                        self._context_momentum = momentum
                    except Exception:
                        momentum = None
                if momentum is not None and hasattr(momentum, "remember"):
                    momentum.remember(selected_file, "file", source="project_search_result", confidence=0.98)
        except Exception as exc:
            try:
                self._log_ui_diagnostic("result_context_commit_failed", error=str(exc))
            except Exception:
                pass

    def _clear_chat_clarification_controls(self) -> None:
        widget = getattr(self, "clarification_controls_widget", None)
        layout = getattr(self, "clarification_controls_layout", None)
        self._chat_clarification_widgets = {}
        self._chat_clarification_multi_control = False
        if layout is not None:
            while layout.count():
                item = layout.takeAt(0)
                child = item.widget()
                if child is not None:
                    child.deleteLater()
        if widget is not None:
            widget.setVisible(False)

    def _render_chat_clarification_controls(self, view_model: dict) -> None:
        layout = getattr(self, "clarification_controls_layout", None)
        widget = getattr(self, "clarification_controls_widget", None)
        if layout is None or widget is None:
            return
        self._clear_chat_clarification_controls()
        layout = getattr(self, "clarification_controls_layout", None)
        controls = list((view_model or {}).get("controls") or [])
        if not controls:
            return
        clarification_type = str((view_model or {}).get("clarification_type") or "")
        is_confirmation = clarification_type == "confirmation"
        self._chat_clarification_multi_control = bool(not is_confirmation and len(controls) > 1)
        waiting_for_choices = any(
            control.get("choice_provider_id")
            and not control.get("choices")
            and str(control.get("state") or "") in {"", "idle", "loading", "refreshing"}
            and control.get("inferred_value") in (None, "", [])
            and control.get("default_value") in (None, "", [])
            for control in controls
        )
        title = QLabel("Approval Required" if is_confirmation else "Confirm Context")
        title.setStyleSheet("color:#b9dcff; font-weight:bold; border:0px; background:transparent;")
        layout.addWidget(title)
        for control in controls[:6]:
            self._add_chat_clarification_control(layout, control)
        if not is_confirmation and not waiting_for_choices:
            approve_btn = QPushButton("Approve")
            approve_btn.setToolTip("Use the selected context and continue the pending operation")
            approve_btn.clicked.connect(self._submit_chat_clarification_form)
            layout.addWidget(approve_btn)
        has_cancel_control = any(
            str(control.get("value") or "").strip().lower() in {"cancel", "deny"}
            for control in controls
            if str(control.get("type") or "") == "button"
        )
        if not has_cancel_control:
            cancel_btn = QPushButton("Deny" if not is_confirmation else "Cancel")
            cancel_btn.setToolTip("Cancel this pending operation")
            cancel_btn.clicked.connect(lambda checked=False: self._submit_chat_clarification_value("cancel"))
            layout.addWidget(cancel_btn)
        layout.addStretch(1)
        widget.setVisible(True)
        for control in controls[:6]:
            if control.get("choice_provider_id") and str(control.get("state") or "") in {"", "idle"} and not control.get("choices"):
                QTimer.singleShot(0, lambda c=dict(control): self._refresh_chat_clarification_choices(c))

    def _add_chat_clarification_control(self, layout, control: dict) -> None:
        control_type = str(control.get("type") or "text")
        slot = str(control.get("slot") or "")
        label = str(control.get("label") or slot or "value")
        choices = list(control.get("choices") or [])
        provider_id = str(control.get("choice_provider_id") or "")
        state = str(control.get("state") or "")
        inferred_value = control.get("inferred_value")
        default_value = control.get("default_value")
        multi_control = bool(getattr(self, "_chat_clarification_multi_control", False))
        widgets = getattr(self, "_chat_clarification_widgets", None)
        if not isinstance(widgets, dict):
            widgets = {}
            self._chat_clarification_widgets = widgets
        if control_type == "button":
            value = control.get("value", label)
            btn = QPushButton(label)
            btn.setToolTip(str(control.get("tooltip") or label))
            btn.clicked.connect(lambda checked=False, v=value, lbl=label: self._submit_chat_clarification_value(v, display_value=lbl))
            layout.addWidget(btn)
            return
        if provider_id:
            refresh_btn = QPushButton("Refresh")
            refresh_btn.setToolTip(f"Refresh {label} choices")
            refresh_btn.clicked.connect(lambda checked=False, c=dict(control): self._refresh_chat_clarification_choices(c))
            layout.addWidget(refresh_btn)
        if slot:
            slot_label = QLabel(label)
            slot_label.setStyleSheet("color:#b9dcff; border:0px; background:transparent;")
            layout.addWidget(slot_label)
        if state in {"loading", "refreshing"}:
            loading = QLabel("Loading choices...")
            loading.setStyleSheet("color:#b9dcff; border:0px; background:transparent;")
            layout.addWidget(loading)
            return
        if provider_id and not choices and state in {"", "idle", "manual"}:
            inferred = inferred_value if inferred_value not in (None, "", []) else default_value
            if inferred not in (None, "", []):
                widgets[slot] = ("value", inferred)
                detecting = QLabel(f"Using {self._chat_clarification_choice_label(inferred)}")
                detecting.setToolTip("Inferred from the chat prompt. Use Ask Anything to correct it, or wait for refreshed choices.")
            else:
                detecting = QLabel("Detecting from prompt...")
            detecting.setStyleSheet("color:#b9dcff; border:0px; background:transparent;")
            layout.addWidget(detecting)
            return
        if state in {"failed", "disconnected", "empty", "stale"} and not choices:
            status = QLabel(str(control.get("error") or f"{label} choices are {state}."))
            status.setStyleSheet("color:#f1d38a; border:0px; background:transparent;")
            layout.addWidget(status)
            for option in list(control.get("recovery_options") or [])[:3]:
                recovery_btn = QPushButton(str(option.get("label") or option.get("action_id") or option.get("action") or "Recover"))
                recovery_btn.setToolTip(str(option.get("description") or "Run this recovery action"))
                recovery_btn.clicked.connect(lambda checked=False, opt=dict(option), c=dict(control): self._execute_chat_recovery_option(opt, c))
                layout.addWidget(recovery_btn)
            return
        if control_type in {"choice", "dropdown", "searchable_select"} and choices and len(choices) <= 5 and not multi_control:
            for choice in choices:
                display = self._chat_clarification_choice_label(choice)
                btn = QPushButton(display)
                btn.setToolTip(f"Use {display} for {label}")
                btn.setProperty("clarification_slot", slot)
                btn.setProperty("clarification_value", choice)
                btn.clicked.connect(lambda checked=False, value=choice: self._submit_chat_clarification_value(value))
                layout.addWidget(btn)
            return
        if control_type in {"choice", "dropdown", "searchable_select", "asset_picker", "file_picker"} and choices:
            combo = QComboBox()
            combo.setToolTip(label)
            for choice in choices:
                combo.addItem(self._chat_clarification_choice_label(choice), choice)
            if control_type in {"searchable_select", "asset_picker", "file_picker"} or control.get("editable"):
                combo.setEditable(True)
                combo.setInsertPolicy(QComboBox.NoInsert)
                combo.setMaxVisibleItems(12)
                completer = combo.completer()
                if completer is not None:
                    completer.setCaseSensitivity(Qt.CaseInsensitive)
                    completer.setFilterMode(Qt.MatchContains)
                    completer.setCompletionMode(completer.PopupCompletion)
            recommended = control.get("recommended_choice") or control.get("default_value") or control.get("inferred_value")
            if recommended:
                idx = combo.findData(recommended)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
                else:
                    idx = combo.findText(self._chat_clarification_choice_label(recommended))
                    if idx >= 0:
                        combo.setCurrentIndex(idx)
                    elif combo.isEditable():
                        combo.setEditText(str(recommended))
            evidence = str(control.get("why_default") or "")
            expected_type = str(control.get("expected_type") or "")
            confidence = float(control.get("confidence") or 0.0)
            if evidence or expected_type:
                details = QLabel(
                    " | ".join(
                        part
                        for part in (
                            expected_type,
                            f"{round(confidence * 100)}% confidence" if confidence else "",
                            evidence,
                        )
                        if part
                    )
                )
                details.setStyleSheet("color:#8fa6ba; border:0px; background:transparent;")
                details.setWordWrap(True)
                layout.addWidget(details)
            layout.addWidget(combo, 1)
            if slot:
                widgets[slot] = ("combo", combo)
            if multi_control:
                return
            use_btn = QPushButton("Use")
            use_btn.clicked.connect(
                lambda checked=False, c=combo: self._submit_chat_clarification_value(
                    self._chat_clarification_combo_value(c)
                )
            )
            layout.addWidget(use_btn)
            return
        if control_type == "toggle":
            toggle = QCheckBox(label)
            layout.addWidget(toggle)
            if slot:
                widgets[slot] = ("toggle", toggle)
            if multi_control:
                return
            use_btn = QPushButton("Apply")
            use_btn.clicked.connect(lambda checked=False, t=toggle: self._submit_chat_clarification_value("true" if t.isChecked() else "false"))
            layout.addWidget(use_btn)
            return
        field = QLineEdit()
        field.setPlaceholderText(label)
        val = control.get("inferred_value") or control.get("default_value") or ""
        if val:
            field.setText(str(val))
        if multi_control:
            field.returnPressed.connect(self._submit_chat_clarification_form)
        else:
            field.returnPressed.connect(lambda f=field: self._submit_chat_clarification_value(f.text()))
        layout.addWidget(field, 1)
        if slot:
            widgets[slot] = ("text", field)
        if multi_control:
            return
        apply_btn = QPushButton("Apply")
        apply_btn.clicked.connect(lambda checked=False, f=field: self._submit_chat_clarification_value(f.text()))
        layout.addWidget(apply_btn)

    def _chat_clarification_choice_label(self, value) -> str:
        if isinstance(value, dict) and value.get("label"):
            return str(value.get("label"))
        try:
            from tech_connector.services.reasoning.clarification_service import choice_label

            return choice_label(value)
        except Exception:
            return str(value)

    @staticmethod
    def _chat_clarification_combo_value(combo):
        text = combo.currentText().strip()
        index = combo.currentIndex()
        if index >= 0 and combo.itemText(index) == text:
            value = combo.itemData(index)
            if isinstance(value, dict) and "value" in value:
                return value.get("value")
            if value is not None:
                return value
        return text

    def _submit_chat_clarification_value(self, value, display_value: str = "") -> None:
        self._handle_pending_chat_continuation(
            str(value),
            from_control=True,
            display_value=display_value or self._chat_clarification_choice_label(value),
        )

    def _submit_chat_clarification_form(self) -> None:
        widgets = dict(getattr(self, "_chat_clarification_widgets", {}) or {})
        if not widgets:
            self._handle_pending_chat_continuation("approve", from_control=True, display_value="Approve")
            return
        values: dict[str, object] = {}
        missing: list[str] = []
        for slot, item in widgets.items():
            kind, widget = item
            if kind == "combo":
                value = self._chat_clarification_combo_value(widget)
            elif kind == "toggle":
                value = "true" if widget.isChecked() else "false"
            elif kind == "value":
                value = widget
            else:
                value = widget.text().strip()
            if value in (None, ""):
                missing.append(slot)
            else:
                values[slot] = value
        if missing:
            self.append(f"\nASSISTANT [Clarification]:\nChoose values for: {', '.join(missing)}.\n")
            self.set_live_process("Waiting for clarification values")
            return
        payload = json.dumps({"slots": values}, default=str)
        display = ", ".join(f"{slot}: {self._chat_clarification_choice_label(value)}" for slot, value in values.items())
        self._handle_pending_chat_continuation(payload, from_control=True, display_value=display or "Approve")

    def _execute_chat_recovery_option(self, option: dict, control: dict) -> None:
        try:
            from tech_connector.services.recovery_action_service import execute_recovery_option

            pending = getattr(self, "_pending_chat_continuation", None) or {}
            operation_id = str(control.get("operation_id") or pending.get("operation_id") or "")
            lifecycle = getattr(self, "_interaction_lifecycle", None)
            action_id = str(option.get("action_id") or option.get("action") or "recover")
            if lifecycle is not None and operation_id:
                claimed = lifecycle.claim_action(
                    operation_id=operation_id,
                    action_id=action_id,
                    idempotency_key=f"recovery:{action_id}:{control.get('slot') or ''}",
                )
                if not claimed:
                    self.set_live_process("Recovery action already running")
                    return
            result = execute_recovery_option(option, {"window": self, "control": control, "operation_id": operation_id})
            self.append(f"\n[Recovery]\n{result.message}\n")
            self.set_live_process(result.message)
            if result.refresh_required and control.get("choice_provider_id"):
                self._refresh_chat_clarification_choices(control)
        except Exception as exc:
            self.append(f"\n[Recovery Error] {exc}\n")

    def _refresh_chat_clarification_choices(self, control: dict) -> None:
        pending = getattr(self, "_pending_chat_continuation", None)
        provider_id = str(control.get("choice_provider_id") or "")
        slot = str(control.get("slot") or "")
        if not pending or not provider_id or not slot:
            return
        try:
            from tech_connector.engine import snapshot_from_window
            from tech_connector.services.choice_provider_service import CHOICE_PROVIDER_JOBS, ChoiceProviderRequest
            from tech_connector.services.interaction_lifecycle_service import InteractionLifecycleManager

            base_context = snapshot_from_window(self, "")
            lifecycle = getattr(self, "_interaction_lifecycle", None)
            if lifecycle is None:
                lifecycle = InteractionLifecycleManager()
                self._interaction_lifecycle = lifecycle
            operation_id = str(pending.get("operation_id") or "")
            if not operation_id:
                operation = lifecycle.start_operation(continuation_id=str(pending.get("continuation_id") or ""))
                operation_id = operation.operation_id
                pending["operation_id"] = operation_id
                self._pending_chat_continuation = pending
            provider_generation = lifecycle.start_provider_request(
                operation_id=operation_id,
                continuation_id=str(pending.get("continuation_id") or ""),
                slot_name=slot,
            )
            context_snapshot = {
                "project_roots": list(base_context.project_roots or []),
                "active_file": base_context.current_file_path,
                "index_state": base_context.index_state,
                "operation_memory": getattr(self, "_active_operation_memory", None),
                "window": self,
            }
            request = ChoiceProviderRequest(
                provider_id=provider_id,
                slot_name=slot,
                query=str(control.get("query") or ""),
                filters=dict(control.get("provider_filters") or {}),
                context_snapshot=context_snapshot,
                continuation_id=str(pending.get("continuation_id") or ""),
            )
            updated_control = dict(control)
            updated_control["state"] = "loading"
            updated_control["operation_id"] = operation_id
            updated_control["continuation_id"] = str(pending.get("continuation_id") or "")
            updated_control["provider_request_id"] = provider_generation.request_id
            updated_control["provider_generation"] = provider_generation.generation
            self._replace_pending_chat_clarification_control(slot, updated_control)
            self._render_chat_clarification_controls({"controls": (getattr(self, "_pending_chat_continuation", None) or {}).get("ui_controls") or []})
            job = CHOICE_PROVIDER_JOBS.start(request)
            self._poll_chat_clarification_choice_job(job.job_id, slot, updated_control)
            self.set_live_process(f"Loading {slot} choices")
        except Exception as exc:
            self.append(f"\n[Choice Refresh Error] {exc}\n")

    def _poll_chat_clarification_choice_job(self, job_id: str, slot: str, control: dict) -> None:
        try:
            from tech_connector.services.choice_provider_service import CHOICE_PROVIDER_JOBS

            snapshot = CHOICE_PROVIDER_JOBS.status(job_id)
            if snapshot.status in {"queued", "running"}:
                QTimer.singleShot(120, lambda jid=job_id, s=slot, c=dict(control): self._poll_chat_clarification_choice_job(jid, s, c))
                return
            result = snapshot.result
            updated_control = dict(control)
            pending = getattr(self, "_pending_chat_continuation", None) or {}
            lifecycle = getattr(self, "_interaction_lifecycle", None)
            operation_id = str(control.get("operation_id") or "")
            continuation_id = str(control.get("continuation_id") or "")
            request_id = str(control.get("provider_request_id") or "")
            generation = int(control.get("provider_generation") or 0)
            if lifecycle is not None and not lifecycle.can_apply_provider_result(
                operation_id=operation_id,
                continuation_id=continuation_id,
                request_id=request_id,
                slot_name=slot,
                generation=generation,
            ):
                if request_id:
                    lifecycle.finish_provider_request(request_id, status="stale_ignored")
                self.set_live_process(f"Ignored stale {slot} choices")
                return
            if str(pending.get("continuation_id") or "") != continuation_id:
                self.set_live_process(f"Ignored stale {slot} choices")
                return
            if result is None:
                updated_control.update({"state": snapshot.status, "error": snapshot.error or "Choice lookup did not return a result."})
            else:
                choices = [choice.to_dict() for choice in result.choices]
                updated_control.update(
                    {
                        "choices": choices,
                        "state": result.status,
                        "error": result.error or "",
                        "recovery_options": [option.to_dict() for option in result.recovery_options],
                        "next_page_token": result.next_page_token or "",
                        "is_stale": result.is_stale,
                        "refresh_policy": result.refresh_policy,
                    }
                )
                self._update_pending_chat_clarification_schema(slot, choices, updated_control)
            if lifecycle is not None and request_id:
                lifecycle.finish_provider_request(request_id, status=str(updated_control.get("state") or snapshot.status or "completed"))
            self._replace_pending_chat_clarification_control(slot, updated_control)
            self._render_chat_clarification_controls({"controls": (getattr(self, "_pending_chat_continuation", None) or {}).get("ui_controls") or []})
            self.set_live_process(f"{slot} choices {updated_control.get('state') or snapshot.status}")
        except Exception as exc:
            self.append(f"\n[Choice Refresh Error] {exc}\n")

    def _replace_pending_chat_clarification_control(self, slot: str, updated_control: dict) -> None:
        pending = getattr(self, "_pending_chat_continuation", None)
        if not pending:
            return
        controls = []
        replaced = False
        for item in list(pending.get("ui_controls") or []):
            if item.get("slot") == slot:
                controls.append(updated_control)
                replaced = True
            else:
                controls.append(item)
        if not replaced:
            controls.append(updated_control)
        pending["ui_controls"] = controls
        self._pending_chat_continuation = pending

    def _update_pending_chat_clarification_schema(self, slot: str, choices: list, updated_control: dict) -> None:
        pending = getattr(self, "_pending_chat_continuation", None)
        if not pending:
            return
        pending_state = dict(pending.get("pending_clarification") or {})
        schemas = dict(pending_state.get("accepted_value_schemas") or {})
        schema = dict(schemas.get(slot) or {})
        schema["choices"] = choices
        schema["free_text_allowed"] = bool(updated_control.get("free_text_allowed", True))
        schemas[slot] = schema
        pending_state["accepted_value_schemas"] = schemas
        unresolved = []
        for unresolved_slot in list(pending_state.get("unresolved_slots") or []):
            if unresolved_slot.get("name") == slot:
                item = dict(unresolved_slot)
                item["choices"] = choices
                unresolved.append(item)
            else:
                unresolved.append(unresolved_slot)
        pending_state["unresolved_slots"] = unresolved
        pending["pending_clarification"] = pending_state
        self._pending_chat_continuation = pending

    def _handle_pending_chat_continuation(self, text: str, *, from_control: bool = False, display_value: str = "") -> bool:
        pending = getattr(self, "_pending_chat_continuation", None)
        if not pending:
            return False
        try:
            from dataclasses import replace
            from tech_connector.engine import snapshot_from_window
            from tech_connector.services.chat_continuation_service import (
                apply_continuation_modifier,
                classify_continuation_reply,
                validate_continuation_context,
            )
            from tech_connector.services.reasoning.clarification_service import bind_clarification_response
            from tech_connector.services.prompt.prompt_dispatch_service import PromptDispatchService

            reply = str(display_value or text or "").strip()
            binding_text = str(text or "").strip() if from_control else reply
            pending_state = dict(pending.get("pending_clarification") or {})
            if (
                pending_state.get("kind") == "confirmation"
                and not from_control
                and not bool(pending_state.get("allow_text_approval"))
            ):
                self.append("\nASSISTANT [Approval]:\nUse the Approve or Deny button for this operation. If you want to change the request, cancel it and send a new follow-up.\n")
                self.set_live_process("Waiting for approval button")
                return True
            kind = classify_continuation_reply(reply)
            if (
                pending_state.get("kind") != "confirmation"
                and kind.get("kind") == "replace"
                and pending_state.get("unresolved_slots")
                and not from_control
            ):
                kind = {"kind": "answer"}
            if kind.get("kind") == "replace":
                self._clear_pending_chat_continuation("Clarification replaced")
                return False
            if kind.get("kind") == "modify":
                pending_state = apply_continuation_modifier(dict(pending.get("pending_clarification") or {}), kind)
            else:
                pending_state = dict(pending.get("pending_clarification") or {})

            binding = bind_clarification_response(pending_state, binding_text)
            if not binding.get("accepted"):
                if binding.get("reroute"):
                    self._clear_pending_chat_continuation("Clarification expired")
                    return False
                self.append(f"\nASSISTANT [Clarification]:\n{binding.get('message') or 'That value does not match the pending clarification.'}\n")
                self.set_live_process("Clarification value rejected")
                return True

            operation_id = str(pending.get("operation_id") or "")
            lifecycle = getattr(self, "_interaction_lifecycle", None)
            if lifecycle is not None and operation_id:
                action_id = "cancel" if binding.get("action") == "cancel" else "submit"
                if not lifecycle.claim_action(
                    operation_id=operation_id,
                    action_id=action_id,
                    idempotency_key=f"clarification:{pending.get('continuation_id') or ''}:{action_id}",
                ):
                    self.set_live_process("Clarification action already handled")
                    return True

            self.input.clear()
            if binding.get("action") == "cancel":
                self.append(f"\nYOU [Clarification]:\n{reply or 'Cancel'}\n")
                self.append("\nASSISTANT [Clarification]:\nCancelled the pending operation.\n")
                self._clear_pending_chat_continuation("Clarification cancelled")
                try:
                    from tech_connector.services.operation_memory_service import clear_operation_memory

                    self._active_operation_memory = clear_operation_memory(getattr(self, "_active_operation_memory", None), reason="user_cancelled")
                except Exception:
                    pass
                return True

            route_decision = dict(binding.get("route_decision") or pending_state.get("route_decision") or pending.get("route_decision") or {})
            if binding.get("action") == "confirm":
                route_decision["approved"] = True
                route_decision["requires_confirmation"] = False

            pending_execution = dict(pending_state.get("execution_request") or {})
            resolved_target = str(
                pending_execution.get("resolved_target_file")
                or pending_execution.get("target_file")
                or pending_execution.get("target_path")
                or pending_execution.get("file")
                or route_decision.get("resolved_target_file")
                or route_decision.get("target_file")
                or ""
            ).strip()

            original_prompt = str((pending_state.get("execution_request") or {}).get("original_prompt") or "")
            clarified_prompt = original_prompt
            if reply:
                clarified_prompt = f"{original_prompt}\n\nClarification answer: {reply}".strip()
            base_context = snapshot_from_window(self, clarified_prompt)
            if resolved_target and str(pending_execution.get("operation_mode") or "").strip().lower() == "plan":
                if not str(base_context.current_file_path or "").strip() or (
                    str(base_context.current_file_path).strip() != resolved_target
                ):
                    base_context = replace(base_context, current_file_path=resolved_target)
                open_files = list(base_context.open_file_paths or [])
                norm_open = [str(path).replace("\\", "/").lower() for path in open_files if path]
                normalized_target = resolved_target.replace("\\", "/").lower()
                if normalized_target and normalized_target not in norm_open:
                    open_files = [resolved_target] + open_files
                    base_context = replace(base_context, open_file_paths=tuple(open_files[:12]))
            if resolved_target:
                route_decision.setdefault("resolved_target_file", resolved_target)
                route_decision.setdefault("target_file", resolved_target)
                index_filters = dict(route_decision.get("index_filters") or {})
                index_filters["target_file"] = resolved_target
                if str(route_decision.get("operation_mode") or "").strip().lower() == "plan":
                    index_filters["scope"] = "active"
                route_decision["index_filters"] = index_filters
            stale = validate_continuation_context(
                SimpleNamespace(**pending),
                base_context,
            )
            if stale.get("status") not in {"safe_to_continue", ""}:
                self.append(f"\nASSISTANT [Clarification]:\n{stale.get('reason') or 'The pending clarification is stale.'}\n")
                if stale.get("status") == "must_cancel_and_reroute":
                    self._clear_pending_chat_continuation("Clarification stale")
                return True

            self.append(f"\nYOU [Clarification]:\n{reply}\n")
            self._clear_pending_chat_continuation("Resuming clarified request")
            extras = dict(base_context.extras or {})
            extras["prompt_route_decision"] = route_decision
            extras["clarification_binding"] = binding
            if getattr(self, "_active_operation_memory", None):
                extras["operation_memory"] = self._active_operation_memory
            context = replace(base_context, extras=extras)
            self.set_live_process("Resuming clarified request in background")
            from tech_connector.engine import RequestPreparationWorker

            self.request_preparation_worker = RequestPreparationWorker(context, self)
            self.request_preparation_worker.progress.connect(self.set_live_process)
            if hasattr(self.request_preparation_worker, "activity"):
                self.request_preparation_worker.activity.connect(self.handle_engine_activity)
            self.request_preparation_worker.finished_result.connect(self.on_intelligence_engine_result)
            self.request_preparation_worker.start()
            return True
        except Exception as exc:
            self.append(f"\n[Clarification Resume Error] {exc}\n")
            return True


    def _attachment_context_for_prompt(self) -> str:
        """Return compact text context for attached files.

        This lets the user attach files to a chat request and ask for issue
        scanning/review without forcing the UI to display raw attachment paths.
        """
        paths = list(getattr(self, "attached_files", []) or [])
        if not paths:
            return ""
        parts = ["Attached files:"]
        for raw in paths[:8]:
            try:
                p = Path(raw)
                parts.append(f"\n---\nFile: {p}")
                if p.exists() and p.is_file() and p.suffix.lower() in {
                    ".py", ".txt", ".md", ".json", ".yaml", ".yml", ".ini", ".cfg", ".bat", ".ps1", ".mel", ".cpp", ".h", ".hpp", ".cs"
                }:
                    content = p.read_text(encoding="utf-8", errors="replace")
                    if len(content) > 12000:
                        content = content[:12000] + "\n... [truncated attachment] ..."
                    parts.append("```text\n" + content + "\n```")
                else:
                    parts.append("(binary or unsupported text preview)")
            except Exception as exc:
                parts.append(f"\n---\nFile: {raw}\nCould not read: {exc}")
        return "\n".join(parts).strip()

    def update_attachment_strip(self):
        """Refresh the compact image/file attachment strip under the chat view."""
        strip = getattr(self, "attachment_strip", None)
        layout = getattr(self, "attachment_strip_layout", None)
        if not strip or not layout:
            if hasattr(self, "image_label"):
                count = len(getattr(self, "attached_images", []) or [])
                self.image_label.setText(f"Images: {count}" if count else "")
                self.image_label.setVisible(bool(count))
            return

        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        has_any = False

        for img_path in list(getattr(self, "attached_images", []) or [])[:12]:
            try:
                label = QLabel()
                pix = QPixmap(str(img_path))
                if not pix.isNull():
                    label.setPixmap(pix.scaled(74, 54, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                else:
                    label.setText(Path(img_path).name)
                label.setToolTip(str(img_path))
                label.setStyleSheet("border:1px solid #1e9bff; border-radius:6px; padding:3px; background:#000711;")
                layout.addWidget(label)
                has_any = True
            except Exception:
                pass

        for file_path in list(getattr(self, "attached_files", []) or [])[:12]:
            try:
                chip = QLabel("File: " + Path(file_path).name)
                chip.setToolTip(str(file_path))
                chip.setStyleSheet("border:1px solid #12324a; border-radius:8px; padding:5px 8px; color:#b9dcff; background:#000711;")
                layout.addWidget(chip)
                has_any = True
            except Exception:
                pass

        layout.addStretch(1)
        strip.setVisible(has_any)

    def attach_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Attach files to chat",
            "",
            "Code/Text Files (*.py *.txt *.md *.json *.yaml *.yml *.ini *.cfg *.bat *.ps1 *.mel *.cpp *.h *.hpp *.cs);;All Files (*.*)",
        )
        if not paths:
            return
        if not hasattr(self, "attached_files"):
            self.attached_files = []
        for path in paths:
            if path not in self.attached_files:
                self.attached_files.append(path)
        self.update_attachment_strip()
        if hasattr(self, "set_live_process"):
            self.set_live_process(f"Attached {len(paths)} file(s)")

    def attach_images(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Attach images to chat",
            "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp *.gif);;All Files (*.*)",
        )
        if not paths:
            return
        if not hasattr(self, "attached_images"):
            self.attached_images = []
        for path in paths:
            if path not in self.attached_images:
                self.attached_images.append(path)
        self.update_attachment_strip()
        if hasattr(self, "set_live_process"):
            self.set_live_process(f"Attached {len(paths)} image(s)")

    def paste_image_from_clipboard(self):
        clipboard = QGuiApplication.clipboard()
        pix = clipboard.pixmap()
        if pix.isNull():
            QMessageBox.information(self, "No image", "The clipboard does not contain an image.")
            return
        try:
            from tech_connector.models.constants import IMAGE_DIR
            IMAGE_DIR.mkdir(parents=True, exist_ok=True)
            path = IMAGE_DIR / f"clipboard_{int(time.time())}.png"
        except Exception:
            path = Path.cwd() / f"clipboard_{int(time.time())}.png"
        pix.save(str(path), "PNG")
        if not hasattr(self, "attached_images"):
            self.attached_images = []
        self.attached_images.append(str(path))
        self.update_attachment_strip()
        if hasattr(self, "set_live_process"):
            self.set_live_process("Pasted clipboard image")

    # ------------------------------------------------------------------
    # Capability Acquisition & Gap Analysis
    # ------------------------------------------------------------------

    @property
    def _capability_registry(self):
        """Lazy-loaded per-project capability registry."""
        if not hasattr(self, "_capability_registry_cache"):
            try:
                from tech_connector.services.capability_registry import CapabilityRegistry
                from tech_connector.models.constants import TOOLS_ROOT, capability_registry_path
                registry_path = capability_registry_path(
                    str(getattr(self, "active_project_root_path", lambda: str(TOOLS_ROOT))())
                )
                self._capability_registry_cache = CapabilityRegistry(registry_path)
            except Exception:
                self._capability_registry_cache = None
        return self._capability_registry_cache

    def _check_capability_gaps(self, text: str) -> bool:
        """Run the capability gap analysis pre-dispatch gate.

        Returns True if the prompt should be held (gaps detected, waiting for approval).
        Returns False if the prompt can proceed normally.
        This method must stay non-blocking. The full capability planner can scan
        project internals or call a local model, so synchronous use is opt-in.
        """
        prompt_chars = len(text or "")
        if not bool(getattr(self, "settings", {}).get("capability_gate_sync_enabled", False)):
            self._log_ui_diagnostic(
                "capability_gate_skipped_disabled",
                prompt_chars=prompt_chars,
                reason="sync_capability_gate_disabled_to_protect_ui_thread",
            )
            return False
        if prompt_chars > int(getattr(self, "settings", {}).get("capability_gate_max_sync_chars", 240) or 240):
            self._log_ui_diagnostic(
                "capability_gate_skipped_long_prompt",
                prompt_chars=prompt_chars,
                reason="avoid_ui_thread_ollama_or_embedding_lookup",
            )
            return False
        try:
            gate_started = time.perf_counter()
            self._log_ui_diagnostic(
                "capability_gate_started",
                prompt_chars=prompt_chars,
            )
            registry = self._capability_registry
            if registry is None:
                self._log_ui_diagnostic(
                    "capability_gate_finished",
                    prompt_chars=prompt_chars,
                    duration_ms=int((time.perf_counter() - gate_started) * 1000),
                    result="no_registry",
                )
                return False

            from tech_connector.services.capability_planner_service import analyze_prompt

            project_roots = []
            try:
                root = str(getattr(self, "active_project_root_path", lambda: "")())
                if root:
                    project_roots = [root]
            except Exception:
                pass

            plan = analyze_prompt(text, registry, project_roots)
            self._log_ui_diagnostic(
                "capability_gate_finished",
                prompt_chars=prompt_chars,
                duration_ms=int((time.perf_counter() - gate_started) * 1000),
                result="gaps" if plan.has_gaps else "no_gaps",
                task_steps=len(plan.task_steps or []),
                missing=len(plan.missing or []),
            )

            # No gaps - proceed normally
            if not plan.has_gaps:
                return False

            # Gaps found - show inline acquisition card in chat
            chat_msg = plan.format_for_chat()
            if chat_msg:
                self.append(f"\nYOU:\n{self._visible_prompt_text(text)}\n")
                self.append(f"\n[Capability Planner]\n{chat_msg}\n")
                self.input.clear()
                # Store plan so we can re-dispatch after approval
                self._pending_capability_plan = plan
                self._pending_capability_text = text
                self._render_capability_acquisition_controls()
                return True

        except Exception:
            import traceback
            traceback.print_exc()

        return False

    def _render_capability_acquisition_controls(self) -> None:
        layout = getattr(self, "clarification_controls_layout", None)
        widget = getattr(self, "clarification_controls_widget", None)
        if layout is None or widget is None:
            return
        self._clear_chat_clarification_controls()
        layout = getattr(self, "clarification_controls_layout", None)
        title = QLabel("Approval Required")
        title.setStyleSheet("color:#b9dcff; font-weight:bold; border:0px; background:transparent;")
        layout.addWidget(title)
        approve_btn = QPushButton("Approve")
        approve_btn.setToolTip("Approve the capability acquisition plan")
        approve_btn.clicked.connect(lambda checked=False: self._approve_capability_acquisition())
        layout.addWidget(approve_btn)
        deny_btn = QPushButton("Deny")
        deny_btn.setToolTip("Skip capability acquisition and continue without it")
        deny_btn.clicked.connect(lambda checked=False: self._deny_capability_acquisition())
        layout.addWidget(deny_btn)
        layout.addStretch(1)
        widget.setVisible(True)

    def _deny_capability_acquisition(self) -> None:
        original = getattr(self, "_pending_capability_text", "")
        self._pending_capability_plan = None
        self._pending_capability_text = ""
        self._clear_chat_clarification_controls()
        self.append("\n[Capability Planner] Acquisition skipped. Proceeding without missing capabilities.\n")
        if original:
            self._capability_skip_once_text = original
            self.input.setText(original)
            self.send_message()

    def _begin_route_capability_acquisition(self, text: str, decision: dict) -> None:
        """Create a resumable acquisition job from the canonical route decision."""
        from tech_connector.services.capability_acquisition_coordinator import (
            CapabilityAcquisitionCoordinator,
        )
        from tech_connector.services.capability_implementation_provider import (
            ModelBackedCapabilityImplementationProvider,
        )
        from tech_connector.models.constants import TOOLS_ROOT

        plan = dict(decision.get("capability_gap_plan") or {})
        if not plan:
            self.append("\n[Capability Acquisition] The route did not include an executable gap plan.\n")
            return

        self._capability_job_events = []

        def event_callback(event: str, payload: dict) -> None:
            self._capability_job_events.append((event, payload))

        root = Path(str(getattr(self, "active_project_root_path", lambda: str(TOOLS_ROOT))()))
        if root.name.lower() == "tech_connector" and (root.parent / "unreal_tools").exists():
            root = root.parent
        if not (root / "tech_connector").exists():
            root = Path(TOOLS_ROOT)
        provider = ModelBackedCapabilityImplementationProvider(
            root,
            active_path=str(getattr(self, "current_file_path", "") or ""),
            settings=dict(getattr(self, "settings", {}) or {}),
            progress_callback=lambda phase, detail: event_callback(
                "substep_progress",
                {
                    "job": (
                        self._active_capability_coordinator.snapshot()
                        if getattr(self, "_active_capability_coordinator", None) is not None
                        else {}
                    ),
                    "substep": {"phase": phase, **dict(detail or {})},
                },
            ),
        )
        self._active_capability_implementation_provider = provider
        self._active_capability_coordinator = CapabilityAcquisitionCoordinator(
            plan,
            original_request=text,
            stage_runner=provider.run_stage,
            event_callback=event_callback,
        )
        self._active_capability_route_decision = dict(decision)
        timer = getattr(self, "_capability_job_event_timer", None)
        if timer is None:
            timer = QTimer(self)
            timer.setInterval(75)
            timer.timeout.connect(self._drain_capability_job_events)
            self._capability_job_event_timer = timer
        timer.start()
        missing = list(plan.get("all_missing_operations") or [plan.get("requested_operation")])
        missing = [str(item) for item in missing if item]
        self.append(
            "\nASSISTANT [Capability Acquisition]:\n"
            f"I found {len(missing)} missing callable(s): {', '.join(missing)}\n"
            "Research and design can proceed in the background. File or plugin changes must return concrete implementation and validation evidence.\n"
        )
        self._render_active_capability_job_controls()
        self.set_live_process("Capability acquisition ready")

    def _drain_capability_job_events(self) -> None:
        events = list(getattr(self, "_capability_job_events", []) or [])
        if not events:
            return
        del self._capability_job_events[: len(events)]
        for event, payload in events:
            self._handle_capability_job_event(event, payload)
        if events[-1][0] in {"completed", "cancelled", "failed"}:
            timer = getattr(self, "_capability_job_event_timer", None)
            if timer is not None:
                timer.stop()

    def _render_active_capability_job_controls(self) -> None:
        coordinator = getattr(self, "_active_capability_coordinator", None)
        layout = getattr(self, "clarification_controls_layout", None)
        widget = getattr(self, "clarification_controls_widget", None)
        if coordinator is None or layout is None or widget is None:
            return
        self._clear_chat_clarification_controls()
        layout = getattr(self, "clarification_controls_layout", None)
        snapshot = coordinator.snapshot()
        status = str(snapshot.get("status") or "queued")
        title = QLabel(str(snapshot.get("current_step_label") or "Capability acquisition"))
        title.setStyleSheet("color:#b9dcff; font-weight:bold; border:0px; background:transparent;")
        layout.addWidget(title)

        if status == "queued":
            start_btn = QPushButton("Approve & Start")
            start_btn.setToolTip("Approve grounded code changes after disposable validation and start acquisition")
            start_btn.clicked.connect(lambda checked=False: coordinator.start())
            layout.addWidget(start_btn)
        elif status == "paused":
            resume_btn = QPushButton("Resume")
            resume_btn.setToolTip("Continue from the last completed checkpoint")
            resume_btn.clicked.connect(lambda checked=False: coordinator.resume())
            layout.addWidget(resume_btn)
        elif status not in {"completed", "cancelled", "failed"}:
            pause_btn = QPushButton("Pause")
            pause_btn.setToolTip("Pause after the current safe step")
            pause_btn.setEnabled(status != "pausing")
            pause_btn.clicked.connect(lambda checked=False: coordinator.request_pause())
            layout.addWidget(pause_btn)

        if status not in {"completed", "cancelled", "failed"}:
            context_btn = QPushButton("Add Context")
            context_btn.setToolTip("Add guidance and pause at the next safe checkpoint")
            context_btn.clicked.connect(lambda checked=False: self._add_context_to_capability_job())
            layout.addWidget(context_btn)
            cancel_btn = QPushButton("Cancel")
            cancel_btn.setToolTip("Cancel at the next safe checkpoint")
            cancel_btn.clicked.connect(lambda checked=False: coordinator.cancel())
            layout.addWidget(cancel_btn)
        layout.addStretch(1)
        widget.setVisible(status not in {"completed", "cancelled", "failed"})

    def _add_context_to_capability_job(self) -> None:
        coordinator = getattr(self, "_active_capability_coordinator", None)
        if coordinator is None:
            return
        text, accepted = QInputDialog.getMultiLineText(
            self,
            "Add Context",
            "Additional context for the remaining work:",
        )
        if accepted and str(text or "").strip():
            coordinator.add_context(text)

    def _handle_capability_job_event(self, event: str, payload: dict) -> None:
        job = dict(payload.get("job") or {})
        label = str(job.get("current_step_label") or event.replace("_", " ").title())
        progress = int(job.get("progress") or 0)
        self.set_live_process(label)
        if hasattr(self, "download_status") and hasattr(self, "download_progress"):
            self.download_status.setText(label)
            self.download_status.setVisible(event not in {"completed", "cancelled", "failed"})
            self.download_progress.setRange(0, 100)
            self.download_progress.setValue(progress)
            self.download_progress.setVisible(event not in {"completed", "cancelled", "failed"})

        if event == "step_started":
            step = dict(payload.get("step") or {})
            self.append(f"[Capability] {step.get('objective') or label}\n")
        elif event == "step_completed":
            step = dict(payload.get("step") or {})
            self.append(f"[Checkpoint] {step.get('step_id') or 'step'} completed ({progress}%).\n")
        elif event == "substep_progress":
            substep = dict(payload.get("substep") or {})
            detail_label = str(substep.get("label") or label)
            self.set_live_process(detail_label)
            if hasattr(self, "download_status"):
                self.download_status.setText(detail_label)
            self.append(f"[Capability] {detail_label}\n")
        elif event == "pause_requested":
            self.append("[Capability] Pause requested; finishing the current safe step.\n")
        elif event == "paused":
            self.append("[Capability] Paused. Completed checkpoints and evidence were preserved.\n")
        elif event == "input_required":
            self.append(f"[Capability] {label}\n")
        elif event == "context_added":
            self.append("[Capability] Added context will be applied to unfinished work on resume.\n")
        elif event == "resumed":
            self.append("[Capability] Resuming from the last completed checkpoint.\n")
        elif event == "failed":
            self.append(f"[Capability Failed] {label}\n")
            self._last_capability_acquisition_job = job
            self._active_capability_coordinator = None
            self._active_capability_route_decision = None
            self._active_capability_implementation_provider = None
            self._clear_chat_clarification_controls()
            return
        elif event == "cancelled":
            self.append("[Capability] Cancelled at a safe checkpoint.\n")
            self._last_capability_acquisition_job = job
            self._active_capability_coordinator = None
            self._active_capability_route_decision = None
            self._active_capability_implementation_provider = None
            self._clear_chat_clarification_controls()
            return
        elif event == "completed":
            self.append("[Capability] Acquisition validated. Resuming the original request.\n")
            original = str(job.get("original_request") or "")
            addenda = list(job.get("context_addenda") or [])
            self._active_capability_coordinator = None
            self._active_capability_route_decision = None
            self._active_capability_implementation_provider = None
            self._clear_chat_clarification_controls()
            if original:
                if addenda:
                    original += "\n\nAdditional context supplied during execution:\n- " + "\n- ".join(addenda)
                self.input.setText(original)
                QTimer.singleShot(0, self.send_message)
            return
        self._render_active_capability_job_controls()

    def _approve_capability_acquisition_legacy_unused(self) -> None:
        """Legacy blocking capability acquisition path retained for reference."""
        plan = getattr(self, "_pending_capability_plan", None)
        if not plan:
            return

        registry = self._capability_registry
        original_text = getattr(self, "_pending_capability_text", "")
        self._pending_capability_plan = None
        self._pending_capability_text = ""
        self._clear_chat_clarification_controls()

        if not plan.acquisition_strategies:
            self.append("\n[Capability Planner] No automated strategies available. Please acquire manually.\n")
            return

        from tech_connector.services.capability_acquisition_service import AcquisitionEngine

        # Expand system status panel if collapsed to ensure user sees the progress bar
        if hasattr(self, "system_status_body") and not self.system_status_body.isVisible():
            if hasattr(self, "toggle_system_status_panel"):
                self.toggle_system_status_panel()

        # Initialize progress bar visibility on the main window UI
        if hasattr(self, "download_status") and hasattr(self, "download_progress"):
            self.download_status.setText("Acquisition starting...")
            self.download_status.setVisible(True)
            self.download_progress.setRange(0, 100)
            self.download_progress.setValue(0)
            self.download_progress.setVisible(True)

        def _progress(msg: str, current: int = 0, total: int = 0) -> None:
            self.append(f"[Acquiring] {msg}\n")
            if hasattr(self, "download_status") and hasattr(self, "download_progress"):
                self.download_status.setText(msg)
                if total > 0:
                    self.download_progress.setRange(0, total)
                    self.download_progress.setValue(max(0, min(current, total)))
                else:
                    self.download_progress.setRange(0, 0)

        try:
            from tech_connector.models.constants import TOOLS_ROOT
            root_path = Path(str(getattr(self, "active_project_root_path", lambda: str(TOOLS_ROOT))()))
            engine = AcquisitionEngine(registry, root_path.parent)

            phase1_strategies = [s for s in plan.acquisition_strategies if s.phase == 1]
            for strategy in phase1_strategies[:3]:
                self.append(f"\n[Acquiring] Executing: {strategy.name}...\n")
                result = engine.execute_strategy(strategy, progress_cb=_progress)
                if result.success:
                    self.append(f"[Acquired] OK: {result.message}\n")
                else:
                    self.append(f"[Acquisition Failed] ERROR: {result.message}\n")

            # Re-dispatch the original prompt now that capabilities are registered
            if original_text:
                self.append(f"\n[Capability Planner] Retrying original prompt with acquired capabilities...\n")
                self.input.setText(original_text)
                self.send_message()
        except Exception:
            import traceback
            traceback.print_exc()
            self.append("\n[Capability Planner] Acquisition error - see console for details.\n")
        finally:
            # Hide the progress bar elements when finished
            if hasattr(self, "download_status") and hasattr(self, "download_progress"):
                self.download_status.setVisible(False)
                self.download_progress.setVisible(False)

    def _approve_capability_acquisition(self) -> None:
        """Approve and run the pending capability acquisition plan without blocking Qt."""
        plan = getattr(self, "_pending_capability_plan", None)
        if not plan:
            return

        registry = self._capability_registry
        original_text = getattr(self, "_pending_capability_text", "")
        self._pending_capability_plan = None
        self._pending_capability_text = ""
        self._clear_chat_clarification_controls()

        if not plan.acquisition_strategies:
            self.append("\n[Capability Planner] No automated strategies available. Please acquire manually.\n")
            return

        if hasattr(self, "system_status_body") and not self.system_status_body.isVisible():
            if hasattr(self, "toggle_system_status_panel"):
                self.toggle_system_status_panel()

        if hasattr(self, "download_status") and hasattr(self, "download_progress"):
            self.download_status.setText("Acquisition starting in background...")
            self.download_status.setVisible(True)
            self.download_progress.setRange(0, 0)
            self.download_progress.setVisible(True)

        def on_ui(callback):
            QTimer.singleShot(0, callback)

        def progress(msg: str, current: int = 0, total: int = 0) -> None:
            def update():
                self.append(f"[Acquiring] {msg}\n")
                if hasattr(self, "download_status") and hasattr(self, "download_progress"):
                    self.download_status.setText(msg)
                    if total > 0:
                        self.download_progress.setRange(0, total)
                        self.download_progress.setValue(max(0, min(current, total)))
                    else:
                        self.download_progress.setRange(0, 0)

            on_ui(update)

        def finish(lines: list[str], retry: bool) -> None:
            for line in lines:
                self.append(line)
            if hasattr(self, "download_status") and hasattr(self, "download_progress"):
                self.download_status.setVisible(False)
                self.download_progress.setVisible(False)
            if retry and original_text:
                self.append("\n[Capability Planner] Retrying original prompt with acquired capabilities...\n")
                self.input.setText(original_text)
                self.send_message()

        def run_worker() -> None:
            lines: list[str] = []
            retry = False
            try:
                from tech_connector.models.constants import TOOLS_ROOT
                from tech_connector.services.capability_acquisition_service import AcquisitionEngine

                root_path = Path(str(getattr(self, "active_project_root_path", lambda: str(TOOLS_ROOT))()))
                engine = AcquisitionEngine(registry, root_path.parent)
                phase1_strategies = [s for s in plan.acquisition_strategies if s.phase == 1]
                for strategy in phase1_strategies[:3]:
                    progress(f"Executing: {strategy.name}")
                    result = engine.execute_strategy(strategy, progress_cb=progress)
                    if result.success:
                        self.append(f"[Acquired] OK: {result.message}\n")
                    else:
                        self.append(f"[Acquisition Failed] ERROR: {result.message}\n")
                retry = bool(original_text)
            except Exception as exc:
                self.append("\n[Capability Planner] Acquisition error - see console for details.\n")
            finally:
                on_ui(lambda lines=lines, retry=retry: finish(lines, retry))

        import threading

        threading.Thread(target=run_worker, daemon=True).start()

    def send_message(self):
        self.last_chat_activity_time = time.time()
        self.ollama_is_idle = False
        send_started = time.perf_counter()
        self._live_work_started_at = time.time()
        self._last_live_process = ""
        self._last_live_process_at = 0
        self._seen_log_status_msgs = set()
        prepared_resume = getattr(self, "_prepared_request_resume", None)
        if prepared_resume:
            self._prepared_request_resume = None
            text = str(prepared_resume.get("text") or "").strip()
        else:
            text = self.input.text().strip()
        self._log_ui_diagnostic(
            "send_message_started",
            prompt_chars=len(text or ""),
            active_response_roles=self._active_response_roles(),
        )
        if not hasattr(self, "attached_files"):
            self.attached_files = []
        if not text and not self.attached_images and not self.attached_files:
            return
        active_acquisition = getattr(self, "_active_capability_coordinator", None)
        if active_acquisition is not None:
            acquisition_status = str(active_acquisition.snapshot().get("status") or "")
            if acquisition_status not in {"completed", "cancelled", "failed"}:
                if text:
                    self.input.clear()
                    active_acquisition.add_context(text)
                return
        # --- Capability plan approval interceptor ---
        if getattr(self, "_pending_capability_plan", None):
            self.input.clear()
            self.append("\nASSISTANT [Approval]:\nUse the Approve or Deny button for the capability plan. If you want different context, deny it and send a follow-up.\n")
            self.set_live_process("Waiting for approval button")
            return

        if not prepared_resume and text and getattr(self, "_pending_chat_continuation", None):
            if self._handle_pending_chat_continuation(text):
                return

        attachment_context = "" if prepared_resume else self._attachment_context_for_prompt()
        if attachment_context:
            text = (text + "\n\n" if text else "") + attachment_context

        from tech_connector.services.source_policy import check_moderation

        flagged, reason = check_moderation(text)
        if flagged:
            self.append(
                f"\n[Moderation Warning] Request Blocked: The input {reason}. Generating malware or exploit code is restricted for safety.\n"
            )
            self.input.clear()
            return

        from tech_connector.services.code_prompt_profile_service import (
            normalize_code_prompt_profile,
        )

        code_prompt_profile = (
            self.code_prompt_profile()
            if hasattr(self, "code_prompt_profile")
            else normalize_code_prompt_profile(settings=getattr(self, "settings", {}))
        )
        read_only_code_mode = code_prompt_profile.mode in {"ask", "plan", "review"}

        if not prepared_resume and text:
            try:
                prompt_host = str(self.command_router.detect_prompt_host(text) or "")
            except Exception:
                prompt_host = ""
            needs_unreal_project = unreal_prompt_requires_project_selection(
                text,
                prompt_host,
            )
            if needs_unreal_project and hasattr(self, "_ensure_unreal_project_ready"):
                saved_uproject = str(
                    getattr(self, "settings", {}).get("unreal_uproject_path", "") or ""
                )
                if not saved_uproject or not Path(saved_uproject).is_file():
                    selected_uproject = self._ensure_unreal_project_ready()
                    if not selected_uproject:
                        self.set_live_process("Waiting for Unreal project selection")
                        return

        if self._active_response_roles():
            if self.attached_images:
                text += "\n\nAttached image paths:\n" + "\n".join(self.attached_images)
            self.input.clear()
            self._send_active_response_addendum(text)
            self.attached_images = []
            self.attached_files = []
            self.update_attachment_strip()
            self._log_ui_diagnostic(
                "send_message_completed",
                path="active_response_addendum",
                duration_ms=int((time.perf_counter() - send_started) * 1000),
            )
            return

        try:
            from tech_connector.services.docstring_service import looks_like_docstring_request

            if (
                not read_only_code_mode
                and looks_like_docstring_request(text)
                and hasattr(self, "add_docstrings_to_current_file")
            ):
                self.input.clear()
                self.append(f"\nYOU [Docstrings]:\n{self._visible_prompt_text(text)}\n")
                self._append_visible_prompt_progress(text=text)
                self.add_docstrings_to_current_file(text)
                return
        except Exception as exc:
            self.input.clear()
            self.append(f"\n[Docstrings Error] {exc}\n")
            return

        # --- Capability Gap Analysis (pre-dispatch) ---
        # Runs only when gaps are detected; zero overhead when all capabilities are satisfied.
        skip_capability_gate = bool(text and text == getattr(self, "_capability_skip_once_text", ""))
        if skip_capability_gate:
            self._capability_skip_once_text = ""
        if (
            not prepared_resume
            and not skip_capability_gate
            and not read_only_code_mode
            and self._check_capability_gaps(text)
        ):
            return

        if not prepared_resume:
            try:
                preview = self._visible_prompt_text(text)
                if len(preview) > 900:
                    preview = preview[:900].rstrip() + "\n..."
                self.input.clear()
                self.append(f"\nYOU [Queued]:\n{preview}\n")
                self.append("[Request] Accepted. Routing and preparing context...\n")
                self._start_prompt_progress_observer("main", label="prompt request")
                self._note_prompt_progress_event("Accepted request - routing", "main")
                self.set_live_process("Accepted request - routing")
                self._log_ui_diagnostic(
                    "send_message_acknowledged",
                    prompt_chars=len(text or ""),
                )
            except Exception:
                pass

        if not prepared_resume:
            self.start_intelligence_engine_request(text)
            return

        from tech_connector.services.prompt.prompt_route_service import ENGINE_PROVIDERS
        prompt_route_decision = dict(prepared_resume.get("route_decision") or {})
        self._last_prompt_route_decision = dict(prompt_route_decision)
        self._last_prompt_execution_context = dict(prepared_resume.get("prompt_execution_context") or {})

        # Intelligence Engine fast paths: project health/dead code and target-discovery edits.
        # These can be expensive, so they run in a QThread before any normal LLM routing.
        decision_provider = (
            prompt_route_decision.get("provider")
            if isinstance(prompt_route_decision, dict)
            else getattr(prompt_route_decision, "provider", "")
        )
        if prompt_route_decision and decision_provider in ENGINE_PROVIDERS:
            self.input.clear()
            self.start_intelligence_engine_request(text, prompt_route_decision)
            return

        # 1. Preset Shortcut Interceptor
        lower_text = text.lower()
        if (
            prompt_route_decision
            and (
                prompt_route_decision.get("route")
                if isinstance(prompt_route_decision, dict)
                else getattr(prompt_route_decision, "route", "")
            ) == "github_ingest"
        ) or self.should_open_github_import_for_prompt(text):
            self.append(f"\nYOU [GitHub Workflow Composer]:\n{self._visible_prompt_text(text)}\n")
            self.append(
                "[Composer] Opening Web / GitHub Import so you can select a repo, ingest it, and compose a workflow from local plus ingested functions.\n"
            )
            self.input.clear()
            self.trigger_web_import(initial_query=text, workflow_goal=text)
            return

        if self._dispatch_prompt_route_from_chat(text, prompt_route_decision):
            return


        if self.attached_images:
            text += "\n\nAttached image paths:\n" + "\n".join(self.attached_images)

        self.input.clear()

        editor_active = (
                hasattr(self, "workspace_tabs")
                and self.workspace_tabs.tabText(self.workspace_tabs.currentIndex())
                == "Editor"
        )

        # Read Model & Safety flags
        _allow_local_only = self._ms_local_only()
        _allow_better = self._ms_allow_better()
        _tutorial_mode = self._ms_tutorial_mode()

        # Build tiers from currently-configured Ollama models
        try:
            from tech_connector.router.ai_router import ModelTiers

            _active_model = self.selected_mcphost_model() or ""
            _tiers = ModelTiers(active=_active_model)
            # If user disabled "allow better model", cap to local_plan
            if not _allow_better:
                _tiers.local_deep = ""
        except Exception:
            _tiers = None

        self.set_live_process("Routing request")
        route_started = time.perf_counter()
        route = self.ai_router.route_prompt(
            text,
            editor_active=editor_active,
            tiers=_tiers,
            allow_local_only=_allow_local_only,
            deep_route_scope=self.settings.get("deep_route_scope", "engine_complex_only"),
            deep_code_complexity_threshold=int(self.settings.get("deep_code_complexity_threshold", 7) or 7),
            get_model_for_role=self.mcphost_manager.get_model_for_role,
        )
        try:
            decision_data = prompt_route_decision.to_dict() if hasattr(prompt_route_decision, "to_dict") else dict(prompt_route_decision or {})

            # Canonical routing owns execution intent. Maya/Unreal subject matter is
            # not permission to start a DCC session. Explanations, examples, plans,
            # and project-code questions remain in a planning/code session unless
            # the canonical decision explicitly requests live host execution.
            understanding = dict(decision_data.get("request_understanding") or {})
            contract = dict(decision_data.get("semantic_execution_contract") or {})
            explicit_dcc_execution = bool(
                understanding.get("live_host_execution_requested")
                or contract.get("execution_requested")
                or str(decision_data.get("execution_route") or "").startswith("dcc.")
                or str(decision_data.get("operation_mode") or "") in {"execute", "mutate", "query_host"}
            )
            if getattr(route, "session_role", "") == "dcc" and not explicit_dcc_execution:
                from dataclasses import replace

                route = replace(
                    route,
                    session_role="plan",
                    reason="This is a code/design question, so live DCC execution is not needed.",
                )
                self._log_ui_diagnostic(
                    "route_session_overridden",
                    reason="canonical_context_did_not_request_dcc_execution",
                    task_role=getattr(route, "task_role", ""),
                    session_role=getattr(route, "session_role", ""),
                )

            if _tutorial_mode and getattr(route, "session_role", "") == "dcc":
                from dataclasses import replace

                route = replace(
                    route,
                    session_role="plan",
                    reason="Tutorial mode is active; all guidance is read-only.",
                )
                self._log_ui_diagnostic(
                    "route_session_overridden",
                    reason="tutorial_mode_forces_guidance",
                    task_role=getattr(route, "task_role", ""),
                    session_role=getattr(route, "session_role", ""),
                )
                if getattr(self, "_chk_allow_modifications", None) is not None:
                    self._chk_allow_modifications.setChecked(False)

            if decision_data.get("intent_category") == "staged_long_contract" and getattr(route, "session_role", "") == "dcc":
                from dataclasses import replace

                route = replace(
                    route,
                    session_role="plan",
                    reason="Staged Unreal planning contract routed through planning session; DCC execution is deferred until an approved action stage.",
                )
                self._log_ui_diagnostic(
                    "route_session_overridden",
                    reason="staged_long_contract_uses_plan_session",
                    task_role=getattr(route, "task_role", ""),
                    session_role=getattr(route, "session_role", ""),
                )
        except Exception:
            pass
        try:
            decision_data = (
                prompt_route_decision.to_dict()
                if hasattr(prompt_route_decision, "to_dict")
                else dict(prompt_route_decision or {})
            )
            terminal_goal_type = str(decision_data.get("goal_type") or "").lower()
            terminal_intent = str(decision_data.get("intent_category") or "").lower()
            mutation_requested = bool((decision_data.get("request_understanding") or {}).get("mutation_requested"))
            code_answer = (
                terminal_goal_type in {"generate", "explain"}
                or "code_generation" in terminal_intent
                or "code_example" in terminal_intent
            ) and not mutation_requested
            if code_answer and getattr(route, "session_role", "") == "plan":
                from dataclasses import replace
                route = replace(
                    route,
                    session_role="code",
                    reason="The requested deliverable is code, so a bounded code session will produce it directly.",
                )
        except Exception:
            pass

        self._update_route_label(route)
        self.set_live_process(f"Route selected: {getattr(route, 'session_role', 'main')}")

        # Auto-check "Allow better model" when a hard Unreal task is detected
        try:
            from tech_connector.router.ai_router import ComplexityScorer

            if ComplexityScorer.needs_deep_model(text) and hasattr(
                    self, "_chk_allow_better"
            ):
                self._chk_allow_better.setChecked(True)
        except Exception:
            pass

        # 2. Main Active Session Reuse
        if self.bridge.running and route.session_role == "plan":
            route_label = f"main | {self.selected_mcphost_model()}"
            self.append(f"\nYOU [{route_label}]:\n{self._visible_prompt_text(text)}\n")
            self._append_prompt_understanding(prompt_route_decision)
            self.append(
                "[Source Mode] "
                + (
                    "Live web/GitHub enabled.\n"
                    if self.service.live_sources_enabled()
                    else "Local only.\n"
                )
            )
            self.append(f"[Router] Reusing active main session.\n")
            self.set_live_process("Preparing prompt in background")

            def _send_main_prompt_background():
                try:
                    started = time.perf_counter()
                    prepared_text = self._prepare_adaptive_goal_prompt(
                        text,
                        route,
                        prompt_route_decision,
                        role="main",
                    )
                    prompt_seconds = time.perf_counter() - started
                    self.live_process_update.emit(
                        f"Serializing request ({len(prepared_text):,} chars, ~{max(1, len(prepared_text) // 4):,} tokens)"
                    )
                    active_model = resolve_model_for_policy(
                        self.selected_mcphost_model(),
                        as_mcphost_model(AI_MODELS["plan"]),
                        self.settings,
                    )
                    request_metadata = self.build_request_metadata(
                        text,
                        prepared_text,
                        route,
                        "main",
                        active_model,
                        fallback_used=active_model != self.selected_mcphost_model(),
                    )
                    self.last_user_prompt = prepared_text
                    self.service.last_user_prompt = prepared_text
                    self.current_session.append(
                        {
                            "role": "user",
                            "content": prepared_text,
                            "task_role": "general",
                            "session": "main",
                            "model": active_model,
                            "source_mode": "live"
                            if self.service.live_sources_enabled()
                            else "local",
                            "metadata": request_metadata,
                        }
                    )
                    self.store_request_metadata("main", request_metadata)
                    if self.bridge.write(prepared_text):
                        self.thread_log_message.emit(
                            f"[Sent to LLM. Prompt prepared in {prompt_seconds:.1f}s. Waiting for assistant/tool output...]\n"
                        )
                        self.response_started.emit("main")
                        self.live_process_update.emit("Waiting for model response")
                    else:
                        self.thread_log_message.emit(
                            "\n[Send failed: MCPHost is not running or input stream is unavailable.]\n"
                        )
                except Exception as exc:
                    self.thread_log_message.emit(
                        f"\n[Prompt Preparation Error] {exc}\n"
                    )

            import threading

            threading.Thread(target=_send_main_prompt_background, daemon=True).start()
            self.attached_images = []
            self.update_image_label()
            return

        role = route.session_role
        config = self.config_box.currentText().strip()
        use_pty = self.use_pty_checkbox.isChecked()
        desired_model = ""
        if route.model:
            try:
                from tech_connector.services.mcphost_service import as_configured_model

                desired_model = as_configured_model(route.model)
            except Exception:
                desired_model = route.model

        session = self.mcphost_manager.get_session(role)

        if not getattr(session, "_ui_signals_connected", False):
            session.bridge.output.connect(
                lambda data, r=role: self.handle_session_output(r, data)
            )
            session.bridge.exited.connect(
                lambda msg, r=role: self.handle_session_finished(r, msg)
            )
            session._ui_signals_connected = True

        if session.bridge.running and desired_model and session.model != desired_model:
            self.append(f"\n[Router] Restarting {role} session for {desired_model}.\n")
            self.mcphost_manager.stop_session(role)

        if not session.bridge.running:
            self.last_chat_activity_time = time.time()
            self.ollama_is_idle = False
            ok, cmd_display, error = self.mcphost_manager.start_session(
                role, config, use_pty, model_override=desired_model
            )
            if not ok:
                QMessageBox.critical(self, f"Start {role} session failed", error)
                return
            self.append(f"\n=== Starting {role} MCPHost session ===\n{cmd_display}\n\n")

        route_label = f"{route.task_role} -> {role}"
        if route.model:
            route_label += f" | {route.model}"
        self.append(f"\nYOU [{route_label}]:\n{self._visible_prompt_text(text)}\n")
        self._start_prompt_progress_observer(role, label=f"{role} routed request")
        self._note_prompt_progress_event("Preparing routed prompt in background", role)
        self._append_prompt_understanding(prompt_route_decision)
        self.append(
            "[Source Mode] "
            + (
                "Live web/GitHub enabled.\n"
                if self.service.live_sources_enabled()
                else "Local only.\n"
            )
        )
        self._log_ui_diagnostic(
            "route_prompt_completed",
            duration_ms=int((time.perf_counter() - route_started) * 1000),
            prompt_chars=len(text or ""),
            route=getattr(route, "session_role", ""),
            task_role=getattr(route, "task_role", ""),
        )
        self.append(f"[Router] {route.reason}.\n")
        if route.task_role == "unreal":
            self.set_live_process("Routing Unreal request to selected model")
            self.append(
                "[Unreal Planning] Using the Unreal TD context for this answer. "
                "For feature-planning questions I will reason from project facts, existing assets/tools, and safe Unreal architecture before recommending steps.\n"
            )
        self.set_live_process("Preparing routed prompt in background")

        def _prepare_and_send_routed_prompt_background():
            try:
                started = time.perf_counter()
                prepared_text = self._prepare_adaptive_goal_prompt(
                    text,
                    route,
                    prompt_route_decision,
                    role=role,
                )
                prompt_seconds = time.perf_counter() - started
                self.live_process_update.emit(
                    f"Serializing {role} request ({len(prepared_text):,} chars, ~{max(1, len(prepared_text) // 4):,} tokens)"
                )
                request_metadata = self.build_request_metadata(
                    text,
                    prepared_text,
                    route,
                    role,
                    session.model,
                    fallback_used=session.model != self.selected_mcphost_model()
                                  and bool(self.settings.get("cloud_model_unavailable", False)),
                )

                self.last_user_prompt = prepared_text
                self.service.last_user_prompt = prepared_text
                self.current_session.append(
                    {
                        "role": "user",
                        "content": prepared_text,
                        "task_role": route.task_role,
                        "session": role,
                        "model": session.model,
                        "source_mode": "live"
                        if self.service.live_sources_enabled()
                        else "local",
                        "metadata": request_metadata,
                    }
                )
                self.store_request_metadata(role, request_metadata)
                ok, msg = self.mcphost_manager.send(role, prepared_text)
                if ok:
                    self.response_started.emit(role)
                    self.live_process_update.emit("Waiting for model response")
                self.thread_log_message.emit(f"[{msg} Prompt prepared in {prompt_seconds:.1f}s.]\n")
            except Exception as exc:
                self.thread_log_message.emit(f"\n[Prompt Preparation Error] {exc}\n")
                self.live_process_update.emit("Prompt preparation failed")

        import threading

        threading.Thread(target=_prepare_and_send_routed_prompt_background, daemon=True).start()

        self.attached_images = []
        self.update_image_label()

    def prime(self):
        self.send_raw(self.prime_editor.toPlainText().strip(), "Prime")

    def handle_session_output(self, role, data):
        self._queue_terminal_output(role, data or "")

    def _process_role_terminal_output(self, role, raw):
        session = self.mcphost_manager.get_session(role)
        if raw:
            self._note_prompt_progress_event("Receiving model/tool output", role)

        # Scan raw for status
        for line in raw.splitlines():
            line_str = ANSI_RE.sub("", line).strip()
            line_str = re.sub(r"[\x00-\x1f]", "", line_str)
            if "Loading Ollama model" in line_str:
                self.append_status_once(
                    f"[{role.capitalize()}] Loading Ollama model..."
                )
            elif "Thinking" in line_str:
                self.append_status_once(f"[{role.capitalize()}] Thinking...")
            elif "Executing " in line_str:
                m = re.search(r"Executing\s+([\w_]+)", line_str, re.IGNORECASE)
                if m:
                    self.append_status_once(
                        f"[{role.capitalize()}] Executing tool {m.group(1)}..."
                    )
                else:
                    self.append_status_once(f"[{role.capitalize()}] {line_str}")

        cleaned = session.cleaner.clean(raw)

        if (
                is_credit_or_quota_failure(raw)
                and self.settings.get("model_source_mode") == "auto_with_local_fallback"
        ):
            metadata = self._pending_response_metadata_by_role.get(role)
            if metadata:
                metadata["fallback_used"] = False
                metadata["provider_error"] = "Cloud provider quota/credit issue"
                self.update_active_response_model_label(
                    metadata.get("active_raw_model"),
                    metadata.get("routing_mode"),
                    False,
                    metadata.get("active_raw_model"),
                )
            self.append(
                "\n[Model Provider] Cloud provider quota/credit issue detected. "
                "The request stopped on the selected cloud model; no local fallback was used. "
                "Add credits, choose another cloud provider, or explicitly switch Source Mode to Always local.\n"
            )

        if (
                "tools from MCP servers" in raw
                or "Enter your prompt" in raw
                or "Type your message" in raw
        ):
            session.ready = True
            self.set_card("mcphost", "ok", f"{role} ready")

        if "Loading Ollama model" in raw:
            self.set_card("ollama", "busy", f"Loading {role}")

        if "Model loaded:" in raw or "Model loaded successfully on GPU" in raw:
            self.set_ollama_card_for_model("ok", session.model)

        if cleaned:
            self.last_assistant_output = cleaned
            self.service.last_assistant_output = cleaned
            self._queue_stream_output(role, cleaned)
            self.current_session.append(
                {
                    "role": f"{role}_assistant_or_tool_output",
                    "content": cleaned,
                    "metadata": self._pending_response_metadata_by_role.get(role),
                }
            )

    def handle_session_finished(self, role, msg="MCPHost exited."):
        self._stop_prompt_progress_observer(role)
        session = self.mcphost_manager.get_session(role)
        session.running = False
        session.ready = False
        self._clear_active_response_addendum_state(role)
        self._flush_stream_output(role)
        self._stream_header_written.discard(role)
        self._stream_buffer_by_role.pop(role, None)
        self._stream_flush_pending.discard(role)
        self.append(f"\n=== {role} session exited: {msg} ===\n")


    # ------------------------------------------------------------------
    # Interactive Terminal integration
    # ------------------------------------------------------------------
    def active_project_root_path(self) -> str:
        for attr in ("project_root", "active_project_root", "current_project_root"):
            value = getattr(self, attr, None)
            if value:
                return str(value)
        try:
            label = getattr(self, "project_root_label", None)
            if label is not None:
                text = label.text()
                if text and "No active project" not in text:
                    return text.strip()
        except Exception:
            pass
        return str(Path.cwd())

    def open_terminal_dialog(self, command: str = "", cwd: str = ""):
        """Open a persistent interactive PowerShell-style terminal."""
        try:
            from tech_connector.ui.interactive_terminal_dialog import InteractiveTerminalDialog
            dialog = getattr(self, "_interactive_terminal_dialog", None)
            if dialog is None:
                dialog = InteractiveTerminalDialog(
                    self,
                    cwd=cwd or self.active_project_root_path(),
                    shell="powershell",
                )
                self._interactive_terminal_dialog = dialog
            if command:
                dialog.stage_command(command)
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
            return dialog
        except Exception as exc:
            try:
                QMessageBox.warning(self, "Terminal unavailable", str(exc))
            except Exception:
                self.append(f"\n[Terminal] unavailable: {exc}\n")
            return None

    def _current_editor_text_selection(self) -> tuple[str, str]:
        file_path = str(getattr(self, "current_file_path", "") or "")
        selected = ""
        try:
            editor = None
            if hasattr(self, "current_editor"):
                editor = self.current_editor()
            if editor is None:
                editor = getattr(self, "editor", None)
            if editor is None and hasattr(self, "open_editors") and file_path:
                editor = self.open_editors.get(file_path)
            if editor is not None:
                selected = editor.textCursor().selectedText().replace("\u2029", "\n")
        except Exception:
            selected = ""
        return selected, file_path

    def send_to_terminal(self, command: str = ""):
        return self.open_terminal_dialog(command=command or "", cwd=self.active_project_root_path())

    def run_selection_in_terminal(self):
        selected, _file_path = self._current_editor_text_selection()
        if not selected.strip():
            self.append("\n[Terminal] No editor selection found to stage.\n")
            return None
        return self.open_terminal_dialog(command=selected.strip(), cwd=self.active_project_root_path())

    def run_current_file_in_terminal(self):
        _selected, file_path = self._current_editor_text_selection()
        path = file_path or getattr(self, "current_file_path", "")
        if not path:
            self.append("\n[Terminal] No active file found to stage.\n")
            return None
        suffix = Path(path).suffix.lower()
        if suffix == ".py":
            command = f'python "{path}"'
        elif suffix == ".ps1":
            command = f'powershell -NoProfile -ExecutionPolicy Bypass -File "{path}"'
        else:
            command = f'"{path}"'
        return self.open_terminal_dialog(command=command, cwd=self.active_project_root_path())

    def run_prompt_in_terminal(self):
        try:
            command = self.input.text().strip()
        except Exception:
            command = ""
        if not command:
            self.append("\n[Terminal] Prompt is empty.\n")
            return None
        return self.open_terminal_dialog(command=command, cwd=self.active_project_root_path())

    def _extract_thread_assets(self) -> str:
        try:
            candidates = self._asset_mention_candidates("", include_index=False, limit=80)
        except Exception:
            candidates = []
        if not candidates:
            return ""
        lines = ["Active Thread / Asset Context:"]
        for candidate in candidates[:30]:
            lines.append(
                f"  - @{candidate.token}: {candidate.kind} from {candidate.source} -> `{candidate.value}`"
            )
        return "\n".join(lines)

    def _asset_mention_candidates(self, query_str: str = "", *, include_index: bool = True, limit: int = 20, text_context: str = ""):
        from tech_connector.services.asset_mention_service import (
            candidates_from_index,
            candidates_from_selected_assets,
            candidates_from_thread,
            candidates_from_unreal_snapshot,
            candidates_from_dcc_scene,
            merge_candidates,
        )

        session = getattr(self, "current_session", None)
        snapshot = getattr(self, "unreal_project_snapshot", "")
        selected_assets = []
        try:
            parsed_snapshot = json.loads(snapshot) if isinstance(snapshot, str) else snapshot
            if isinstance(parsed_snapshot, dict):
                data = parsed_snapshot.get("data") if isinstance(parsed_snapshot.get("data"), dict) else parsed_snapshot
                selected_assets = list(data.get("selected_assets") or [])
        except Exception:
            parsed_snapshot = snapshot

        if not text_context:
            text_context = self.input.text() if hasattr(self, "input") and hasattr(self.input, "text") else ""
        groups = [
            candidates_from_selected_assets(selected_assets),
            candidates_from_thread(session),
            candidates_from_unreal_snapshot(snapshot),
            candidates_from_dcc_scene(query_str, getattr(self, "command_router", None), text_context),
        ]
        if include_index:
            groups.append(candidates_from_index(query_str, limit=12))
        return merge_candidates(*groups, query=query_str, limit=limit)

    def on_chat_input_text_changed(self, text: str):
        import time
        self.last_chat_activity_time = time.time()
        cursor_pos = self.input.cursorPosition()
        before_cursor = text[:cursor_pos]
        if len(text or "") > 4000 and not any(marker in before_cursor[-120:] for marker in ("@", "!")):
            if hasattr(self, "_autocomplete_menu") and self._autocomplete_menu:
                self._autocomplete_menu.hide()
            self._log_ui_diagnostic(
                "autocomplete_skipped_large_prompt",
                prompt_chars=len(text or ""),
                cursor_pos=cursor_pos,
            )
            return

        at_idx = before_cursor.rfind("@")
        bang_idx = before_cursor.rfind("!")
        trigger_idx = max(at_idx, bang_idx)
        if trigger_idx == -1:
            if hasattr(self, "_autocomplete_menu") and self._autocomplete_menu:
                self._autocomplete_menu.hide()
            return

        if " " in before_cursor[trigger_idx:]:
            if hasattr(self, "_autocomplete_menu") and self._autocomplete_menu:
                self._autocomplete_menu.hide()
            return

        trigger = before_cursor[trigger_idx]
        query_str = before_cursor[trigger_idx + 1:]
        if trigger == "!":
            query_str = "!" + query_str

        seq = int(getattr(self, "_autocomplete_query_seq", 0) or 0) + 1
        self._autocomplete_query_seq = seq
        text_snapshot = text or ""
        self._log_ui_diagnostic(
            "autocomplete_query_scheduled",
            seq=seq,
            query=query_str,
            prompt_chars=len(text_snapshot),
            cursor_pos=cursor_pos,
        )
        QTimer.singleShot(
            175,
            lambda s=seq, q=query_str, snap=text_snapshot, at=trigger_idx, pos=cursor_pos: self._start_autocomplete_query(s, q, snap, at, pos),
        )

    def _autocomplete_popup_visible(self) -> bool:
        popup = getattr(self, "_autocomplete_menu", None)
        return bool(popup is not None and popup.isVisible())

    def _autocomplete_current_row(self) -> int:
        popup = getattr(self, "_autocomplete_menu", None)
        if popup is None or not hasattr(popup, "currentRow"):
            return -1
        try:
            return int(popup.currentRow())
        except Exception:
            return -1

    def _move_autocomplete_selection(self, delta: int) -> bool:
        popup = getattr(self, "_autocomplete_menu", None)
        if popup is None or not popup.isVisible() or not hasattr(popup, "count"):
            return False
        count = int(popup.count())
        if count <= 0:
            return False
        row = self._autocomplete_current_row()
        if row < 0:
            row = 0
        else:
            row = max(0, min(count - 1, row + int(delta)))
        popup.setCurrentRow(row)
        try:
            popup.scrollToItem(popup.item(row))
        except Exception:
            pass
        return True

    def _accept_autocomplete_selection(self) -> bool:
        popup = getattr(self, "_autocomplete_menu", None)
        if popup is None or not popup.isVisible() or not hasattr(popup, "currentItem"):
            return False
        item = popup.currentItem()
        if item is None and hasattr(popup, "count") and popup.count():
            item = popup.item(0)
        if item is None:
            return False
        token = item.data(Qt.UserRole) if hasattr(item, "data") else ""
        if token is None:
            token = item.text()
        at_idx = int(getattr(self, "_autocomplete_active_at_idx", -1))
        cursor_pos = self.input.cursorPosition() if hasattr(self, "input") else int(getattr(self, "_autocomplete_active_cursor_pos", 0))
        self._insert_autocomplete_suggestion(str(token), at_idx, cursor_pos)
        return True

    def eventFilter(self, obj, event):
        try:
            if obj is getattr(self, "input", None) and event.type() == QEvent.KeyPress:
                if self._autocomplete_popup_visible():
                    key = event.key()
                    if key in (Qt.Key_Tab, Qt.Key_Return, Qt.Key_Enter):
                        if self._accept_autocomplete_selection():
                            event.accept()
                            return True
                    if key == Qt.Key_Down:
                        if self._move_autocomplete_selection(1):
                            event.accept()
                            return True
                    if key == Qt.Key_Up:
                        if self._move_autocomplete_selection(-1):
                            event.accept()
                            return True
                    if key == Qt.Key_Escape:
                        self._autocomplete_menu.hide()
                        event.accept()
                        return True
        except Exception:
            pass
        try:
            return super().eventFilter(obj, event)
        except Exception:
            return False

    def _start_autocomplete_query(self, seq: int, query_str: str, text_snapshot: str, at_idx: int, cursor_pos: int):
        if seq != int(getattr(self, "_autocomplete_query_seq", 0) or 0):
            return
        include_index = len(query_str or "") >= 2
        self._log_ui_diagnostic(
            "autocomplete_query_started",
            seq=seq,
            query=query_str,
            include_index=include_index,
            prompt_chars=len(text_snapshot or ""),
        )

        def run_query():
            started = time.perf_counter()
            suggestions = []
            try:
                suggestions = self._query_autocomplete_suggestions(
                    query_str,
                    include_index=include_index,
                    text_context=text_snapshot,
                )
            except Exception:
                suggestions = []
            duration_ms = int((time.perf_counter() - started) * 1000)
            self._log_ui_diagnostic(
                "autocomplete_query_finished",
                seq=seq,
                query=query_str,
                duration_ms=duration_ms,
                count=len(suggestions or []),
            )
            try:
                self.autocomplete_suggestions_ready.emit(seq, at_idx, cursor_pos, suggestions)
            except Exception:
                pass

        import threading

        threading.Thread(target=run_query, daemon=True).start()

    def _apply_autocomplete_suggestions(self, seq: int, at_idx: int, cursor_pos: int, suggestions):
        if seq != int(getattr(self, "_autocomplete_query_seq", 0) or 0):
            return
        try:
            text = self.input.text()
            before_cursor = text[: self.input.cursorPosition()]
            latest_trigger = max(before_cursor.rfind("@"), before_cursor.rfind("!"))
            if latest_trigger != at_idx or " " in before_cursor[at_idx:]:
                return
        except Exception:
            return

        if not suggestions:
            if hasattr(self, "_autocomplete_menu") and self._autocomplete_menu:
                self._autocomplete_menu.hide()
            return

        if not hasattr(self, "_autocomplete_menu") or not self._autocomplete_menu:
            self._autocomplete_menu = QListWidget(self.input.window())
            self._autocomplete_menu.setWindowFlags(Qt.ToolTip | Qt.FramelessWindowHint)
            self._autocomplete_menu.setFocusPolicy(Qt.NoFocus)
            self._autocomplete_menu.setMouseTracking(True)
            self._autocomplete_menu.setUniformItemSizes(True)
            self._autocomplete_menu.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self._autocomplete_menu.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            self._autocomplete_menu.itemClicked.connect(lambda item: self._insert_autocomplete_suggestion(str(item.data(Qt.UserRole) or item.text()), getattr(self, "_autocomplete_active_at_idx", at_idx), self.input.cursorPosition()))
            self._autocomplete_menu.setStyleSheet("""
                QListWidget {
                    background-color: #0b0f14;
                    color: #d7dde5;
                    border: 1px solid #1e9bff;
                    border-radius: 4px;
                    outline: 0;
                }
                QListWidget::item {
                    padding: 4px 7px;
                }
                QListWidget::item:selected {
                    background-color: #1e9bff;
                    color: #ffffff;
                }
            """)
        else:
            self._autocomplete_menu.clear()

        self._autocomplete_active_at_idx = at_idx
        self._autocomplete_active_cursor_pos = cursor_pos
        max_rows = 5
        max_label_chars = 150
        for candidate in suggestions[:max_rows]:
            label = candidate.display() if hasattr(candidate, "display") else str(candidate)
            token = candidate.token if hasattr(candidate, "token") else str(candidate)
            display_label = " ".join(str(label or "").split())
            if len(display_label) > max_label_chars:
                display_label = display_label[: max_label_chars - 1].rstrip() + "..."
            item = QListWidgetItem(display_label)
            item.setData(Qt.UserRole, str(token or ""))
            item.setToolTip(str(label or ""))
            self._autocomplete_menu.addItem(item)
        if self._autocomplete_menu.count():
            self._autocomplete_menu.setCurrentRow(0)

        cursor_rect = self.input.cursorRect()
        pos = self.input.mapToGlobal(cursor_rect.bottomLeft())
        row_height = max(24, self._autocomplete_menu.sizeHintForRow(0) if self._autocomplete_menu.count() else 24)
        visible_rows = max(1, min(max_rows, self._autocomplete_menu.count()))
        width = min(640, max(300, min(520, self.input.width() + 180)))
        height = min(240, visible_rows * row_height + 8)
        screen = QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            width = min(width, max(260, available.width() - 24))
            if pos.x() + width > available.right():
                pos.setX(max(available.left() + 8, available.right() - width))
            if pos.y() + height > available.bottom():
                pos.setY(max(available.top() + 8, self.input.mapToGlobal(cursor_rect.topLeft()).y() - height))
        self._autocomplete_menu.setFixedSize(width, height)
        self._autocomplete_menu.move(pos)
        self._autocomplete_menu.show()
        self._autocomplete_menu.raise_()
        self.input.setFocus()

    def _insert_autocomplete_suggestion(self, val: str, at_idx: int, cursor_pos: int):
        text = self.input.text()
        if at_idx < 0:
            return
        live_cursor_pos = self.input.cursorPosition()
        cursor_pos = max(cursor_pos, live_cursor_pos)
        before_at = text[:at_idx]
        after_cursor = text[cursor_pos:]

        token = str(val or "").strip()
        if token.startswith("!"):
            pass
        elif not token.startswith("@"):
            token = "@" + token
        continues = token.endswith((".", "/"))
        spacer = "" if continues or not after_cursor or after_cursor.startswith((" ", "\n", "\t", ".", ",", ";", ":")) else " "
        new_text = before_at + token + spacer + after_cursor
        self.input.setText(new_text)

        self.input.setCursorPosition(len(before_at) + len(token) + len(spacer))
        if not continues and hasattr(self, "_autocomplete_menu") and self._autocomplete_menu:
            self._autocomplete_menu.hide()

    def _query_autocomplete_suggestions(self, query_str: str, *, include_index: bool = True, text_context: str = ""):
        from tech_connector.game_engine.integration.dcc_smart_search_service import (
            active_hosts_from_context,
            smart_search_suggestions,
        )

        active_context = ""
        try:
            active_context = self.command_router.get_active_dcc_context_cached()
        except Exception:
            pass
        smart_candidates = smart_search_suggestions(
            query_str,
            active_hosts=active_hosts_from_context(active_context),
            limit=16,
        )
        structured = any(marker in (query_str or "") for marker in (".", "/", "!"))
        if structured:
            return smart_candidates
        try:
            asset_candidates = self._asset_mention_candidates(
                query_str,
                include_index=include_index,
                limit=10,
                text_context=text_context,
            )
        except Exception:
            asset_candidates = []
        combined = []
        seen = set()
        for candidate in [*smart_candidates, *asset_candidates]:
            token = str(getattr(candidate, "token", candidate)).lower()
            if token in seen:
                continue
            seen.add(token)
            combined.append(candidate)
        return combined[:16]
