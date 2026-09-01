import tempfile
import unittest
from pathlib import Path

from core.skills.store import SkillStore


class SkillStoreTests(unittest.TestCase):
    def test_loads_agentskills_style_file_and_selects_relevant_skill(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill_dir = root / "coding"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(
                "---\nname: Coding\ndescription: debug code repository\n---\nInspect, edit, test.\n",
                encoding="utf-8",
            )
            store = SkillStore((root,))

            skills = store.relevant("Please debug this code")
            prompt = store.prompt_for("debug code")

        self.assertEqual("Coding", skills[0].name)
        self.assertIn("Inspect, edit, test.", prompt)

    def test_ignores_empty_skill(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill_dir = root / "empty"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text("", encoding="utf-8")
            self.assertEqual([], SkillStore((root,)).list())


if __name__ == "__main__":
    unittest.main()
