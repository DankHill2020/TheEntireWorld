import json
import unittest
from zipfile import ZipFile
from io import BytesIO
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from services.application_command_service import ApplicationCommandService
from services.remote_mobile_server import RemoteMobileServer


class DummyAppService:
    settings = {
        "active_project": "C:/project",
        "enable_live_sources": False,
        "research_best_practices": False,
        "model": "test-model",
    }
    command_router = None

    def project_roots(self):
        return []


def read_json(url: str, token: str):
    req = Request(url, headers={"X-AI-Studio-Token": token})
    with urlopen(req, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def read_text(url: str, token: str):
    req = Request(url, headers={"X-AI-Studio-Token": token})
    with urlopen(req, timeout=5) as response:
        return response.read().decode("utf-8")


def read_bytes(url: str, token: str):
    req = Request(url, headers={"X-AI-Studio-Token": token})
    with urlopen(req, timeout=5) as response:
        return response.read()


class TestRemoteMobileServer(unittest.TestCase):
    def test_mobile_server_serves_page_and_authorized_api(self):
        commands = ApplicationCommandService(DummyAppService())
        commands.screen_png_bytes = lambda target="desktop": (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
            b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
            b"\x1f\x15\xc4\x89\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        server = RemoteMobileServer(commands, host="127.0.0.1", port=0, token="test-token")
        try:
            url = server.start()
            self.assertIn("token=test-token", url)
            with urlopen(url, timeout=5) as response:
                html = response.read().decode("utf-8")
            self.assertIn("Tech Connector Remote", html)
            with urlopen(f"http://127.0.0.1:{server.port}/app.js", timeout=5) as response:
                js = response.read().decode("utf-8")
            self.assertIn("refreshApplications", js)
            self.assertIn("refreshScreen", js)
            with urlopen(f"http://127.0.0.1:{server.port}/manifest.webmanifest", timeout=5) as response:
                manifest = json.loads(response.read().decode("utf-8"))
            self.assertEqual(manifest["name"], "Tech Connector Remote")
            logo_data = read_bytes(f"http://127.0.0.1:{server.port}/tech_connector_logo.png", "test-token")
            self.assertGreater(len(logo_data), 1000)
            qr = read_text(f"http://127.0.0.1:{server.port}/pair.svg", "test-token")
            self.assertIn("<svg", qr)
            download_qr = read_text(f"http://127.0.0.1:{server.port}/download.svg", "test-token")
            self.assertIn("<svg", download_qr)
            zip_data = read_bytes(f"http://127.0.0.1:{server.port}/download/mobile-app.zip", "test-token")
            with ZipFile(BytesIO(zip_data)) as archive:
                self.assertIn("index.html", archive.namelist())
                self.assertIn("app.js", archive.namelist())
                self.assertIn("tech_connector_logo.png", archive.namelist())
            status = read_json(f"http://127.0.0.1:{server.port}/api/status", "test-token")
            self.assertTrue(status["ok"])
            req = Request(
                f"http://127.0.0.1:{server.port}/api/status",
                headers={"X-AI-Studio-Token": "test-token"},
                method="OPTIONS",
            )
            with urlopen(req, timeout=5) as response:
                self.assertEqual(response.headers.get("Access-Control-Allow-Origin"), "*")
            jobs = read_json(f"http://127.0.0.1:{server.port}/api/jobs?state=finished", "test-token")
            self.assertTrue(jobs["ok"])
            job_detail = read_json(f"http://127.0.0.1:{server.port}/api/job?job_id=missing", "test-token")
            self.assertFalse(job_detail["ok"])
            apps = read_json(f"http://127.0.0.1:{server.port}/api/applications", "test-token")
            self.assertTrue(apps["ok"])
            progress = read_json(f"http://127.0.0.1:{server.port}/api/application-progress", "test-token")
            self.assertTrue(progress["ok"])
            self.assertIn("desktop", progress["progress"])
            screen = read_bytes(f"http://127.0.0.1:{server.port}/api/screen.png?target=desktop", "test-token")
            self.assertTrue(screen.startswith(b"\x89PNG"))
            pipelines = read_json(f"http://127.0.0.1:{server.port}/api/pipelines", "test-token")
            self.assertTrue(pipelines["ok"])
        finally:
            server.stop()

    def test_mobile_server_rejects_missing_token(self):
        commands = ApplicationCommandService(DummyAppService())
        server = RemoteMobileServer(commands, host="127.0.0.1", port=0, token="test-token")
        try:
            server.start()
            with self.assertRaises(HTTPError) as caught:
                urlopen(f"http://127.0.0.1:{server.port}/api/status", timeout=5)
            self.assertEqual(caught.exception.code, 401)
        finally:
            server.stop()


if __name__ == "__main__":
    unittest.main()
