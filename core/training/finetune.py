"""Fine-tuning job manager (Unsloth-style QLoRA on Friday's conversation memory).

The real training runs in a subprocess (``core.training.train_run``) so a CUDA
failure or OOM can never take down the HUD server. The Boss controls it from
HUD -> Settings -> Fine-tuning.
"""

from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

from core import config

_SENSITIVE = re.compile(
    r"password|passcode|\bpin\b|api[ _-]?key|access[ _-]?token|secret|"
    r"private[ _-]?key|seed phrase|credit card|\bcvv\b",
    re.IGNORECASE,
)

ALLOWED_MODELS = (
    "unsloth/Qwen2.5-3B-Instruct",
    "unsloth/Qwen2.5-7B-Instruct",
    "unsloth/Llama-3.2-3B-Instruct",
    "unsloth/Phi-4-mini-instruct",
)

DEFAULTS = {
    "model": ALLOWED_MODELS[0],
    "lora_r": 16,
    "lora_alpha": 16,
    "lora_dropout": 0.05,
    "epochs": 1,
    "learning_rate": 2e-4,
    "batch_size": 2,
    "grad_accum": 4,
    "max_seq": 2048,
    "max_pairs": 2000,
    "export_gguf": True,
}

MIN_PAIRS = 10

state: dict = {
    "state": "idle",
    "message": "",
    "step": 0,
    "total": 0,
    "loss": None,
    "run_name": "",
    "started_at": None,
    "finished_at": None,
    "output_dir": "",
    "gguf_path": "",
}
_process: subprocess.Popen | None = None
_lock = threading.Lock()
_emit = None


def set_emit(callback) -> None:
    """Register a callback(dict) used to push train_status updates to the HUD."""
    global _emit
    _emit = callback


def status() -> dict:
    with _lock:
        return dict(state)


def _set_state(**fields) -> None:
    with _lock:
        state.update(fields)
        snapshot = dict(state)
    if _emit is not None:
        try:
            _emit(snapshot)
        except Exception:
            pass


def export_dataset(path: Path, max_pairs: int = DEFAULTS["max_pairs"]) -> int:
    """Build chat-format JSONL from Friday's own interaction memory."""
    con = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT role, content FROM memory_interactions ORDER BY rowid"
        ).fetchall()
    finally:
        con.close()

    pairs = 0
    buffer: list[dict] = []
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            role = str(row["role"] or "")
            content = str(row["content"] or "").strip()
            if not content or _SENSITIVE.search(content):
                buffer.clear()
                continue
            if role == "user":
                buffer = [{"role": "user", "content": content[:4000]}]
            elif role == "assistant" and buffer and buffer[-1]["role"] == "user":
                buffer.append({"role": "assistant", "content": content[:4000]})
                fh.write(json.dumps({"messages": buffer}, ensure_ascii=False) + "\n")
                pairs += 1
                buffer = []
                if pairs >= max_pairs:
                    break
            else:
                buffer.clear()
    return pairs


def start_job(params: dict) -> dict:
    global _process
    with _lock:
        if state["state"] == "running":
            return {"ok": False, "message": "A training run is already active, Boss."}

    cfg = dict(DEFAULTS)
    try:
        cfg["model"] = str(params.get("model") or cfg["model"]).strip()
        if cfg["model"] not in ALLOWED_MODELS:
            raise ValueError(f"unsupported base model {cfg['model']}")
        for key in ("lora_r", "lora_alpha", "epochs", "batch_size", "grad_accum", "max_seq", "max_pairs"):
            cfg[key] = int(params.get(key, cfg[key]))
        cfg["lora_dropout"] = float(params.get("lora_dropout", cfg["lora_dropout"]))
        cfg["learning_rate"] = float(params.get("learning_rate", cfg["learning_rate"]))
        cfg["export_gguf"] = bool(params.get("export_gguf", True))
        if not 1 <= cfg["lora_r"] <= 128:
            raise ValueError("LoRA rank must be 1-128")
        if not 1 <= cfg["lora_alpha"] <= 256:
            raise ValueError("LoRA alpha must be 1-256")
        if not 1 <= cfg["epochs"] <= 10:
            raise ValueError("Epochs must be 1-10")
        if not 1 <= cfg["batch_size"] <= 16:
            raise ValueError("Batch size must be 1-16")
        if not 512 <= cfg["max_seq"] <= 8192:
            raise ValueError("Max sequence length must be 512-8192")
        if not 1e-6 <= cfg["learning_rate"] <= 1e-2:
            raise ValueError("Learning rate must be between 1e-6 and 1e-2")
    except (TypeError, ValueError) as exc:
        return {"ok": False, "message": f"Invalid training setting: {exc}"}

    run_name = f"friday-ft-{time.strftime('%Y%m%d-%H%M%S')}"
    run_dir = config.MODELS_DIR / "finetune" / run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    dataset_path = run_dir / "dataset.jsonl"
    try:
        pairs = export_dataset(dataset_path, cfg["max_pairs"])
    except Exception as exc:
        return {"ok": False, "message": f"Could not build the dataset: {exc}"}
    if pairs < MIN_PAIRS:
        return {
            "ok": False,
            "message": (
                f"Only {pairs} usable conversation pair(s) in memory — chat with me "
                f"more first, Boss (need at least {MIN_PAIRS})."
            ),
        }

    output_dir = run_dir / "adapter"
    cfg_path = run_dir / "train_config.json"
    cfg_path.write_text(
        json.dumps(
            {"config": cfg, "dataset": str(dataset_path), "output_dir": str(output_dir)},
            indent=2,
        ),
        encoding="utf-8",
    )

    _set_state(
        state="running",
        message=f"Starting: {pairs} conversation pairs, base model {cfg['model']}...",
        step=0,
        total=0,
        loss=None,
        run_name=run_name,
        started_at=time.time(),
        finished_at=None,
        output_dir=str(output_dir),
        gguf_path="",
    )
    try:
        _process = subprocess.Popen(
            [sys.executable, "-m", "core.training.train_run", str(cfg_path)],
            cwd=str(config.BASE_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except Exception as exc:
        _set_state(state="error", message=f"Could not launch trainer: {exc}", finished_at=time.time())
        return {"ok": False, "message": f"Could not launch the trainer: {exc}"}

    threading.Thread(target=_pump, args=(_process,), daemon=True).start()
    return {
        "ok": True,
        "message": f"Fine-tune started: {run_name} ({pairs} pairs)",
        "run_name": run_name,
        "pairs": pairs,
    }


def _pump(process: subprocess.Popen) -> None:
    global _process
    assert process.stdout is not None
    for line in process.stdout:
        line = line.strip()
        if not line:
            continue
        if line.startswith("TRAIN_PROGRESS "):
            try:
                data = json.loads(line[len("TRAIN_PROGRESS "):])
            except ValueError:
                continue
            _set_state(
                step=int(data.get("step", 0)),
                total=int(data.get("total", 0)),
                loss=data.get("loss"),
                message=str(data.get("message", "Training...")),
            )
        elif line.startswith("TRAIN_ERROR "):
            _set_state(
                state="error",
                message=line[len("TRAIN_ERROR "):][:500],
                finished_at=time.time(),
            )
        elif line.startswith("TRAIN_GGUF "):
            _set_state(gguf_path=line[len("TRAIN_GGUF "):].strip())
        elif line.startswith("TRAIN_DONE"):
            out = line[len("TRAIN_DONE"):].strip()
            _set_state(
                state="done",
                message="Fine-tune complete. LoRA adapter saved.",
                finished_at=time.time(),
                output_dir=out or state.get("output_dir", ""),
            )
    code = process.wait()
    with _lock:
        still_running = state["state"] == "running"
        if still_running:
            state.update(
                state="error" if code != 0 else "done",
                message=(
                    "Trainer exited unexpectedly."
                    if code != 0
                    else "Fine-tune complete. LoRA adapter saved."
                ),
                finished_at=time.time(),
            )
    _process = None


def stop_job() -> dict:
    global _process
    with _lock:
        if state["state"] != "running" or _process is None:
            return {"ok": False, "message": "No training run is active, Boss."}
        process = _process
    process.terminate()
    _set_state(state="idle", message="Training stopped by the Boss.", finished_at=time.time())
    return {"ok": True, "message": "Training stopped, Boss."}


def latest_gguf() -> Path | None:
    """Most recent fine-tuned GGUF: the last run's export, else newest on disk."""
    with _lock:
        candidate = str(state.get("gguf_path") or "")
    if candidate:
        path = Path(candidate)
        if path.is_file():
            return path
    base = config.MODELS_DIR / "finetune"
    if base.is_dir():
        ggufs = sorted(
            base.glob("*/gguf/*.gguf"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        if ggufs:
            return ggufs[0]
    return None
