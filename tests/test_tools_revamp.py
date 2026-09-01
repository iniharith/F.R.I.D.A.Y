import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from core.hands.agent import MANIFEST
from core.hands.cloud_agent import CloudAgent, native_tool_schema
from core.hands.tools import Risk, TOOL_REGISTRY, TaskAgent, ToolRequest, ToolResult


class ToolsRevampTests(unittest.TestCase):
    def test_manifest_derives_typed_canonical_registry(self):
        self.assertEqual({tool["name"] for tool in MANIFEST}, set(TOOL_REGISTRY))
        timer = TOOL_REGISTRY["timer"]
        parameters = {parameter.name: parameter for parameter in timer.parameters}

        self.assertIs(Risk.SAFE, timer.risk)
        self.assertIs(float, parameters["seconds"].value_type)
        self.assertTrue(parameters["seconds"].required)
        self.assertFalse(parameters["label"].required)

    def test_native_schema_uses_typed_parameter_metadata(self):
        schema = native_tool_schema(TOOL_REGISTRY["timer"])["function"]["parameters"]

        self.assertEqual("number", schema["properties"]["seconds"]["type"])
        self.assertNotIn("label", schema["required"])

    def test_forged_safe_risk_cannot_run_careful_tool(self):
        agent = TaskAgent()
        request = ToolRequest("write_file", {"path": "x", "content": "x"}, Risk.SAFE, "x", "x")
        agent._write_file = Mock(return_value=ToolResult(True, "written"))

        result = asyncio.run(agent.execute(request))

        self.assertFalse(result.ok)
        self.assertEqual("authorization_required", result.data["error"])
        self.assertIs(Risk.CAREFUL, request.risk)
        agent._write_file.assert_not_called()

    def test_careful_authorization_is_bound_to_request_and_one_use(self):
        agent = TaskAgent()
        request = ToolRequest("write_file", {"path": "x", "content": "x"}, Risk.SAFE, "x", "x")
        agent._write_file = Mock(return_value=ToolResult(True, "written"))

        self.assertTrue(agent.authorize(request))
        self.assertTrue(asyncio.run(agent.execute(request)).ok)
        self.assertFalse(asyncio.run(agent.execute(request)).ok)
        agent._write_file.assert_called_once()

    def test_careful_authorization_rejects_post_approval_mutation(self):
        agent = TaskAgent()
        request = ToolRequest("write_file", {"path": "x", "content": "approved"}, Risk.CAREFUL, "x", "x")
        agent._write_file = Mock(return_value=ToolResult(True, "written"))

        self.assertTrue(agent.authorize(request))
        request.args["content"] = "changed after approval"
        result = asyncio.run(agent.execute(request))

        self.assertFalse(result.ok)
        self.assertEqual("authorization_required", result.data["error"])
        agent._write_file.assert_not_called()

    def test_general_file_read_is_scoped_to_user_profile(self):
        with tempfile.TemporaryDirectory() as home_dir, tempfile.TemporaryDirectory() as outside_dir:
            outside = Path(outside_dir) / "note.txt"
            outside.write_text("secret", encoding="utf-8")
            with patch("core.hands.tools.Path.home", return_value=Path(home_dir)):
                result = TaskAgent()._read_file(str(outside))

        self.assertFalse(result.ok)
        self.assertIn("user profile", result.message)

    def test_cloud_resolves_every_call_when_model_emits_more_than_four(self):
        calls = [
            {
                "id": f"call_{index}",
                "type": "function",
                "function": {"name": "math", "arguments": '{"expression":"2+2"}'},
            }
            for index in range(5)
        ]
        client = _FakeClient(calls)
        agent = CloudAgent(_FakeBrain(), TaskAgent(), None, client=client)

        result = asyncio.run(agent.run("calculate several values", []))

        follow_up = client.messages[1]
        tool_messages = [message for message in follow_up if message["role"] == "tool"]
        self.assertEqual(5, len(tool_messages))
        self.assertEqual({f"call_{index}" for index in range(5)}, {m["tool_call_id"] for m in tool_messages})
        self.assertIn("limited to four", tool_messages[-1]["content"])
        self.assertEqual(4, result.tool_count)

    def test_cloud_does_not_execute_malformed_arguments(self):
        calls = [
            {
                "id": "bad_args",
                "type": "function",
                "function": {"name": "current_time", "arguments": "{not-json"},
            }
        ]
        client = _FakeClient(calls)
        task_agent = TaskAgent()
        task_agent._current_time = Mock(return_value=ToolResult(True, "should not run"))
        agent = CloudAgent(_FakeBrain(), task_agent, None, client=client)

        result = asyncio.run(agent.run("what time is it", []))

        task_agent._current_time.assert_not_called()
        payload = json.loads(client.messages[1][-1]["content"])
        self.assertIn("malformed JSON", payload["result"])
        self.assertEqual(0, result.tool_count)

    def test_inspect_image_tool_is_in_canonical_registry(self):
        self.assertIn("inspect_image", TOOL_REGISTRY)
        spec = TOOL_REGISTRY["inspect_image"]
        self.assertIs(Risk.CAREFUL, spec.risk)
        arg_names = {parameter.name for parameter in spec.parameters}
        self.assertIn("path", arg_names)

    def test_inspect_image_routes_path_to_vision_analyzer(self):
        agent = TaskAgent()
        analyzer = Mock(return_value="A red mug on a desk.")
        agent.vision_analyzer = analyzer
        with tempfile.TemporaryDirectory() as home_dir:
            image = Path(home_dir) / "photo.png"
            image.write_bytes(b"\x89PNG\r\n\x1a\n")
            with patch("core.hands.tools.Path.home", return_value=Path(home_dir)):
                result = agent._inspect_image(str(image), "What is in it?")

        self.assertTrue(result.ok)
        analyzer.assert_called_once_with(str(image), "What is in it?")
        self.assertIn("red mug", result.message)

    def test_inspect_image_rejects_non_image_path(self):
        with tempfile.TemporaryDirectory() as home_dir:
            text = Path(home_dir) / "note.txt"
            text.write_text("hi", encoding="utf-8")
            with patch("core.hands.tools.Path.home", return_value=Path(home_dir)):
                result = TaskAgent()._inspect_image(str(text))

        self.assertFalse(result.ok)
        self.assertIn("not a supported image", result.message)

    def test_parse_see_image_path_produces_inspect_request(self):
        agent = TaskAgent()
        request = agent.parse("see the image at C:/Users/me/Downloads/photo.png")
        self.assertIsNotNone(request)
        self.assertEqual("inspect_image", request.name)
        self.assertIs(Risk.CAREFUL, request.risk)
        self.assertTrue(request.args["path"].endswith("photo.png"))


class _FakeBrain:
    system_prompt = "system"

    @staticmethod
    def image_content(text, path):
        return text


class _FakeClient:
    model = "test/model"

    def __init__(self, calls):
        self.tool_calls = calls
        self.messages = []

    def complete(self, messages, tools, tool_choice):
        self.messages.append(messages)
        if len(self.messages) == 1:
            return {"message": {"role": "assistant", "content": None, "tool_calls": self.tool_calls}}
        return {"message": {"role": "assistant", "content": "finished"}}


if __name__ == "__main__":
    unittest.main()
