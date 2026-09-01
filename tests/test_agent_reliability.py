import asyncio
import inspect
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests

from core import config
from core.brain.cloud import CloudProviderError, OpenRouterClient
from core.brain.llm import Brain, clean_final_reply
from core.hands.agent import Agent, MANIFEST, parse_toolcalls, select_tools
from core.hands.cloud_agent import CloudAgent, native_tool_schema
from core.hands.tools import Risk, TaskAgent, ToolRequest, ToolResult
from core.hud import server
from core.hud.server import _looks_actionable


class AgentReliabilityTests(unittest.TestCase):
    def test_manifest_arguments_match_tool_handlers(self):
        task_agent = TaskAgent()
        manifest = {tool["name"]: tool for tool in MANIFEST}

        for name, tool in manifest.items():
            if name in {"timer", "reminder", "list_reminders", "cancel_reminders"}:
                continue
            handler = getattr(task_agent, f"_{name}")
            parameters = inspect.signature(handler).parameters
            for argument in tool["arguments"]:
                self.assertIn(argument, parameters, f"{name}.{argument}")
            required = {
                key
                for key, value in parameters.items()
                if value.default is inspect.Parameter.empty
            }
            self.assertTrue(
                required.issubset(tool["arguments"]),
                f"{name} is missing required arguments: {required - tool['arguments'].keys()}",
            )

    def test_confirmation_error_denies_action(self):
        async def broken_confirmation(_request):
            raise RuntimeError("HUD disconnected")

        agent = Agent(None, TaskAgent(), broken_confirmation)
        request = ToolRequest(
            name="write_file",
            args={},
            risk=None,
            title="test",
            description="test",
        )

        self.assertFalse(asyncio.run(agent._confirm(request)))

    def test_conversation_is_not_misrouted_to_tools(self):
        for text in (
            "Show me how closures work",
            "Summarize dependency injection",
            "What does memory safety mean?",
            "Read this sentence and explain it",
            "Analyze this image",
        ):
            self.assertFalse(_looks_actionable(text), text)

    def test_concrete_actions_are_routed(self):
        for text in (
            "Open Chrome",
            "Read the file C:/notes.txt",
            "Check system health",
            "Calculate 12 * 8",
            "Summarize C:/notes.txt",
        ):
            self.assertTrue(_looks_actionable(text), text)

    def test_stock_instruction_model_is_default(self):
        if config.DEFAULT_STOCK_MODEL.is_file():
            self.assertEqual(config.DEFAULT_STOCK_MODEL, config.MODEL_FILE)
            self.assertIn("Qwen2.5-VL-3B-Instruct", config.MODEL_FILE.name)

    def test_cloud_is_opt_in_even_when_key_exists(self):
        with patch.object(config, "REASONING_MODE", "local"):
            client = OpenRouterClient(api_key=None)
            client.api_key = "configured-key"
            self.assertFalse(client.enabled)

    def test_vision_projector_is_discovered(self):
        self.assertIsNotNone(config.MMPROJ_FILE)
        self.assertTrue(config.MMPROJ_FILE.is_file())

    def test_image_content_uses_file_uri(self):
        with tempfile.NamedTemporaryFile(suffix=".png") as image:
            content = Brain.image_content("Describe it", image.name)

        self.assertEqual("image_url", content[0]["type"])
        self.assertTrue(content[0]["image_url"]["url"].startswith("file:///"))
        self.assertEqual("Describe it", content[1]["text"])

    def test_rgba_image_content_is_decoder_safe(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "transparent.png"
            Image.new("RGBA", (2, 2), (0, 255, 255, 128)).save(image)
            content = Brain.image_content("Describe it", str(image))

        self.assertTrue(content[0]["image_url"]["url"].startswith("data:image/jpeg;base64,"))

    def test_context_drops_a_complete_exchange(self):
        messages = [
            {"role": "system", "content": "rules"},
            {"role": "user", "content": "old question"},
            {"role": "assistant", "content": "old answer"},
            {"role": "user", "content": "current question"},
        ]

        self.assertTrue(Brain._drop_oldest_exchange(messages))
        self.assertEqual(["system", "user"], [message["role"] for message in messages])
        self.assertEqual("current question", messages[-1]["content"])

    def test_tool_public_payload_is_bounded(self):
        result = ToolResult(True, "m" * 7000, data={"content": "x" * 10000})

        public = result.public()

        self.assertEqual(6000, len(public["message"]))
        self.assertEqual(6000, len(public["data"]["content"]))

    def test_open_url_preserves_case(self):
        request = TaskAgent().parse("open https://example.com/CaseSensitive?Token=AbC")

        self.assertEqual("https://example.com/CaseSensitive?Token=AbC", request.args["url"])

    def test_download_folder_question_uses_directory_tool(self):
        for text in (
            "what is in my download folder",
            "what's inside my Downloads directory",
            "show me my downloads",
        ):
            request = TaskAgent().parse(text)
            self.assertIsNotNone(request, text)
            self.assertEqual("list_directory", request.name, text)
            self.assertEqual(Path.home() / "Downloads", Path(request.args["path"]), text)

    def test_directory_tool_returns_real_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "real-file.txt").write_text("real", encoding="utf-8")
            (root / "real-folder").mkdir()

            result = TaskAgent._list_directory(str(root))

        self.assertTrue(result.ok)
        self.assertIn("real-file.txt", result.message)
        self.assertIn("[folder] real-folder", result.message)
        self.assertEqual(
            {"real-file.txt", "real-folder"},
            {entry["name"] for entry in result.data["entries"]},
        )

    def test_file_management_tools_use_real_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.txt"
            copied = root / "copied.txt"
            moved = root / "moved.txt"
            folder = root / "created"
            source.write_text("verified", encoding="utf-8")
            agent = TaskAgent()

            self.assertTrue(agent._create_directory(str(folder)).ok)
            self.assertTrue(agent._copy_path(str(source), str(copied)).ok)
            self.assertEqual("verified", copied.read_text(encoding="utf-8"))
            self.assertTrue(agent._move_path(str(copied), str(moved)).ok)
            self.assertFalse(copied.exists())
            self.assertEqual("verified", moved.read_text(encoding="utf-8"))
            self.assertTrue(agent._file_info(str(moved)).ok)

    def test_self_edit_is_scoped_validated_and_backed_up(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "module.py"
            source.write_text("VALUE = 1\n", encoding="utf-8")
            with patch.object(config, "BASE_DIR", root):
                result = TaskAgent._edit_own_file(
                    str(source), "VALUE = 1", "VALUE = 2"
                )

            self.assertTrue(result.ok)
            self.assertEqual("VALUE = 2\n", source.read_text(encoding="utf-8"))
            self.assertTrue(Path(result.data["backup"]).is_file())

    def test_self_edit_rejects_invalid_python(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "module.py"
            source.write_text("VALUE = 1\n", encoding="utf-8")
            with patch.object(config, "BASE_DIR", root):
                result = TaskAgent._edit_own_file(
                    str(source), "VALUE = 1", "if broken syntax"
                )

            self.assertFalse(result.ok)
            self.assertEqual("VALUE = 1\n", source.read_text(encoding="utf-8"))

    def test_code_requests_receive_coding_tools_without_full_catalog(self):
        tools = select_tools("debug the Python code in C:/work/app.py")
        names = {tool["name"] for tool in tools}

        self.assertIn("search_text", names)
        self.assertIn("replace_in_file", names)
        self.assertIn("run_shell", names)
        self.assertNotIn("weather", names)
        self.assertLess(len(tools), len(MANIFEST))

    def test_replace_in_file_validates_and_backs_up(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "module.py"
            source.write_text("VALUE = 1\n", encoding="utf-8")
            result = TaskAgent()._replace_in_file(
                str(source), "VALUE = 1", "VALUE = 3"
            )

            self.assertTrue(result.ok)
            self.assertEqual("VALUE = 3\n", source.read_text(encoding="utf-8"))
            self.assertTrue(Path(result.data["backup"]).is_file())

    def test_search_text_returns_exact_file_and_line(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "module.py"
            source.write_text("first\nTARGET_VALUE = 7\n", encoding="utf-8")
            result = TaskAgent._search_text(str(root), "TARGET_VALUE", ".py")

            self.assertTrue(result.ok)
            self.assertEqual(2, result.data["matches"][0]["line"])
            self.assertEqual(str(source), result.data["matches"][0]["path"])

    def test_native_tool_schema_has_typed_required_arguments(self):
        tool = next(item for item in MANIFEST if item["name"] == "timer")
        schema = native_tool_schema(tool)["function"]["parameters"]

        self.assertEqual("number", schema["properties"]["seconds"]["type"])
        self.assertIn("seconds", schema["required"])
        self.assertNotIn("label", schema["required"])
        self.assertFalse(schema["additionalProperties"])

    def test_cloud_image_is_converted_to_data_url(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "image.png"
            image.write_bytes(b"fake-image")
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": image.as_uri()}},
                        {"type": "text", "text": "describe"},
                    ],
                }
            ]
            prepared = OpenRouterClient.prepare_messages(messages)

        self.assertTrue(
            prepared[0]["content"][0]["image_url"]["url"].startswith("data:image/png;base64,")
        )
        self.assertTrue(messages[0]["content"][0]["image_url"]["url"].startswith("file:"))

    def test_cloud_agent_executes_native_tool_then_finishes(self):
        class FakeBrain:
            system_prompt = "system"

            @staticmethod
            def image_content(text, path):
                return text

        class FakeClient:
            model = "test/agent"

            def __init__(self):
                self.calls = []

            def complete(self, messages, tools, tool_choice):
                self.calls.append(messages)
                if len(self.calls) == 1:
                    return {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_math",
                                    "type": "function",
                                    "function": {
                                        "name": "math",
                                        "arguments": '{"expression":"6*7"}',
                                    },
                                }
                            ],
                        }
                    }
                return {"message": {"role": "assistant", "content": "The result is 42."}}

        client = FakeClient()
        agent = CloudAgent(FakeBrain(), TaskAgent(), None, client=client)

        result = asyncio.run(agent.run("Calculate 6*7", []))

        self.assertEqual(1, result.tool_count)
        self.assertEqual("The result is 42.", result.reply)
        self.assertEqual("tool", client.calls[1][-1]["role"])
        self.assertIn("42", client.calls[1][-1]["content"])

    def test_cloud_file_read_requires_disclosure_confirmation(self):
        confirmations = []

        async def deny(request):
            confirmations.append(request.name)
            return False

        agent = CloudAgent(None, TaskAgent(), deny, client=Mock())
        result = asyncio.run(
            agent._run_step_tools(
                [{"name": "read_file", "arguments": {"path": str(Path.home() / "note.txt")}}]
            )
        )

        self.assertEqual(["read_file"], confirmations)
        self.assertEqual("denied", result[0]["kind"])

    def test_openrouter_client_sends_native_tools(self):
        response = Mock(status_code=200)
        response.json.return_value = {
            "model": "test/large-agent",
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": "Ready."},
                }
            ],
            "usage": {"total_tokens": 12},
        }
        client = OpenRouterClient(
            api_key="test-key", model="test/large-agent", base_url="https://router.test"
        )
        tools = [native_tool_schema(next(item for item in MANIFEST if item["name"] == "math"))]

        with patch("core.brain.cloud.requests.post", return_value=response) as post:
            result = client.complete([{"role": "user", "content": "2+2"}], tools)

        self.assertEqual("Ready.", result["message"]["content"])
        request = post.call_args.kwargs
        self.assertEqual("Bearer test-key", request["headers"]["Authorization"])
        self.assertEqual("auto", request["json"]["tool_choice"])
        self.assertEqual("math", request["json"]["tools"][0]["function"]["name"])
        self.assertEqual({"enabled": True}, request["json"]["reasoning"])

    def test_cloud_agent_preserves_reasoning_details(self):
        class FakeBrain:
            system_prompt = "system"

        class FakeClient:
            model = "z-ai/glm-5.3-flash"

            def __init__(self):
                self.calls = []

            def complete(self, messages, tools, tool_choice):
                self.calls.append(messages)
                if len(self.calls) == 1:
                    return {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "reasoning_details": [{"type": "reasoning.text", "text": "plan"}],
                            "tool_calls": [{
                                "id": "call_time",
                                "type": "function",
                                "function": {"name": "current_time", "arguments": "{}"},
                            }],
                        }
                    }
                return {
                    "message": {
                        "role": "assistant",
                        "content": "Finished.",
                        "reasoning_details": [{"type": "reasoning.text", "text": "done"}],
                    }
                }

        client = FakeClient()
        result = asyncio.run(CloudAgent(FakeBrain(), TaskAgent(), None, client=client).run("time", []))

        preserved = next(
            message
            for message in client.calls[1]
            if message.get("role") == "assistant" and message.get("reasoning_details")
        )
        self.assertEqual("plan", preserved["reasoning_details"][0]["text"])
        self.assertEqual("done", result.assistant_message["reasoning_details"][0]["text"])

    def test_openrouter_error_redacts_key(self):
        response = Mock(status_code=401)
        response.json.return_value = {
            "error": {"message": "Rejected credential test-secret-key"}
        }
        client = OpenRouterClient(api_key="test-secret-key", base_url="https://router.test")

        with patch("core.brain.cloud.requests.post", return_value=response):
            with self.assertRaises(CloudProviderError) as raised:
                client.complete([{"role": "user", "content": "hello"}])

        self.assertNotIn("test-secret-key", str(raised.exception))
        self.assertIn("[redacted]", str(raised.exception))

    def _hermes_fallback(self, client):
        client.fallback_api_key = "hermes-key"
        client.fallback_model = "z-ai/glm-5.3-flash"
        client.fallback_base_url = "https://hermes.test/v1"

    def _ok_response(self):
        response = Mock(status_code=200)
        response.json.return_value = {
            "model": "z-ai/glm-5.3-flash",
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": "Ready."},
                }
            ],
            "usage": {"total_tokens": 3},
        }
        return response

    def test_openrouter_falls_back_to_hermes_on_rate_limit(self):
        limited = Mock(status_code=429)
        limited.json.return_value = {"error": {"message": "Rate limit exceeded"}}
        client = OpenRouterClient(api_key="test-key", base_url="https://router.test")
        self._hermes_fallback(client)

        with patch(
            "core.brain.cloud.requests.post",
            side_effect=[limited, self._ok_response()],
        ) as post:
            result = client.complete([{"role": "user", "content": "2+2"}])

        self.assertEqual("Hermes Portal", result["provider"])
        self.assertEqual(2, post.call_count)
        self.assertEqual("https://hermes.test/v1/chat/completions", post.call_args.args[0])
        self.assertEqual("Bearer hermes-key", post.call_args.kwargs["headers"]["Authorization"])

    def test_openrouter_falls_back_on_connection_failure(self):
        client = OpenRouterClient(api_key="test-key", base_url="https://router.test")
        self._hermes_fallback(client)

        with patch(
            "core.brain.cloud.requests.post",
            side_effect=[
                requests.ConnectionError("refused"),
                self._ok_response(),
            ],
        ):
            result = client.complete([{"role": "user", "content": "2+2"}])

        self.assertEqual("Hermes Portal", result["provider"])

    def test_openrouter_bad_request_skips_fallback(self):
        bad = Mock(status_code=400)
        bad.json.return_value = {"error": {"message": "bad request"}}
        client = OpenRouterClient(api_key="test-key", base_url="https://router.test")
        self._hermes_fallback(client)

        with patch("core.brain.cloud.requests.post", return_value=bad) as post:
            with self.assertRaises(CloudProviderError):
                client.complete([{"role": "user", "content": "hi"}])

        self.assertEqual(1, post.call_count)

    def test_both_providers_failing_reports_both(self):
        first = Mock(status_code=429)
        first.json.return_value = {"error": {"message": "rate limited"}}
        second = Mock(status_code=503)
        second.json.return_value = {"error": {"message": "unavailable"}}
        client = OpenRouterClient(api_key="test-key", base_url="https://router.test")
        self._hermes_fallback(client)

        with patch("core.brain.cloud.requests.post", side_effect=[first, second]):
            with self.assertRaises(CloudProviderError) as raised:
                client.complete([{"role": "user", "content": "hi"}])

        self.assertIn("OpenRouter", str(raised.exception))
        self.assertIn("Hermes Portal", str(raised.exception))

    def test_fallback_disabled_when_unconfigured(self):
        limited = Mock(status_code=429)
        limited.json.return_value = {"error": {"message": "rate limited"}}
        client = OpenRouterClient(api_key="test-key", base_url="https://router.test")
        client.fallback_api_key = ""

        with patch("core.brain.cloud.requests.post", return_value=limited) as post:
            with self.assertRaises(CloudProviderError):
                client.complete([{"role": "user", "content": "hi"}])

        self.assertEqual(1, post.call_count)

    def test_invalid_tool_arguments_fail_cleanly(self):
        request = ToolRequest("volume", {"action": "maximum"}, Risk.SAFE, "Volume", "test")

        result = asyncio.run(TaskAgent().execute(request))

        self.assertFalse(result.ok)
        self.assertIn("up, down, or mute", result.message)

    def test_shell_uses_process_exit_code(self):
        failed = SimpleNamespace(returncode=7, stdout="partial output", stderr="")
        with patch("core.hands.tools.subprocess.run", return_value=failed):
            result = TaskAgent._run_shell("test command")

        self.assertFalse(result.ok)
        self.assertEqual(7, result.data["exit_code"])

    def test_shell_confirmation_shows_full_command(self):
        command = "Get-ChildItem C:/Users/ROG/Downloads | Select-Object Name,Length"
        request = ToolRequest(
            "run_shell", {"command": command}, Risk.CAREFUL, "Run command", "Execute command"
        )

        self.assertIn(command, request.public()["description"])

    def test_fetch_blocks_private_networks(self):
        address = [(2, 1, 6, "", ("127.0.0.1", 80))]
        with patch("core.hands.tools.socket.getaddrinfo", return_value=address):
            error = TaskAgent._validate_public_url("http://example.test")

        self.assertIn("private or local", error)

    def test_vision_tool_returns_real_analyzer_output(self):
        analyzer = Mock(return_value="The screen shows a text editor.")
        agent = TaskAgent(vision_analyzer=analyzer)
        fake_frame = object()
        with patch("core.hands.tools._LOCAL_VISION.capture_screen", return_value=fake_frame), patch(
            "core.hands.tools._LOCAL_VISION.save_frame", return_value=Path("C:/capture.png")
        ):
            result = agent._vision_screen()

        self.assertTrue(result.ok)
        self.assertEqual("The screen shows a text editor.", result.message)
        analyzer.assert_called_once()

    def test_agent_confirmation_resolves_while_conversation_is_locked(self):
        async def scenario():
            request_id = "confirmation-test"
            future = asyncio.get_running_loop().create_future()
            server.agent_confirm_waiters[request_id] = future
            try:
                async with server.conversation_lock:
                    await server.handle_confirmation(request_id, True)
                return future.result()
            finally:
                server.agent_confirm_waiters.pop(request_id, None)

        self.assertTrue(asyncio.run(scenario()))

    def test_cleaner_removes_thinking_and_tool_scaffolding(self):
        raw = (
            "<think>private reasoning</think>"
            '[[TOOLCALL]]{"name":"find_files","arguments":{}}[[/TOOLCALL]]'
            "Final answer"
        )

        self.assertEqual("Final answer", clean_final_reply(raw))

    def test_exact_malformed_toolcall_is_repaired(self):
        raw = (
            '[[TOOLCALL]]name="find_files","arguments":{"query":"Downloads"}} '
            '[[/TOOLCALL ]]'
        )

        self.assertEqual(
            [{"name": "find_files", "arguments": {"query": "Downloads"}}],
            parse_toolcalls(raw),
        )

    def test_combined_malformed_windows_toolcall_is_repaired(self):
        raw = (
            '[[TOOLCALL]]name="read_file",arguments={"path":"C:\\Users\\Boss\\note.txt"}}'
            '[[/TOOLCALL]]'
        )
        parsed = parse_toolcalls(raw)

        self.assertEqual("read_file", parsed[0]["name"])
        self.assertEqual(r"C:\Users\Boss\note.txt", parsed[0]["arguments"]["path"])

    def test_corrupted_opening_tag_escaped_json_and_smart_quotes_are_repaired(self):
        raw = r'[[TOOLCALL]}{\"name\":\"find_files\",\"arguments\":{“query”:"Downloads"}}'

        self.assertEqual(
            [{"name": "find_files", "arguments": {"query": "Downloads"}}],
            parse_toolcalls(raw),
        )


if __name__ == "__main__":
    unittest.main()
