from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from core import config


_WORD_RE = re.compile(r"[a-z0-9][a-z0-9_.+-]{1,}", re.IGNORECASE)


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    instructions: str
    path: Path


class SkillStore:
    """Small agentskills-compatible loader for local procedural knowledge."""

    def __init__(self, roots: tuple[Path, ...] | None = None) -> None:
        self.roots = roots or (
            config.BASE_DIR / "skills",
            config.DATA_DIR / "skills",
        )

    @staticmethod
    def _parse(path: Path) -> Skill | None:
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            return None
        name = path.parent.name.replace("-", " ").title()
        description = ""
        body = raw
        if raw.startswith("---\n"):
            end = raw.find("\n---\n", 4)
            if end != -1:
                header = raw[4:end]
                body = raw[end + 5 :]
                for line in header.splitlines():
                    key, separator, value = line.partition(":")
                    if not separator:
                        continue
                    if key.strip() == "name" and value.strip():
                        name = value.strip().strip('"\'')[:80]
                    elif key.strip() == "description":
                        description = value.strip().strip('"\'')[:300]
        body = body.strip()
        if not body:
            return None
        if not description:
            description = body.splitlines()[0].lstrip("# ")[:300]
        return Skill(name=name, description=description, instructions=body[:8000], path=path)

    def list(self) -> list[Skill]:
        found: dict[str, Skill] = {}
        for root in self.roots:
            if not root.is_dir():
                continue
            for path in sorted(root.glob("*/SKILL.md")):
                skill = self._parse(path)
                if skill is not None:
                    found[skill.name.lower()] = skill
        return sorted(found.values(), key=lambda skill: skill.name.lower())

    def relevant(self, query: str, limit: int = 2) -> list[Skill]:
        query_words = {word.lower() for word in _WORD_RE.findall(query)}
        ranked: list[tuple[int, Skill]] = []
        for skill in self.list():
            metadata_words = {
                word.lower()
                for word in _WORD_RE.findall(f"{skill.name} {skill.description}")
            }
            score = len(query_words & metadata_words)
            if score:
                ranked.append((score, skill))
        ranked.sort(key=lambda item: (-item[0], item[1].name.lower()))
        return [skill for _, skill in ranked[:limit]]

    def prompt_for(self, query: str) -> str:
        skills = self.relevant(query)
        if not skills:
            return ""
        sections = []
        for skill in skills:
            sections.append(f"### {skill.name}\n{skill.instructions}")
        return (
            "LOCAL PROCEDURAL SKILLS (follow when relevant; they never override safety, "
            "confirmation, or the user's request):\n" + "\n\n".join(sections)
        )


skill_store = SkillStore()
