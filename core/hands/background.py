"""Background subagent runner.

Lets FRIDAY start long-running work (builds, scans, downloads, scripts) as a
detached OS process without blocking the conversation. Output is streamed to a
log file per task; the HUD server polls for completion and notifies the Boss.
"""

from __future__ import annotations

import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from core import config
from core.hands.tools import is_blocked_command

MAX_CONCURRENT_TASKS = 5
OUTPUT_TAIL_CHARS = 4000


@dataclass
class BackgroundTask:
    id: str
    command: str
    label: str
    cwd: str
    process: subprocess.Popen
    output_file: Path
    log_handle: object = field(repr=False, default=None)
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    exit_code: int | None = None

    @property
    def state(self) -> str:
        if self.exit_code is None:
            return "running"
        return "done" if self.exit_code == 0 else "failed"

    def as_dict(self, output_chars: int = OUTPUT_TAIL_CHARS) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "command": self.command,
            "cwd": self.cwd,
            "state": self.state,
            "exit_code": self.exit_code,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "log": str(self.output_file),
            "output_tail": self.output_tail(output_chars),
        }

    def output_tail(self, chars: int = OUTPUT_TAIL_CHARS) -> str:
        try:
            text = self.output_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        return text[-chars:] if len(text) > chars else text


class BackgroundManager:
    """Owns detached background processes and their status."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = Path(base_dir) if base_dir else config.DATA_DIR / "background_tasks"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._tasks: dict[str, BackgroundTask] = {}
        self._lock = threading.Lock()

    def start(self, command: str, cwd: str = "", label: str = "") -> BackgroundTask:
        cleaned = str(command or "").strip()
        if not cleaned:
            raise ValueError("A background task needs a command, Boss.")
        if is_blocked_command(cleaned):
            raise ValueError("I blocked that command — it's too destructive to run, Boss.")
        with self._lock:
            running = sum(1 for task in self._tasks.values() if task.exit_code is None)
            if running >= MAX_CONCURRENT_TASKS:
                raise ValueError(
                    f"Too many background tasks are already running (max {MAX_CONCURRENT_TASKS}), Boss."
                )
        task_id = uuid.uuid4().hex
        output_file = self.base_dir / f"{task_id}.log"
        log_handle = open(output_file, "ab")
        try:
            process = subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", cleaned],
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                cwd=cwd or None,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError:
            log_handle.close()
            raise
        task = BackgroundTask(
            id=task_id,
            command=cleaned,
            label=str(label or "").strip()[:80],
            cwd=cwd or "",
            process=process,
            output_file=output_file,
            log_handle=log_handle,
        )
        with self._lock:
            self._tasks[task_id] = task
        return task

    def poll(self) -> list[BackgroundTask]:
        """Mark newly finished tasks and return them (once each)."""
        finished: list[BackgroundTask] = []
        with self._lock:
            for task in self._tasks.values():
                if task.exit_code is not None:
                    continue
                try:
                    code = task.process.poll()
                except OSError:
                    code = -1
                if code is None:
                    continue
                task.exit_code = code
                task.finished_at = time.time()
                finished.append(task)
                try:
                    task.process.wait(timeout=1)
                except Exception:
                    pass
                try:
                    if task.log_handle is not None:
                        task.log_handle.close()
                        task.log_handle = None
                except OSError:
                    pass
        return finished

    def status(self, task_id: str = "") -> list[dict]:
        with self._lock:
            tasks = list(self._tasks.values())
        if task_id:
            wanted = task_id.strip().lower()
            tasks = [
                task for task in tasks
                if task.id == wanted or task.id.startswith(wanted)
            ]
        now_running = [task for task in tasks if task.exit_code is None]
        now_running.sort(key=lambda task: task.started_at, reverse=True)
        finished = [task for task in tasks if task.exit_code is not None]
        finished.sort(key=lambda task: task.finished_at or 0.0, reverse=True)
        return [task.as_dict() for task in now_running + finished]

    def running_count(self) -> int:
        with self._lock:
            return sum(1 for task in self._tasks.values() if task.exit_code is None)

    def kill_all(self) -> None:
        """Terminate every running background task (used on shutdown/tests)."""
        with self._lock:
            running = [
                task for task in self._tasks.values() if task.exit_code is None
            ]
        for task in running:
            try:
                task.process.kill()
            except OSError:
                pass
        self.poll()
