import asyncio
import sqlite3
import time
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from pathlib import Path

from core import config

Notify = Callable[[str], Awaitable[None]]


class ReminderScheduler:
    def __init__(self, notify: Notify, db_path: Path = config.DB_PATH) -> None:
        self.notify = notify
        self.db_path = db_path
        self._tasks: dict[int, asyncio.Task] = {}
        self._init_db()

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
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS task_reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message TEXT NOT NULL,
                    due_at REAL NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at REAL NOT NULL
                )
                """
            )

    async def start(self) -> None:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, message, due_at FROM task_reminders
                WHERE status = 'pending' ORDER BY due_at
                """
            ).fetchall()
        for row in rows:
            self._schedule(row["id"], row["message"], row["due_at"])

    async def add(self, seconds: float, message: str) -> int:
        due_at = time.time() + max(seconds, 0.0)
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO task_reminders(message, due_at, status, created_at)
                VALUES (?, ?, 'pending', ?)
                """,
                (message, due_at, time.time()),
            )
            reminder_id = int(cursor.lastrowid)
        self._schedule(reminder_id, message, due_at)
        return reminder_id

    def _schedule(self, reminder_id: int, message: str, due_at: float) -> None:
        existing = self._tasks.pop(reminder_id, None)
        if existing is not None:
            existing.cancel()
        task = asyncio.create_task(self._wait(reminder_id, message, due_at))
        self._tasks[reminder_id] = task

        def cleanup(done: asyncio.Task) -> None:
            if self._tasks.get(reminder_id) is done:
                self._tasks.pop(reminder_id, None)

        task.add_done_callback(cleanup)

    async def _wait(self, reminder_id: int, message: str, due_at: float) -> None:
        try:
            await asyncio.sleep(max(0.0, due_at - time.time()))
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT status FROM task_reminders WHERE id = ?",
                    (reminder_id,),
                ).fetchone()
                if row is None or row["status"] != "pending":
                    return
                conn.execute(
                    "UPDATE task_reminders SET status = 'fired' WHERE id = ?",
                    (reminder_id,),
                )
            await self.notify(message)
        except asyncio.CancelledError:
            raise

    def list_pending(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, message, due_at FROM task_reminders
                WHERE status = 'pending' ORDER BY due_at
                """
            ).fetchall()
        return [dict(row) for row in rows]

    async def cancel_all(self) -> int:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id FROM task_reminders WHERE status = 'pending'"
            ).fetchall()
            conn.execute(
                "UPDATE task_reminders SET status = 'cancelled' WHERE status = 'pending'"
            )
        active = list(self._tasks.values())
        for task in active:
            task.cancel()
        if active:
            await asyncio.gather(*active, return_exceptions=True)
        self._tasks.clear()
        return len(rows)

    async def close(self) -> None:
        for task in tuple(self._tasks.values()):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()
