"""Extracted MainWindow methods. Generated from the uploaded monolithic file."""

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
from tech_connector.ui.design_system import set_status_state

PROMPT_PROGRESS_QUIET_SECONDS = 10
PROMPT_PROGRESS_CHAT_INTERVAL_SECONDS = 15
DEFAULT_CHAT_VISIBLE_MAX_CHARS = 120_000



from .main_window_chat_capability_mixin import MainWindowChatCapabilityMixin


class MainWindowChatRuntimeMixin(MainWindowChatCapabilityMixin):
    def _start_prompt_progress_observer(self, role: str = "main", *, label: str = "request") -> None:
        """Watch background prompt work and publish liveness without blocking UI."""
        role = role or "main"
        now = time.time()
        if not hasattr(self, "_prompt_progress_observers"):
            self._prompt_progress_observers = {}
        state = self._prompt_progress_observers.get(role, {})
        state.update(
            {
                "label": label or state.get("label") or "request",
                "started_at": state.get("started_at") or now,
                "stage_started_at": state.get("stage_started_at") or now,
                "last_event_at": now,
                "last_chat_update_at": state.get("last_chat_update_at") or 0.0,
                "last_message": state.get("last_message") or "Accepted request",
                "last_raw_message": state.get("last_raw_message") or "Accepted request",
                "last_human_stage": state.get("last_human_stage") or "",
                "observer_notice_sent": bool(state.get("observer_notice_sent", False)),
                "active": True,
            }
        )
        self._prompt_progress_observers[role] = state
        timer = getattr(self, "_prompt_progress_observer_timer", None)
        if timer is None:
            timer = QTimer(self)
            timer.setInterval(5000)
            timer.timeout.connect(self._tick_prompt_progress_observers)
            self._prompt_progress_observer_timer = timer
        if not timer.isActive():
            timer.start()

    def _note_prompt_progress_event(
        self,
        message: str,
        role: str = "main",
        *,
        raw_message: str = "",
    ) -> None:
        observers = getattr(self, "_prompt_progress_observers", None)
        if not observers:
            return
        role = role or "main"
        state = observers.get(role) or observers.get("main")
        if not state:
            return
        new_message = (message or "").strip() or state.get("last_message") or "Working"
        old_stage = self._background_status_stage_key(state.get("last_message") or "")
        new_stage = self._background_status_stage_key(new_message)
        now = time.time()
        state["last_event_at"] = now
        state["last_message"] = new_message
        state["last_raw_message"] = (raw_message or message or "").strip() or new_message
        if new_stage and new_stage != old_stage:
            state["observer_notice_sent"] = False
            state["stage_started_at"] = now

    def _stop_prompt_progress_observer(self, role: str = "main") -> None:
        observers = getattr(self, "_prompt_progress_observers", None)
        if observers:
            observers.pop(role or "main", None)
        timer = getattr(self, "_prompt_progress_observer_timer", None)
        if timer is not None and (not observers):
            timer.stop()

    def _tick_prompt_progress_observers(self) -> None:
        observers = getattr(self, "_prompt_progress_observers", {}) or {}
        if not observers:
            timer = getattr(self, "_prompt_progress_observer_timer", None)
            if timer is not None:
                timer.stop()
            return
        now = time.time()
        for role, state in list(observers.items()):
            if not state.get("active"):
                continue
            elapsed = int(now - float(state.get("started_at") or now))
            quiet = int(now - float(state.get("last_event_at") or now))
            if quiet < PROMPT_PROGRESS_QUIET_SECONDS:
                continue
            last_message = str(state.get("last_message") or "Working")
            label = str(state.get("label") or "request")
            human = self._humanize_background_status(last_message)
            stage_elapsed = max(
                0,
                int(now - float(state.get("stage_started_at") or state.get("started_at") or now)),
            )
            quiet = max(0, int(now - float(state.get("last_event_at") or now)))
            status = (
                f"{human.rstrip('.')} | stage {stage_elapsed}s | "
                f"total {elapsed}s | last update {quiet}s ago"
            )
            if hasattr(self, "live_process_label"):
                self.live_process_label.setText(f"Working: {status}")
            if (
                now - float(state.get("last_chat_update_at") or 0.0)
                >= PROMPT_PROGRESS_CHAT_INTERVAL_SECONDS
            ):
                stage_key = self._background_status_stage_key(last_message)
                if human:
                    state["last_chat_update_at"] = now
                    state["last_human_stage"] = stage_key
                    state["observer_notice_sent"] = True
                    metadata_by_role = getattr(self, "_pending_response_metadata_by_role", {}) or {}
                    metadata = dict(metadata_by_role.get(role) or {})
                    model = str(
                        metadata.get("active_raw_model")
                        or metadata.get("model")
                        or metadata.get("requested_model")
                        or ""
                    ).strip()
                    provider = str(
                        metadata.get("provider")
                        or metadata.get("model_provider")
                        or ""
                    ).strip()
                    route_data = dict(getattr(self, "_last_prompt_route_decision", {}) or {})
                    target = str(
                        route_data.get("selected_target")
                        or route_data.get("resolved_target_file")
                        or route_data.get("target_file")
                        or ""
                    ).strip()
                    decision_terms = (
                        "because",
                        "rejected",
                        "resolved",
                        "recover",
                        "escalat",
                        "evidence",
                        "approved",
                        "skip",
                        "failed",
                        "invalid",
                    )
                    update_label = (
                        "Current reasoning"
                        if any(term in human.casefold() for term in decision_terms)
                        else "Active step"
                    )
                    detail_lines = [
                        f"{update_label}: {human.rstrip('.')}",
                        f"Request: {label}",
                    ]
                    if model or provider:
                        model_label = model or "selected model"
                        if provider:
                            model_label += f" via {provider}"
                        detail_lines.append(f"Model: {model_label}")
                    if target:
                        detail_lines.append(f"Target: {target}")
                    detail_lines.extend(
                        [
                            f"Stage elapsed: {stage_elapsed}s | Total elapsed: {elapsed}s",
                            f"Last engine update: {quiet}s ago",
                        ]
                    )
                    detail = "\n".join(detail_lines)
                    self.append(f"\nASSISTANT [Update]:\n{detail}\n")

    def _background_status_stage_key(self, message: str) -> str:
        """Return a stable stage key so observer notices are not repeated."""
        text = re.sub(r"\s+", " ", str(message or "")).strip().lower()
        for noise in ("serializing", "chars", "tokens", "elapsed", "waiting for model response"):
            text = text.replace(noise, "")
        text = re.sub(r"\d+", "", text)
        text = re.sub(r"[^a-z ]+", " ", text)
        return re.sub(r"\s+", " ", text).strip() or "background_work"

    def _humanize_background_status(self, message: str) -> str:
        """Preserve observable stage facts while removing only transport noise."""
        text = re.sub(r"\s+", " ", str(message or "")).strip()
        if not text:
            return "Working; no stage message has been received yet."
        lower = text.lower()
        if "waiting for model response" in lower:
            return "Waiting for the selected model to produce output."
        if "receiving model/tool output" in lower:
            return "Receiving model or tool output."
        if "serializing" in lower:
            return text.rstrip(".") + "."
        if "subprocess pipe active" in lower:
            return "The model subprocess is active; waiting for its next progress event."
        text = re.sub(r"^(working:|still working:?|accepted request[- :]*|preparing[- :]*)", "", text, flags=re.I).strip(" .")
        if not text:
            return "Routing the request and resolving its execution context."
        return text[0].upper() + text[1:].rstrip(".") + "."

    def append_status_once(self, msg):
        if not hasattr(self, "_seen_log_status_msgs"):
            self._seen_log_status_msgs = set()
        if msg not in self._seen_log_status_msgs:
            self._seen_log_status_msgs.add(msg)
            self.append(f"\n[Status] {msg}\n")

    def _mark_response_started(self, role="main"):
        role = role or "main"
        self.last_chat_activity_time = time.time()
        self.ollama_is_idle = False
        self._response_started_at_by_role[role] = time.time()
        self._start_prompt_progress_observer(role, label=f"{role} model response")
        self._note_prompt_progress_event("Waiting for model response", role)
        QTimer.singleShot(30000, lambda r=role: self.pending_response_notice(r))

    def _consume_response_elapsed_label(self, role="main"):
        started = self._response_started_at_by_role.pop(role or "main", None)
        if not started:
            return ""
        elapsed = max(0, int(time.time() - started))
        minutes, seconds = divmod(elapsed, 60)
        if minutes:
            return f"Worked for {minutes}m {seconds}s"
        return f"Worked for {seconds}s"

    def _canonical_thread_transcript(self) -> str:
        """Return the complete structured thread independently of the rendered chat window."""
        session = list(getattr(self, "current_session", []) or [])
        formatter = getattr(self, "_history_session_to_transcript", None)
        if callable(formatter):
            return formatter(session)

        parts = []
        for message in session:
            if not isinstance(message, dict):
                continue
            role = str(message.get("role") or "message").upper()
            content = message.get("content") or ""
            if not isinstance(content, str):
                content = json.dumps(content, indent=2, ensure_ascii=False)
            if content.strip():
                parts.append(f"\n{role}:\n{content}\n")
        return "".join(parts)

    def _chat_visible_max_chars(self) -> int:
        try:
            configured = int(
                self.settings.get(
                    "chat_visible_max_chars",
                    DEFAULT_CHAT_VISIBLE_MAX_CHARS,
                )
            )
        except (TypeError, ValueError):
            configured = DEFAULT_CHAT_VISIBLE_MAX_CHARS
        return max(40_000, configured)

    def _trim_visible_chat_history(self) -> None:
        """Bound Qt-facing text while the canonical session remains complete."""
        raw = str(getattr(self, "chat_history_raw", "") or "")
        limit = self._chat_visible_max_chars()
        if len(raw) <= limit:
            return

        minimum_cut = len(raw) - limit
        boundaries = [
            raw.find(marker, minimum_cut)
            for marker in ("\nYOU", "\nASSISTANT", "\nSYSTEM", "\n[")
        ]
        valid_boundaries = [index for index in boundaries if index >= minimum_cut]
        cut_at = min(valid_boundaries) if valid_boundaries else minimum_cut
        self._chat_history_omitted_chars = int(
            getattr(self, "_chat_history_omitted_chars", 0) or 0
        ) + cut_at
        self.chat_history_raw = raw[cut_at:].lstrip()

    def _visible_chat_transcript(self) -> str:
        self._trim_visible_chat_history()
        raw = str(getattr(self, "chat_history_raw", "") or "")
        omitted = int(getattr(self, "_chat_history_omitted_chars", 0) or 0)
        if not omitted:
            return raw
        return (
            "[Earlier thread content is retained in context and saved history. "
            f"{omitted:,} display characters are hidden here; use Full Thread to view everything.]\n\n"
            + raw
        )

    def show_full_thread(self) -> None:
        transcript = self._canonical_thread_transcript()
        if not transcript.strip():
            transcript = str(getattr(self, "chat_history_raw", "") or "")

        dialog = QDialog(self)
        dialog.setWindowTitle("Full Thread")
        dialog.resize(1000, 760)
        layout = QVBoxLayout(dialog)
        viewer = QPlainTextEdit(dialog)
        viewer.setReadOnly(True)
        viewer.setLineWrapMode(QPlainTextEdit.NoWrap)
        viewer.setPlainText(transcript)
        layout.addWidget(viewer, 1)

        actions = QHBoxLayout()
        copy_btn = QPushButton("Copy Full Thread", dialog)
        close_btn = QPushButton("Close", dialog)
        copy_btn.clicked.connect(
            lambda: QGuiApplication.clipboard().setText(transcript)
        )
        close_btn.clicked.connect(dialog.accept)
        actions.addStretch(1)
        actions.addWidget(copy_btn)
        actions.addWidget(close_btn)
        layout.addLayout(actions)
        dialog.exec()
        dialog.deleteLater()

    def append(self, text):
        if not text:
            return
        self.extract_code_blocks(text)
        self.chat_history_raw += text
        self._trim_visible_chat_history()

        if hasattr(self, "log"):
            scroll = self.log.verticalScrollBar()
            self._chat_render_pending_bottom = scroll.value() >= scroll.maximum() - 20
            self._chat_render_previous_scroll = scroll.value()
        if hasattr(self, "chat_render_timer"):
            self.chat_render_timer.start(60)
        else:
            self.render_chat_history()

    def _ui_diagnostic_enabled(self) -> bool:
        try:
            return bool(self.settings.get("ui_diagnostic_mode", False))
        except Exception:
            return False

    def _log_ui_diagnostic(self, event: str, **details) -> None:
        try:
            from tech_connector.services.diagnostic_service import log_ui_event

            log_ui_event(event, enabled=self._ui_diagnostic_enabled(), **details)
        except Exception:
            pass

    def _visible_prompt_text(self, text: str, *, limit=None) -> str:
        """Return a chat-display-safe prompt preview while preserving full session data."""
        text = text or ""
        try:
            limit = int(limit or self.settings.get("chat_visible_prompt_char_limit", 6000) or 6000)
        except Exception:
            limit = 6000
        if limit <= 0 or len(text) <= limit:
            return text
        omitted = len(text) - limit
        return (
            text[:limit].rstrip()
            + f"\n\n[Prompt preview truncated in chat: {omitted:,} characters kept in the request/session.]"
        )

    def clear_visible_chat_state(self):
        """Reset rendered chat and pending stream buffers without touching saved history."""
        self.chat_history_raw = ""
        self._chat_history_omitted_chars = 0
        self.chat_copy_blocks = []
        self._stream_buffer_by_role = {}
        self._stream_header_written = set()
        self._stream_flush_pending = set()
        self._stream_preview_content_by_role = {}
        self._stream_preview_render_pending = set()
        self._stream_plain_started_roles = set()
        self._stream_preview_base_html = ""
        self._stream_finalize_pending = set()
        self._raw_terminal_buffer_by_role = {}
        self._raw_terminal_flush_pending = set()
        self._response_started_at_by_role = {}
        for role in list(getattr(self, "_prompt_progress_observers", {}) or {}):
            self._stop_prompt_progress_observer(role)
        self._pending_response_metadata_by_role = {}
        self._active_response_addendum_counts = {}
        self._active_response_addendum_keys = set()
        self._chat_current_response_index = None
        if hasattr(self, "_autocomplete_menu") and self._autocomplete_menu:
            self._autocomplete_menu.hide()
        if hasattr(self, "chat_render_timer"):
            self.chat_render_timer.stop()
        if hasattr(self, "log"):
            self.log.clear()

    def _queue_stream_output(self, role: str, text: str):
        role = role or "main"
        if not text:
            return
        self._stream_buffer_by_role[role] = (
                self._stream_buffer_by_role.get(role, "") + text
        )
        if role not in self._stream_flush_pending:
            self._stream_flush_pending.add(role)
            QTimer.singleShot(120, lambda r=role: self._flush_stream_output(r))
        self._schedule_stream_finalize(role)

    def _flush_stream_output(self, role: str):
        role = role or "main"
        self._stream_flush_pending.discard(role)
        chunk = self._stream_buffer_by_role.get(role, "")
        if not chunk:
            return
        self._stream_buffer_by_role[role] = ""

        if role not in self._stream_header_written:
            elapsed_label = self._consume_response_elapsed_label(role)
            header = (
                f"ASSISTANT [{elapsed_label}]"
                if elapsed_label
                else ("ASSISTANT" if role == "main" else f"ASSISTANT [{role}]")
            )
            metadata = self.consume_request_metadata(role)
            route_summary = self.render_model_route_summary(metadata)
            self._stream_header_written.add(role)
            self._queue_stream_preview(role, header, route_summary + chunk)
            return

        header = "ASSISTANT" if role == "main" else f"ASSISTANT [{role}]"
        self._queue_stream_preview(role, header, chunk)

    def _finish_stream_output(self, role: str, cleaned: str = ""):
        role = role or "main"
        if cleaned:
            self._queue_stream_output(role, cleaned)
        self._flush_stream_output(role)
        preview_payload = self._stream_preview_content_by_role.get(role) or {}
        preview_header = preview_payload.get("header")
        preview_content = preview_payload.get("content") or ""
        if preview_content:
            header = preview_header or (
                "ASSISTANT" if role == "main" else f"ASSISTANT [{role}]"
            )
            final_text = f"\n{header}:\n{preview_content}\n"
            self.extract_code_blocks(final_text)
            self.chat_history_raw += final_text
            self._trim_visible_chat_history()

            project_edit_preview = None
            if ("<modify_file" in preview_content or "<create_file" in preview_content) and hasattr(self, "editor_diff_widget"):
                project_edit_preview = self._handle_chat_stream_file_edits(preview_content)

            # The Goal Graph now drives runtime continuation. A completed model
            # response is committed to the active goal, then the next dependency-
            # ready goal is sent without rebuilding the entire request prompt.
            self._commit_adaptive_goal_response(
                role,
                preview_content,
                project_edit_preview=project_edit_preview,
            )

        self._clear_stream_preview(role, render_base=False)
        self._stream_header_written.discard(role)
        self._stop_prompt_progress_observer(role)
        self._stream_buffer_by_role.pop(role, None)
        self._stream_flush_pending.discard(role)
        self._stream_finalize_pending.discard(role)
        self._clear_active_response_addendum_state(role)
        self.render_chat_history()

    def _handle_chat_stream_file_edits(self, content: str):
        try:
            from tech_connector.services.project_edit_agent_service import preview_project_edit_agent_response
            
            project_root = self.active_project_root_path()
            execution_context = dict(getattr(self, "_last_prompt_execution_context", {}) or {})
            request_prompt = str(
                execution_context.get("normalized_prompt")
                or execution_context.get("prompt")
                or getattr(self, "last_user_prompt", "")
                or ""
            )
            preview = preview_project_edit_agent_response(
                content,
                project_root=project_root,
                request_prompt=request_prompt,
            )
            
            if preview.changes:
                changes_list = []
                for change in preview.changes:
                    changes_list.append({
                        "path": change["path"],
                        "action": change["action"],
                        "original_content": change.get("before", ""),
                        "new_content": change.get("after", ""),
                    })

                if changes_list:
                    self.workspace_tabs.setCurrentIndex(1)
                    if hasattr(self, "normal_editor_widget"):
                        self.normal_editor_widget.setVisible(False)
                    self.editor_diff_widget.set_changes(changes_list)
                    self.editor_diff_widget.set_validation_evidence(
                        {
                            "summary": "Disposable project-edit preview",
                            "validation": list(
                                getattr(preview, "validation", []) or []
                            ),
                            "errors": list(preview.errors or []),
                        }
                    )
                    self.editor_diff_widget.setVisible(True)
                    self.append(
                        "\n[Project Edit Agent] Proposed code changes loaded into the Editor Diff comparison view. Review and approve to apply.\n"
                    )
            elif preview.errors:
                self.append(
                    "\n[Project Edit Agent] Could not prepare a safe diff preview:\n"
                    + "\n".join(f"- {error}" for error in preview.errors)
                    + "\n"
                )
            return preview
        except Exception as e:
            print(f"Error handling chat stream file edits: {e}")
            return None

    def render_chat_history(self):
        if not hasattr(self, "log"):
            return
        started = time.perf_counter()
        visible_transcript = self._visible_chat_transcript()
        if visible_transcript == getattr(self, "_last_rendered_visible_transcript", None):
            if self._chat_render_pending_bottom:
                self.log.moveCursor(QTextCursor.End)
            return
        html = self.raw_text_to_html(visible_transcript)
        self._stream_preview_base_html = html

        previous_scroll = int(getattr(self, "_chat_render_previous_scroll", 0) or 0)
        self.log.setHtml(html)
        self._last_rendered_visible_transcript = visible_transcript
        self._last_rendered_chat_html = html
        if self._chat_render_pending_bottom:
            self.log.moveCursor(QTextCursor.End)
        else:
            try:
                scroll = self.log.verticalScrollBar()
                scroll.setValue(min(previous_scroll, scroll.maximum()))
            except Exception:
                pass
        duration_ms = int((time.perf_counter() - started) * 1000)
        if duration_ms >= 250 or self._ui_diagnostic_enabled():
            self._log_ui_diagnostic(
                "chat_render",
                duration_ms=duration_ms,
                raw_chars=len(self.chat_history_raw or ""),
                omitted_chars=int(getattr(self, "_chat_history_omitted_chars", 0) or 0),
                html_chars=len(html or ""),
            )

    def _render_stream_preview(self, role: str):
        role = role or "main"
        self._stream_preview_render_pending.discard(role)
        if not hasattr(self, "log"):
            return
        if not self._stream_preview_content_by_role:
            return
        for preview_role, payload in self._stream_preview_content_by_role.items():
            content = payload.get("content") or ""
            rendered = int(payload.get("rendered", 0) or 0)
            delta = content[rendered:]
            if not delta:
                continue
            header = payload.get("header") or (
                "ASSISTANT" if preview_role == "main" else f"ASSISTANT [{preview_role}]"
            )
            self._append_stream_plain_text(preview_role, header, delta)
            payload["rendered"] = len(content)
            self._stream_preview_content_by_role[preview_role] = payload

    def _append_stream_plain_text(self, role: str, header: str, text: str):
        """Append streaming text without reparsing the full rich-text transcript."""
        if not hasattr(self, "log") or not text:
            return
        previous_scroll = 0
        try:
            scroll = self.log.verticalScrollBar()
            previous_scroll = scroll.value()
        except Exception:
            scroll = None
        try:
            try:
                cursor = QTextCursor(self.log.document())
            except Exception:
                cursor = self.log.textCursor()
            cursor.movePosition(QTextCursor.End)
            if role not in self._stream_plain_started_roles:
                if self.log.document().characterCount() > 1:
                    cursor.insertBlock()
                cursor.insertText(f"{header}:\n")
                self._stream_plain_started_roles.add(role)
            cursor.insertText(text)
            if self._chat_render_pending_bottom:
                self.log.setTextCursor(cursor)
                self.log.moveCursor(QTextCursor.End)
            elif scroll is not None:
                scroll.setValue(previous_scroll)
        except Exception:
            # If QTextBrowser insertion fails, the final rich render still happens.
            pass

    def _queue_stream_preview(self, role: str, header: str, text: str):
        role = role or "main"
        if not text:
            return
        payload = self._stream_preview_content_by_role.get(role) or {
            "header": header,
            "content": "",
        }
        payload["header"] = header
        payload["content"] = (payload.get("content") or "") + text
        payload.setdefault("rendered", 0)
        self._stream_preview_content_by_role[role] = payload
        if role in self._stream_preview_render_pending:
            return
        self._stream_preview_render_pending.add(role)
        QTimer.singleShot(75, lambda r=role: self._render_stream_preview(r))

    def _schedule_stream_finalize(self, role: str):
        role = role or "main"
        if role in self._stream_finalize_pending:
            return
        self._stream_finalize_pending.add(role)

        def _finalize_if_quiet(r=role):
            self._stream_finalize_pending.discard(r)
            if self._stream_buffer_by_role.get(r):
                self._schedule_stream_finalize(r)
                return
            if self._stream_preview_content_by_role.get(r):
                self._finish_stream_output(r)

        QTimer.singleShot(1500, _finalize_if_quiet)

    def _clear_stream_preview(self, role: str, *, render_base: bool = True):
        role = role or "main"
        self._stream_preview_content_by_role.pop(role, None)
        self._stream_preview_render_pending.discard(role)
        self._stream_plain_started_roles.discard(role)
        if render_base and hasattr(self, "log"):
            self.log.setHtml(
                self._stream_preview_base_html
                or self.raw_text_to_html(self._visible_chat_transcript())
            )
            if self._chat_render_pending_bottom:
                self.log.moveCursor(QTextCursor.End)

    def _active_response_roles(self) -> list[str]:
        """Return genuinely active responses, expiring abandoned response markers."""
        now = time.time()
        started = getattr(self, "_response_started_at_by_role", {}) or {}
        previews = getattr(self, "_stream_preview_content_by_role", {}) or {}
        buffers = getattr(self, "_stream_buffer_by_role", {}) or {}
        metadata = getattr(self, "_pending_response_metadata_by_role", {}) or {}
        try:
            stale_after = max(30.0, float(self.settings.get("active_response_stale_seconds", 180) or 180))
        except Exception:
            stale_after = 180.0

        roles = set(previews.keys())
        roles.update(role for role, text in buffers.items() if text)
        for role, started_at in list(started.items()):
            age = max(0.0, now - float(started_at or now))
            has_output = bool(previews.get(role) or buffers.get(role))
            has_request = role in metadata
            if age <= stale_after and (has_request or has_output):
                roles.add(role)
                continue
            started.pop(role, None)
            metadata.pop(role, None)
            self._stop_prompt_progress_observer(role)
            self._clear_active_response_addendum_state(role)
        return sorted(role for role in roles if role)

    def _role_for_active_response_addendum(self) -> str:
        roles = self._active_response_roles()
        if not roles:
            return ""
        try:
            metadata = getattr(self, "_pending_response_metadata_by_role", {}) or {}
            for role in roles:
                if role in metadata:
                    return role
        except Exception:
            pass
        return "main" if "main" in roles else roles[0]

    def _clear_active_response_addendum_state(self, role: str) -> None:
        role = role or "main"
        try:
            keys = getattr(self, "_active_response_addendum_keys", set())
            self._active_response_addendum_keys = {key for key in keys if not str(key).startswith(f"{role}:")}
            counts = getattr(self, "_active_response_addendum_counts", {})
            counts.pop(role, None)
        except Exception:
            pass

    def _format_active_response_addendum(self, text: str, role: str) -> str:
        count = int(getattr(self, "_active_response_addendum_counts", {}).get(role, 1))
        return (
            f"Additional context update #{count} for the answer currently in progress.\n"
            "Incorporate this into your current answer if possible. If you already committed to a direction, revise before finalizing.\n\n"
            f"{text}"
        )

    def _send_active_response_addendum(self, text: str) -> bool:
        role = self._role_for_active_response_addendum()
        if not role or not text.strip():
            return False
        key = f"{role}:{hash(text.strip())}"
        keys = getattr(self, "_active_response_addendum_keys", set())
        if key in keys:
            self.set_live_process("Already added that context")
            return True
        keys.add(key)
        self._active_response_addendum_keys = keys
        counts = getattr(self, "_active_response_addendum_counts", {})
        counts[role] = int(counts.get(role, 0)) + 1
        self._active_response_addendum_counts = counts
        payload = self._format_active_response_addendum(text.strip(), role)
        self.append(f"\nYOU [Addendum -> {role}]:\n{self._visible_prompt_text(text.strip())}\n")
        self.current_session.append(
            {
                "role": "user_addendum",
                "content": text.strip(),
                "session": role,
                "metadata": {"kind": "active_response_addendum", "role": role, "addendum_index": counts[role]},
            }
        )
        self.set_live_process(f"Sending context update to {role}")
        self._log_ui_diagnostic(
            "active_response_addendum_queued",
            role=role,
            prompt_chars=len(text.strip()),
            payload_chars=len(payload),
        )

        def send_addendum():
            started = time.perf_counter()
            try:
                if role == "main":
                    ok = bool(getattr(self.bridge, "running", False) and self.bridge.write(payload))
                    msg = "Added context to active main response." if ok else "Could not add context; main session is not accepting input."
                else:
                    ok, msg = self.mcphost_manager.send(role, payload)
                elapsed = time.perf_counter() - started
                self.live_process_update.emit(msg)
                self.thread_log_message.emit(f"[{msg} Context update send took {elapsed:.1f}s.]\n")
                self._log_ui_diagnostic(
                    "active_response_addendum_sent",
                    role=role,
                    ok=ok,
                    duration_ms=int(elapsed * 1000),
                    payload_chars=len(payload),
                )
            except Exception as exc:
                self.thread_log_message.emit(f"\n[Addendum Send Error] {exc}\n")
                self.live_process_update.emit("Context update failed")

        import threading

        threading.Thread(target=send_addendum, daemon=True).start()
        return True

    def raw_text_to_html(self, raw_text: str) -> str:
        """Render saved plain-text chat into polished QTextBrowser HTML.

        The renderer lives in ui.chat_renderer so the chat visual quality is not
        tangled with runtime/model-routing logic. It preserves fenced code blocks
        as whole cards, supports copy actions, and formats messages closer to
        ChatGPT-style conversation output.
        """
        try:
            from tech_connector.ui.chat_renderer import render_thread
            return render_thread(self, raw_text or "")
        except Exception as exc:
            import html as html_module
            safe = html_module.escape(raw_text or "").replace("\n", "<br/>")
            return (
                "<html><body style='font-family: Segoe UI; color:#d7dde5; "
                "background:#0b0f14; padding:18px;'>"
                f"<div style='color:#ff7b72;'>Chat render failed: {html_module.escape(str(exc))}</div>"
                f"<div>{safe}</div></body></html>"
            )

    def handle_log_anchor_clicked(self, url: QUrl):
        href = url.toString()
        if href.startswith("action://copy_snippet_"):
            try:
                idx = int(href.split("_")[-1])
                code = ""
                # Attempt to extract current edited snippet from QTextDocument
                cursor = self.log.document().find(f"action://copy_snippet_{idx}")
                if not cursor.isNull():
                    cursor.movePosition(QTextCursor.NextBlock)
                    lines = []
                    while True:
                        block = cursor.block()
                        if not block.isValid():
                            break
                        block_fmt = block.blockFormat()
                        block_bg = block_fmt.background().color().name().lower()
                        char_font = block.charFormat().font()
                        family = char_font.family().lower()

                        is_code_block = (
                                any(
                                    f in family
                                    for f in ("consolas", "monaco", "courier", "monospace")
                                )
                                or char_font.fixedPitch()
                                or block_bg in ("#161b22", "#0d1117", "#0f141c")
                                or block.charFormat().background().color().name().lower()
                                in ("#161b22", "#0d1117", "#0f141c")
                        )

                        if is_code_block:
                            lines.append(block.text())
                            if not cursor.movePosition(QTextCursor.NextBlock):
                                break
                        else:
                            break
                    if lines:
                        code = "\n".join(lines)

                # Fallback to initial code cache
                if not code and 0 <= idx < len(self.code_snippets):
                    code = self.code_snippets[idx][1]

                if code:
                    QGuiApplication.clipboard().setText(code)
                    self.append(
                        f"\n[Status] Copied code snippet {idx + 1} to clipboard.\n"
                    )
            except Exception as e:
                print(f"Error copying snippet: {e}")
        elif href == "action://copy_thread":
            self.copy_full_log()
        elif href.startswith("action://copy_block_"):
            try:
                idx = int(href.split("_")[-1])
                if 0 <= idx < len(self.chat_copy_blocks):
                    QGuiApplication.clipboard().setText(self.chat_copy_blocks[idx])
                    self._set_current_chat_response_from_copy_index(idx)
                    self.append(
                        f"\n[Status] Copied message block {idx + 1} to clipboard.\n"
                    )
            except Exception as e:
                print(f"Error copying message block: {e}")
        elif href == "action://undo_last_applied":
            self.undo_last_applied_changes()
        elif href.startswith("action://open_file"):
            try:
                parsed = urlparse(href)
                params = parse_qs(parsed.query)
                path = unquote((params.get("path") or [""])[0])
                line = int((params.get("line") or ["1"])[0] or 1)
                if path:
                    self.open_file_at_line(path, line)
            except Exception as exc:
                self.append(f"\n[Open File] Could not open linked file: {exc}\n")

    def export_log_to_pdf(self):

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Conversation to PDF", str(HISTORY_DIR), "PDF Files (*.pdf)"
        )
        if file_path:
            try:
                self.log.document().printToPdf(file_path)
                self.append(f"\n[Status] Conversation exported to PDF: {file_path}\n")
                QMessageBox.information(
                    self,
                    "Export Complete",
                    f"PDF successfully created at:\n{file_path}",
                )
            except Exception as e:
                QMessageBox.critical(
                    self, "Export Failed", f"Could not create PDF:\n{e}"
                )

    def undo_last_applied_changes(self):
        if not hasattr(self, "last_applied_backup") or not self.last_applied_backup:
            self.append("\n[Status] No changes available to undo.\n")
            QMessageBox.information(self, "Undo", "No changes available to undo.")
            return

        restored = []
        deleted = []
        failed = []

        from pathlib import Path

        for path, data in list(self.last_applied_backup.items()):
            action = data["action"]
            if action == "create":
                try:
                    if Path(path).exists():
                        Path(path).unlink()
                        deleted.append(path)
                except Exception as e:
                    failed.append(f"Could not delete {path}: {e}")
            elif action == "modify":
                try:
                    Path(path).write_text(data["content"], encoding="utf-8")
                    restored.append(path)
                except Exception as e:
                    failed.append(f"Could not restore {path}: {e}")

        self.last_applied_backup = {}
        self.refresh_project_tree_fast()
        self.build_index()

        summary = ""
        if restored:
            summary += f"[Undo] Restored modified files: {', '.join(restored)}\n"
        if deleted:
            summary += f"[Undo] Deleted created files: {', '.join(deleted)}\n"
        if failed:
            summary += f"[Undo Error] Failures:\n" + "\n".join(failed) + "\n"

        self.append(f"\n[Status] Undid last applied changes.\n{summary}\n")
        QMessageBox.information(
            self,
            "Undo Complete",
            "Last applied changes have been rolled back successfully.",
        )

    def handle_diff_accepted(self, pending_changes):
        self.last_applied_backup = {}
        changed_paths = []
        report_changes = []
        saved_change_session_path = None

        from pathlib import Path

        try:
            from tech_connector.services.change_history_service import create_change_session, save_change_session
            session = create_change_session(pending_changes, summary="Accepted AI code changes")
            saved_change_session_path = save_change_session(session)
        except Exception as exc:
            self.append(f"\n[Change History] Could not persist undo session: {exc}\n")

        for path, data in pending_changes.items():
            action = data["action"]
            if action == "create":
                self.last_applied_backup[path] = {"action": "create"}
                try:
                    Path(path).parent.mkdir(parents=True, exist_ok=True)
                    Path(path).write_text(data["current"], encoding="utf-8")
                    changed_paths.append(path)
                    report_changes.append(
                        {
                            "path": path,
                            "action": "create",
                            "before": "",
                            "after": data.get("current") or "",
                            "summary": "Created a new file from the accepted AI diff.",
                        }
                    )
                except Exception as e:
                    QMessageBox.critical(
                        self, "Create Failed", f"Could not create file {path}:\n{e}"
                    )
            elif action == "modify":
                ok, content = self.service.read_file(path)
                before_content = content if ok else data.get("original") or data.get("previous") or ""
                if ok:
                    self.last_applied_backup[path] = {
                        "action": "modify",
                        "content": content,
                    }
                try:
                    Path(path).write_text(data["current"], encoding="utf-8")
                    changed_paths.append(path)
                    report_changes.append(
                        {
                            "path": path,
                            "action": "modify",
                            "before": before_content,
                            "after": data.get("current") or "",
                            "summary": "Accepted and wrote the reviewed diff.",
                        }
                    )
                except Exception as e:
                    QMessageBox.critical(
                        self, "Modify Failed", f"Could not modify file {path}:\n{e}"
                    )

        self.refresh_project_tree_fast()
        self.build_index()
        self.refresh_open_editors_after_diff(changed_paths)

        self.editor_diff_widget.setVisible(False)
        self.normal_editor_widget.setVisible(True)
        try:
            from tech_connector.services.chat_report_service import format_code_change_report
            from tech_connector.services.project_edit_agent_service import validate_project_edit_paths

            validation = ["Project tree refreshed.", "Knowledge index refresh queued."]
            for item in validate_project_edit_paths(changed_paths):
                label = "passed" if item.get("ok") else "failed"
                validation.append(
                    f"{label}: `{item.get('command')}` - {item.get('message')}"
                )
            if saved_change_session_path:
                validation.append(f"Undo session saved: `{saved_change_session_path}`")
            report = format_code_change_report(
                report_changes,
                title="Code Changes Applied",
                validation=validation,
            )
            self.append(f"\nASSISTANT [Code Change Report]:\n{report}\n")
        except Exception:
            self.append(
                "\n[Status] Code changes applied successfully. Click 'Undo Last Change' at the top of the Chat if you need to rollback.\n"
            )

    def open_file_at_line(self, path: str, line: int = 1):
        self.workspace_tabs.setCurrentIndex(1)
        self.open_code_file(path)
        try:
            self.code_editor.goto_line(max(1, int(line or 1)))
            self.update_cursor_status()
        except Exception:
            pass

    def handle_diff_cancelled(self):
        self.editor_diff_widget.setVisible(False)
        self.normal_editor_widget.setVisible(True)
        self.append("\n[Status] Code changes discarded.\n")

    def handle_editor_diff_repair_requested(self, change):
        """Queue a focused preview repair for one rejected change.

        :param change: Selected diff data and validation evidence.
        """

        path = str((change or {}).get("path") or "").strip()
        evidence = [
            str(item)
            for item in list((change or {}).get("validation_evidence") or [])
            if str(item).strip()
        ]
        if not path:
            return
        request = (
            f"Repair only the proposed change for {path}. Preserve its approved intent and unrelated code. "
            "Return a new reviewable preview; do not apply files."
        )
        if evidence:
            request += "\n\nValidation evidence to fix:\n- " + "\n- ".join(evidence[:12])
        if hasattr(self, "code_prompt_mode_box"):
            index = self.code_prompt_mode_box.findData("edit")
            if index >= 0:
                self.code_prompt_mode_box.setCurrentIndex(index)
        if hasattr(self, "code_prompt_permission_box"):
            index = self.code_prompt_permission_box.findData("preview")
            if index >= 0:
                self.code_prompt_permission_box.setCurrentIndex(index)
        self.input.setText(request)
        self.set_live_process(f"Focused repair queued: {Path(path).name}")
        QTimer.singleShot(0, self.send_message)

    def refresh_open_editors_after_diff(self, paths):
        focused_path = ""
        for path in paths:
            resolved = str(Path(path).resolve())
            ok, content = self.service.read_file(resolved)
            if not ok:
                continue

            editor = self.open_editors.get(resolved)
            if editor:
                editor.blockSignals(True)
                editor.setPlainText(content)
                editor.blockSignals(False)
                editor.document().setModified(False)
                focused_path = focused_path or resolved
                continue

            if Path(resolved).exists() and is_supported_code_file(Path(resolved)):
                focused_path = focused_path or resolved

        if focused_path:
            self.open_code_file(focused_path)
        self.update_cursor_status()

    def _format_chat_block(self, header, content):
        """Format a single live/streaming chat block using the shared renderer."""
        try:
            from tech_connector.ui.chat_renderer import format_message
            return format_message(self, header or "ASSISTANT", content or "")
        except Exception:
            import html as html_module
            return (
                "<div class='assistant-card'>"
                f"<pre>{html_module.escape(content or '')}</pre>"
                "</div>"
            )

    def _format_system_block(self, text):
        try:
            from tech_connector.ui.chat_renderer import format_status
            return format_status(text or "")
        except Exception:
            import html as html_module
            return f"<div class='status-chip'>{html_module.escape(text or '')}</div>"

    def _format_status_block(self, text):
        try:
            from tech_connector.ui.chat_renderer import format_status
            return format_status(text or "")
        except Exception:
            import html as html_module
            return f"<div class='status-chip'>{html_module.escape(text or '')}</div>"

    def extract_code_blocks(self, text):
        for m in re.finditer(r"```([A-Za-z0-9_+.-]*)\n(.*?)```", text, re.DOTALL):
            lang = m.group(1) or "text"
            code = m.group(2).strip()
            if not code:
                continue
            key = (lang, code)
            if key in self.code_snippets:
                continue
            self.code_snippets.append(key)
            preview = code.splitlines()[0] if code.splitlines() else code[:70]
            self.code_list.addItem(
                f"{len(self.code_snippets)}. {lang} - {preview[:70]}"
            )

    def copy_selected_code(self):
        item = self.code_list.currentItem()
        if not item:
            return
        idx = self.code_list.row(item)
        if 0 <= idx < len(self.code_snippets):
            QGuiApplication.clipboard().setText(self.code_snippets[idx][1])
            self.append(f"\n[Copied code snippet {idx + 1}.]\n")

    def copy_last_prompt(self):
        QGuiApplication.clipboard().setText(self.last_user_prompt or "")
        self.append("\n[Copied last prompt.]\n")

    def copy_last_response(self):
        QGuiApplication.clipboard().setText(
            self.last_assistant_output or self.last_tool_output or ""
        )
        self.append("\n[Copied last response/output.]\n")

    def _set_current_chat_response_from_copy_index(self, copy_index: int) -> bool:
        try:
            for idx, item in enumerate(getattr(self, "chat_response_anchors", []) or []):
                if int(item.get("copy_index", -1)) == int(copy_index):
                    self._chat_current_response_index = idx
                    return True
        except Exception:
            pass
        return False

    def navigate_chat_response(self, direction: int):
        anchors = list(getattr(self, "chat_response_anchors", []) or [])
        if not anchors or not hasattr(self, "log"):
            return
        current = getattr(self, "_chat_current_response_index", None)
        if current is None:
            current = 0 if direction >= 0 else len(anchors) - 1
        else:
            current = max(0, min(len(anchors) - 1, int(current) + (1 if direction >= 0 else -1)))
        self._chat_current_response_index = current
        anchor = str(anchors[current].get("anchor") or "")
        if anchor:
            self.log.scrollToAnchor(anchor)
        self._chat_render_pending_bottom = False

    def copy_current_chat_response(self):
        anchors = list(getattr(self, "chat_response_anchors", []) or [])
        if not anchors:
            self.copy_last_response()
            return
        current = getattr(self, "_chat_current_response_index", None)
        if current is None:
            current = len(anchors) - 1
        current = max(0, min(len(anchors) - 1, int(current)))
        self._chat_current_response_index = current
        copy_index = int(anchors[current].get("copy_index", -1))
        if 0 <= copy_index < len(getattr(self, "chat_copy_blocks", []) or []):
            QGuiApplication.clipboard().setText(self.chat_copy_blocks[copy_index])
            self.append(f"\n[Status] Copied response {current + 1} to clipboard.\n")

    def copy_full_log(self):
        transcript = self._canonical_thread_transcript()
        if not transcript.strip():
            transcript = str(getattr(self, "chat_history_raw", "") or "")
        QGuiApplication.clipboard().setText(transcript)
        self.append("\n[Copied full log.]\n")

    def health_check(self):
        msg = self.service.get_health_check()
        self.append("\n" + msg + "\n")

    def check_mcphost_startup_visibility(self):
        if not self.bridge.running:
            return
        if not self.mcphost_ready:
            self.set_card("mcphost", "warn", "Running, readiness unknown")
            if self.mcphost_use_pty:
                self.append(
                    "\n[Status] MCPHost is running in PTY mode, but the ready marker was not detected yet. "
                    "Wait a little longer, or check the visible terminal output above.\n"
                )
            else:
                self.append(
                    "\n[Status] MCPHost process is running, but no ready prompt/tool-load output was detected yet. "
                    "Pipe mode can be quiet with MCPHost's terminal UI. Turn on 'Use PTY' before starting MCPHost "
                    "for visible terminal output.\n"
                )

    def send_with_timeout_notice(self, text, label):
        self.send_raw(text, label)

    def pending_response_notice(self, label):
        running = bool(getattr(self.bridge, "running", False))
        if hasattr(self, "mcphost_manager") and label != "main":
            try:
                running = self.mcphost_manager.get_session(label).bridge.running
            except Exception:
                pass
        if running and label in self._response_started_at_by_role:
            # The progress observer owns user-facing liveness. Keep this timer
            # silent so it cannot create a second repeating wait message.
            self._note_prompt_progress_event("Waiting for model response", label)

    def _queue_terminal_output(self, role: str, raw: str):
        role = role or "main"
        if not raw:
            return
        buffers = getattr(self, "_raw_terminal_buffer_by_role", {})
        buffers[role] = buffers.get(role, "") + raw
        self._raw_terminal_buffer_by_role = buffers
        pending = getattr(self, "_raw_terminal_flush_pending", set())
        if role not in pending:
            pending.add(role)
            self._raw_terminal_flush_pending = pending
            QTimer.singleShot(90, lambda r=role: self._flush_terminal_output(r))

    def _flush_terminal_output(self, role: str):
        role = role or "main"
        pending = getattr(self, "_raw_terminal_flush_pending", set())
        pending.discard(role)
        self._raw_terminal_flush_pending = pending
        raw = (getattr(self, "_raw_terminal_buffer_by_role", {}) or {}).get(role, "")
        if not raw:
            return
        max_chars = int(getattr(self, "settings", {}).get("terminal_output_process_chunk_chars", 24000) or 24000)
        chunk = raw[:max_chars]
        remainder = raw[max_chars:]
        self._raw_terminal_buffer_by_role[role] = remainder
        started = time.perf_counter()
        if role == "main":
            self._process_main_terminal_output(chunk)
        else:
            self._process_role_terminal_output(role, chunk)
        duration_ms = int((time.perf_counter() - started) * 1000)
        if duration_ms >= 200 or self._ui_diagnostic_enabled():
            self._log_ui_diagnostic(
                "terminal_output_processed",
                role=role,
                duration_ms=duration_ms,
                chunk_chars=len(chunk),
                remaining_chars=len(remainder),
            )
        if remainder:
            pending.add(role)
            self._raw_terminal_flush_pending = pending
            QTimer.singleShot(30, lambda r=role: self._flush_terminal_output(r))

    def handle_output(self, data):
        self._queue_terminal_output("main", data or "")

    def _process_main_terminal_output(self, raw):
        if raw.strip():
            self.set_card("service", "busy", "Streaming output")

        # Scan raw for status
        for line in raw.splitlines():
            line_str = ANSI_RE.sub("", line).strip()
            line_str = re.sub(r"[\x00-\x1f]", "", line_str)
            if "Loading Ollama model" in line_str:
                self.set_live_process("Loading model")
                self.append_status_once("Loading Ollama model...")
            elif "Thinking" in line_str:
                self.set_live_process("Thinking")
                self.append_status_once("Thinking...")
            elif "Executing " in line_str:
                m = re.search(r"Executing\s+([\w_]+)", line_str, re.IGNORECASE)
                if m:
                    self.set_live_process(f"Calling tool {m.group(1)}")
                    self.append_status_once(f"Executing tool {m.group(1)}...")
                else:
                    self.set_live_process("Calling tool")
                    self.append_status_once(line_str)

        cleaned = self.output_cleaner.clean(raw)

        if (
                is_credit_or_quota_failure(raw)
                and self.settings.get("model_source_mode") == "auto_with_local_fallback"
        ):
            metadata = self._pending_response_metadata_by_role.get("main")
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

        if "subprocess pipe active" in raw:
            self.set_card("mcphost", "busy", "Process active")
        if "PTY active" in raw:
            self.set_card("mcphost", "busy", "PTY active")
        if "Loading Ollama model" in raw:
            self.set_card("ollama", "busy", "Loading")
        if "[Ollama Status] Active model:" in raw:
            m = re.search(r"\[Ollama Status\] Active model:\s*(.*)", raw)
            if m:
                self.set_card("ollama", "ok", m.group(1).strip())
        if "Model loaded:" in raw:
            self.set_ollama_card_for_model("ok", self.selected_mcphost_model())
        if "Model loaded successfully on GPU" in raw:
            self.set_card("ollama", "ok", "GPU loaded")
        m_tools = re.search(r"Loaded\s+(\d+)\s+tools", raw, re.IGNORECASE)
        if m_tools:
            self.mcphost_ready = True
            self.set_card("mcphost", "ok", f"Ready ({m_tools.group(1)} tools)")
            self.set_ollama_card_for_model("ok", self.selected_mcphost_model())
        if "tools from MCP servers" in raw:
            self.mcphost_ready = True
            m = re.search(r"Loaded\s+(\d+)\s+tools", raw)
            self.set_card(
                "mcphost", "ok", f"Ready ({m.group(1)} tools)" if m else "Ready"
            )
        if (
                "Enter your prompt" in raw
                or "Type your message" in raw
                or "Model loaded" in raw
        ):
            self.mcphost_ready = True
            self.set_ollama_card_for_model("ok", self.selected_mcphost_model())
            if "ok" not in self.status_cards["mcphost"].styleSheet():
                self.set_card("mcphost", "ok", "Ready")
        if "maya__" in raw or "Maya" in raw:
            if "Failed to load MCP server 'maya'" in raw:
                self.set_card("maya", "bad", "MCP failed")
            elif "maya__" in raw:
                self.set_card("maya", "busy", "Tool activity")
        if "Goodbye!" in raw:
            self.set_card("mcphost", "bad", "Exited after input")
            self.append(
                "\n[Status] MCPHost printed Goodbye after input. This usually means the terminal UI interpreted "
                "the programmatic input as a quit/EOF event. v5.2 sends prompts using bracketed paste to avoid this. "
                "If it still happens, the next step is direct model/tool orchestration instead of driving MCPHost's TUI.\n"
            )
        if "motionbuilder" in raw.lower():
            if "failed" in raw.lower():
                self.set_card("motionbuilder", "warn", "Optional / unavailable")
            else:
                self.set_card("motionbuilder", "busy", "Tool activity")

        response_active = bool(
            getattr(self, "_response_started_at_by_role", {}) or {}
        )
        startup_only_lines = {
            "[subprocess pipe active]",
            "[pty active]",
            "mcphost ready for input.",
        }
        cleaned_lines = [
            line.strip().lower()
            for line in cleaned.splitlines()
            if line.strip()
        ]
        if cleaned and not response_active and all(
            line in startup_only_lines
            or "loaded" in line and "tools from mcp servers" in line
            or line.startswith("model loaded")
            for line in cleaned_lines
        ):
            if any("ready" in line or "tools from mcp servers" in line for line in cleaned_lines):
                self.mcphost_ready = True
                if "ok" not in self.status_cards["mcphost"].styleSheet():
                    self.set_card("mcphost", "ok", "Ready")
            return

        if cleaned:
            self.set_live_process("Streaming response")
            self.mcphost_ready = True
            if "ok" not in self.status_cards["mcphost"].styleSheet():
                self.set_card("mcphost", "ok", "Ready")
            self.last_assistant_output = cleaned
            self.service.last_assistant_output = cleaned
            self._queue_stream_output("main", cleaned)
            self.current_session.append(
                {
                    "role": "assistant_or_tool_output",
                    "content": cleaned,
                    "metadata": self._pending_response_metadata_by_role.get("main"),
                }
            )

    def on_finished(self, msg="MCPHost exited."):
        self._stop_prompt_progress_observer("main")
        self._clear_active_response_addendum_state("main")
        self.set_card("mcphost", "off", "Exited")
        set_status_state(self.status, "error", "Exited")
        self.append(f"\n=== {msg} ===\n")

    def start_mcphost(self):
        if self.bridge.running:
            return
        self.last_chat_activity_time = time.time()
        self.ollama_is_idle = False
        model = self.selected_mcphost_model()
        config = self.config_box.currentText().strip()
        use_pty = self.use_pty_checkbox.isChecked()
        self.output_cleaner.reset()
        self.mcphost_started_at = time.time()
        self.mcphost_ready = False
        self.mcphost_use_pty = use_pty
        self.set_card("mcphost", "busy", "Starting")
        if provider_for_model(model) == "ollama":
            self.set_card("ollama", "busy", "Loading model")
        else:
            self.set_card("ollama", "off", "Cloud selected")

        ok, cmd_display, error = self.service.start_mcphost(model, config, use_pty)
        if not ok:
            if error == "Already running":
                return
            QMessageBox.critical(self, "Start failed", error)
            self.set_card("mcphost", "bad", "Start failed")
            return

        set_status_state(self.status, "ok", "Running")

        if not use_pty:
            self.mcphost_ready = True
            self.set_card("mcphost", "ok", "Ready")
            self.set_ollama_card_for_model("ok", model)

        QTimer.singleShot(15000, self.check_mcphost_startup_visibility)

    def stop_mcphost(self):
        self.bridge.stop()
        if hasattr(self, 'mcphost_manager'):
            self.mcphost_manager.stop_all()
        self.set_card('mcphost', 'off', 'Stopped')
        set_status_state(self.status, "error", "Stopped")

    def cancel_active_query(self):
        for role in list(getattr(self, "_prompt_progress_observers", {}) or {}):
            self._stop_prompt_progress_observer(role)
        if self.bridge.running:
            self.service.interrupt_mcphost()
        if hasattr(self, "mcphost_manager"):
            for role in ["plan", "code", "dcc"]:
                session = self.mcphost_manager.get_session(role)
                if session.running:
                    session.bridge.interrupt()

        # Terminate active Editor Assist background threads immediately
        if (
                hasattr(self, "editor_assist_worker")
                and self.editor_assist_worker
                and self.editor_assist_worker.isRunning()
        ):
            try:
                self.editor_assist_worker.terminate()
                self.editor_assist_worker.wait(1000)
                self.editor_assist_worker = None
                if hasattr(self, "_stop_editor_assist_progress"):
                    self._stop_editor_assist_progress()
                self.append("\n[Status] Cancelled active Editor Assist generation.\n")
            except Exception as e:
                print(f"Error cancelling editor worker: {e}")

        self.append(
            "\n[Status] Sent cancel/interrupt signal to active query processes.\n"
        )

    def prestart_core_mcphost_sessions(self):
        if bool(self.settings.get("ollama_lazy_start", True)):
            self.append("\n[Status] Lazy model start is enabled; core model sessions will start on first use.\n")
            return
        config = self.config_box.currentText().strip()
        use_pty = self.use_pty_checkbox.isChecked()

        for role in ["plan", "code"]:
            session = self.mcphost_manager.get_session(role)

            if not getattr(session, "_ui_signals_connected", False):
                session.bridge.output.connect(
                    lambda data, r=role: self.handle_session_output(r, data)
                )
                session.bridge.exited.connect(
                    lambda msg, r=role: self.handle_session_finished(r, msg)
                )
                session._ui_signals_connected = True

            if session.bridge.running:
                continue

            ok, cmd_display, error = self.mcphost_manager.start_session(
                role, config, use_pty
            )

            if ok:
                self.append(
                    f"\n=== Prestarted {role} MCPHost session ===\n{cmd_display}\n\n"
                )
            else:
                self.append(f"\n[Prestart failed: {role}] {error}\n")

    def _append_runtime_error(self, title: str, exc: BaseException) -> None:
        """Show traceback detail only for real errors."""
        import traceback

        detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).strip()
        self.append(
            f"\nASSISTANT [Error]:\n{title}: {exc}\n\n"
            f"```text\n{detail}\n```\n"
        )

    def set_live_process(self, text):
        raw_message = (text or "").strip()
        if not raw_message:
            return

        try:
            from tech_connector.services.prompt.prompt_progress_service import narrate_progress_message
            message = narrate_progress_message(
                raw_message,
                getattr(self, "_active_reasoning_narration", None),
            )
        except Exception:
            message = raw_message

        # Empty narration means internal plumbing. Keep it out of the normal
        # thread while retaining it for diagnostics and developer activity.
        if not message:
            self._note_prompt_progress_event(raw_message, raw_message=raw_message)
            return

        self._note_prompt_progress_event(message, raw_message=raw_message)

        try:
            app = QApplication.instance()
            if app is not None and QThread.currentThread() != app.thread():
                if hasattr(self, "live_process_update"):
                    self.live_process_update.emit(message)
                    return
        except Exception:
            pass

        now = time.time()
        is_context_change = message.startswith("Context changed:")
        if not is_context_change and not getattr(self, "_live_work_started_at", None):
            self._live_work_started_at = now
        self.set_card("service", "busy", message[:100])
        if hasattr(self, "live_process_label"):
            self.live_process_label.setText(f"Working: {message}")
        if (
            message == self._last_live_process
            and (now - self._last_live_process_at) < 1.5
        ):
            return
        self._last_live_process = message
        self._last_live_process_at = now
        # Normal progress belongs in the status area, not as a stream of
        # implementation jargon in the conversation.  Add only occasional,
        # genuinely useful human updates to chat.
        last_chat_at = float(getattr(self, "_last_human_progress_chat_at", 0.0) or 0.0)
        human_milestone = any(
            token in message.lower()
            for token in (
                "found ", "comparing", "checking that", "needs input",
                "ready", "failed", "could not", "validation found",
            )
        )
        if human_milestone and now - last_chat_at >= 12.0:
            self._last_human_progress_chat_at = now
            self.append(f"\nASSISTANT [Update]:\n{message.rstrip('.')} .\n".replace(" .", "."))


    def show_activity_details_enabled(self) -> bool:
        """Whether observable engine activity should be shown in the chat thread."""
        try:
            widget = getattr(self, "show_activity_details_checkbox", None)
            if widget is not None:
                return bool(widget.isChecked())
        except Exception:
            pass
        try:
            return bool(self.settings.get("show_activity_details", False))
        except Exception:
            return False

    def set_ui_diagnostic_mode(self, enabled: bool):
        enabled = bool(enabled)
        self.settings["ui_diagnostic_mode"] = enabled
        try:
            self.service.settings["ui_diagnostic_mode"] = enabled
            self.service.save_settings()
        except Exception:
            pass
        self.append(f"\n[Diagnostics] UI diagnostic mode {'enabled' if enabled else 'disabled'}.\n")
        self._log_ui_diagnostic("diagnostic_mode_changed", diagnostic_enabled=enabled)

    def show_ui_diagnostic_report(self):
        try:
            from tech_connector.services.diagnostic_service import diagnostic_path, read_ui_diagnostics

            report = read_ui_diagnostics(limit=300)
            path = diagnostic_path()
        except Exception as exc:
            report = f"Could not read UI diagnostics: {exc}"
            path = ""
        dialog = QDialog(self)
        dialog.setWindowTitle("UI Diagnostic Report")
        dialog.resize(980, 720)
        layout = QVBoxLayout(dialog)
        title = QLabel("UI Diagnostic Report")
        title.setStyleSheet("font-weight:bold; color:#b9dcff;")
        layout.addWidget(title)
        if path:
            path_label = QLabel(str(path))
            path_label.setStyleSheet("color:#8fb9c9;")
            layout.addWidget(path_label)
        box = QPlainTextEdit()
        box.setReadOnly(True)
        box.setPlainText(report)
        box.setLineWrapMode(QPlainTextEdit.NoWrap)
        layout.addWidget(box, 1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)
        dialog.exec()

    def clear_ui_diagnostic_report(self):
        try:
            from tech_connector.services.diagnostic_service import clear_ui_diagnostics

            clear_ui_diagnostics()
            self.append("\n[Diagnostics] UI diagnostic report cleared.\n")
        except Exception as exc:
            self.append(f"\n[Diagnostics] Could not clear UI diagnostic report: {exc}\n")

    def handle_engine_activity(self, event):
        """Keep engine objects out of chat; surface only human milestones and errors."""
        try:
            from tech_connector.services.prompt.prompt_progress_service import narrate_activity_event

            narrated = narrate_activity_event(
                event,
                getattr(self, "_active_reasoning_narration", None),
            )
        except Exception:
            narrated = {"message": "", "debug_text": str(event)}

        message = str(narrated.get("message") or "").strip()
        status = str(getattr(event, "status", "") or "").lower()
        kind = str(getattr(event, "kind", "") or "").lower()
        metadata = getattr(event, "metadata", None) or {}

        if message and hasattr(self, "set_live_process"):
            self.set_live_process(message)

        # Structured ActivityEvent reprs are diagnostics, never assistant chat.
        self._log_ui_diagnostic(
            "engine_activity",
            activity_kind=kind,
            activity_status=status,
            activity_title=str(getattr(event, "title", "") or ""),
            activity_detail=str(getattr(event, "detail", "") or ""),
            activity_metadata=metadata,
        )

        if status not in {"error", "failed", "failure", "fatal"}:
            return

        title = str(getattr(event, "title", "") or "Request failed")
        detail = str(getattr(event, "detail", "") or message or "An unexpected error occurred.")
        trace = str(
            metadata.get("traceback")
            or metadata.get("stack_trace")
            or metadata.get("exception_traceback")
            or ""
        ).strip()
        error_text = f"{title}: {detail}"
        if trace:
            error_text += f"\n\n```text\n{trace}\n```"
        self.append(f"\nASSISTANT [Error]:\n{error_text}\n")

    def set_show_activity_details(self, enabled: bool):
        self.settings["show_activity_details"] = bool(enabled)
        try:
            self.service.settings["show_activity_details"] = bool(enabled)
            self.service.save_settings()
        except Exception:
            pass
        widget = getattr(self, "show_activity_details_checkbox", None)
        if widget is not None and widget.isChecked() != bool(enabled):
            widget.blockSignals(True)
            widget.setChecked(bool(enabled))
            widget.blockSignals(False)
        self.append(f"\n[Status] Activity details {'enabled' if enabled else 'disabled'}.\n")

    def send_raw(self, text, label="Prompt"):
        self.last_chat_activity_time = time.time()
        self.ollama_is_idle = False
        self.last_user_prompt = text
        self.service.last_user_prompt = text
        self.set_live_process(f"Preparing raw prompt: {label}")
        self.append(f"\nYOU [{label}]:\n{self._visible_prompt_text(text)}\n")
        active_model = resolve_model_for_policy(
            self.selected_mcphost_model(),
            as_mcphost_model(AI_MODELS["plan"]),
            self.settings,
        )
        route = SimpleNamespace(task_role="general", reason=f"Manual prompt: {label}")
        request_metadata = self.build_request_metadata(
            text,
            text,
            route,
            "main",
            active_model,
            fallback_used=active_model != self.selected_mcphost_model(),
        )
        self.current_session.append(
            {"role": "user", "content": text, "metadata": request_metadata}
        )
        self.store_request_metadata("main", request_metadata)
        self._mark_response_started("main")
        chatbot_module = self.settings.get("chatbot_provider_module", "default")
        if chatbot_module and chatbot_module != "default":
            def run_custom_chatbot():
                from tech_connector.services.modular_provider_utils import invoke_custom_provider, resolve_custom_provider_binding
                def append_chunk(chunk):
                    from PySide6.QtCore import QTimer
                    from PySide6.QtWidgets import QApplication
                    if QApplication.instance() is not None:
                        QTimer.singleShot(0, lambda: self.append(chunk))
                    else:
                        self.append(chunk)
                try:
                    history_list = []
                    for msg in self.current_session:
                        history_list.append({"role": msg.get("role"), "content": msg.get("content")})
                    def generate_chat_response(*args, **kwargs):
                        pass

                    invoke_custom_provider(
                        resolve_custom_provider_binding("chatbot_module", chatbot_module, "generate_chat_response", self.settings),
                        generate_chat_response,
                        text,
                        history_list,
                        append_chunk
                    )
                except Exception as e:
                    append_chunk("\n[Custom Chatbot Error]: " + str(e) + "\n")
            import threading
            threading.Thread(target=run_custom_chatbot, daemon=True).start()
            return

        if not bool(getattr(self.bridge, "running", False)):
            self.set_live_process("Starting model session")
            self.start_mcphost()

        def send_main_prompt_background() -> None:
            started = time.perf_counter()
            try:
                running = bool(getattr(self.bridge, "running", False))
                mode = getattr(self.bridge, "mode", "") if running else ""
                if running and self.bridge.write(text):
                    if str(mode).lower() == "pty":
                        self.thread_log_message.emit("[Sent to LLM via PTY. Waiting for assistant/tool output...]\n")
                    else:
                        self.thread_log_message.emit("[Sent to LLM. Waiting for assistant/tool output...]\n")
                    self.response_started.emit("main")
                    self.live_process_update.emit("Waiting for model response")
                    self._log_ui_diagnostic(
                        "raw_prompt_send_complete",
                        prompt_chars=len(text or ""),
                        route_label=str(label),
                        mode=str(mode),
                        elapsed_ms=int((time.perf_counter() - started) * 1000),
                    )
                else:
                    self.thread_log_message.emit(
                        "\n[Send failed: MCPHost is not running or input stream is unavailable.]\n"
                    )
            except Exception as exc:
                self.thread_log_message.emit(
                    f"\n[Send failed: MCPHost stream write failed: {exc}]\n"
                )
                self.live_process_update.emit("Prompt send failed")

        import threading

        threading.Thread(target=send_main_prompt_background, daemon=True).start()


    def _emit_unreal_milestone(self, message: str):
        """Append honest Unreal planning status without exposing hidden reasoning."""
        try:
            self.set_live_process(message)
        except Exception:
            pass
        try:
            self.append(f"[Unreal Planning] {message}\n")
        except Exception:
            pass

    def _resolve_unreal_project_root(self):
        try:
            roots = self.project_roots() if hasattr(self, "project_roots") else []
            if roots:
                return roots[0]
        except Exception:
            pass
        try:
            value = (getattr(self, "settings", {}) or {}).get("unreal_project_root")
            if value:
                return value
        except Exception:
            pass
        return None

    def _get_project_intelligence_service(self, project_root=None):
        """Return the shared ProjectIntelligenceService used by the UI and Unreal planner."""
        root = project_root or self._resolve_unreal_project_root()
        existing = getattr(self, "intel_service", None)
        if existing is not None:
            try:
                if root and not getattr(existing, "project_root", None):
                    existing.project_root = root
                return existing
            except Exception:
                return existing
        try:
            from tech_connector.services.project_service import ProjectIntelligenceService
            service = ProjectIntelligenceService(project_root=root, auto_start=True)
            self.intel_service = service
            return service
        except Exception as exc:
            self.append(f"[UnrealContext] Project Intelligence unavailable: {exc}\n")
            return None

    def _request_unreal_project_intelligence_context(self, request_text: str, *, mode: str = "quick", max_tokens: int = 4000):
        """Fetch warm daemon context. Returns None so the caller can direct-scan fallback."""
        root = self._resolve_unreal_project_root()
        service = self._get_project_intelligence_service(root)
        if service is None:
            return None
        timeout_seconds = float((getattr(self, "settings", {}) or {}).get("project_intelligence_context_timeout_seconds", 5.0) or 5.0)

        def call_with_timeout(label, func, fallback=None):
            import concurrent.futures

            started = time.perf_counter()
            executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"tc-{label}")
            future = executor.submit(func)
            try:
                result = future.result(timeout=timeout_seconds)
                self._log_ui_diagnostic(
                    "project_intelligence_call_finished",
                    label=label,
                    duration_ms=int((time.perf_counter() - started) * 1000),
                )
                return result
            except concurrent.futures.TimeoutError:
                future.cancel()
                self._log_ui_diagnostic(
                    "project_intelligence_call_timed_out",
                    label=label,
                    timeout_seconds=timeout_seconds,
                )
                self._emit_unreal_milestone(f"Project Intelligence {label} timed out; using cached/quick context")
                return fallback
            finally:
                try:
                    executor.shutdown(wait=False, cancel_futures=True)
                except TypeError:
                    executor.shutdown(wait=False)

        try:
            self._emit_unreal_milestone("Checking Project Intelligence daemon")
            ok, message = call_with_timeout(
                "ensure_running",
                lambda: service.ensure_running(root) if hasattr(service, "ensure_running") else (service.is_daemon_running(), ""),
                fallback=(False, "Project Intelligence daemon check timed out"),
            )
            if not ok:
                self.append(f"[UnrealContext] Project Intelligence daemon unavailable: {message}\n")
                return None
            self._emit_unreal_milestone("Gathering warm Unreal context")
            return call_with_timeout(
                "get_context",
                lambda: service.get_context(
                    prompt=request_text or "unreal request",
                    mode=mode,
                    max_tokens=max_tokens,
                    project_root=root,
                ),
                fallback=None,
            )
        except TypeError:
            try:
                return call_with_timeout(
                    "get_context_legacy",
                    lambda: service.get_context(
                        prompt=request_text or "unreal request",
                        mode=mode,
                        max_tokens=max_tokens,
                    ),
                    fallback=None,
                )
            except Exception as exc:
                self.append(f"[UnrealContext] daemon context unavailable; using direct scanner: {exc}\n")
                return None
        except Exception as exc:
            self.append(f"[UnrealContext] daemon context unavailable; using direct scanner: {exc}\n")
    def _adaptive_goal_state_for_request(self, text: str, decision=None, *, role: str = "main"):
        """Create or restore the goal-driven execution state for a routed request."""
        from tech_connector.services.adaptive.execution_state import AdaptiveExecutionState

        if not hasattr(self, "_adaptive_execution_states_by_role"):
            self._adaptive_execution_states_by_role = {}
        decision_data = (
            decision.to_dict()
            if hasattr(decision, "to_dict")
            else dict(decision or {})
        )
        state = AdaptiveExecutionState.from_route_decision(
            text,
            decision_data,
            active_file=str(getattr(self, "current_file_path", "") or ""),
            project_roots=self.project_roots() if hasattr(self, "project_roots") else (),
            operation_memory=getattr(self, "_active_operation_memory", None),
        )
        execution_context = dict(
            decision_data.get("execution_context")
            or decision_data.get("prompt_execution_context")
            or getattr(self, "_last_prompt_execution_context", {})
            or {}
        )
        graph = (
            decision_data.get("goal_graph")
            or decision_data.get("task_graph")
            or execution_context.get("goal_graph")
            or execution_context.get("task_graph")
            or []
        )
        state.set_goal_graph(graph)

        # Understanding/formulation goals have already been completed by the
        # canonical execution-context builder. Do not send those administrative
        # goals back to the model as if they were user deliverables. Prime them
        # from the context and advance to the first goal that can produce useful
        # evidence or the requested result.
        execution_snapshot = execution_context or decision_data
        precomputed_actions = {"understand", "normalize", "resolve", "formulate", "classify"}
        while True:
            ready = state.next_executable_goal()
            if ready is None:
                break
            action = str(ready.get("action") or "").strip().lower()
            capability = str(ready.get("capability") or "").strip().lower()
            goal_id = str(ready.get("goal_id") or ready.get("task_id") or "")
            if action not in precomputed_actions and capability not in {"understanding", "problem_formulation", "semantic_contract"}:
                state.current_goal_id = ""
                break
            state.commit_goal_result(
                {
                    "status": "already_available",
                    "source": "prompt_execution_context",
                    "understanding": execution_snapshot.get("understanding") or execution_snapshot.get("request_understanding") or {},
                    "problem_formulation": execution_snapshot.get("problem_formulation") or {},
                    "semantic_contract": execution_snapshot.get("semantic_contract") or execution_snapshot.get("semantic_execution_contract") or {},
                },
                goal=ready,
                validated=True,
                validation={"kind": "canonical_context_available", "valid": True},
            )
        state.artifacts["route_decision"] = decision_data
        state.artifacts["prompt_execution_context"] = execution_context
        self._adaptive_execution_states_by_role[role or "main"] = state
        return state

    def _adaptive_goal_state(self, role: str = "main"):
        return (getattr(self, "_adaptive_execution_states_by_role", {}) or {}).get(role or "main")

    def _build_adaptive_goal_prompt(self, state, goal: dict, *, task_role: str = "") -> str:
        """Build a compact prompt for one executable goal, not the full request graph."""
        goal_id = str(goal.get("goal_id") or goal.get("id") or "current")
        objective = str(
            goal.get("objective")
            or goal.get("goal")
            or goal.get("label")
            or "Complete the current goal."
        ).strip()
        success = str(
            goal.get("success_condition")
            or goal.get("success")
            or "Return a concrete result that directly satisfies this goal."
        ).strip()
        dependencies = state.dependency_outputs(goal)
        lines = [
            "CURRENT EXECUTABLE GOAL",
            f"Goal ID: {goal_id}",
            f"Objective: {objective}",
            f"Success condition: {success}",
            "",
            "ORIGINAL USER OUTCOME",
            str(state.original_prompt or "").strip(),
        ]
        if state.active_file:
            lines.extend(["", "RESOLVED ACTIVE FILE", state.active_file])
        if dependencies:
            lines.extend(["", "COMPLETED DEPENDENCY OUTPUTS"])
            for dependency_id, record in dependencies.items():
                result = record.get("result") if isinstance(record, dict) else record
                text = str(result or "").strip()
                if text:
                    lines.append(f"[{dependency_id}]\n{text[:5000]}")
        relevant_evidence = list(getattr(state, "evidence", []) or [])[-8:]
        if relevant_evidence:
            lines.extend(["", "RELEVANT EVIDENCE"])
            for item in relevant_evidence:
                data = item.to_dict() if hasattr(item, "to_dict") else item
                if isinstance(data, dict):
                    lines.append(f"- {data.get('source') or data.get('kind') or 'evidence'}: {data.get('summary') or data}")
                else:
                    lines.append(f"- {data}")
        validation_failures = list(state.artifacts.get("last_goal_validation_failures") or [])
        if validation_failures:
            lines.extend(["", "FAILURES FROM THE PREVIOUS ATTEMPT"])
            lines.extend(f"- {item}" for item in validation_failures[:12])
            lines.append("Repair every failure before returning the goal result again.")
        lines.extend([
            "",
            "EXECUTION RULES",
            "Work only on this goal.",
            "Use completed dependency outputs instead of repeating earlier work.",
            "Return the concrete result, code, patch, decision, or evidence requested by this goal.",
            "Do not return progress narration.",
            "If blocked, begin with BLOCKED: and state the exact missing information.",
        ])
        if self._ms_tutorial_mode():
            sections, remember_sections = self._tutorial_section_preferences(
                str(state.original_prompt or "")
            )
            if remember_sections:
                self._persist_tutorial_guidance_preferences(sections)
            lines.append("")
            lines.extend(
                self._tutorial_premium_contract(
                    str(state.original_prompt or ""),
                    sections=sections,
                ).splitlines()
            )
        prompt = "\n".join(lines)
        try:
            from tech_connector.services.source_policy import apply_source_policy
            prompt = apply_source_policy(prompt, self.settings)
        except Exception:
            pass
        return prompt

    def _tutorial_guidance_sections_defaults(self) -> set[str]:
        base_sections = {
            "understood",
            "approach",
            "now",
            "steps",
            "links",
            "references",
            "tools",
            "risks",
        }
        stored = dict((getattr(self, "settings", {}) or {}).get("tutorial_guidance_sections", {}) or {})
        if isinstance(stored, dict):
            explicit = {
                key
                for key in base_sections
                if bool(stored.get(key, key in base_sections))
            }
            return explicit or base_sections
        if isinstance(stored, (list, tuple, set)):
            selected = {str(key).strip().lower() for key in stored if str(key).strip().lower()}
            explicit = {key for key in base_sections if key in selected}
            if explicit:
                return explicit
        return base_sections

    def _tutorial_section_preferences(self, prompt: str) -> tuple[set[str], bool]:
        text = str(prompt or "").lower()
        sections = set(self._tutorial_guidance_sections_defaults())
        explicit_preference = False

        if (
            "just give me the step-by-step guidance" in text
            or "just step-by-step guidance" in text
            or "only step-by-step guidance" in text
            or "step-by-step guidance only" in text
        ):
            return {"steps"}, True

        if re.search(r"\b(no|don't|do not|without|omit|skip)\b[^\n.]*\b(file|files|workspace|knowledge|internal|links?)\b", text):
            sections.discard("links")
            explicit_preference = True
        if re.search(r"\b(no|don't|do not|without|omit|skip)\b[^\n.]*\b(external|official|github|reference|references|docs?)\b", text):
            sections.discard("references")
            explicit_preference = True
        if re.search(r"\b(no|don't|do not|without|omit|skip)\b[^\n.]*\b(tool\s+steps?|terminal\s+steps?|ui\s+steps?|tool actions?)\b", text):
            sections.discard("tools")
            explicit_preference = True
        if re.search(r"\b(no|don't|do not|without|omit|skip)\b[^\n.]*\b(risk|validation|checkpoint|checks)\b", text):
            sections.discard("risks")
            explicit_preference = True

        return sections, explicit_preference

    def _persist_tutorial_guidance_preferences(self, sections: set[str]) -> None:
        normalized = {
            "understood": "understood" in sections,
            "approach": "approach" in sections,
            "now": "now" in sections,
            "steps": "steps" in sections,
            "links": "links" in sections,
            "references": "references" in sections,
            "tools": "tools" in sections,
            "risks": "risks" in sections,
        }
        existing = (getattr(self, "settings", {}) or {}).get("tutorial_guidance_sections", {})
        if isinstance(existing, dict) and all(
            bool(existing.get(key, value)) == value for key, value in normalized.items()
        ):
            return
        try:
            self.settings["tutorial_guidance_sections"] = normalized
            if getattr(self, "service", None) is not None and hasattr(
                self.service, "settings"
            ):
                if isinstance(self.service.settings, dict):
                    self.service.settings["tutorial_guidance_sections"] = normalized
            if getattr(self, "service", None) is not None:
                self.service.save_settings()
        except Exception:
            pass

    def _tutorial_premium_contract(self, prompt: str, sections: set[str] | None = None) -> str:
        if sections is None:
            sections = set(self._tutorial_guidance_sections_defaults())
        lines = [
            "=== TUTORIAL / PREMIUM GUIDANCE MODE ===",
            "No code writes, no project mutations, and no live command execution.",
            "Deliver a premium practical guide with the requested sections below.",
        ]
        if "understood" in sections:
            lines.append("1) What I understood")
        if "approach" in sections:
            lines.append("2) How I will approach it")
        if "now" in sections:
            lines.append("3) What I am doing now")
        if "steps" in sections:
            lines.extend(
                [
                    "4) Step-by-step guidance",
                    "   4.1) Discovery and evidence collection",
                    "   4.2) API/extension-point selection",
                    "   4.3) Implementation sketch + snippets",
                    "   4.4) Validation + cleanup",
                ]
            )
        if "links" in sections:
            lines.extend(
                [
                    "5) File and knowledge links",
                    "   - Workspace files: use markdown links to absolute paths.",
                    "   - Internal docs/notes: use absolute-path markdown links.",
                ]
            )
        if "references" in sections:
            lines.extend(
                [
                    "6) External references",
                    "   - Official docs URLs.",
                    "   - GitHub links for comparable implementations.",
                ]
            )
        if "tools" in sections:
            lines.extend(
                [
                    "7) Tool actions",
                    "   - Concrete terminal / GUI steps to run next.",
                ]
            )
        if "risks" in sections:
            lines.extend(
                [
                    "8) Risks, validation checks, and next checkpoint",
                    "   - Include a concise checklist with expected pass/fail signals.",
                ]
            )
        return "\n".join(lines)

    def _prepare_adaptive_goal_prompt(self, text: str, route, decision=None, *, role: str = "main") -> str:
        """Prepare the first dependency-ready goal and retain state for continuation."""
        state = self._adaptive_goal_state_for_request(text, decision, role=role)
        goal = state.next_executable_goal()
        if goal is None:
            # No canonical graph means the request is genuinely atomic or a
            # legacy caller. Preserve compatibility with the existing assembler.
            return self.prepare_prompt_for_llm(text, task_role=getattr(route, "task_role", ""))
        attempt = state.begin_goal_attempt(goal)
        state.artifacts["active_role"] = role
        state.artifacts["active_goal_attempt"] = attempt
        self._note_prompt_progress_event(
            f"Working on {str(goal.get('objective') or goal.get('label') or 'the next step')}",
            role,
        )
        return self._build_adaptive_goal_prompt(
            state,
            goal,
            task_role=getattr(route, "task_role", ""),
        )

    def _adaptive_goal_result_valid(self, text: str, *, project_edit_preview=None) -> bool:
        value = str(text or "").strip()
        if len(value) < 8:
            return False
        if value.upper().startswith(("BLOCKED:", "ERROR:", "FAILED:")):
            return False
        if "<modify_file" in value or "<create_file" in value:
            return bool(project_edit_preview is not None and project_edit_preview.ok)
        return True

    def _commit_adaptive_goal_response(self, role: str, response_text: str, *, project_edit_preview=None) -> None:
        """Commit the finished goal and queue the next dependency-ready goal."""
        state = self._adaptive_goal_state(role)
        if state is None or not state.goal_graph:
            return
        goal = state.current_goal()
        if goal is None:
            return
        valid = self._adaptive_goal_result_valid(
            response_text,
            project_edit_preview=project_edit_preview,
        )
        quality_errors = list(getattr(project_edit_preview, "errors", None) or [])
        if valid:
            state.artifacts.pop("last_goal_validation_failures", None)
        elif quality_errors:
            state.artifacts["last_goal_validation_failures"] = quality_errors
        state.commit_goal_result(
            response_text,
            goal=goal,
            validated=valid,
            validation={
                "kind": "project_edit_quality" if project_edit_preview is not None else "response_presence",
                "valid": valid,
                "failures": quality_errors,
            },
        )
        if valid and state.goal_execution_complete():
            self._stop_prompt_progress_observer(role)
            self.set_live_process("Completed the requested work")
            return
        if not valid and not state.goal_retry_available(str(goal.get("goal_id") or "")):
            self._stop_prompt_progress_observer(role)
            self.append(
                "\nASSISTANT [Error]:\n"
                "The current step did not produce a usable result after the allowed attempts. "
                "The request was stopped instead of remaining stuck.\n"
            )
            return
        QTimer.singleShot(0, lambda r=role: self._send_next_adaptive_goal(r))

    def _send_next_adaptive_goal(self, role: str = "main") -> None:
        state = self._adaptive_goal_state(role)
        if state is None:
            return
        goal = state.next_executable_goal()
        if goal is None:
            self._stop_prompt_progress_observer(role)
            return
        state.begin_goal_attempt(goal)
        prompt = self._build_adaptive_goal_prompt(state, goal, task_role=state.host or "")
        objective = str(goal.get("objective") or goal.get("label") or "the next step")
        self.set_live_process(f"Working on {objective}")
        self._start_prompt_progress_observer(role, label=objective)
        self._note_prompt_progress_event(f"Working on {objective}", role)
        try:
            if role == "main":
                ok = bool(getattr(self.bridge, "running", False) and self.bridge.write(prompt))
                model = self.selected_mcphost_model()
            else:
                session = self.mcphost_manager.get_session(role)
                ok, _message = self.mcphost_manager.send(role, prompt)
                model = session.model
            if not ok:
                raise RuntimeError(f"The {role} model session did not accept the next goal.")
            route = SimpleNamespace(task_role=state.host or "general", reason="Goal execution continuation")
            metadata = self.build_request_metadata(
                state.original_prompt,
                prompt,
                route,
                role,
                model,
                fallback_used=False,
            )
            metadata["goal_id"] = str(goal.get("goal_id") or "")
            metadata["goal_attempt"] = int(state.goal_attempts.get(str(goal.get("goal_id") or ""), 1))
            self.store_request_metadata(role, metadata)
            self._mark_response_started(role)
        except Exception as exc:
            self._append_runtime_error("The next goal could not be started", exc)
            self._stop_prompt_progress_observer(role)

    def prepare_prompt_for_llm(self, text, task_role=""):
        self.set_live_process("Preparing prompt for LLM")
        original_text = text or ""
        from tech_connector.services.code_prompt_profile_service import (
            normalize_code_prompt_profile,
            render_code_prompt_contract,
        )

        code_profile = (
            self.code_prompt_profile()
            if hasattr(self, "code_prompt_profile")
            else normalize_code_prompt_profile(settings=self.settings)
        )
        try:
            from tech_connector.services.prompt.prompt_task_splitter_service import staged_prompt_for_llm

            staged_text, staged_contract = staged_prompt_for_llm(
                original_text,
                threshold=int(self.settings.get("long_prompt_stage_threshold", 2600) or 2600),
            )
            if staged_contract is not None:
                text = staged_text
                self._last_staged_prompt_contract = staged_contract
                self.set_live_process(f"Staged long prompt: {staged_contract.active_stage.title}")
                self._log_ui_diagnostic(
                    "long_prompt_staged",
                    original_chars=staged_contract.original_chars,
                    staged_chars=len(staged_text),
                    source_hash=staged_contract.source_hash,
                    active_stage=staged_contract.active_stage.key,
                    deferred_stages=[stage.key for stage in staged_contract.deferred_stages],
                )
                if hasattr(self, "thread_log_message"):
                    self.thread_log_message.emit(
                        "[Prompt Staging] Long request split into staged work. "
                        f"Sending {staged_contract.active_stage.title}; "
                        f"{len(staged_contract.deferred_stages)} later stage(s) held as deferred contract.\n"
                    )
            else:
                self._last_staged_prompt_contract = None
        except Exception as exc:
            self._log_ui_diagnostic("long_prompt_staging_failed", error=str(exc), prompt_chars=len(original_text))
        if hasattr(self.service, "prepare_prompt"):
            self.set_live_process("Applying source policy and project context")
            prepared = self.service.prepare_prompt(text)
        else:
            from tech_connector.services.source_policy import apply_source_policy

            self.set_live_process("Applying source policy")
            prepared = apply_source_policy(text, self.settings)

        # One compact request-level policy is authoritative. Domain packets add
        # evidence and techniques, but must not restate or expand permissions.
        prepared = render_code_prompt_contract(code_profile) + "\n\n" + prepared

        if self._ms_tutorial_mode():
            sections, remember_sections = self._tutorial_section_preferences(original_text)
            if remember_sections:
                self._persist_tutorial_guidance_preferences(sections)
            prepared = self._tutorial_premium_contract(
                original_text,
                sections=sections,
            ) + "\n\n" + prepared

        self.set_live_process("Checking connected-application context")
        dcc_context = self.command_router.build_dcc_tool_context(
            text, route_task_role=task_role
        )
        if dcc_context:
            prepared = f"{prepared}\n\n{dcc_context}"

        try:
            self.set_live_process("Applying studio decision profile")
            from tech_connector.services.studio_profile_service import studio_decision_profile_context

            studio_profile_context = studio_decision_profile_context(
                text or "",
                host=task_role or "",
            )
            if studio_profile_context:
                prepared = f"{prepared}\n\n{studio_profile_context}"
        except Exception:
            pass

        try:
            self.set_live_process("Planning capability gaps")
            from tech_connector.services.reasoning.goal_gap_planning_service import goal_gap_planning_context

            gap_context = goal_gap_planning_context(
                text or "",
                {
                    "host": task_role or "",
                    "route": task_role or "",
                    "provider": "dcc" if task_role else "",
                    "context_resolvers": ["thread_context", "project_context", "tool_context"],
                },
                max_chars=int(
                    self.settings.get(
                        "goal_gap_context_max_chars",
                        self.settings.get("goal_bridge_context_max_chars", 3000),
                    )
                    or 3000
                ),
            )
            if gap_context:
                prepared = f"{prepared}\n\n{gap_context}"
        except Exception:
            pass

        try:
            self.set_live_process("Building expert memory packet")
            from tech_connector.services.expert_memory_service import build_expert_memory_packet
            from tech_connector.services.task_playbook_service import thread_context_text

            try:
                roots = self.project_roots() if hasattr(self, "project_roots") else []
            except Exception:
                roots = []
            project_context = "\n".join(str(root) for root in roots[:4])
            packet = build_expert_memory_packet(
                text or "",
                {"host": task_role or "", "route": task_role or ""},
                settings=self.settings,
                host=task_role or "",
                thread_context=thread_context_text(getattr(self, "current_session", []) or []),
                project_context=project_context,
                tool_context=dcc_context,
                operation_memory=getattr(self, "_active_operation_memory", None),
                max_chars=int(self.settings.get("expert_memory_packet_max_chars", 3500) or 3500),
            )
            if packet:
                prepared = f"{prepared}\n\n{packet}"
        except Exception:
            pass

        try:
            self.set_live_process("Checking local task playbooks")
            from tech_connector.services.source_policy import live_sources_enabled
            from tech_connector.services.task_playbook_service import best_practices_context, thread_context_text

            try:
                roots = self.project_roots() if hasattr(self, "project_roots") else []
            except Exception:
                roots = []
            project_context = "\n".join(str(root) for root in roots[:4])
            allow_best_practice_research = (
                live_sources_enabled(self.settings)
                and bool(self.settings.get("research_best_practices", False))
            )
            playbook_context = best_practices_context(
                text or "",
                host=task_role or "",
                thread_context=thread_context_text(getattr(self, "current_session", []) or []),
                project_context=project_context,
                tool_context=dcc_context,
                allow_research=allow_best_practice_research,
            )
            if playbook_context and "KNOWN PRACTICES AND TECHNIQUES" not in dcc_context:
                prepared = f"{prepared}\n\n{playbook_context}"
        except Exception:
            pass

        active_dcc = self.command_router.get_active_dcc_context_cached()
        if active_dcc:
            prepared = f"{prepared}\n\n{active_dcc}"

        try:
            self.set_live_process("Checking AI memory and locked knowledge")
            from tech_connector.services.ai_work_memory_service import relevant_ai_work_context

            work_context = relevant_ai_work_context(
                self.settings,
                text or "",
                host=task_role or "",
                max_chars=int(
                    self.settings.get("ai_work_memory_max_context_chars", 6000)
                ),
            )
            if work_context:
                prepared = f"{prepared}\n\n{work_context}"
        except Exception:
            pass

        try:
            thread_context = self._extract_thread_assets()
            if thread_context:
                prepared = f"{prepared}\n\n{thread_context}"
        except Exception:
            pass

        try:
            from tech_connector.services.asset_mention_service import mention_context_block
            from tech_connector.game_engine.integration.dcc_smart_search_service import smart_search_context_block

            mention_context = mention_context_block(
                text or "",
                self._asset_mention_candidates("", include_index=False, limit=80),
            )
            if mention_context:
                prepared = f"{prepared}\n\n{mention_context}"
            smart_search_context = smart_search_context_block(text or "")
            if smart_search_context:
                prepared = f"{prepared}\n\n{smart_search_context}"
        except Exception:
            pass

        # Unreal TD system prompt (prepended as LLM system context)
        # Fires on any Unreal-context query. Assembles three layers:
        #   1. Senior Principal TD persona + engineering priorities
        #   2. Live or cached project assets (parsed from snapshot JSON)
        #   3. Execution philosophy (capability-first, compose-before-create)
        _is_unreal = (
                task_role == "unreal"
                or "unreal" in (text or "").lower()
        )
        _is_maya = (
                task_role == "maya"
                or "maya" in (text or "").lower()
        )

        if _is_unreal:
            try:
                from tech_connector.bridges.unreal.unreal_scanner import UnrealScanner

                project_root = self._resolve_unreal_project_root()
                scanner = UnrealScanner(project_root=project_root)
                self.set_live_process("Building Unreal context")
                status = None
                scan = None
                daemon_prompt_context = ""
                daemon_context = self._request_unreal_project_intelligence_context(
                    text or "unreal request",
                    mode="standard",
                    max_tokens=4000,
                )
                if isinstance(daemon_context, dict):
                    status = daemon_context.get("status") or {}
                    scan = daemon_context.get("scan") or None
                    daemon_prompt_context = str(daemon_context.get("context") or "")
                if not scan:
                    if getattr(
                            scanner, "should_use_fast_path", None
                    ) and scanner.should_use_fast_path(text or ""):
                        scan = scanner.load_cached() or {
                            "data": {},
                            "connected": False,
                            "cache_used": True,
                            "mode": "cached_fast",
                        }
                    else:
                        self._emit_unreal_milestone("Running standard live Unreal asset scan")
                        scan = scanner.scan_all(mode="standard")
                if not status:
                    try:
                        status = scanner.context_status(text or "", mode="standard")
                    except Exception:
                        status = {}
                self.unreal_project_snapshot = json.dumps(scan, indent=2, default=str)
                if scan.get("connected"):
                    health = (scan.get("data") or {}).get("health", {})
                    level = (
                            (scan.get("data") or {}).get("loaded_level")
                            or health.get("loaded_level")
                            or "unknown level"
                    )
                    engine = health.get("engine_version") or "UE"
                    self.set_card(
                        "unreal", "ok", f"Connected - {engine} - Level: {level}"
                    )
                elif scan.get("cache_used"):
                    self.set_card("unreal", "warn", "Not connected - using cache")
                else:
                    self.set_card("unreal", "bad", "Bridge unavailable")
                self.append(
                    "\n[UnrealContext] "
                    f"live={str(status.get('unreal_live_context')).lower()} "
                    f"cache_used={str(status.get('cache_used')).lower()} "
                    f"memory_cache={str(status.get('used_memory_cache')).lower()} "
                    f"mode={status.get('scan_mode')} "
                    f"intelligence_db={status.get('intelligence_db')} "
                    f"selected_assets={status.get('selected_assets')} "
                    f"selected_actors={status.get('selected_actors')} "
                    f"blueprint_index={status.get('blueprint_index')}\n"
                    f"[UnrealContext] {status.get('stage_summary') or 'No staged checks reported.'}\n"
                )
                if not getattr(
                        scanner, "should_use_fast_path", None
                ) or not scanner.should_use_fast_path(text or ""):

                    def _refresh_unreal_context_background():
                        try:
                            fresh_scan = scanner.scan_all(mode="standard", force=True)
                            self.unreal_project_snapshot = json.dumps(
                                fresh_scan, indent=2, default=str
                            )
                            self.thread_log_message.emit(
                                "[UnrealContext] Background refresh completed.\n"
                            )
                        except Exception as refresh_exc:
                            self.thread_log_message.emit(
                                f"[UnrealContext] Background refresh skipped: {refresh_exc}\n"
                            )

                    import threading

                    threading.Thread(
                        target=_refresh_unreal_context_background, daemon=True
                    ).start()
            except Exception as scan_exc:
                self.set_card("unreal", "warn", "Context scan skipped")
                self.append(f"\n[UnrealContext] quick scan skipped: {scan_exc}\n")
            try:
                from tech_connector.bridges.unreal.unreal_td_prompt import build_for_prompt

                _raw_snap = getattr(self, "unreal_project_snapshot", "")
                _td_system = build_for_prompt(text=text or "", raw_snapshot=_raw_snap)
                if daemon_prompt_context:
                    _td_system = (
                        _td_system
                        + "\n\n============================================================\n"
                        + "WARM PROJECT INTELLIGENCE CONTEXT\n"
                        + "============================================================\n"
                        + daemon_prompt_context[:6000]
                    )
                sep = "=" * 60
                prepared = f"{_td_system}\n\n{sep}\nUSER REQUEST\n{sep}\n\n{prepared}"
            except Exception:
                pass  # never break chat on prompt assembly failure
        elif _is_maya:
            try:
                from tech_connector.bridges.maya.maya_td_prompt import build_for_prompt

                _raw_snap = getattr(self, "maya_project_snapshot", "")
                _td_system = build_for_prompt(text=text or "", raw_snapshot=_raw_snap)
                sep = "=" * 60
                prepared = f"{_td_system}\n\n{sep}\nUSER REQUEST\n{sep}\n\n{prepared}"
            except Exception:
                pass

        resolved_role = task_role
        if not resolved_role:
            try:
                from tech_connector.router.ai_router import AIRouter
                editor_active = (
                    hasattr(self, "workspace_tabs")
                    and self.workspace_tabs.tabText(self.workspace_tabs.currentIndex())
                    == "Editor"
                )
                resolved_role = AIRouter.choose_role(text, editor_active=editor_active)
            except Exception:
                resolved_role = "plan"

        if (
            resolved_role not in ("plan", "docs")
            and code_profile.mode not in {"ask", "plan", "review"}
            and code_profile.permission != "read_only"
        ):
            file_edit_caps = (
                "You have autonomous file-editing capabilities. "
                "To propose changes to a file, you MUST output special XML tags:\n"
                "- To MODIFY an existing file, output:\n"
                "  <modify_file path=\"relative/or/absolute/path.py\">\n"
                "  <<<< ORIGINAL\n"
                "  ... exact original lines to replace ...\n"
                "  ====\n"
                "  ... replacement lines ...\n"
                "  >>>>\n"
                "  </modify_file>\n\n"
                "- To CREATE a new file, output:\n"
                "  <create_file path=\"relative/or/absolute/path.py\">\n"
                "  ... file content ...\n"
                "  </create_file>\n"
                "If you only need to modify a small part of a file, use the <modify_file> tags. Do not use standard markdown code blocks for multi-file changes; use the XML tags specified above."
            )
        else:
            file_edit_caps = ""

        if file_edit_caps:
            sep = "=" * 60
            prepared = f"{file_edit_caps}\n\n{sep}\n\n{prepared}"
        
        self.set_live_process("Prompt context ready")
        return prepared


    def _engine_should_prepare_request(self, text: str) -> bool:
        """Return True for requests that should use the Intelligence Engine before LLM routing.

        This is intentionally broader than the first pass: project-wide search,
        project-health/dead-code questions, and target-discovery edits all go
        through the same background preparation path so the UI does not freeze.
        """
        try:
            from tech_connector.services.prompt.prompt_route_service import ENGINE_PROVIDERS
            decision = self._classify_prompt_route_decision(text)
            if decision.provider in ENGINE_PROVIDERS:
                return True
        except Exception:
            pass
        return False

    def _classify_prompt_route_decision(self, text: str):
        """Build canonical request state once, then route the understood request."""
        from tech_connector.services.code_prompt_profile_service import (
            apply_code_prompt_profile_to_decision,
            normalize_code_prompt_profile,
        )
        from tech_connector.services.prompt.prompt_execution_context_service import build_prompt_execution_context
        from tech_connector.services.prompt.prompt_route_service import classify_prompt_route
        from tech_connector.engine.request_context import should_prioritize_open_file_context

        roots = self.project_roots() if hasattr(self, "project_roots") else []
        active_path = str(getattr(self, "current_file_path", "") or "")
        if active_path and not should_prioritize_open_file_context(self, text):
            active_path = ""
        host_hint = ""
        try:
            host_hint = str(self.command_router.detect_prompt_host(text) or "")
        except Exception:
            pass
        profile = (
            self.code_prompt_profile()
            if hasattr(self, "code_prompt_profile")
            else normalize_code_prompt_profile(settings=self.settings)
        )
        execution_context = build_prompt_execution_context(
            text,
            host_hint=host_hint,
            decision_facts={
                "project_roots": list(roots),
                "active_path": active_path,
                "code_prompt_profile": profile.to_dict(),
            },
        )
        execution_context.planning_result["user_prompt_preferences"] = profile.to_dict()
        execution_context.task_graph["user_prompt_preferences"] = profile.to_dict()
        decision = classify_prompt_route(
            text,
            project_roots=roots,
            active_path=active_path,
            execution_context=execution_context,
        )
        decision = apply_code_prompt_profile_to_decision(decision, profile)
        decision.execution_context = execution_context.to_dict()
        self._last_prompt_execution_context = execution_context.to_dict()
        self._last_prompt_route_decision = decision.to_dict()
        return decision

    def on_prioritize_open_file_context_changed(self, state):
        enabled = state == 2
        self.settings["prioritize_open_file_context"] = enabled
        try:
            self.service.settings["prioritize_open_file_context"] = enabled
            self.service.save_settings()
        except Exception:
            pass
        try:
            self.set_live_process(
                "Open file priority enabled" if enabled else "Open file priority disabled"
            )
            self.update_unified_prompt_context_label()
        except Exception:
            pass

    def _append_prompt_understanding(self, decision) -> None:
        """Expose the interpreted problem and plan before work begins."""
        self._append_visible_prompt_progress(decision)
        if not self.show_activity_details_enabled():
            return
        try:
            from tech_connector.services.reasoning.engineering_reasoning_service import (
                render_senior_prompt_analysis,
            )

            data = (
                decision.to_dict()
                if hasattr(decision, "to_dict")
                else dict(decision or {})
            )
            analysis = data.get("senior_prompt_analysis") or {}
            summary = render_senior_prompt_analysis(analysis)
            if summary:
                self.append(f"\n[Prompt Analysis]\n{summary}\n")
        except Exception:
            pass

    def _append_visible_prompt_progress(
        self,
        decision=None,
        text: str = "",
    ) -> None:
        """Show the interpreted outcome and high-level reasoning approach."""
        try:
            from tech_connector.services.prompt.prompt_progress_service import (
                build_prompt_progress_plan,
                first_progress_status,
                render_prompt_progress_plan,
            )

            data = (
                decision.to_dict()
                if hasattr(decision, "to_dict")
                else dict(decision or {})
            )
            prompt_text = (
                text
                or data.get("user_text")
                or data.get("prompt_preview")
                or getattr(self, "last_user_prompt", "")
            )
            plan = dict(data.get("visible_progress") or {})
            # Fast-path route metadata often contains only a single search stage.
            # Rebuild the user-facing explanation when the canonical plan lacks
            # an interpreted outcome so chat still shows what was understood.
            if not plan or not (
                plan.get("interpreted_request")
                or plan.get("desired_outcome")
                or (plan.get("reasoning_narration") or {}).get("interpreted_request")
            ):
                plan = build_prompt_progress_plan(prompt_text, data)
            narration = dict(plan.get("reasoning_narration") or {})
            self._active_reasoning_narration = narration
            compact = render_prompt_progress_plan(plan, max_stages=6)
            if hasattr(self, "set_live_process"):
                self.set_live_process(first_progress_status(plan))
            if compact:
                self.append(f"\nASSISTANT [Working on it]:\n{compact}\n")
        except Exception:
            pass
