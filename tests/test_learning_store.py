import tempfile
import unittest
from pathlib import Path

from core.learning.store import ExperienceStore


class ExperienceStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "learning.db"
        self.store = ExperienceStore(self.db_path)
        self.store.start()

    def tearDown(self):
        self.store.close()
        self.temp_dir.cleanup()

    def test_learns_explicit_and_observed_style_preferences(self):
        for text in ["Status?", "Any news?", "Open Chrome", "CPU status", "Are you awake?"]:
            self.store.observe_user(text)
        self.store.observe_user("Reply in English and be more concise")
        self.store.observe_user("Don't call me Boss")

        context = self.store.adaptation_context("Give me a status update")

        self.assertIn("Preferred language: English", context)
        self.assertIn("Preferred answer length: concise", context)
        self.assertIn("Preferred form of address: no title", context)

    def test_feedback_is_attached_by_stable_response_id(self):
        first = self.store.record_response(
            "conversation", "conversation", "Explain CPU usage", "A long answer", True
        )
        second = self.store.record_response(
            "conversation", "conversation", "Explain CPU temperature", "A concise answer", True
        )

        self.assertTrue(self.store.set_feedback(1, response_id=second["response_id"]))
        context = self.store.adaptation_context("Explain CPU temperature")

        self.assertIn("positively rated exchange", context)
        self.assertIn("A concise answer", context)
        self.assertNotIn("A long answer", context)
        self.assertNotEqual(first["response_id"], second["response_id"])

    def test_negative_feedback_becomes_avoidance_guidance(self):
        target = self.store.record_response(
            "tool", "weather", "Check weather in KL", "Unhelpful weather reply", False
        )
        self.store.set_feedback(-1, response_id=target["response_id"])

        context = self.store.adaptation_context("Check weather in Kuala Lumpur")

        self.assertIn("Avoid repeating this negatively rated response pattern", context)

    def test_sensitive_text_is_not_retained_for_adaptation(self):
        self.store.observe_user("My API key is sk_1234567890")
        target = self.store.record_response(
            "conversation", "conversation", "My password is swordfish", "Noted", True
        )
        assistant_secret = self.store.record_response(
            "conversation", "conversation", "Show credentials", "API key: sk_1234567890", True
        )

        self.assertEqual("", target["response_id"])
        self.assertEqual("", assistant_secret["response_id"])
        self.assertEqual("", self.store.adaptation_context("password"))

    def test_profile_persists_across_restarts(self):
        self.store.observe_user("Please respond in English")
        self.store.close()
        self.store = ExperienceStore(self.db_path)
        self.store.start()

        context = self.store.adaptation_context("Hello")

        self.assertIn("Preferred language: English", context)


if __name__ == "__main__":
    unittest.main()
