import asyncio
import tempfile
import time
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from core.hands.agent import MANIFEST, select_tools
from core.hands.background import BackgroundManager
from core.hands.tools import Risk, TOOL_REGISTRY, TaskAgent, ToolRequest
from core.hud.server import _looks_actionable


class FolderQuestionRoutingTests(unittest.TestCase):
    """Regression: folder questions must never be answered from (poisoned) memory."""

    def test_folder_questions_are_actionable(self):
        for text in (
            "what is in my download folder ?",
            "whats on my download folder ?",
            "what's inside my downloads",
            "check my downloads folder",
            "what is in the documents folder",
            "list my desktop",
        ):
            self.assertTrue(_looks_actionable(text), text)

    def test_plain_chat_is_still_not_actionable(self):
        for text in (
            "Show me how closures work",
            "What does memory safety mean?",
            "Read this sentence and explain it",
            "Analyze this image",
            "What is machine learning?",
        ):
            self.assertFalse(_looks_actionable(text), text)

    def test_parse_folder_question_with_punctuation_returns_real_listing(self):
        agent = TaskAgent()
        request = agent.parse("what is in my download folder ?")
        self.assertIsNotNone(request)
        self.assertEqual("list_directory", request.name)
        self.assertIs(Risk.SAFE, request.risk)
        self.assertTrue(request.args["path"].lower().endswith("downloads"))

    def test_parse_on_my_download_folder_returns_real_listing(self):
        agent = TaskAgent()
        request = agent.parse("whats on my download folder ?")
        self.assertIsNotNone(request)
        self.assertEqual("list_directory", request.name)

    def test_parse_list_desktop(self):
        agent = TaskAgent()
        request = agent.parse("show my desktop")
        self.assertIsNotNone(request)
        self.assertEqual("list_directory", request.name)
        self.assertIn("Desktop", request.args["path"])

    def test_real_listing_reports_truthfully(self):
        with tempfile.TemporaryDirectory() as home_dir:
            downloads = Path(home_dir) / "Downloads"
            downloads.mkdir()
            (downloads / "note.txt").write_text("hi", encoding="utf-8")
            with patch("core.hands.tools.Path.home", return_value=Path(home_dir)):
                result = TaskAgent._list_directory(str(downloads))

        self.assertTrue(result.ok)
        self.assertIn("note.txt", result.message)
        self.assertNotIn("tabby", result.message.lower())


class BackgroundSubagentTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.manager = BackgroundManager(base_dir=Path(self._tmp.name))
        self.agent = TaskAgent()
        self.agent.background = self.manager

    def tearDown(self):
        self.manager.kill_all()
        self._tmp.cleanup()

    def test_background_tools_are_registered(self):
        self.assertIn("run_background", TOOL_REGISTRY)
        self.assertIn("background_status", TOOL_REGISTRY)
        self.assertIs(Risk.CAREFUL, TOOL_REGISTRY["run_background"].risk)
        self.assertIs(Risk.SAFE, TOOL_REGISTRY["background_status"].risk)

    def test_manifest_matches_handlers(self):
        manifest = {tool["name"]: tool for tool in MANIFEST}
        handler = getattr(TaskAgent, "_run_background")
        parameters = handler.__code__.co_varnames[: handler.__code__.co_argcount]
        for argument in manifest["run_background"]["arguments"]:
            self.assertIn(argument, parameters)

    def test_select_tools_offers_background_tools(self):
        names = {tool["name"] for tool in select_tools("start the build in the background")}
        self.assertIn("run_background", names)
        self.assertIn("background_status", names)

    def test_parse_run_in_background(self):
        agent = TaskAgent()
        request = agent.parse("run the backup script in the background")
        self.assertIsNotNone(request)
        self.assertEqual("run_background", request.name)
        self.assertIs(Risk.CAREFUL, request.risk)
        self.assertEqual("the backup script", request.args["command"])

    def test_parse_background_status(self):
        agent = TaskAgent()
        for text in ("background tasks", "list background tasks", "what are my background tasks"):
            request = agent.parse(text)
            self.assertIsNotNone(request, text)
            self.assertEqual("background_status", request.name, text)
            self.assertIs(Risk.SAFE, request.risk, text)

    def test_start_run_and_collect_output(self):
        result = self.agent._run_background(
            "Write-Output 'FRIDAY_BG_OK'", label="echo test"
        )
        self.assertTrue(result.ok, result.message)
        task_id = result.data["task_id"]

        deadline = time.time() + 30
        finished = []
        while time.time() < deadline and not finished:
            finished = self.manager.poll()
            if not finished:
                time.sleep(0.2)

        self.assertEqual(1, len(finished))
        task = finished[0]
        self.assertEqual(task_id, task.id)
        self.assertEqual(0, task.exit_code)
        self.assertIn("FRIDAY_BG_OK", task.output_tail())

        status = self.agent._background_status(task_id)
        self.assertTrue(status.ok)
        self.assertIn("failed" if False else "done", str(status.data))

    def test_blocked_command_is_refused(self):
        result = self.agent._run_background("format C:")
        self.assertFalse(result.ok)
        self.assertIn("blocked", result.message.lower())

    def test_cwd_outside_profile_is_refused(self):
        agent = TaskAgent()
        agent.background = self.manager
        result = agent._run_background("Write-Output hi", cwd=r"C:\Windows")
        self.assertFalse(result.ok)
        self.assertIn("user profile", result.message)

    def test_status_empty_when_no_tasks(self):
        result = self.agent._background_status()
        self.assertTrue(result.ok)

    def test_unknown_status_id_fails(self):
        result = self.agent._background_status("does-not-exist")
        self.assertFalse(result.ok)


class SelfEditSecurityTests(unittest.TestCase):
    def test_apply_fix_cannot_touch_files_outside_user_profile(self):
        agent = TaskAgent()
        result = agent._apply_fix("a", "b", r"C:\Windows\evil.py")
        self.assertFalse(result.ok)

    def test_apply_fix_cannot_touch_friday_source(self):
        from core import config

        agent = TaskAgent()
        target = Path(config.BASE_DIR) / "core" / "config.py"
        result = agent._apply_fix("a", "b", str(target))
        self.assertFalse(result.ok)

    def test_apply_fix_rejects_non_python_files(self):
        with tempfile.TemporaryDirectory() as home_dir:
            target = Path(home_dir) / "notes.txt"
            target.write_text("hello", encoding="utf-8")
            with patch("core.hands.tools.Path.home", return_value=Path(home_dir)):
                agent = TaskAgent()
                result = agent._apply_fix("hello", "bye", str(target))
        self.assertFalse(result.ok)
        self.assertIn("Python", result.message)

    def test_self_edit_refuses_paths_outside_user_profile(self):
        agent = TaskAgent()
        result = agent._self_edit(r"C:\Windows\win.ini")
        self.assertFalse(result.ok)
        self.assertIn("user profile", result.message)


class SystemToolTruthTests(unittest.TestCase):
    def test_list_processes_returns_real_processes(self):
        result = TaskAgent._list_processes()
        self.assertTrue(result.ok, result.message)
        self.assertIn("Top processes", result.message)

    def test_system_health_reports_home_drive_disk(self):
        result = TaskAgent._system_health()
        self.assertTrue(result.ok, result.message)
        self.assertIn("Disk", result.message)


class UploadEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from core.hud import server

        cls.server = server
        cls.client = TestClient(server.app)

    def test_upload_uses_filename_not_broken_global(self):
        """Regression: /upload referenced an undefined `original` and 500'd."""
        response = self.client.post(
            "/upload",
            files={"file": ("my photo.PNG", BytesIO(b"\x89PNG\r\n\x1a\n"), "image/png")},
        )
        self.assertEqual(200, response.status_code, response.text)
        payload = response.json()
        self.assertEqual("my photo.PNG", payload["name"])
        self.assertEqual("image", payload["kind"])
        self.assertTrue(payload["url"].startswith("/uploads/"))

    def test_upload_rejects_disallowed_type(self):
        response = self.client.post(
            "/upload",
            files={"file": ("evil.exe", BytesIO(b"MZ"), "application/octet-stream")},
        )
        self.assertEqual(400, response.status_code)


if __name__ == "__main__":
    unittest.main()
