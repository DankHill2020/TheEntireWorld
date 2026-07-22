# coding=utf-8
"""Run isolated project-edit UI-flow stress cases against local Ollama."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import textwrap
import time
from typing import Callable


ROOT = Path("C:/depot/tools/.codex_stress/project_edit_ui_stress").resolve()
PKG = ROOT / "stresspkg"
TESTS = ROOT / "tests"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).strip() + "\n", encoding="utf-8")


def _reset_root() -> None:
    if ROOT.exists():
        shutil.rmtree(ROOT)
    PKG.mkdir(parents=True, exist_ok=True)
    TESTS.mkdir(parents=True, exist_ok=True)
    _write(PKG / "__init__.py", "")
    _write(TESTS / "__init__.py", "")


def _build_fixture_index() -> None:
    from tech_connector.knowledge.build_knowledge_index_v2 import main as build_index

    build_index(["--root", str(ROOT)])


def _case_circular_imports() -> dict[str, str]:
    processor = PKG / "user_processor.py"
    notifier = PKG / "user_notifier.py"
    test_file = TESTS / "test_user_services.py"
    _write(
        processor,
        """
# coding=utf-8
import os
import sys

from stresspkg.user_notifier import send_notification_alert


def deprecated_cleanup_method(u):
    print("Deprecated cleanup for user")
    return None


def process_user_data(abc1, xyz2):
    print("Starting processing user data...")
    temp_val_for_loop = []
    a = abc1.get("username", "")
    b = abc1.get("email", "")
    c = xyz2.get("level", 0)
    if not a or not b:
        print("Invalid user record")
        return False
    formatted_username_str = a.strip().lower()
    unused_flag_var = True
    unused_counter_index = 999
    if c > 5:
        print("Processing high level user:", formatted_username_str)
        temp_val_for_loop.append(formatted_username_str)
    else:
        print("Standard user:", formatted_username_str)
        temp_val_for_loop.append(formatted_username_str)
    notification_sent_ok = send_notification_alert(
        formatted_username_str,
        "Welcome to Tech Connector!",
    )
    return notification_sent_ok
""",
    )
    _write(
        notifier,
        """
# coding=utf-8
import os
import sys

from stresspkg.user_processor import process_user_data


def send_notification_alert(usr_id, msg_payload_data_str):
    print(f"Sending notification alert to user: {usr_id}")
    if usr_id == "admin":
        print("Admin user notification bypass validation")
        return True
    try:
        dummy_user = {"username": usr_id, "email": "test@example.com"}
        dummy_config = {"level": 1}
        recheck_ok = process_user_data(dummy_user, dummy_config)
        print("User validation recheck returned:", recheck_ok)
    except Exception as exc:
        print("Error in circular verification:", exc)
    print(f"Alert sent: {msg_payload_data_str}")
    return True
""",
    )
    _write(
        test_file,
        """
# coding=utf-8
import unittest


class TestUserServices(unittest.TestCase):
    pass
""",
    )
    question = (
        "Refactor stresspkg user_processor.py and user_notifier.py to resolve circular imports, messy naming, "
        "and dead code. Move imports of send_notification_alert and process_user_data inside their functions. "
        "Rename abc1/xyz2 to user_record/user_profile, a/b/c to username/email/user_level, "
        "usr_id/msg_payload_data_str to user_id/message_body. Remove deprecated_cleanup_method and unused variables. "
        "Update tests/test_user_services.py with unittest coverage for successful processing and notification."
    )
    plan = (
        "Intent:\nResolve the circular user-service import refactor and add tests.\n\n"
        f"Evidence-backed targets:\n{processor}\n{notifier}\n{test_file}\n\n"
        "Existing symbols to reuse:\nprocess_user_data\nsend_notification_alert\nTestUserServices\n\n"
        "Proposed changes:\nReplace process_user_data and send_notification_alert; replace TestUserServices with focused tests.\n\n"
        "Tests and verification:\nRun python -m unittest tests.test_user_services\n\n"
        "Blockers:\nNone\n\n"
        "Plan self-check:\nAll requested targets are listed and the test target is included.\n\n"
        f"Approval scope:\n{processor}, {notifier}, and {test_file}"
    )
    return {"name": "circular_import_cleanup", "active": str(processor), "question": question, "plan": plan}


def _case_long_branchy_function() -> dict[str, str]:
    source = PKG / "billing_reconciler.py"
    test_file = TESTS / "test_billing_reconciler.py"
    noisy_lines = "\n".join(
        f"        scratch_value_{i} = invoice.get('unused_{i}', 0)" for i in range(1, 34)
    )
    _write(
        source,
        f"""
# coding=utf-8
import os
import json
from datetime import datetime


def reconcile_invoice_records(a1, b2, c3=None):
    hardcoded_log_path = "D:/example_user/.ai_studio/logs/billing.log"
    results_tmp = []
    grand_total_tmp = 0.0
    dead_switch_flag = False
    c3 = c3 or {{}}
    for invoice in a1:
        raw_customer = invoice.get("customer", "")
        raw_status = invoice.get("status", "")
        raw_amount = invoice.get("amount", 0)
{noisy_lines}
        if not raw_customer:
            continue
        if raw_status == "void":
            continue
        if raw_status == "paid":
            adjusted_amount = float(raw_amount)
        elif raw_status == "discount":
            adjusted_amount = float(raw_amount) * 0.9
        else:
            adjusted_amount = float(raw_amount)
        if b2.get(raw_customer):
            adjusted_amount -= float(b2[raw_customer])
        if c3.get("round"):
            adjusted_amount = round(adjusted_amount, 2)
        grand_total_tmp += adjusted_amount
        results_tmp.append({{"customer": raw_customer.strip().lower(), "amount": adjusted_amount}})
    if dead_switch_flag:
        print(json.dumps(results_tmp))
    return {{"total": grand_total_tmp, "records": results_tmp, "log_path": hardcoded_log_path}}
""",
    )
    _write(
        test_file,
        """
# coding=utf-8
import unittest


class TestBillingReconciler(unittest.TestCase):
    pass
""",
    )
    question = (
        "Refactor billing_reconciler.py. Rename a1, b2, c3 to invoices, credits_by_customer, options. "
        "Remove the unused scratch variables and dead_switch_flag. Replace the hardcoded user log path with "
        "os.path.expanduser('~/.ai_studio/logs/billing.log'). Keep behavior for paid, discount, void, credits, and rounding. "
        "Add unittest coverage in tests/test_billing_reconciler.py for totals and dynamic log path."
    )
    plan = (
        "Intent:\nClean and test the long billing reconciliation function.\n\n"
        f"Evidence-backed targets:\n{source}\n{test_file}\n\n"
        "Existing symbols to reuse:\nreconcile_invoice_records\nTestBillingReconciler\n\n"
        "Proposed changes:\nReplace reconcile_invoice_records with clearer names and no dead code; replace TestBillingReconciler with tests.\n\n"
        "Tests and verification:\nRun python -m unittest tests.test_billing_reconciler\n\n"
        "Blockers:\nNone\n\n"
        "Plan self-check:\nThe source and test targets are both in scope.\n\n"
        f"Approval scope:\n{source}, and {test_file}"
    )
    return {"name": "long_branchy_cleanup", "active": str(source), "question": question, "plan": plan}


def _case_ui_import_docstrings() -> dict[str, str]:
    source = PKG / "mini_dashboard.py"
    test_file = TESTS / "test_mini_dashboard.py"
    _write(
        source,
        """
# coding=utf-8
import os

try:
    from PySide2.QtWidgets import QWidget, QVBoxLayout, QLabel
except Exception:
    QWidget = object
    QVBoxLayout = None
    QLabel = None


class MiniDashboard(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.path = "D:/example_user/.ai_studio/scratches/chat_history"
        self.label = None
        self.build_ui()

    def build_ui(self):
        if QVBoxLayout is None:
            return None
        layout = QVBoxLayout(self)
        self.label = QLabel("0 ms")
        layout.addWidget(self.label)
        return layout

    def load_latency_values(self, rows):
        vals = []
        for r in rows:
            if "latency" in r:
                vals.append(float(r["latency"]))
        return vals
""",
    )
    _write(
        test_file,
        """
# coding=utf-8
import unittest


class TestMiniDashboard(unittest.TestCase):
    pass
""",
    )
    question = (
        "Fix mini_dashboard.py for the project UI conventions. Use PySide6, not PySide2. "
        "Replace the hardcoded D:/example_user path with os.path.expanduser. Add descriptive docstrings to the class "
        "and public methods using :param/:return: style. Keep the no-Qt fallback importable. "
        "Add tests in tests/test_mini_dashboard.py for dynamic pathing and latency parsing without requiring a visible UI."
    )
    plan = (
        "Intent:\nRepair the mini dashboard UI code for framework, pathing, docstrings, and tests.\n\n"
        f"Evidence-backed targets:\n{source}\n{test_file}\n\n"
        "Existing symbols to reuse:\nMiniDashboard\nMiniDashboard.__init__\nMiniDashboard.build_ui\nMiniDashboard.load_latency_values\nTestMiniDashboard\n\n"
        "Proposed changes:\nReplace MiniDashboard and TestMiniDashboard with compliant, testable implementations.\n\n"
        "Tests and verification:\nRun python -m unittest tests.test_mini_dashboard\n\n"
        "Blockers:\nNone\n\n"
        "Plan self-check:\nThe PySide6, dynamic path, docstring, and test requirements are all covered.\n\n"
        f"Approval scope:\n{source}, and {test_file}"
    )
    return {"name": "ui_import_docstring_pathing", "active": str(source), "question": question, "plan": plan}


def _case_parser_cleanup() -> dict[str, str]:
    source = PKG / "usage_parser.py"
    test_file = TESTS / "test_usage_parser.py"
    _write(
        source,
        """
# coding=utf-8
import os
import json


def parse_usage_blob(xx, yy=None):
    yy = yy or {}
    user_home_file = "D:/example_user/.ai_studio/cache/usage.json"
    temporary_holder = []
    unused_debug_blob = {"enabled": False}
    for row in xx.splitlines():
        pieces = row.split("|")
        if len(pieces) < 3:
            continue
        a = pieces[0].strip()
        b = pieces[1].strip()
        c = pieces[2].strip()
        if not a:
            continue
        try:
            value = float(c)
        except Exception:
            value = 0.0
        if yy.get("uppercase"):
            a = a.upper()
        temporary_holder.append({"name": a, "kind": b, "value": value})
    if unused_debug_blob["enabled"]:
        print(json.dumps(temporary_holder))
    return {"rows": temporary_holder, "cache_path": user_home_file}
""",
    )
    _write(
        test_file,
        """
# coding=utf-8
import unittest


class TestUsageParser(unittest.TestCase):
    pass
""",
    )
    question = (
        "Refactor usage_parser.py. Rename xx to usage_text and yy to options; rename a/b/c to name/kind/raw_value. "
        "Remove unused_debug_blob and any dead debug branch. Replace the hardcoded D:/example_user cache path with "
        "os.path.expanduser('~/.ai_studio/cache/usage.json'). Preserve parsing behavior and add unittest coverage "
        "in tests/test_usage_parser.py for bad numeric values, uppercase option, and dynamic cache path."
    )
    plan = (
        "Intent:\nClean the usage parser and add behavior tests.\n\n"
        f"Evidence-backed targets:\n{source}\n{test_file}\n\n"
        "Existing symbols to reuse:\nparse_usage_blob\nTestUsageParser\n\n"
        "Proposed changes:\nReplace parse_usage_blob and TestUsageParser with clearer, tested code.\n\n"
        "Tests and verification:\nRun python -m unittest tests.test_usage_parser\n\n"
        "Blockers:\nNone\n\n"
        "Plan self-check:\nBoth source and test targets are in scope.\n\n"
        f"Approval scope:\n{source}, and {test_file}"
    )
    return {"name": "parser_dead_code_pathing", "active": str(source), "question": question, "plan": plan}


def _case_three_module_cycle() -> dict[str, str]:
    service = PKG / "auth_service.py"
    audit = PKG / "audit_logger.py"
    policy = PKG / "access_policy.py"
    test_file = TESTS / "test_auth_flow.py"
    _write(
        service,
        """
# coding=utf-8
from stresspkg.audit_logger import log_auth_event
from stresspkg.access_policy import is_action_allowed


def check_login(u, p, meta):
    unused_reason = "legacy"
    if not u or not p:
        log_auth_event(u, "failed")
        return False
    if not is_action_allowed(u, meta.get("action", "login")):
        log_auth_event(u, "denied")
        return False
    log_auth_event(u, "ok")
    return True
""",
    )
    _write(
        audit,
        """
# coding=utf-8
from stresspkg.auth_service import check_login


def log_auth_event(who, state):
    stale_format = "old"
    print(f"{who}:{state}")
    return True
""",
    )
    _write(
        policy,
        """
# coding=utf-8
from stresspkg.audit_logger import log_auth_event


def is_action_allowed(name, act):
    unused_cache = {}
    if name == "blocked":
        log_auth_event(name, "policy_block")
        return False
    return act in {"login", "refresh"}
""",
    )
    _write(
        test_file,
        """
# coding=utf-8
import unittest


class TestAuthFlow(unittest.TestCase):
    pass
""",
    )
    question = (
        "Refactor auth_service.py, audit_logger.py, and access_policy.py to remove cyclic top-level imports by using "
        "local imports only where needed. Rename check_login parameters u/p/meta to username/password/request_meta, "
        "log_auth_event parameters who/state to username/status, and is_action_allowed parameters name/act to username/action. "
        "Remove unused variables. Add tests in tests/test_auth_flow.py for allowed, blocked, and missing-password cases."
    )
    plan = (
        "Intent:\nClean a three-module cyclic auth flow and add tests.\n\n"
        f"Evidence-backed targets:\n{service}\n{audit}\n{policy}\n{test_file}\n\n"
        "Existing symbols to reuse:\ncheck_login\nlog_auth_event\nis_action_allowed\nTestAuthFlow\n\n"
        "Proposed changes:\nReplace each listed function and replace TestAuthFlow with coverage.\n\n"
        "Tests and verification:\nRun python -m unittest tests.test_auth_flow\n\n"
        "Blockers:\nNone\n\n"
        "Plan self-check:\nAll source and test targets are in scope.\n\n"
        f"Approval scope:\n{service}, {audit}, {policy}, and {test_file}"
    )
    return {"name": "three_module_cycle_cleanup", "active": str(service), "question": question, "plan": plan}


def _case_task_tracker_tool_request() -> dict[str, str]:
    tool = PKG / "task_tracker_tool.py"
    store = PKG / "task_store.py"
    report = PKG / "task_report.py"
    test_file = TESTS / "test_task_tracker_tool.py"
    _write(
        tool,
        """
# coding=utf-8
from stresspkg.task_store import save_tasks, load_tasks
from stresspkg.task_report import summarize_tasks


class TaskTrackerTool:
    def __init__(self, path=None):
        self.path = path or "D:/example_user/.ai_studio/tasks/tasks.json"
        self.debug_cache_unused = []

    def add_task(self, t, p=None):
        p = p or {}
        rows = load_tasks(self.path)
        task_name = t.get("name", "").strip()
        if not task_name:
            raise ValueError("Task requires name")
        row = {
            "name": task_name,
            "status": t.get("status", "todo"),
            "priority": int(t.get("priority", 0)),
        }
        rows.append(row)
        save_tasks(self.path, rows)
        if p.get("summary"):
            return summarize_tasks(rows)
        return row

    def complete_task(self, nm):
        rows = load_tasks(self.path)
        for r in rows:
            if r.get("name") == nm:
                r["status"] = "done"
        save_tasks(self.path, rows)
        return summarize_tasks(rows)
""",
    )
    _write(
        store,
        """
# coding=utf-8
import json
import os

from stresspkg.task_report import summarize_tasks


def load_tasks(file_path):
    try:
        with open(file_path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return []


def save_tasks(file_path, task_rows):
    tmp_debug_payload = {"enabled": False}
    if tmp_debug_payload["enabled"]:
        print(summarize_tasks(task_rows))
    folder = os.path.dirname(file_path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as handle:
        json.dump(task_rows, handle)
    return file_path
""",
    )
    _write(
        report,
        """
# coding=utf-8
from stresspkg.task_store import load_tasks


def summarize_tasks(records):
    total_count = 0
    done_count = 0
    todo_count = 0
    high_priority_names = []
    for r in records:
        total_count += 1
        if r.get("status") == "done":
            done_count += 1
        else:
            todo_count += 1
        if int(r.get("priority", 0)) >= 5:
            high_priority_names.append(r.get("name"))
    return {
        "total": total_count,
        "done": done_count,
        "todo": todo_count,
        "high_priority": high_priority_names,
    }
""",
    )
    _write(
        test_file,
        """
# coding=utf-8
import unittest


class TestTaskTrackerTool(unittest.TestCase):
    pass
""",
    )
    question = (
        "Build out the task tracker tool across task_tracker_tool.py, task_store.py, and task_report.py. "
        "Resolve cyclic top-level imports by moving project-local imports inside functions where needed. "
        "Replace the hardcoded D:/example_user task path with os.path.expanduser('~/.ai_studio/tasks/tasks.json'). "
        "Rename t/p/nm/r to task/options/task_name/task_record. Remove debug_cache_unused and tmp_debug_payload. "
        "Make save_tasks write atomically with a .tmp file and os.replace. Keep load_tasks returning [] for missing "
        "or invalid JSON. Add useful docstrings to public classes/functions/methods. Add unittest coverage in "
        "tests/test_task_tracker_tool.py for add with summary, complete task, invalid missing name, invalid JSON load, "
        "and dynamic default path."
    )
    plan = (
        "Intent:\nBuild a multi-file task tracker tool with persistence, reporting, cleanup, and tests.\n\n"
        f"Evidence-backed targets:\n{tool}\n{store}\n{report}\n{test_file}\n\n"
        "Existing symbols to reuse:\nTaskTrackerTool\nTaskTrackerTool.__init__\nTaskTrackerTool.add_task\nTaskTrackerTool.complete_task\n"
        "load_tasks\nsave_tasks\nsummarize_tasks\nTestTaskTrackerTool\n\n"
        "Proposed changes:\nReplace the task tool class and storage/report helpers; replace TestTaskTrackerTool with focused unittest coverage.\n\n"
        "Tests and verification:\nRun python -m unittest tests.test_task_tracker_tool\n\n"
        "Blockers:\nNone\n\n"
        "Plan self-check:\nAll requested source files and test coverage are in approval scope.\n\n"
        f"Approval scope:\n{tool}, {store}, {report}, and {test_file}"
    )
    return {"name": "task_tracker_tool_request", "active": str(tool), "question": question, "plan": plan}


def _case_preferences_manager_atomic_write() -> dict[str, str]:
    source = PKG / "preferences_manager.py"
    test_file = TESTS / "test_preferences_manager.py"
    _write(
        source,
        """
# coding=utf-8
import json
import os


DEFAULT_PREF_PATH = "D:/example_user/.ai_studio/preferences/settings.json"


class PreferencesManager:
    def __init__(self, path=None):
        self.path = path or DEFAULT_PREF_PATH
        self.last_error = None
        self.unused_dirty_cache = []

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except Exception as exc:
            self.last_error = str(exc)
            return {}

    def save(self, data_blob, options=None):
        options = options or {}
        temporary_debug_payload = {"enabled": False}
        if temporary_debug_payload["enabled"]:
            print(data_blob)
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(data_blob, handle)
        if options.get("reload"):
            return self.load()
        return {"path": self.path, "count": len(data_blob)}
""",
    )
    _write(
        test_file,
        """
# coding=utf-8
import unittest


class TestPreferencesManager(unittest.TestCase):
    pass
""",
    )
    question = (
        "Refactor preferences_manager.py for safer preference persistence. Replace DEFAULT_PREF_PATH with "
        "os.path.expanduser('~/.ai_studio/preferences/settings.json'), remove unused_dirty_cache and temporary_debug_payload, "
        "rename data_blob to preferences and options to save_options, and make save write atomically via a .tmp file plus "
        "os.replace. Validate save input is a dict and raise TypeError otherwise. Keep load returning {} for missing or invalid "
        "JSON while storing last_error. Add unittest coverage in tests/test_preferences_manager.py for dynamic default path, "
        "atomic save/reload behavior, invalid JSON load, and non-dict save rejection."
    )
    plan = (
        "Intent:\nRefactor PreferencesManager for dynamic paths, atomic save behavior, validation, and tests.\n\n"
        f"Evidence-backed targets:\n{source}\n{test_file}\n\n"
        "Existing symbols to reuse:\nPreferencesManager\nPreferencesManager.__init__\nPreferencesManager.load\nPreferencesManager.save\nTestPreferencesManager\n\n"
        "Proposed changes:\nReplace PreferencesManager and TestPreferencesManager with focused, behavior-preserving improvements.\n\n"
        "Tests and verification:\nRun python -m unittest tests.test_preferences_manager\n\n"
        "Blockers:\nNone\n\n"
        "Plan self-check:\nNested class methods, dynamic pathing, atomic write, validation, and tests are all in scope.\n\n"
        f"Approval scope:\n{source}, and {test_file}"
    )
    return {"name": "preferences_manager_atomic_write", "active": str(source), "question": question, "plan": plan}


def _case_pipeline_report_cycle() -> dict[str, str]:
    runner = PKG / "pipeline_runner.py"
    reporter = PKG / "pipeline_report.py"
    test_file = TESTS / "test_pipeline_report.py"
    _write(
        runner,
        """
# coding=utf-8
from stresspkg.pipeline_report import format_pipeline_summary


def run_pipeline(job_rows, cfg=None):
    cfg = cfg or {}
    temp_records = []
    unused_debug_counter = 0
    for r in job_rows:
        nm = r.get("name", "")
        st = r.get("status", "")
        ms = r.get("duration_ms", 0)
        if not nm:
            continue
        if st == "skip":
            continue
        temp_records.append({"name": nm.strip(), "status": st or "unknown", "duration_ms": float(ms)})
    if cfg.get("summary"):
        return format_pipeline_summary(temp_records, cfg)
    return temp_records
""",
    )
    _write(
        reporter,
        """
# coding=utf-8
from stresspkg.pipeline_runner import run_pipeline


def format_pipeline_summary(items, opts=None):
    opts = opts or {}
    scratch_total = 0
    rows = []
    for item in items:
        scratch_total += item.get("duration_ms", 0)
        rows.append(f"{item.get('name')}:{item.get('status')}:{item.get('duration_ms')}")
    if opts.get("include_total"):
        rows.append(f"total:{scratch_total}")
    return "\\n".join(rows)
""",
    )
    _write(
        test_file,
        """
# coding=utf-8
import unittest


class TestPipelineReport(unittest.TestCase):
    pass
""",
    )
    question = (
        "Refactor pipeline_runner.py and pipeline_report.py to remove their cyclic top-level imports and clean naming. "
        "Rename job_rows to jobs, cfg to options, r/nm/st/ms to job/name/status/duration_ms, items to records, and opts to options. "
        "Remove unused_debug_counter. Keep skipped jobs filtered, missing status as unknown, numeric durations as float, and summary formatting with totals. "
        "Add unittest coverage in tests/test_pipeline_report.py for raw records, summary output, skipped jobs, and total duration."
    )
    plan = (
        "Intent:\nClean a pipeline/report cycle and add behavior tests.\n\n"
        f"Evidence-backed targets:\n{runner}\n{reporter}\n{test_file}\n\n"
        "Existing symbols to reuse:\nrun_pipeline\nformat_pipeline_summary\nTestPipelineReport\n\n"
        "Proposed changes:\nReplace run_pipeline, format_pipeline_summary, and TestPipelineReport.\n\n"
        "Tests and verification:\nRun python -m unittest tests.test_pipeline_report\n\n"
        "Blockers:\nNone\n\n"
        "Plan self-check:\nBoth modules and the focused test file are in scope.\n\n"
        f"Approval scope:\n{runner}, {reporter}, and {test_file}"
    )
    return {"name": "pipeline_report_cycle", "active": str(runner), "question": question, "plan": plan}


def _summarize_payload(payload: dict | None, text: str) -> dict[str, object]:
    changes = list((payload or {}).get("changes") or [])
    joined = "\n\n".join(str(change.get("new_content") or "") for change in changes)
    flow_timings = (payload or {}).get("timings") or _parse_timing_section(text)
    stage_audit = dict((payload or {}).get("stage_audit") or {})
    if not stage_audit:
        stage_audit = _stage_audit_from_timings(flow_timings)
    return {
        "preview_ready": bool(payload and payload.get("type") == "project_changes"),
        "change_count": len(changes),
        "changed_files": [str(change.get("path") or "") for change in changes],
        "edit_locations": list((payload or {}).get("edit_locations") or []),
        "stage_audit": stage_audit,
        "change_lines": [
            {"path": str(change.get("path") or ""), "line": change.get("line")}
            for change in changes
            if change.get("line")
        ],
        "blocked": text.startswith("## Generating patchable code changes\n\nBLOCKED:")
        or text.startswith("BLOCKED:"),
        "has_pass_placeholder": "pass\n" in joined or joined.strip().endswith("pass"),
        "has_hardcoded_user_path": "D:/example_user" in joined or "D:\\example_user" in joined,
        "uses_pyside2_or_pyqt5": "PySide2" in joined or "PyQt5" in joined,
        "has_docstring_params": ":param " in joined,
        "has_return_doc": ":return:" in joined,
        "flow_timings": flow_timings,
        "response_excerpt": text[:1200],
    }


def _stage_audit_from_timings(flow_timings: dict[str, object] | None) -> dict[str, object]:
    """Build a stage audit from timing data when no UI payload was returned."""

    steps = list((flow_timings or {}).get("steps") or [])

    def issue_count(entry: dict[str, object]) -> int:
        try:
            return int(entry.get("issues") or 0)
        except (TypeError, ValueError):
            return 0

    target_generations = [
        entry for entry in steps
        if entry.get("step") == "target_generation" and entry.get("target")
    ]
    retry_steps = [
        entry for entry in steps
        if "retry" in str(entry.get("step") or "") or entry.get("step") in {"repair_attempt", "target_syntax_repair"}
    ]
    validation_steps = [
        entry for entry in steps
        if "validation" in str(entry.get("step") or "")
        or str(entry.get("step") or "") in {"quality_gate_preview", "runtime_unittest_preview", "syntax_repair_preview"}
    ]
    first_pass_ok = [entry for entry in target_generations if issue_count(entry) == 0]
    semantic_retries = [entry for entry in retry_steps if "semantic" in str(entry.get("step") or "")]
    runtime_steps = [entry for entry in steps if entry.get("step") == "runtime_unittest_preview"]
    quality_steps = [entry for entry in steps if entry.get("step") == "quality_gate_preview"]
    retry_targets = sorted({
        str(entry.get("target") or "")
        for entry in retry_steps
        if entry.get("target")
    })
    total_targets = len(target_generations)
    score = 100
    if total_targets:
        score -= max(0, total_targets - len(first_pass_ok)) * 10
    score -= len([entry for entry in retry_steps if issue_count(entry) > 0]) * 4
    if runtime_steps and issue_count(runtime_steps[-1]) > 0:
        score -= 20
    if quality_steps and issue_count(quality_steps[-1]) > 0:
        score -= 20
    if not runtime_steps and not quality_steps and steps:
        score -= 25
    score = max(0, min(100, score))
    return {
        "summary": {
            "intent_stage_count": len([entry for entry in steps if entry.get("step") in {"target_discovery", "build_model_stages", "validate_approved_plan"}]),
            "generation_stage_count": len(target_generations),
            "validation_stage_count": len(validation_steps),
            "retry_stage_count": len(retry_steps),
            "target_first_pass_ok": len(first_pass_ok),
            "target_first_pass_total": total_targets,
            "semantic_retry_count": len(semantic_retries),
            "retry_targets": [item for item in retry_targets if item],
            "runtime_unittest_ok": bool(runtime_steps and issue_count(runtime_steps[-1]) == 0),
            "quality_gate_ok": bool(quality_steps and issue_count(quality_steps[-1]) == 0),
            "intent_confidence_score": score,
            "status": "clean" if score >= 95 and not retry_steps else "recovered" if score >= 75 else "needs_attention",
        },
        "steps": steps,
    }


def _write_code_outputs(case_name: str, payload: dict | None) -> list[str]:
    """Save generated new_content snippets as reviewable files for each stress case."""

    changes = list((payload or {}).get("changes") or [])
    if not changes:
        failed_candidate = ROOT / "project_edit_debug_failed_candidate.json"
        try:
            failed_payload = json.loads(failed_candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            failed_payload = {}
        changes = list((failed_payload or {}).get("changes") or [])
    output_dir = ROOT / "code_outputs" / case_name
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[str] = []
    for index, change in enumerate(changes, start=1):
        source = str(change.get("new_content") or "")
        if not source:
            continue
        original_path = Path(str(change.get("path") or f"change_{index}.py"))
        output_path = output_dir / f"{index:02d}_{original_path.name}"
        output_path.write_text(source, encoding="utf-8")
        outputs.append(str(output_path))
    return outputs


def _run_preview_runtime_checks(payload: dict | None) -> dict[str, object]:
    """Temporarily apply preview output and run focused unittest modules."""

    changes = list((payload or {}).get("changes") or [])
    if not changes:
        return {"ran": False, "ok": False, "reason": "no preview changes"}
    backups: dict[Path, str] = {}
    test_modules: list[str] = []
    for change in changes:
        path = Path(str(change.get("path") or ""))
        if not path:
            continue
        try:
            backups[path] = path.read_text(encoding="utf-8")
        except OSError:
            backups[path] = ""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(change.get("new_content") or ""), encoding="utf-8")
        if path.name.startswith("test_") and path.suffix == ".py":
            try:
                rel = path.resolve().relative_to(ROOT.resolve()).with_suffix("")
                test_modules.append(".".join(rel.parts))
            except ValueError:
                pass
    if not test_modules:
        for path, content in backups.items():
            path.write_text(content, encoding="utf-8")
        return {"ran": False, "ok": True, "reason": "no changed test modules"}
    started = time.perf_counter()
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "unittest", *test_modules],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=45,
        )
        return {
            "ran": True,
            "ok": completed.returncode == 0,
            "seconds": round(time.perf_counter() - started, 3),
            "modules": test_modules,
            "stdout": completed.stdout[-2000:],
            "stderr": completed.stderr[-2000:],
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "ran": True,
            "ok": False,
            "seconds": round(time.perf_counter() - started, 3),
            "modules": test_modules,
            "stdout": str(exc.stdout or "")[-2000:],
            "stderr": "Timed out running focused unittest modules.",
        }
    finally:
        for path, content in backups.items():
            path.write_text(content, encoding="utf-8")


def _parse_timing_section(text: str) -> dict[str, object]:
    timing_match = re.search(r"## Timing\s*(.*)", str(text or ""), re.DOTALL)
    if not timing_match:
        return {}
    steps = []
    total_seconds = None
    for raw_line in timing_match.group(1).splitlines():
        line = raw_line.strip()
        match = re.match(r"-\s+([^:]+):\s+([0-9.]+)s(?:\s+\((.*)\))?", line)
        if not match:
            continue
        name, seconds, detail_text = match.groups()
        if name == "total":
            total_seconds = float(seconds)
            continue
        entry = {"step": name, "seconds": float(seconds)}
        for part in (detail_text or "").split(","):
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            entry[key.strip()] = value.strip()
        steps.append(entry)
    return {"total_seconds": total_seconds, "steps": steps}


def run_case(case_factory: Callable[[], dict[str, str]]) -> dict[str, object]:
    from tech_connector.app.main_window_editor import answer_project_index_request
    from tech_connector.services.project_edit_agent_service import (
        build_project_edit_agent_request,
        project_edit_plan_fingerprint,
    )

    case = case_factory()
    statuses: list[dict[str, object]] = []
    case_started = time.perf_counter()

    def status_callback(message: str) -> None:
        entry = {
            "at_seconds": round(time.perf_counter() - case_started, 3),
            "message": str(message),
        }
        statuses.append(entry)
        print(f"[{case['name']}] +{entry['at_seconds']}s {message}", flush=True)

    start = time.perf_counter()
    edit_plan = build_project_edit_agent_request(case["question"], active_path=case["active"], limit=8)
    approved_plan = {
        "plan": case["plan"],
        "fingerprint": project_edit_plan_fingerprint(edit_plan),
        "leaf_work_units": edit_plan.discovery.get("leaf_work_units", None),
    }
    text, payload = answer_project_index_request(
        path=case["active"],
        question=case["question"],
        intent="project_edit",
        status_callback=status_callback,
        approved_plan=approved_plan,
    )
    response_log = ROOT / f"project_edit_ui_stress_response_{case['name']}.txt"
    response_log.write_text(str(text or ""), encoding="utf-8")
    elapsed = time.perf_counter() - start
    payload_dict = payload if isinstance(payload, dict) else None
    code_outputs = _write_code_outputs(case["name"], payload_dict)
    runtime_verification = _run_preview_runtime_checks(payload_dict)
    summary = _summarize_payload(payload_dict, str(text or ""))
    summary.update(
        {
            "case": case["name"],
            "elapsed_seconds": round(elapsed, 2),
            "response_log": str(response_log),
            "code_outputs": code_outputs,
            "runtime_verification": runtime_verification,
            "status_count": len(statuses),
            "last_statuses": statuses[-8:],
            "status_timeline": statuses,
        }
    )
    return summary


def _write_markdown_report(results: list[dict[str, object]], path: Path) -> None:
    lines = [
        "# Project Edit UI Stress Results",
        "",
        f"Cases run: {len(results)}",
        "",
        "| Case | Result | Audit | Intent | Time | Changes | Key Issues |",
        "| --- | --- | --- | ---: | ---: | ---: | --- |",
    ]
    for result in results:
        result_label = "preview" if result.get("preview_ready") else "blocked"
        issues = []
        if result.get("has_pass_placeholder"):
            issues.append("pass placeholder")
        if result.get("has_hardcoded_user_path"):
            issues.append("hardcoded user path")
        if result.get("uses_pyside2_or_pyqt5"):
            issues.append("legacy Qt import")
        if result.get("blocked"):
            excerpt = str(result.get("response_excerpt") or "").replace("\n", " ")
            issues.append(excerpt[:160])
        runtime = dict(result.get("runtime_verification") or {})
        if runtime.get("ran") and not runtime.get("ok"):
            issues.append("runtime unittest failed")
        audit_summary = dict((result.get("stage_audit") or {}).get("summary") or {})
        target_ok = audit_summary.get("target_first_pass_ok")
        target_total = audit_summary.get("target_first_pass_total")
        intent_score = audit_summary.get("intent_confidence_score")
        lines.append(
            f"| {result.get('case')} | {result_label} | {audit_summary.get('status') or 'n/a'} | "
            f"{intent_score if intent_score is not None else 'n/a'} | {result.get('elapsed_seconds')}s | "
            f"{result.get('change_count')} | {'; '.join(issues) or 'none flagged'} |"
        )
    lines.append("")
    for result in results:
        lines.extend([
            f"## {result.get('case')}",
            "",
            f"- Total elapsed: {result.get('elapsed_seconds')}s",
            f"- Preview ready: {result.get('preview_ready')}",
            f"- Change count: {result.get('change_count')}",
            f"- Edit locations: {result.get('edit_locations') or []}",
            f"- Code outputs: {result.get('code_outputs') or []}",
            f"- Runtime verification: {result.get('runtime_verification') or {}}",
            "",
            "### Stage Audit",
        ])
        audit_summary = dict((result.get("stage_audit") or {}).get("summary") or {})
        if audit_summary:
            lines.extend([
                f"- status: {audit_summary.get('status')}",
                f"- intent confidence: {audit_summary.get('intent_confidence_score')}/100",
                f"- target first-pass: {audit_summary.get('target_first_pass_ok')}/{audit_summary.get('target_first_pass_total')}",
                f"- semantic retries: {audit_summary.get('semantic_retry_count')}",
                f"- retry targets: {audit_summary.get('retry_targets') or []}",
                f"- runtime unittest ok: {audit_summary.get('runtime_unittest_ok')}",
                f"- quality gate ok: {audit_summary.get('quality_gate_ok')}",
            ])
        else:
            lines.append("- No structured stage audit returned.")
        lines.extend([
            "",
            "### Flow Timings",
        ])
        timings = dict(result.get("flow_timings") or {})
        if timings:
            lines.append(f"- total_seconds: {timings.get('total_seconds')}")
            for step in timings.get("steps") or []:
                lines.append(f"- {step}")
        else:
            lines.append("- No structured timing payload returned.")
        lines.extend(["", "### Status Timeline"])
        for status in result.get("status_timeline") or []:
            lines.append(f"- +{status.get('at_seconds')}s {status.get('message')}")
        lines.extend(["", "### Response Excerpt", "", "```text", str(result.get("response_excerpt") or ""), "```", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ["TECH_CONNECTOR_PROJECT_ROOT"] = str(ROOT)
    os.environ["TECH_CONNECTOR_PROJECT_EDIT_DEBUG_CANDIDATE"] = "1"
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, "C:/depot/tools")
    _reset_root()
    cases = [
        _case_circular_imports,
        _case_long_branchy_function,
        _case_ui_import_docstrings,
        _case_parser_cleanup,
        _case_three_module_cycle,
        _case_task_tracker_tool_request,
        _case_preferences_manager_atomic_write,
        _case_pipeline_report_cycle,
    ]
    requested_cases = {
        item.strip()
        for item in os.environ.get("TECH_CONNECTOR_STRESS_CASES", "").split(",")
        if item.strip()
    }
    if requested_cases:
        selected = []
        for factory in cases:
            case_name = factory()["name"]
            if case_name in requested_cases:
                selected.append(factory)
        cases = selected
    for factory in cases:
        factory()
    _build_fixture_index()
    results = []
    for factory in cases:
        results.append(run_case(factory))
    report_path = ROOT / "project_edit_ui_stress_results.json"
    report_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    markdown_path = ROOT / "project_edit_ui_stress_results.md"
    _write_markdown_report(results, markdown_path)
    print("\n=== STRESS RESULTS ===")
    print(json.dumps(results, indent=2))
    print(f"\nWrote {report_path}")
    print(f"Wrote {markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
