import unittest
from unittest.mock import patch

from core import config
from core.hud import server


class RuntimeTuningTests(unittest.TestCase):
    def setUp(self):
        self.original = {
            "temperature": config.GEN_TEMPERATURE,
            "top_p": config.GEN_TOP_P,
            "max_new_tokens": config.MAX_NEW_TOKENS,
            "cloud_max_tokens": config.OPENROUTER_MAX_TOKENS,
            "context_turns": config.CONTEXT_HISTORY_TURNS,
            "brain_max_new_tokens": server.brain.max_new_tokens,
        }

    def tearDown(self):
        config.GEN_TEMPERATURE = self.original["temperature"]
        config.GEN_TOP_P = self.original["top_p"]
        config.MAX_NEW_TOKENS = self.original["max_new_tokens"]
        config.OPENROUTER_MAX_TOKENS = self.original["cloud_max_tokens"]
        config.CONTEXT_HISTORY_TURNS = self.original["context_turns"]
        server.brain.max_new_tokens = self.original["brain_max_new_tokens"]

    @patch("core.hud.server._save_runtime_settings")
    def test_runtime_tuning_applies_and_persists(self, save_mock):
        result = server._apply_runtime_tuning(
            {
                "temperature": 0.4,
                "top_p": 0.8,
                "max_new_tokens": 640,
                "context_turns": 8,
            }
        )

        self.assertEqual(0.4, config.GEN_TEMPERATURE)
        self.assertEqual(0.8, config.GEN_TOP_P)
        self.assertEqual(640, config.OPENROUTER_MAX_TOKENS)
        self.assertEqual(640, server.brain.max_new_tokens)
        self.assertEqual(8, config.CONTEXT_HISTORY_TURNS)
        self.assertEqual(result, save_mock.call_args.args[0]["tuning"])

    def test_runtime_tuning_rejects_out_of_range_values(self):
        invalid = {
            "temperature": 2.1,
            "top_p": 0.8,
            "max_new_tokens": 640,
            "context_turns": 8,
        }
        with self.assertRaisesRegex(ValueError, "Temperature"):
            server._apply_runtime_tuning(invalid, persist=False)
        self.assertEqual(self.original["temperature"], config.GEN_TEMPERATURE)


class MobileModeSnapshotTests(unittest.TestCase):
    def tearDown(self):
        server.openrouter_client.set_mode(None)

    def test_snapshot_distinguishes_selected_and_effective_mode(self):
        with patch.object(server.openrouter_client, "api_key", ""), patch.object(
            server.openrouter_client, "fallback_api_key", ""
        ):
            server.openrouter_client.set_mode("openrouter")
            snapshot = server._mode_snapshot()

        self.assertEqual("openrouter", snapshot["selected_mode"])
        self.assertEqual("local", snapshot["effective_mode"])
        self.assertFalse(snapshot["cloud_available"])


if __name__ == "__main__":
    unittest.main()
