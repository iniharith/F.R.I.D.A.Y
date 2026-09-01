import json
import re
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from core import config

_SECRET = re.compile(
    r"password|passcode|\bpin\b|api[ _-]?key|access[ _-]?token|secret|"
    r"private[ _-]?key|seed phrase|credit card|\bcvv\b|social security|"
    r"\b(?:sk|hf)_[a-zA-Z0-9_-]{8,}",
    re.IGNORECASE,
)
_WORDS = re.compile(r"[a-z0-9]{2,}", re.IGNORECASE)
_PROFILE_FIELDS = (
    "name|birthday|timezone|city|country|job|role|company|project|computer|"
    "laptop|gpu|editor|language|pet|pronouns"
)


class MemoryStore:
    def __init__(self, db_path: Path = config.DB_PATH) -> None:
        self.db_path = db_path
        self.session_id: str | None = None
        self._db_lock = threading.RLock()
        self._model_lock = threading.RLock()
        self._embedder = None
        self._embedding_failed = False
        self._init_db()
        self._recover_sessions()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=20)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=10000")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._db_lock, self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS memory_facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT NOT NULL UNIQUE,
                    category TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    source TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    embedding BLOB,
                    active INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS memory_sessions (
                    id TEXT PRIMARY KEY,
                    started_at REAL NOT NULL,
                    ended_at REAL
                );
                CREATE TABLE IF NOT EXISTS memory_interactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS memory_episodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL UNIQUE,
                    summary TEXT NOT NULL,
                    embedding BLOB,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_memory_facts_active
                    ON memory_facts(active, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_memory_interactions_session
                    ON memory_interactions(session_id, created_at);
                """
            )

    def _get_embedder(self):
        if self._embedding_failed:
            return None
        with self._model_lock:
            if self._embedder is not None:
                return self._embedder
            try:
                from sentence_transformers import SentenceTransformer

                self._embedder = SentenceTransformer(
                    str(config.MEMORY_MODEL_DIR),
                    device="cpu",
                    local_files_only=True,
                )
            except Exception as exc:
                print(f"[FRIDAY] semantic memory fallback: {exc.__class__.__name__}")
                self._embedding_failed = True
                return None
            return self._embedder

    def _vector(self, text: str):
        model = self._get_embedder()
        if model is None:
            return None
        try:
            import numpy as np

            with self._model_lock:
                vector = model.encode(
                    text,
                    normalize_embeddings=True,
                    convert_to_numpy=True,
                    show_progress_bar=False,
                )
            return np.asarray(vector, dtype=np.float32)
        except Exception:
            return None

    @staticmethod
    def _blob(vector) -> bytes | None:
        return None if vector is None else vector.astype("float32").tobytes()

    @staticmethod
    def _unblob(blob):
        if blob is None:
            return None
        import numpy as np

        return np.frombuffer(blob, dtype=np.float32)

    def start_session(self) -> str:
        if self.session_id is not None:
            return self.session_id
        self.session_id = uuid.uuid4().hex
        with self._db_lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO memory_sessions(id, started_at) VALUES (?, ?)",
                (self.session_id, time.time()),
            )
        return self.session_id

    def record(self, role: str, content: str, source: str = "chat") -> None:
        content = content.strip()
        if not content or _SECRET.search(content):
            return
        session_id = self.start_session()
        with self._db_lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_interactions(
                    session_id, role, content, source, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, role, content, source, time.time()),
            )

    def _recover_sessions(self) -> None:
        with self._connect() as conn:
            ids = [
                row[0]
                for row in conn.execute(
                    "SELECT id FROM memory_sessions WHERE ended_at IS NULL"
                ).fetchall()
            ]
        for session_id in ids:
            self._close_session_id(session_id)

    def close_session(self) -> None:
        session_id = self.session_id
        self.session_id = None
        if session_id is not None:
            self._close_session_id(session_id)

    def _close_session_id(self, session_id: str) -> None:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT role, content FROM memory_interactions
                WHERE session_id = ? ORDER BY created_at
                """,
                (session_id,),
            ).fetchall()
        ended = time.time()
        if not rows:
            with self._db_lock, self._connect() as conn:
                conn.execute(
                    "UPDATE memory_sessions SET ended_at = ? WHERE id = ?",
                    (ended, session_id),
                )
            return
        selected = rows[-12:]
        summary = " | ".join(
            f"{'Boss' if row['role'] == 'user' else 'FRIDAY'}: {row['content'][:220]}"
            for row in selected
        )[:2200]
        vector = self._vector(summary)
        with self._db_lock, self._connect() as conn:
            conn.execute(
                "UPDATE memory_sessions SET ended_at = ? WHERE id = ?",
                (ended, session_id),
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO memory_episodes(
                    session_id, summary, embedding, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (session_id, summary, self._blob(vector), ended),
            )

    @staticmethod
    def _clean(text: str) -> str:
        text = re.sub(r"\s+", " ", text).strip(" \t\r\n,;:")
        return text[:400]

    @staticmethod
    def _sentence(text: str) -> str:
        text = MemoryStore._clean(text)
        if text and text[-1] not in ".!?":
            text += "."
        return text

    def capture(self, text: str) -> dict:
        text = self._clean(text)
        if not text:
            return {"facts": [], "blocked": False}
        if _SECRET.search(text):
            return {"facts": [], "blocked": True}

        candidates: list[tuple[str, str, float, str]] = []
        explicit = re.search(r"\bremember(?: that| this)?\s+(.+)", text, re.IGNORECASE)
        if explicit:
            fact = explicit.group(1)
            if re.match(r"^my\b", fact, re.IGNORECASE):
                fact = re.sub(r"^my\b", "The user's", fact, flags=re.IGNORECASE)
            elif re.match(r"^i\b", fact, re.IGNORECASE):
                fact = re.sub(r"^i\b", "The user", fact, flags=re.IGNORECASE)
            candidates.append((self._sentence(fact), "explicit", 1.0, "explicit"))
        else:
            patterns = [
                (
                    r"\bmy name is\s+([^.!?]+)",
                    lambda m: f"The user's name is {m.group(1)}",
                    "identity",
                ),
                (
                    r"\bcall me\s+([^.!?]+)",
                    lambda m: f"The user prefers to be called {m.group(1)}",
                    "identity",
                ),
                (
                    r"\bi (?:prefer|like|love|enjoy)\s+([^.!?]+)",
                    lambda m: f"The user prefers {m.group(1)}",
                    "preference",
                ),
                (
                    r"\bi (?:dislike|hate|do not like|don't like)\s+(?:you to\s+)?([^.!?]+)",
                    lambda m: f"The user dislikes {m.group(1)}",
                    "preference",
                ),
                (
                    r"\bi (?:do not want|don't want|want to avoid|don't send|do not send|never send|stop sending)\s+(?:you to\s+)?([^.!?]+)",
                    lambda m: f"The user does not want {m.group(1)}",
                    "preference",
                ),
                (
                    r"\b(?:please )?(?:do not|don't|never|stop)\s+(?:use|send|include|using|sending|including)\s+(?:any\s+)?([^.!?]+)",
                    lambda m: f"The user does not want {m.group(1)}",
                    "preference",
                ),
                (
                    r"\bi (?:live|am based) in\s+([^.!?]+)",
                    lambda m: f"The user lives in {m.group(1)}",
                    "location",
                ),
                (
                    r"\bi work (?:at|for|as)\s+([^.!?]+)",
                    lambda m: f"The user's work is {m.group(1)}",
                    "work",
                ),
                (
                    r"\bi use\s+([^.!?]+)",
                    lambda m: f"The user uses {m.group(1)}",
                    "environment",
                ),
                (
                    rf"\bmy ({_PROFILE_FIELDS}) is\s+([^.!?]+)",
                    lambda m: f"The user's {m.group(1)} is {m.group(2)}",
                    "profile",
                ),
            ]
            for pattern, formatter, category in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    candidates.append(
                        (self._sentence(formatter(match)), category, 0.9, "auto")
                    )

        saved: list[dict] = []
        seen: set[str] = set()
        for fact, category, confidence, source in candidates:
            key = fact.lower()
            if not fact or key in seen or _SECRET.search(fact):
                continue
            seen.add(key)
            saved.append(self.remember_fact(fact, category, confidence, source))
        return {"facts": saved, "blocked": False}

    def remember_fact(
        self,
        text: str,
        category: str = "general",
        confidence: float = 0.8,
        source: str = "auto",
    ) -> dict:
        text = self._sentence(text)
        now = time.time()
        vector = self._vector(text)
        with self._db_lock, self._connect() as conn:
            exact = conn.execute(
                "SELECT id, text FROM memory_facts WHERE lower(text) = lower(?)",
                (text,),
            ).fetchone()
            if exact:
                conn.execute(
                    """
                    UPDATE memory_facts SET active = 1, updated_at = ?,
                    confidence = MAX(confidence, ?), source = ?, embedding = ?
                    WHERE id = ?
                    """,
                    (now, confidence, source, self._blob(vector), exact["id"]),
                )
                return {
                    "id": exact["id"],
                    "text": exact["text"],
                    "category": category,
                    "new": False,
                }

            if vector is not None:
                rows = conn.execute(
                    "SELECT id, text, category, embedding FROM memory_facts WHERE active = 1"
                ).fetchall()
                for row in rows:
                    existing = self._unblob(row["embedding"])
                    if existing is not None and float(existing @ vector) >= 0.94:
                        conn.execute(
                            "UPDATE memory_facts SET updated_at = ? WHERE id = ?",
                            (now, row["id"]),
                        )
                        return {
                            "id": row["id"],
                            "text": row["text"],
                            "category": row["category"],
                            "new": False,
                        }

            cursor = conn.execute(
                """
                INSERT INTO memory_facts(
                    text, category, confidence, source, created_at,
                    updated_at, embedding, active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    text,
                    category,
                    confidence,
                    source,
                    now,
                    now,
                    self._blob(vector),
                ),
            )
            return {
                "id": cursor.lastrowid,
                "text": text,
                "category": category,
                "new": True,
            }

    @staticmethod
    def _lexical_score(query: str, text: str) -> float:
        q = set(_WORDS.findall(query.lower()))
        t = set(_WORDS.findall(text.lower()))
        if not q or not t:
            return 0.0
        return len(q & t) / max(len(q), 1)

    def _rank(self, rows: list[sqlite3.Row], query: str, text_key: str, limit: int):
        if not rows:
            return []
        vector = self._vector(query)
        scored = []
        for row in rows:
            score = self._lexical_score(query, row[text_key])
            existing = self._unblob(row["embedding"])
            if vector is not None and existing is not None:
                score = max(score, float(existing @ vector))
            scored.append((score, row))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [row for score, row in scored[:limit] if score >= 0.12]

    def context_for(self, query: str) -> str:
        with self._connect() as conn:
            facts = conn.execute(
                """
                SELECT id, text, category, embedding, updated_at
                FROM memory_facts WHERE active = 1 ORDER BY updated_at DESC
                """
            ).fetchall()
            episodes = conn.execute(
                """
                SELECT summary, embedding, created_at FROM memory_episodes
                ORDER BY created_at DESC LIMIT 30
                """
            ).fetchall()

        generic = bool(
            re.search(r"what do you (?:know|remember)|about me|your memory", query, re.I)
        )
        ranked_facts = facts[: config.MEMORY_CONTEXT_FACTS] if generic else self._rank(
            facts, query, "text", config.MEMORY_CONTEXT_FACTS
        )
        identity = [
            row
            for row in facts
            if row["category"] in {"identity", "preference"}
            and row not in ranked_facts
        ][:2]
        ranked_facts = (identity + ranked_facts)[: config.MEMORY_CONTEXT_FACTS]
        ranked_episodes = self._rank(
            episodes, query, "summary", config.MEMORY_CONTEXT_EPISODES
        )

        blocks = []
        if ranked_facts:
            blocks.append(
                "Relevant durable facts:\n"
                + "\n".join(f"- {row['text']}" for row in ranked_facts)
            )
        if ranked_episodes:
            blocks.append(
                "Relevant previous sessions:\n"
                + "\n".join(f"- {row['summary']}" for row in ranked_episodes)
            )
        return "\n\n".join(blocks)[:3000]

    def list_facts(self, limit: int = 100) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, text, category, source, created_at, updated_at
                FROM memory_facts WHERE active = 1
                ORDER BY updated_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def forget(self, fact_id: int) -> bool:
        with self._db_lock, self._connect() as conn:
            cursor = conn.execute(
                "UPDATE memory_facts SET active = 0 WHERE id = ? AND active = 1",
                (fact_id,),
            )
            return cursor.rowcount > 0

    def stats(self) -> dict:
        with self._connect() as conn:
            facts = conn.execute(
                "SELECT COUNT(*) FROM memory_facts WHERE active = 1"
            ).fetchone()[0]
            episodes = conn.execute(
                "SELECT COUNT(*) FROM memory_episodes"
            ).fetchone()[0]
        return {"facts": facts, "episodes": episodes}

    def clear(self) -> None:
        self.session_id = None
        with self._db_lock, self._connect() as conn:
            conn.execute("DELETE FROM memory_facts")
            conn.execute("DELETE FROM memory_episodes")
            conn.execute("DELETE FROM memory_interactions")
            conn.execute("DELETE FROM memory_sessions")

    def export_json(self) -> str:
        return json.dumps(
            {"facts": self.list_facts(), "stats": self.stats()},
            indent=2,
        )


memory_store = MemoryStore()
