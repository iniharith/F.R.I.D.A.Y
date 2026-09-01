import unittest
from unittest.mock import patch

from core import config
from core.brain.cloud import OpenRouterClient


class OpenRouterClientModeTests(unittest.TestCase):
    def setUp(self):
        self.client = OpenRouterClient.__new__(OpenRouterClient)
        self.client._explicit_api_key = False
        self.client._runtime_mode = None
        self.client.api_key = "sk-or-test"
        self.client.model = "z-ai/glm-5.3-flash"
        self.client.base_url = "https://openrouter.ai/api/v1"
        self.client.timeout = 60.0
        self.client.fallback_api_key = ""
        self.client.fallback_model = "z-ai/glm-5.3-flash"
        self.client.fallback_base_url = "https://inference-api.nousresearch.com/v1"

    def test_default_mode_follows_config(self):
        with patch.object(config, "REASONING_MODE", "local"):
            self.assertEqual("local", "local")
            self.assertFalse(self.client.enabled)
        with patch.object(config, "REASONING_MODE", "openrouter"):
            self.assertTrue(self.client.enabled)

    def test_set_mode_overrides_config_at_runtime(self):
        with patch.object(config, "REASONING_MODE", "local"):
            self.assertFalse(self.client.enabled)
            self.client.set_mode("openrouter")
            self.assertTrue(self.client.enabled)
            self.client.set_mode("local")
            self.assertFalse(self.client.enabled)

    def test_set_mode_rejects_invalid_values(self):
        self.client._runtime_mode = "openrouter"
        self.client.set_mode("bogus")
        self.assertIsNone(self.client._runtime_mode)

    def test_set_mode_none_restores_config_behavior(self):
        with patch.object(config, "REASONING_MODE", "openrouter"):
            self.client.set_mode("local")
            self.assertFalse(self.client.enabled)
            self.client.set_mode(None)
            self.assertTrue(self.client.enabled)


class SettingsModeEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from core.hud import server

        cls.client = TestClient(server.app)
        cls.server = server

    def tearDown(self):
        self.server.openrouter_client.set_mode(None)

    @patch(
        "core.hud.server.RUNTIME_SETTINGS_FILE",
        new=lambda: None,
    )
    def test_valid_mode_switches_runtime(self):
        response = self.client.post("/settings/mode?mode=openrouter")
        self.assertEqual(200, response.status_code)
        self.assertEqual("openrouter", response.json()["reasoning"])
        response = self.client.post("/settings/mode?mode=local")
        self.assertEqual(200, response.status_code)
        self.assertEqual("local", response.json()["reasoning"])

    @patch(
        "core.hud.server.RUNTIME_SETTINGS_FILE",
        new=lambda: None,
    )
    def test_invalid_mode_rejected(self):
        response = self.client.post("/settings/mode?mode=bogus")
        self.assertEqual(422, response.status_code)

    @patch("core.hud.server._save_runtime_reasoning_mode")
    def test_mode_switch_persists(self, save_mock):
        self.client.post("/settings/mode?mode=openrouter")
        save_mock.assert_called_once_with("openrouter")


if __name__ == "__main__":
    unittest.main()
