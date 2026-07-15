import unittest
import json
import tempfile
from pathlib import Path

from engine.progress_events import EngineResult, ProgressEvent, ActivityEvent
from services.application_command_service import ApplicationCommandService


class DummyAppService:
    def __init__(self, root="C:/project"):
        self.settings = {
            "active_project": root,
            "enable_live_sources": True,
            "research_best_practices": True,
            "model": "test-model",
        }
        self.root = root
        self.command_router = None

    def project_roots(self):
        return [self.root]


class TestApplicationCommandService(unittest.TestCase):
    def test_retrieve_status_exposes_studio_profile_and_jobs(self):
        commands = ApplicationCommandService(DummyAppService())
        result = commands.execute("retrieve_status")
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"]["active_project"], "C:/project")
        self.assertTrue(result["status"]["best_practice_lookup_enabled"])
        self.assertIn("studio_profile", result["status"])

    def test_submit_prompt_creates_job_and_events(self):
        def runner(prompt, context, progress, activity):
            progress(ProgressEvent("route", "Routing", current=1, total=2))
            activity(ActivityEvent("route", "Selected test route", status="ok"))
            self.assertEqual(prompt, "hello")
            self.assertEqual(context.active_tab, "Remote")
            return EngineResult("answer", "Done", text="ok")

        commands = ApplicationCommandService(DummyAppService(), prompt_runner=runner)
        result = commands.execute("submit_prompt", {"prompt": "hello"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["job"]["status"], "completed")
        self.assertEqual(result["job"]["result"]["text"], "ok")
        events = commands.execute("recent_events", {"limit": 10})["events"]
        self.assertTrue(any(event["event_type"] == "prompt_submitted" for event in events))
        self.assertTrue(any(event["event_type"] == "job_completed" for event in events))
        detail = commands.execute("get_job", {"job_id": result["job"]["job_id"]})
        self.assertTrue(detail["ok"])
        self.assertIn("output_log", detail["job"])
        self.assertTrue(any(row["kind"] == "result_text" for row in detail["job"]["output_log"]))

    def test_finished_job_filter_and_create_job(self):
        def runner(prompt, context, progress, activity):
            return EngineResult("answer", "Created", text="created")

        commands = ApplicationCommandService(DummyAppService(), prompt_runner=runner)
        result = commands.execute(
            "create_job",
            {
                "title": "Mobile composed job",
                "goal": "Build a small pipeline",
                "provider": "maya",
                "steps": [{"label": "Inspect", "detail": "Check scene"}, {"label": "Run", "detail": "Execute"}],
            },
        )
        self.assertTrue(result["ok"])
        finished = commands.execute("list_jobs", {"state": "finished"})
        self.assertEqual(len(finished["jobs"]), 1)
        self.assertIn("Mobile composed job", finished["jobs"][0]["payload"]["title"])

    def test_deferred_remote_commands_have_stable_job_shape(self):
        commands = ApplicationCommandService(DummyAppService())
        result = commands.execute("launch_application", {"provider": "maya"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["job"]["status"], "awaiting_confirmation")
        self.assertIn("execution adapter", result["job"]["warnings"][0])

    def test_cancel_job(self):
        commands = ApplicationCommandService(DummyAppService())
        created = commands.execute("execute_workflow", {"workflow_id": "test"})
        job_id = created["job"]["job_id"]
        cancelled = commands.execute("cancel_job", {"job_id": job_id})
        self.assertTrue(cancelled["ok"])
        self.assertEqual(commands.job_store.get(job_id).status, "cancelled")

    def test_list_pipelines_reads_project_workflow_manifests(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workflow_dir = root / "workflows" / "maya"
            workflow_dir.mkdir(parents=True)
            manifest = workflow_dir / "build_rig.workflow.json"
            manifest.write_text(
                json.dumps(
                    {
                        "host": "maya",
                        "function": "build_rig",
                        "goal": "Build a character rig",
                        "function_path": "workflows.maya.build_rig.build_rig",
                        "slots": {"mesh": "body_GEO"},
                        "selected_capabilities": [{"name": "skin.bind"}],
                    }
                ),
                encoding="utf-8",
            )
            commands = ApplicationCommandService(DummyAppService(str(root)))
            result = commands.execute("list_pipelines")
            self.assertTrue(result["ok"])
            self.assertEqual(len(result["pipelines"]), 1)
            self.assertEqual(result["pipelines"][0]["host"], "maya")
            self.assertEqual(result["pipelines"][0]["slot_count"], 1)

    def test_list_applications_exposes_view_modes(self):
        commands = ApplicationCommandService(DummyAppService())
        result = commands.execute("list_applications")
        self.assertTrue(result["ok"])
        self.assertTrue(any(app["id"] == "unreal" for app in result["applications"]))
        unreal = next(app for app in result["applications"] if app["id"] == "unreal")
        self.assertIn("view_modes", unreal)

    def test_application_progress_and_screenshot_commands(self):
        commands = ApplicationCommandService(DummyAppService())
        commands.screen_png_bytes = lambda target="desktop": b"\x89PNG fake"

        progress = commands.execute("application_progress", {"application_id": "tech_connector"})
        self.assertTrue(progress["ok"])
        self.assertEqual(progress["progress"]["application"]["id"], "tech_connector")
        self.assertIn("screen", progress["progress"])

        monitor = commands.execute("monitor_application", {"application_id": "tech_connector"})
        self.assertTrue(monitor["ok"])
        self.assertEqual(monitor["job"]["status"], "completed")

        screenshot = commands.execute("request_screenshot", {"target": "desktop"})
        self.assertTrue(screenshot["ok"])
        self.assertTrue(screenshot["snapshot_available"])


if __name__ == "__main__":
    unittest.main()
