from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from core import config


_SECRET = re.compile(
    r"password|passcode|\bpin\b|api[ _-]?key|access[ _-]?token|secret|"
    r"private[ _-]?key|seed phrase|credit card|\bcvv\b|"
    r"\b(?:sk|hf)_[a-zA-Z0-9_-]{8,}",
    re.IGNORECASE,
)
_WORDS = re.compile(r"[a-zA-Z0-9']+")


class ExperienceStore:
    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or config.DATA_DIR / "learning.db"
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.RLock()

    def start(self) -> None:
        with self._lock:
            if self._conn is not None:
                return
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS experiences (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    action TEXT NOT NULL,
                    context TEXT NOT NULL,
                    result TEXT NOT NULL,
                    success INTEGER NOT NULL DEFAULT 1,
                    feedback INTEGER DEFAULT NULL
                )
            """)
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS tool_fixes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    file_path TEXT NOT NULL,
                    old_code TEXT NOT NULL,
                    new_code TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    verified INTEGER NOT NULL DEFAULT 0
                )
            """)
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS adaptive_responses (
                    response_id TEXT PRIMARY KEY,
                    timestamp REAL NOT NULL,
                    kind TEXT NOT NULL,
                    action TEXT NOT NULL,
                    user_text TEXT NOT NULL,
                    assistant_text TEXT NOT NULL,
                    success INTEGER NOT NULL DEFAULT 1,
                    feedback INTEGER DEFAULT NULL
                )
            """)
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS adaptive_preferences (
                    name TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    evidence_count INTEGER NOT NULL DEFAULT 1,
                    updated_at REAL NOT NULL
                )
            """)
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS adaptive_signals (
                    name TEXT PRIMARY KEY,
                    total REAL NOT NULL DEFAULT 0,
                    samples INTEGER NOT NULL DEFAULT 0
                )
            """)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            if self._conn:
                self._conn.close()
                self._conn = None

    def _signal(self, name: str, value: float) -> None:
        if not self._conn:
            return
        self._conn.execute(
            """
            INSERT INTO adaptive_signals (name, total, samples) VALUES (?, ?, 1)
            ON CONFLICT(name) DO UPDATE SET
                total = total + excluded.total,
                samples = samples + 1
            """,
            (name, value),
        )

    def _preference(self, name: str, value: str, confidence: float = 1.0) -> None:
        if not self._conn:
            return
        self._conn.execute(
            """
            INSERT INTO adaptive_preferences
                (name, value, confidence, evidence_count, updated_at)
            VALUES (?, ?, ?, 1, ?)
            ON CONFLICT(name) DO UPDATE SET
                value = excluded.value,
                confidence = excluded.confidence,
                evidence_count = adaptive_preferences.evidence_count + 1,
                updated_at = excluded.updated_at
            """,
            (name, value, confidence, time.time()),
        )

    def observe_user(self, text: str) -> None:
        """Learn low-risk communication preferences, never message content."""
        if not self._conn or not text.strip() or _SECRET.search(text):
            return
        words = [word.lower() for word in _WORDS.findall(text)]
        if not words:
            return
        lower = " ".join(words)
        with self._lock:
            self._signal("message_words", float(len(words)))
            self._signal("uppercase", 1.0 if text.isupper() and len(text) > 4 else 0.0)

            language = re.search(
                r"(?:reply|respond|speak|answer)(?: to me)? in english\b",
                lower,
            )
            if language:
                self._preference("language", "English")

            if re.search(r"\b(?:be|keep it|reply|respond) (?:more )?(?:brief|concise|short)\b", lower):
                self._preference("verbosity", "concise")
            elif re.search(r"\b(?:be more detailed|give more detail|explain in detail|longer answers?)\b", lower):
                self._preference("verbosity", "detailed")

            if re.search(r"\b(?:be|sound) (?:more )?(?:casual|relaxed)\b", lower):
                self._preference("tone", "casual")
            elif re.search(r"\b(?:be|sound) (?:more )?(?:formal|professional)\b", lower):
                self._preference("tone", "professional")

            address = re.search(r"\b(?:call|address) me (?:as )?([a-z][a-z0-9 _-]{0,30})", lower)
            if re.search(r"\b(?:do not|don't|stop) call(?:ing)? me boss\b", lower):
                self._preference("address", "no title")
            elif address:
                value = address.group(1).strip().title()
                if value not in {"Something", "Anything"}:
                    self._preference("address", value)
            self._conn.commit()

    def log_action(self, action: str, context: str, result: str, success: bool = True) -> float:
        timestamp = time.time()
        if not self._conn:
            return timestamp
        with self._lock:
            if _SECRET.search(context):
                context = "Sensitive action context omitted"
            if _SECRET.search(result):
                result = "Sensitive action result omitted"
            self._conn.execute(
                "INSERT INTO experiences (timestamp, action, context, result, success) VALUES (?, ?, ?, ?, ?)",
                (timestamp, action, context, result, 1 if success else 0),
            )
            self._conn.commit()
        return timestamp

    def record_response(
        self,
        kind: str,
        action: str,
        user_text: str,
        assistant_text: str,
        success: bool = True,
    ) -> dict:
        response_id = uuid.uuid4().hex
        timestamp = time.time()
        if not self._conn or _SECRET.search(user_text) or _SECRET.search(assistant_text):
            return {"response_id": "", "timestamp": timestamp}
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO adaptive_responses
                    (response_id, timestamp, kind, action, user_text, assistant_text, success)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    response_id,
                    timestamp,
                    kind[:30],
                    action[:80],
                    user_text[:2000],
                    assistant_text[:4000],
                    1 if success else 0,
                ),
            )
            self._conn.execute(
                """
                DELETE FROM adaptive_responses WHERE response_id IN (
                    SELECT response_id FROM adaptive_responses
                    ORDER BY timestamp DESC LIMIT -1 OFFSET 500
                )
                """
            )
            self._conn.commit()
        return {"response_id": response_id, "timestamp": timestamp}

    def log_fix(self, file_path: str, old_code: str, new_code: str, reason: str) -> None:
        if not self._conn:
            return
        with self._lock:
            self._conn.execute(
                "INSERT INTO tool_fixes (timestamp, file_path, old_code, new_code, reason) VALUES (?, ?, ?, ?, ?)",
                (time.time(), file_path, old_code, new_code, reason),
            )
            self._conn.commit()

    def set_feedback(
        self,
        feedback: int,
        response_id: str = "",
        action_timestamp: float = 0.0,
    ) -> bool:
        if not self._conn or feedback not in {-1, 1}:
            return False
        with self._lock:
            changed = 0
            if response_id:
                cursor = self._conn.execute(
                    "UPDATE adaptive_responses SET feedback = ? WHERE response_id = ?",
                    (feedback, response_id),
                )
                changed = cursor.rowcount
            elif action_timestamp:
                row = self._conn.execute(
                    """
                    SELECT response_id FROM adaptive_responses
                    WHERE timestamp BETWEEN ? - 30 AND ? + 30
                    ORDER BY ABS(timestamp - ?) LIMIT 1
                    """,
                    (action_timestamp, action_timestamp, action_timestamp),
                ).fetchone()
                if row:
                    self._conn.execute(
                        "UPDATE adaptive_responses SET feedback = ? WHERE response_id = ?",
                        (feedback, row[0]),
                    )
                    changed = 1
                self._conn.execute(
                    "UPDATE experiences SET feedback = ? WHERE ABS(timestamp - ?) < 5.0",
                    (feedback, action_timestamp),
                )
            self._conn.commit()
        return bool(changed)

    def get_recent_fixes(self, file_path: str, limit: int = 5) -> list[dict]:
        if not self._conn:
            return []
        with self._lock:
            cursor = self._conn.execute(
                "SELECT file_path, old_code, new_code, reason, verified FROM tool_fixes WHERE file_path = ? ORDER BY timestamp DESC LIMIT ?",
                (file_path, limit),
            )
            return [
                {"file": r[0], "old": r[1], "new": r[2], "reason": r[3], "verified": bool(r[4])}
                for r in cursor.fetchall()
            ]

    def get_stats(self) -> dict:
        if not self._conn:
            return {"total_actions": 0, "successful": 0, "failed": 0, "fixes": 0, "rated": 0}
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) FROM experiences").fetchone()[0]
            successful = self._conn.execute("SELECT COUNT(*) FROM experiences WHERE success = 1").fetchone()[0]
            fixes = self._conn.execute("SELECT COUNT(*) FROM tool_fixes").fetchone()[0]
            rated = self._conn.execute(
                "SELECT COUNT(*) FROM adaptive_responses WHERE feedback IS NOT NULL"
            ).fetchone()[0]
        return {
            "total_actions": total,
            "successful": successful,
            "failed": total - successful,
            "fixes": fixes,
            "rated": rated,
        }

    def context_for(self, action: str) -> str:
        if not self._conn:
            return ""
        with self._lock:
            cursor = self._conn.execute(
                """
                SELECT context, result, success, feedback FROM experiences
                WHERE action = ?
                ORDER BY CASE WHEN feedback IS NOT NULL THEN 0 ELSE 1 END, timestamp DESC
                LIMIT 4
                """,
                (action,),
            )
            rows = cursor.fetchall()
        if not rows:
            return ""
        lines = [f"Past verified outcomes for '{action}':"]
        for ctx, result, ok, feedback in rows:
            status = "succeeded" if ok else "failed"
            rating = " positively rated" if feedback == 1 else " negatively rated" if feedback == -1 else ""
            lines.append(f"- {ctx} -> {status}{rating}: {result[:160]}")
        return "\n".join(lines)

    def adaptation_context(self, user_text: str) -> str:
        if not self._conn:
            return ""
        with self._lock:
            preferences = self._conn.execute(
                "SELECT name, value FROM adaptive_preferences ORDER BY updated_at DESC"
            ).fetchall()
            signals = {
                name: (total / samples if samples else 0.0, samples)
                for name, total, samples in self._conn.execute(
                    "SELECT name, total, samples FROM adaptive_signals"
                ).fetchall()
            }
            rated = self._conn.execute(
                """
                SELECT user_text, assistant_text, feedback FROM adaptive_responses
                WHERE feedback IS NOT NULL ORDER BY timestamp DESC LIMIT 30
                """
            ).fetchall()

        lines = ["Learned interaction guidance (soft preferences; the current request always wins):"]
        labels = {
            "language": "Preferred language",
            "verbosity": "Preferred answer length",
            "tone": "Preferred tone",
            "address": "Preferred form of address",
        }
        for name, value in preferences:
            if name in labels:
                lines.append(f"- {labels[name]}: {value}.")

        words_avg, samples = signals.get("message_words", (0.0, 0))
        if samples >= 5 and not any(name == "verbosity" for name, _ in preferences):
            if words_avg <= 12:
                lines.append("- The user usually communicates briefly; default to concise answers.")
            elif words_avg >= 45:
                lines.append("- The user often provides detail; preserve useful context in answers.")

        query_words = set(_WORDS.findall(user_text.lower()))
        scored: list[tuple[float, str, str, int]] = []
        for past_user, assistant, feedback in rated:
            past_words = set(_WORDS.findall(past_user.lower()))
            union = query_words | past_words
            similarity = len(query_words & past_words) / len(union) if union else 0.0
            if similarity > 0.08:
                scored.append((similarity, past_user, assistant, feedback))
        scored.sort(key=lambda item: item[0], reverse=True)
        for _, past_user, assistant, feedback in scored[:2]:
            if feedback == 1:
                lines.append(
                    f"- A similar positively rated exchange was: request '{past_user[:120]}'; "
                    f"response style '{assistant[:180]}'. Follow the useful pattern, not the wording verbatim."
                )
            else:
                lines.append(
                    f"- Avoid repeating this negatively rated response pattern for '{past_user[:120]}': "
                    f"'{assistant[:180]}'."
                )
        return "\n".join(lines) if len(lines) > 1 else ""

    def clear(self) -> None:
        if not self._conn:
            return
        with self._lock:
            for table in (
                "experiences",
                "tool_fixes",
                "adaptive_responses",
                "adaptive_preferences",
                "adaptive_signals",
            ):
                self._conn.execute(f"DELETE FROM {table}")
            self._conn.commit()

    def export_data(self) -> dict:
        if not self._conn:
            return {"preferences": [], "responses": [], "stats": self.get_stats()}
        with self._lock:
            preferences = [
                {"name": row[0], "value": row[1], "confidence": row[2], "evidence_count": row[3]}
                for row in self._conn.execute(
                    "SELECT name, value, confidence, evidence_count FROM adaptive_preferences"
                ).fetchall()
            ]
            responses = [
                {
                    "response_id": row[0],
                    "timestamp": row[1],
                    "kind": row[2],
                    "action": row[3],
                    "user_text": row[4],
                    "assistant_text": row[5],
                    "success": bool(row[6]),
                    "feedback": row[7],
                }
                for row in self._conn.execute(
                    """
                    SELECT response_id, timestamp, kind, action, user_text,
                           assistant_text, success, feedback
                    FROM adaptive_responses ORDER BY timestamp
                    """
                ).fetchall()
            ]
        return {"preferences": preferences, "responses": responses, "stats": self.get_stats()}

    def export_json(self) -> str:
        return json.dumps(self.export_data(), indent=2)


experience_store = ExperienceStore()
