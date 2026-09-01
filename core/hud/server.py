import asyncio
import ast
import hashlib
import hmac
import json
import mimetypes
import re
import shutil
import subprocess
import threading
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path


import uvicorn
from fastapi import FastAPI, File, HTTPException, Request, UploadFile, WebSocket
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from core import config
from core.brain.llm import Brain, clean_final_reply
from core.brain.cloud import CloudProviderError, OpenRouterClient
from core.ear.listener import VoiceListener
from core.hands.agent import Agent
from core.hands.background import BackgroundManager
from core.hands.cloud_agent import CloudAgent
from core.hands.reminders import ReminderScheduler
from core.hands.tools import Risk, TaskAgent, ToolRequest
from core.learning.store import experience_store
from core.memory.store import memory_store
from core.voice.tts import Speaker
from core.skills import skill_store
from core.training import finetune as train_manager

BASE = Path(__file__).resolve().parents[2]
STATIC = BASE / "hud" / "static"

UPLOAD_DIR = config.DATA_DIR / "chat_uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

brain = Brain()
speaker = Speaker()
history: list[dict] = []
clients: set[WebSocket] = set()
tasks: set[asyncio.Task] = set()
conversation_lock = asyncio.Lock()

assistant_state = "idle"
voice_status = "Starting microphone"
model_state = "not_loaded"
model_error = ""
current_cancel: threading.Event | None = None
event_loop: asyncio.AbstractEventLoop | None = None
listener: VoiceListener | None = None
scheduler: ReminderScheduler | None = None
background_supervisor_task: asyncio.Task | None = None
task_agent = TaskAgent(vision_analyzer=brain.describe_image)
background_manager = BackgroundManager()
task_agent.background = background_manager
last_action_time = 0.0

agent_confirm_waiters: dict[str, asyncio.Future] = {}
pending_train_actions: dict[str, dict] = {}
agent_instance: Agent | None = None
cloud_agent_instance: CloudAgent | None = None
openrouter_client = OpenRouterClient()

# ---- HUD settings (runtime state, persisted to hud-settings.json) ----
_settings_lock = threading.Lock()


def _load_settings_file() -> dict:
    try:
        data = json.loads(config.SETTINGS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_settings_file(settings: dict) -> None:
    with _settings_lock:
        try:
            config.SETTINGS_FILE.write_text(
                json.dumps(settings, indent=2), encoding="utf-8"
            )
        except Exception:
            pass


hud_settings: dict = {"auto_accept_tools": config.AUTO_ACCEPT_TOOLS, "session_pin_hash": ""}
_stored_settings = _load_settings_file()
if "auto_accept_tools" in _stored_settings:
    hud_settings["auto_accept_tools"] = bool(_stored_settings["auto_accept_tools"])
if isinstance(_stored_settings.get("session_pin_hash"), str):
    hud_settings["session_pin_hash"] = _stored_settings["session_pin_hash"]


def _public_settings() -> dict:
    """Settings safe to broadcast (never leaks the PIN hash)."""
    return {
        "auto_accept_tools": bool(hud_settings.get("auto_accept_tools")),
        "pin_enabled": bool(hud_settings.get("session_pin_hash")),
    }


async def broadcast_settings() -> None:
    await broadcast("settings", **_public_settings())


def _pin_matches(supplied: str, stored: str) -> bool:
    if not supplied:
        return False
    digest = hashlib.sha256(supplied.encode("utf-8")).hexdigest()
    return hmac.compare_digest(digest, stored)


async def set_setting(key: str, value, pin: str = "", conn_local: bool = True) -> bool:
    """Apply a settings change; remote (phone) clients need the PIN when one is set."""
    stored = str(hud_settings.get("session_pin_hash") or "")
    if key == "auto_accept_tools":
        if not conn_local and stored and not _pin_matches(pin, stored):
            return False
        hud_settings[key] = bool(value)
    elif key == "session_pin_hash":
        new_pin = str(value or "").strip()
        if new_pin and not re.fullmatch(r"\d{4,8}", new_pin):
            return False
        if stored and not conn_local and not _pin_matches(pin, stored):
            return False
        hud_settings[key] = (
            hashlib.sha256(new_pin.encode("utf-8")).hexdigest() if new_pin else ""
        )
    else:
        return False
    await asyncio.to_thread(_save_settings_file, hud_settings)
    await broadcast("settings", **_public_settings())
    return True

RUNTIME_SETTINGS_FILE = config.DATA_DIR / "runtime_settings.json"


def _load_runtime_reasoning_mode() -> str | None:
    try:
        payload = json.loads(
            RUNTIME_SETTINGS_FILE.read_text(encoding="utf-8")
        )
        mode = str(payload.get("reasoning_mode") or "")
        return mode if mode in {"local", "openrouter"} else None
    except Exception:
        return None


def _save_runtime_reasoning_mode(mode: str | None) -> None:
    try:
        existing = {}
        if RUNTIME_SETTINGS_FILE.exists():
            existing = json.loads(RUNTIME_SETTINGS_FILE.read_text(encoding="utf-8"))
        if mode is None:
            existing.pop("reasoning_mode", None)
        else:
            existing["reasoning_mode"] = mode
        RUNTIME_SETTINGS_FILE.write_text(
            json.dumps(existing, indent=2), encoding="utf-8"
        )
    except Exception:
        pass


def apply_runtime_reasoning_mode() -> str:
    """Apply any persisted runtime mode and return the effective mode."""
    persisted = _load_runtime_reasoning_mode()
    if persisted is not None:
        openrouter_client.set_mode(persisted)
        return persisted
    return config.REASONING_MODE


async def broadcast(type_: str, **data) -> None:
    payload = json.dumps({"type": type_, **data})
    stale: list[WebSocket] = []
    for ws in tuple(clients):
        try:
            await ws.send_text(payload)
        except Exception:
            stale.append(ws)
    clients.difference_update(stale)


async def set_state(value: str) -> None:
    global assistant_state
    assistant_state = value
    await broadcast("state", value=value)

async def set_vision(active: bool) -> None:
    await broadcast("vision", active=active)



async def broadcast_memory_stats() -> None:
    stats = await asyncio.to_thread(memory_store.stats)
    await broadcast("memory_stats", **stats)


async def deliver_response(
    message: str,
    speech: str | None = None,
    persist: bool = True,
    learning_kind: str = "",
    learning_action: str = "",
    user_text: str = "",
    success: bool = True,
) -> None:
    target = {"response_id": "", "timestamp": time.time()}
    if learning_kind and user_text:
        target = await asyncio.to_thread(
            experience_store.record_response,
            learning_kind,
            learning_action,
            user_text,
            message,
            success,
        )
    await broadcast("assistant", text=message, **target)
    if persist:
        await asyncio.to_thread(memory_store.record, "assistant", message, "tool")
    if speaker.enabled:
        await set_state("speaking")
        
        def volume_callback(vol):
            # Normalize and broadcast volume
            normalized = min(vol * 10, 1.0)
            voice_emit("volume", normalized)

        await speaker.speak(speech or message, on_volume=volume_callback)


async def notify_reminder(message: str) -> None:
    async with conversation_lock:
        await broadcast("notification", text=message)
        await deliver_response(message)
        await set_state("idle")


async def execute_tool(request: ToolRequest) -> None:
    await set_state("executing")
    
    if request.name in {"vision_screen", "vision_camera"}:
        await set_vision(True)
        
    await broadcast("tool_started", action=request.public())
    result = await task_agent.execute(request)
    
    if request.name in {"vision_screen", "vision_camera"}:
        await set_vision(False)
        
    await broadcast("tool_result", action=request.public(), result=result.public())
    global last_action_time
    last_action_time = time.time()
    sensitive = request.name in {"read_clipboard", "type_text", "recycle_file"}
    await asyncio.to_thread(
        experience_store.log_action,
        request.name,
        "Sensitive local action" if sensitive else request.description,
        "Sensitive result omitted" if sensitive else result.message,
        result.ok,
    )

    if not sensitive:
        history.extend(
            [
                {"role": "user", "content": request.description},
                {"role": "assistant", "content": result.message},
            ]
        )
        history[:] = history[-40:]
    await deliver_response(
        result.message,
        result.speech,
        persist=not sensitive,
        learning_kind="" if sensitive else "tool",
        learning_action=request.name,
        user_text=request.description,
        success=result.ok,
    )


_DIFF_START_RE = re.compile(r"<FIXED_FILE_START>", re.IGNORECASE)
_DIFF_END_RE = re.compile(r"<FIXED_FILE_END>", re.IGNORECASE)


def _split_fixed_content(raw: str) -> str | None:
    start = _DIFF_START_RE.search(raw)
    end = _DIFF_END_RE.search(raw)
    if not start or not end or end.start() <= start.end():
        return None
    return raw[start.end():end.start()].strip("\n")


async def run_code_agent(text: str) -> dict:
    """Best-effort coding agent: reason -> read -> propose -> diff -> write.

    Emits structured `reason`, `todo`, `toolcall` and `edit` events so the
    IDE-style HUD can visualize reasoning, tool calls and file changes.
    """
    await broadcast("reason", text=f"Received request: {text}")
    await broadcast(
        "todo",
        items=[
            {"id": 1, "label": "Locate target file", "status": "done"},
            {"id": 2, "label": "Analyze code", "status": "done"},
            {"id": 3, "label": "Propose fix", "status": "in_progress"},
            {"id": 4, "label": "Apply + verify", "status": "pending"},
        ],
    )

    m = re.search(r"\bin\s+[\"']?(.+?)[\"']?\s*$", text, re.IGNORECASE)
    file_hint = (m.group(1).strip(' "\'"') if m else "")

    if file_hint and not Path(file_hint).is_absolute():
        candidate = Path.cwd() / file_hint
        file_hint = str(candidate.resolve()) if candidate.exists() else file_hint

    path = Path(file_hint).resolve() if file_hint else None
    if path is None or not path.is_file():
        await broadcast("reason", text="Could not locate the target file. I can analyze, but won't edit anything.")
        await broadcast("todo", items=[{"id": i, "label": l, "status": "done" if i in (1, 2) else "done" if i < 4 else "pending"} for i, l in enumerate(["Locate target file", "Analyze code", "Propose fix", "Apply + verify"], 1)])
        return {"ok": False, "message": "I couldn't locate the file to fix — tell me the path (e.g. 'fix my code in core/config.py')."}

    try:
        original = path.read_text(encoding="utf-8")
    except Exception:
        return {"ok": False, "message": f"Could not read {path.name}, Boss."}

    await broadcast("toolcall", tool="read_file", title="Read target file", status="done", file=str(path))
    await broadcast("reason", text=f"Read {path.name} ({len(original)} chars). Now generating the fix.")

    prompt = (
            "You are a careful Python engineer fixing a bug. Rewrite the ENTIRE file below "
            "with your fix applied. Do not summarize. Output ONLY the corrected full file "
            f"between <FIXED_FILE_START> and <FIXED_FILE_END>.\\n\\nTASK: {text}\\n\\n"
            f"CURRENT FILE ({path.name}):\\n<FIXED_FILE_START>\\n{original}\\n<FIXED_FILE_END>"
        )
    proposal = await asyncio.to_thread(
        lambda: "".join(brain.stream_reply([], prompt))
    )
    proposed = _split_fixed_content(proposal)
    if proposed is None:
        await broadcast("reason", text="Model returned no structured edit; falling back to conversational reply.")
        await broadcast(
            "todo",
            items=[{"id": 1, "label": "Locate target file", "status": "done"},
                   {"id": 2, "label": "Analyze code", "status": "done"},
                   {"id": 3, "label": "Propose fix", "status": "done"},
                   {"id": 4, "label": "Apply + verify", "status": "done"}],
        )
        return {"ok": False, "message": proposal.strip() or "I wasn't able to produce a safe edit, Boss."}

    if proposed == original:
        await broadcast("reason", text="No changes needed — the file already looks correct.")
        return {"ok": True, "message": "I reviewed the file and it already looks correct — no changes were needed, Boss."}

    if path.suffix.lower() == ".py":
        try:
            ast.parse(proposed)
        except SyntaxError as e:
            await broadcast("reason", text=f"Proposed edit has a syntax error ({e}); not writing it.")
            await broadcast("toolcall", tool="edit", title="Apply fix", status="error", file=str(path), message=str(e))
            return {"ok": False, "message": f"I drafted a fix, but it had a Python syntax error and I refused to write it: {e}"}

    backup_path = path.with_suffix(path.suffix + f".{int(time.time())}.bak")
    temporary_path = path.with_suffix(path.suffix + f".{uuid.uuid4().hex}.tmp")
    shutil.copy(path, backup_path)
    try:
        temporary_path.write_text(proposed, encoding="utf-8")
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)

    await broadcast("edit", file=str(path), old=original, new=proposed, backup=str(backup_path))
    await broadcast("toolcall", tool="edit", title="Apply fix", status="done", file=str(path), message="Edit written atomically; backup saved.", backup=str(backup_path))
    await broadcast("reason", text="Fix applied and backup saved.")
    await broadcast(
        "todo",
        items=[
            {"id": 1, "label": "Locate target file", "status": "done"},
            {"id": 2, "label": "Analyze code", "status": "done"},
            {"id": 3, "label": "Propose fix", "status": "done"},
            {"id": 4, "label": "Apply + verify", "status": "done"},
        ],
    )
    return {"ok": True, "message": f"Applied the fix to {path.name} (backup: {backup_path.name}), Boss."}


async def request_confirmation(request: ToolRequest) -> None:
    task_agent.queue_confirmation(request)
    await broadcast("confirmation", action=request.public())
    await set_state("awaiting")
    await speaker.speak("This action needs confirmation, Boss.")


async def resolve_confirmation(
    request_id: str,
    approved: bool,
) -> None:
    request = task_agent.resolve(request_id, approved)
    await broadcast(
        "confirmation_resolved",
        id=request_id,
        approved=bool(approved and request is not None),
    )
    if not approved:
        await deliver_response("Cancelled, Boss.", persist=False)
        await set_state("idle")
        return
    if request is None:
        await deliver_response("That confirmation expired, Boss.", persist=False)
        await set_state("idle")
        return
    await execute_tool(request)


def interrupt_current() -> None:
    if current_cancel is not None:
        current_cancel.set()
    def deny_waiters() -> None:
        for request_id, future in tuple(agent_confirm_waiters.items()):
            if not future.done():
                future.set_result(False)
                track(broadcast("confirmation_resolved", id=request_id, approved=False))

    if event_loop is not None and event_loop.is_running():
        event_loop.call_soon_threadsafe(deny_waiters)
    else:
        deny_waiters()
    speaker.stop()


def is_interruptible() -> bool:
    return assistant_state in {"thinking", "speaking", "awaiting"}


def track(coro) -> None:
    task = asyncio.create_task(coro)
    tasks.add(task)
    def finished(done: asyncio.Task) -> None:
        tasks.discard(done)
        try:
            exc = done.exception()
        except asyncio.CancelledError:
            return
        if exc is not None:
            print(f"[FRIDAY] background task failed: {exc.__class__.__name__}: {exc}")

    task.add_done_callback(finished)


def voice_emit(kind: str, value: object) -> None:
    if event_loop is None:
        return

    def dispatch() -> None:
        global voice_status
        if kind == "command":
            interrupt_current()
            track(process_message(str(value), "voice"))
        elif kind == "state":
            track(set_state(str(value)))
        elif kind == "mic":
            track(broadcast("mic", active=bool(value)))
        elif kind == "transcript":
            track(broadcast("transcript", text=str(value)))
        elif kind == "wake":
            track(broadcast("wake", word=str(value)))
        elif kind == "voice_status":
            voice_status = str(value)
            track(broadcast("voice_status", text=voice_status))
        elif kind == "volume":
            track(broadcast("volume", value=value))
        elif kind == "error":
            track(broadcast("error", text=str(value)))

    event_loop.call_soon_threadsafe(dispatch)


def _get_gpu_temp() -> float | None:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return float(result.stdout.strip().split("\n")[0])
    except Exception:
        pass
    return None


async def _guardian_loop() -> None:
    import psutil
    from core import config as _cfg
    last_alert_time = 0.0
    while True:
        await asyncio.sleep(_cfg.GUARDIAN_INTERVAL_SECONDS)
        try:
            cpu = await asyncio.to_thread(psutil.cpu_percent, interval=0.5)
            ram = await asyncio.to_thread(psutil.virtual_memory)
            gpu_temp = await asyncio.to_thread(_get_gpu_temp)

            alerts: list[str] = []
            if cpu >= _cfg.GUARDIAN_CPU_THRESHOLD:
                alerts.append(f"CPU at {cpu:.0f}%")
            if ram.percent >= _cfg.GUARDIAN_RAM_THRESHOLD:
                alerts.append(f"RAM at {ram.percent:.0f}% ({ram.used // (1024**3):.1f}/{ram.total // (1024**3):.1f} GB)")
            if gpu_temp is not None and gpu_temp >= _cfg.GUARDIAN_TEMP_THRESHOLD:
                alerts.append(f"GPU temperature at {gpu_temp:.0f}C")

            if alerts and (time.time() - last_alert_time) > 60.0:
                last_alert_time = time.time()
                message = "System Guardian Alert: " + "; ".join(alerts) + "."
                await broadcast("guardian", active=True, message=message)
                await broadcast("notification", text=message)
            elif not alerts:
                await broadcast("guardian", active=False, message="")
        except asyncio.CancelledError:
            raise
        except Exception:
            pass


async def _background_supervisor_loop() -> None:
    """Notify the Boss when a background (subagent) task finishes."""
    while True:
        await asyncio.sleep(2.0)
        try:
            finished = await asyncio.to_thread(background_manager.poll)
            for task in finished:
                ok = task.exit_code == 0
                verb = "finished" if ok else f"failed (exit code {task.exit_code})"
                title = task.label or task.command[:60]
                message = f"Background task '{title}' {verb}, Boss."
                tail = task.output_tail(1200).strip()
                await broadcast(
                    "notification", text=message, ok=ok, task_id=task.id
                )
                await deliver_response(
                    message + (f"\nOutput:\n{tail}" if tail else ""),
                    speech=message,
                    persist=False,
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            pass


async def process_phone_audio(audio_b64: str, ws: WebSocket) -> None:
    """Receive base64-encoded audio chunks from phone mic, transcribe, process."""
    import base64
    try:
        audio_bytes = base64.b64decode(audio_b64, validate=True)
        if len(audio_bytes) > 15 * 1024 * 1024:
            raise ValueError("Phone audio exceeds the 15 MB limit")
        tmp_path = Path(os.environ.get("TEMP", "/tmp")) / f"phone_audio_{uuid.uuid4().hex}.wav"
        await asyncio.to_thread(tmp_path.write_bytes, audio_bytes)
        try:
            def transcribe() -> str:
                from faster_whisper import WhisperModel
                from core import config as _cfg

                model = WhisperModel(
                    str(_cfg.STT_MODEL_DIR),
                    device="cpu",
                    compute_type="int8",
                    cpu_threads=_cfg.STT_CPU_THREADS,
                )
                segments, _ = model.transcribe(
                    str(tmp_path),
                    language=_cfg.STT_LANGUAGE,
                    beam_size=3,
                    vad_filter=True,
                    condition_on_previous_text=False,
                )
                return " ".join(seg.text.strip() for seg in segments).strip()

            text = await asyncio.to_thread(transcribe)
        finally:
            tmp_path.unlink(missing_ok=True)

        if not text:
            await ws.send_text(json.dumps({"type": "phone_transcript", "text": "", "empty": True}))
            return

        await ws.send_text(json.dumps({"type": "phone_transcript", "text": text, "empty": False}))
        interrupt_current()
        track(process_message(text, "phone"))
    except Exception as exc:
        await ws.send_text(json.dumps({"type": "error", "text": f"Phone audio error: {exc}"}))


@asynccontextmanager
async def lifespan(app: FastAPI):
    global event_loop, listener, scheduler, model_state, model_error, background_supervisor_task
    event_loop = asyncio.get_running_loop()
    mode = apply_runtime_reasoning_mode()
    print(f"[FRIDAY] reasoning mode: {mode}")
    await asyncio.to_thread(memory_store.start_session)
    await asyncio.to_thread(experience_store.start)
    scheduler = ReminderScheduler(notify_reminder)
    task_agent.scheduler = scheduler
    await scheduler.start()
    try:
        import psutil as _psutil
        _guardian_task = asyncio.create_task(_guardian_loop())
    except ImportError:
        _guardian_task = None
    background_supervisor_task = asyncio.create_task(_background_supervisor_loop())
    listener = VoiceListener(voice_emit, is_interruptible, interrupt_current)
    listener.start()

    def _train_emit(payload: dict) -> None:
        if event_loop is not None and event_loop.is_running():
            event_loop.call_soon_threadsafe(
                lambda: track(broadcast("train_status", **payload))
            )

    train_manager.set_emit(_train_emit)

    model_state = "loading"
    try:
        await asyncio.to_thread(brain.load)
        model_state = "ready"
        print(f"[FRIDAY] local model ready: {config.MODEL_FILE.name}")
    except Exception as exc:
        model_state = "failed"
        model_error = f"{exc.__class__.__name__}: {exc}"
        print(f"[FRIDAY] local model failed: {model_error}")

    async def startup_greeting() -> None:
        try:
            await asyncio.sleep(2.0)
            message = (
                "Hello, Boss. Local systems are online and ready."
                if model_state == "ready"
                else "Hello, Boss. Friday started in degraded mode. Check diagnostics."
            )
            await speaker.speak(message)
            print("[FRIDAY] startup greeting spoken")
        except Exception as exc:
            print(f"[FRIDAY] startup greeting failed: {exc.__class__.__name__}: {exc}")

    track(startup_greeting())

    yield
    listener.stop()
    interrupt_current()
    if background_supervisor_task is not None:
        background_supervisor_task.cancel()
        try:
            await background_supervisor_task
        except asyncio.CancelledError:
            pass
        background_supervisor_task = None
    for pending_task in tuple(tasks):
        pending_task.cancel()
    if tasks:
        await asyncio.gather(*tuple(tasks), return_exceptions=True)
    if _guardian_task is not None:
        _guardian_task.cancel()
        try:
            await _guardian_task
        except asyncio.CancelledError:
            pass
    await scheduler.close()
    await asyncio.to_thread(experience_store.close)
    await asyncio.to_thread(memory_store.close_session)



app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["null", "http://127.0.0.1", "http://localhost"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


@app.get("/health")
async def health():
    return JSONResponse({
        "status": "ok" if model_state == "ready" else model_state,
        "state": assistant_state,
        "reasoning": "openrouter" if openrouter_client.enabled else "local",
        "cloud_model": openrouter_client.model if openrouter_client.enabled else None,
        "local_model": config.MODEL_FILE.name if config.MODEL_FILE else None,
        "model_backend": "llama.cpp" if config.MODEL_IS_GGUF else "transformers",
        "model_state": model_state,
        "model_error": model_error if model_state == "failed" else None,
        "vision": model_state == "ready" and config.MMPROJ_FILE is not None,
        "skills": [skill.name for skill in skill_store.list()],
    })


@app.post("/settings/mode")
async def set_reasoning_mode(request: Request):
    valid = {"local", "openrouter"}
    mode = request.query_params.get("mode")
    if mode is None:
        form = await request.form()
        mode = form.get("mode")
    cleaned = (mode or "").strip().lower()
    if cleaned not in valid:
        raise HTTPException(status_code=422, detail="mode must be 'local' or 'openrouter'")
    openrouter_client.set_mode(cleaned)
    _save_runtime_reasoning_mode(cleaned)
    return JSONResponse({"reasoning": "openrouter" if openrouter_client.enabled else "local"})


@app.get("/manifest.json")
async def manifest():
    return FileResponse(STATIC / "manifest.json", media_type="application/json")

@app.get("/sw.js")
async def service_worker():
    return FileResponse(STATIC / "sw.js", media_type="application/javascript")


app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
ALLOWED_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp",
    ".txt", ".md", ".csv", ".json", ".log", ".py", ".js",
    ".html", ".pdf",
}


@app.post("/upload")
async def upload_attachment(file: UploadFile = File(...)):
    original = Path(file.filename or "upload.bin").name
    ext = Path(original).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext or 'none'}")
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 25 MB)")
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    token = uuid.uuid4().hex
    fname = f"{token}{ext}"
    dest = UPLOAD_DIR / fname
    dest.write_bytes(data)
    content_type = mimetypes.guess_type(original)[0] or "application/octet-stream"
    kind = "image" if content_type.startswith("image/") else "file"
    return JSONResponse({
        "id": token,
        "name": Path(original).name[:255],
        "kind": kind,
        "url": f"/uploads/{fname}",
    })


TEXT_READABLE_EXT = {
    ".txt", ".md", ".csv", ".json", ".log", ".py", ".js", ".html",
}


@app.get("/train/status")
async def train_status():
    return JSONResponse(train_manager.status())


@app.post("/train/start")
async def train_start(params: dict = None):
    params = params or {}
    if hud_settings.get("auto_accept_tools"):
        return JSONResponse(train_manager.start_job(params))
    request_id = uuid.uuid4().hex
    summary = json.dumps(params, indent=2)[:1200]
    request = ToolRequest(
        name="train_start",
        args=params,
        risk=Risk.CAREFUL,
        title="Start fine-tuning",
        description=(
            "Fine-tune a model with Unsloth QLoRA using your conversation memory.\n\n"
            f"Settings:\n{summary}"
        ),
    )
    pending_train_actions[request_id] = {"params": params, "request": request}
    await broadcast("confirmation", action=request.public())
    await set_state("awaiting")
    await speaker.speak("This action needs confirmation, Boss.")
    return JSONResponse({
        "ok": True,
        "pending": True,
        "id": request_id,
        "message": "Awaiting your approval, Boss.",
    })


@app.post("/train/stop")
async def train_stop():
    return JSONResponse(train_manager.stop_job())


@app.post("/train/apply")
async def train_apply():
    if train_manager.status().get("state") == "running":
        return JSONResponse({"ok": False, "message": "Training is still running, Boss."})
    gguf = await asyncio.to_thread(train_manager.latest_gguf)
    if gguf is None:
        return JSONResponse({"ok": False, "message": "No fine-tuned GGUF model found yet, Boss."})
    async with conversation_lock:
        ok, message = await asyncio.to_thread(_swap_model_to, gguf)
    await broadcast("reason", text=message)
    await deliver_response(message, persist=False)
    return JSONResponse({"ok": ok, "message": message, "model": str(gguf)})


def _swap_model_to(gguf_path: Path) -> tuple[bool, str]:
    """Hot-swap the llama.cpp brain to a freshly fine-tuned GGUF."""
    import gc

    from core import config as cfg

    if cfg.MODEL_IS_GGUF and brain.model is not None:
        brain.model = None
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
    cfg.MODEL_FILE = gguf_path
    cfg.MODEL_IS_GGUF = True
    cfg.MODEL_DIR = gguf_path.parent
    cfg.MMPROJ_FILE = cfg.find_mmproj_file(cfg.MODEL_DIR)
    brain.is_gguf = True
    brain.max_input_tokens = cfg.MAX_INPUT_TOKENS
    brain.max_new_tokens = cfg.MAX_NEW_TOKENS
    try:
        brain.load()
        return True, f"Brain hot-swapped to {gguf_path.name}, Boss."
    except Exception as exc:
        return False, f"Hot-swap failed: {exc}"


def _resolve_attachments(attachments, base_text: str):
    """Return (image_path, text) — vision path plus any readable text inlined."""
    image_path: str | None = None
    additions: list[str] = []
    up = UPLOAD_DIR.resolve()
    for a in attachments or []:
        token = str(a.get("id") or "")
        if not re.fullmatch(r"[0-9a-f]{32}", token):
            continue
        try:
            matches = list(up.glob(f"{token}.*"))
            p = matches[0].resolve() if len(matches) == 1 else Path()
        except Exception:
            continue
        if up not in p.parents or not p.is_file():
            continue
        name = Path(str(a.get("name") or p.name)).name[:255]
        content_type = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        kind = "image" if content_type.startswith("image/") else "file"
        if kind == "image" and image_path is None:
            image_path = str(p)
            additions.append(f"[Attached image: {name}]")
            continue
        ext = p.suffix.lower()
        if ext in TEXT_READABLE_EXT and p.stat().st_size <= 512 * 1024:
            try:
                content = p.read_text(encoding="utf-8", errors="replace")
                if len(content) > 12000:
                    content = content[:12000] + "\n...[truncated]"
                additions.append(f"\n[Attached file: {name}]\n```\n{content}\n```")
            except Exception:
                additions.append(f"[Attached file: {name}]")
        else:
            additions.append(f"[Attached file: {name}]")
    text = base_text
    if additions:
        text = (text + "\n\n" + "\n".join(additions)).strip()
    return image_path, text



async def capture_memory(text: str, source: str) -> str:
    try:
        await asyncio.to_thread(memory_store.record, "user", text, source)
        capture = await asyncio.to_thread(memory_store.capture, text)
        if capture["blocked"]:
            await broadcast(
                "memory_warning",
                text="Sensitive information was not stored.",
            )
        if capture["facts"]:
            await broadcast("memory_saved", facts=capture["facts"])
            await broadcast_memory_stats()
        return await asyncio.to_thread(memory_store.context_for, text)
    except Exception as exc:
        await broadcast("memory_warning", text=f"Memory unavailable: {exc}")
        return ""


async def _confirm_agent_tool(request: ToolRequest) -> bool:
    """Confirm a CAREFUL tool requested by the agent loop via the HUD approve/deny panel.
    Returns True if the user approves (or the waiter resolves True)."""
    global assistant_state
    if hud_settings.get("auto_accept_tools"):
        await broadcast("reason", text=f"Auto-accepted: {request.title}")
        return True
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    agent_confirm_waiters[request.id] = future
    await broadcast("confirmation", action=request.public())
    await set_state("awaiting")
    try:
        await asyncio.wait_for(future, timeout=config.TASK_CONFIRM_SECONDS)
        return bool(future.result())
    except (asyncio.TimeoutError, asyncio.CancelledError):
        await broadcast("confirmation_resolved", id=request.id, approved=False)
        return False
    finally:
        agent_confirm_waiters.pop(request.id, None)


async def _run_subagent(task_text: str):
    """Run a bounded, sequential sub-agent that returns its final answer."""
    from core.hands.tools import ToolResult

    task_text = str(task_text or "").strip()
    if not task_text:
        return ToolResult(False, "A sub-agent needs a task to work on, Boss.")
    _run_subagent.depth = getattr(_run_subagent, "depth", 0) + 1
    try:
        if _run_subagent.depth > 2:
            return ToolResult(
                False,
                "Sub-agents can't spawn further sub-agents (nesting limit reached), Boss.",
            )
        sub = Agent(
            brain,
            task_agent,
            confirm_cb=_confirm_agent_tool,
            emit=broadcast,
        )
        # Focused context: no history, a clear task, and a bounded step budget.
        result = await sub.run(
            task_text,
            [],
            cancel=current_cancel,
            memory_context="",
            adaptation_context="",
        )
        reply = (result.reply or "").strip()
        if not reply:
            reply = "I completed the sub-task but didn't produce a clear answer."
        if result.cancelled:
            return ToolResult(False, "The sub-task was interrupted, Boss.")
        return ToolResult(True, reply[:8000])
    except Exception as exc:
        return ToolResult(False, f"The sub-task failed: {exc}")
    finally:
        _run_subagent.depth -= 1


task_agent.subagent_runner = _run_subagent


def _make_local_agent() -> Agent:
    global agent_instance
    if agent_instance is None:
        agent_instance = Agent(
            brain,
            task_agent,
            confirm_cb=_confirm_agent_tool,
            emit=broadcast,
        )
    return agent_instance


def _make_agent() -> Agent:
    global cloud_agent_instance
    if not openrouter_client.enabled:
        return _make_local_agent()
    if cloud_agent_instance is None:
        cloud_agent_instance = CloudAgent(
            brain,
            task_agent,
            confirm_cb=_confirm_agent_tool,
            emit=broadcast,
            client=openrouter_client,
        )
    return cloud_agent_instance


_ACTIONABLE_RE = re.compile(
    r"^\s*(?:please\s+)?(?:run|execute|write|save|open|fetch|search|find|list|"
    r"debug|refactor|improve|repair|"
    r"create|delete|move|copy|install|start|stop|kill)\b|"
    r"^\s*(?:please\s+)?read\s+(?:the\s+)?(?:file|folder|directory|clipboard)\b|"
    r"^\s*(?:please\s+)?(?:check|show)\s+(?:my\s+|the\s+)?"
    r"(?:cpu|disk|system|processes|uptime|health)\b|"
    r"^\s*(?:calculate|compute)\b|"
    r"\d+\s*[+\-*/^]\s*\d+|"
    r"(?:[a-zA-Z]:[\\/]|\.?\.?[\\/])[\w .\\/-]+",
    re.IGNORECASE,
)

# Questions about the real contents of known folders must always be answered
# with tools (list_directory / find_files) — never from memory or guessing.
_FOLDER_QUESTION_RE = re.compile(
    r"\b(?:in|inside|under|on)\s+(?:my|the)\s+"
    r"(?:downloads?|documents?|desktop|pictures?|videos?|music|folders?|directories?)\b|"
    r"^\s*(?:list|show|check|open|read)\s+(?:me\s+)?(?:my|the)\s+"
    r"(?:downloads?|documents?|desktop)\b|"
    r"^\s*what(?:'s|s| is| are)\s+(?:in\s+|inside\s+|on\s+|under\s+)?(?:my\s+|the\s+)?"
    r"(?:downloads?|documents?|desktop)\b",
    re.IGNORECASE,
)


def _looks_actionable(text: str) -> bool:
    """Cheap pre-filter: does this message plausibly want an action / data answer?"""
    return bool(_ACTIONABLE_RE.search(text) or _FOLDER_QUESTION_RE.search(text))


async def handle_confirmation(request_id: str, approved: bool) -> None:
    pending = pending_train_actions.pop(request_id, None)
    if pending is not None:
        await broadcast(
            "confirmation_resolved", id=request_id, approved=bool(approved)
        )
        if approved:
            async with conversation_lock:
                await set_state("executing")
                result = await asyncio.to_thread(
                    train_manager.start_job, pending["params"]
                )
            await deliver_response(result.get("message", "Training started."), persist=False)
        else:
            await deliver_response("Training cancelled, Boss.", persist=False)
            await set_state("idle")
        return
    future = agent_confirm_waiters.get(request_id)
    if future is not None and not future.done():
        future.set_result(bool(approved))
        await broadcast(
            "confirmation_resolved",
            id=request_id,
            approved=bool(approved),
        )
        return
    async with conversation_lock:
        await resolve_confirmation(request_id, approved)


async def process_message(text: str, source: str, image_path: str | None = None) -> None:
    global current_cancel, history
    text = text.strip()
    if not text:
        return
    decision = task_agent.confirmation_decision(text)
    if decision is not None and agent_confirm_waiters:
        request_id = next(reversed(agent_confirm_waiters))
        await handle_confirmation(request_id, decision)
        return
    async with conversation_lock:
        cancel = threading.Event()
        current_cancel = cancel
        try:
            await broadcast("user", text=text, source=source)
            await set_state("thinking")
            await asyncio.to_thread(experience_store.observe_user, text)

            pending = task_agent.latest_pending()
            decision = task_agent.confirmation_decision(text)
            if pending is not None and decision is not None:
                await resolve_confirmation(pending.id, decision)
                return

            request = task_agent.parse(text)
            sensitive_task = request is not None and request.name in {
                "read_clipboard",
                "type_text",
                "recycle_file",
                "screenshot",
                "vision_screen",
                "vision_camera",
            }
            memory_context = "" if sensitive_task else await capture_memory(text, source)
            if request is not None:
                if request.risk is Risk.CAREFUL:
                    if hud_settings.get("auto_accept_tools"):
                        task_agent.authorize(request)
                        await broadcast("reason", text=f"Auto-accepted: {request.title}")
                        await execute_tool(request)
                    else:
                        await request_confirmation(request)
                else:
                    await execute_tool(request)
                return

            if _looks_actionable(text) or openrouter_client.enabled:
                await set_state("executing")
                await broadcast("agent_begin")
                try:
                    agent = _make_agent()
                    adaptation_context = await asyncio.to_thread(
                        experience_store.adaptation_context, text
                    )
                    run_args = {
                        "cancel": cancel,
                        "memory_context": memory_context,
                        "adaptation_context": adaptation_context,
                        "image_path": image_path,
                    }
                    try:
                        result = await agent.run(text, list(history), **run_args)
                    except CloudProviderError as exc:
                        await broadcast(
                            "reason",
                            text=f"Cloud reasoning unavailable ({exc}); using local fallback.",
                        )
                        result = await _make_local_agent().run(
                            text, list(history), **run_args
                        )
                    if cancel.is_set():
                        await broadcast("interrupted")
                        return
                    reply = clean_final_reply(result.reply)
                    assistant_message = result.assistant_message or {
                        "role": "assistant",
                        "content": reply,
                    }
                    history.extend(
                        [{"role": "user", "content": text}, assistant_message]
                    )
                    history[:] = history[-40:]
                    await deliver_response(
                        reply,
                        persist=True,
                        learning_kind="agent",
                        learning_action=f"tools={result.tool_count}",
                        user_text=text,
                        success=not result.cancelled,
                    )
                except Exception as exc:
                    await broadcast("error", text=f"Agent error: {exc}")
                    await deliver_response(
                        "I couldn't complete that action because the local agent failed. "
                        "Please try again or give me a more specific target.",
                        persist=False,
                    )
                finally:
                    await broadcast("agent_end")
                return

            adaptation_context = await asyncio.to_thread(
                experience_store.adaptation_context, text
            )
            queue: asyncio.Queue[object] = asyncio.Queue()
            loop = asyncio.get_running_loop()
            sentinel = object()

            def pump() -> None:
                try:
                    raw_reply = "".join(
                        brain.stream_reply(
                            history,
                            text,
                            cancel,
                            memory_context,
                            adaptation_context,
                            image_path=image_path,
                        )
                    )
                    cleaned_reply = clean_final_reply(raw_reply)
                    if cleaned_reply:
                        loop.call_soon_threadsafe(queue.put_nowait, cleaned_reply)
                except Exception as exc:
                    loop.call_soon_threadsafe(queue.put_nowait, exc)
                finally:
                    loop.call_soon_threadsafe(queue.put_nowait, sentinel)

            threading.Thread(target=pump, daemon=True).start()
            chunks: list[str] = []
            speak_queue: asyncio.Queue = asyncio.Queue()
            speaking_task: asyncio.Task | None = None
            if speaker.enabled:

                def volume_callback(vol):
                    voice_emit("volume", min(vol * 10, 1.0))

                def on_speaking():
                    track(set_state("speaking"))

                speaking_task = asyncio.create_task(
                    speaker.speak_stream(
                        speak_queue,
                        cancel,
                        on_volume=volume_callback,
                        on_started=on_speaking,
                    )
                )
            while True:
                item = await queue.get()
                if item is sentinel:
                    if speaking_task is not None:
                        await speak_queue.put(None)
                    break
                if isinstance(item, Exception):
                    cancel.set()
                    if speaking_task is not None:
                        await speak_queue.put(None)
                    await broadcast("error", text=f"Brain error: {item}")
                    break
                chunk = str(item)
                chunks.append(chunk)
                await broadcast("delta", text=chunk)
                if speaking_task is not None:
                    await speak_queue.put(chunk)
            if speaking_task is not None:
                await speaking_task

            reply = clean_final_reply("".join(chunks))
            if cancel.is_set():
                await broadcast("interrupted")
                return

            if not reply:
                reply = "I couldn't produce a usable response. Please try rephrasing the request."
                await broadcast("assistant", text=reply, response_id="", timestamp=time.time())

            history.extend(
                [
                    {"role": "user", "content": text},
                    {"role": "assistant", "content": reply},
                ]
            )
            history[:] = history[-40:]
            await asyncio.to_thread(memory_store.record, "assistant", reply, "friday")
            if reply:
                target = await asyncio.to_thread(
                    experience_store.record_response,
                    "conversation",
                    "conversation",
                    text,
                    reply,
                    True,
                )
                await broadcast("response_complete", text=reply, **target)

            if cancel.is_set():
                await broadcast("interrupted")
        finally:
            if current_cancel is cancel:
                current_cancel = None
            if assistant_state not in {"listening", "awake", "awaiting"}:
                await set_state("idle")


@app.websocket("/ws")
async def channel(ws: WebSocket):
    from core import config

    client_host = ws.client.host if ws.client else ""
    is_local = client_host in {"127.0.0.1", "::1"}
    supplied_token = ws.query_params.get("token", "")
    if not is_local and (not config.PAIRING_TOKEN or supplied_token != config.PAIRING_TOKEN):
        await ws.close(code=1008, reason="Pairing token required")
        return
    await ws.accept()
    clients.add(ws)
    await ws.send_text(json.dumps({"type": "state", "value": assistant_state}))
    await ws.send_text(
        json.dumps(
            {
                "type": "mic",
                "active": listener.enabled if listener is not None else False,
            }
        )
    )
    await ws.send_text(json.dumps({"type": "voice_status", "text": voice_status}))
    await ws.send_text(json.dumps({"type": "settings", **_public_settings()}))
    await ws.send_text(json.dumps({"type": "memory_stats", **memory_store.stats()}))
    try:
        while True:
            msg = json.loads(await ws.receive_text())
            kind = msg.get("type")
            if kind == "chat":
                interrupt_current()
                img, chat_text = _resolve_attachments(
                    msg.get("attachments"), str(msg.get("text") or "")
                )
                track(process_message(chat_text, "typed", image_path=img))
            elif kind == "mic_toggle" and listener is not None:
                listener.toggle()
            elif kind == "stop":
                interrupt_current()
                await set_state("idle")
            elif kind == "memory_list":
                facts = await asyncio.to_thread(memory_store.list_facts)
                await ws.send_text(json.dumps({"type": "memory_list", "facts": facts}))
            elif kind == "memory_forget":
                fact_id = int(msg.get("id") or 0)
                await asyncio.to_thread(memory_store.forget, fact_id)
                facts = await asyncio.to_thread(memory_store.list_facts)
                await ws.send_text(json.dumps({"type": "memory_list", "facts": facts}))
                await broadcast_memory_stats()
            elif kind == "tool_confirm":
                track(handle_confirmation(str(msg.get("id") or ""), True))
            elif kind == "tool_deny":
                track(handle_confirmation(str(msg.get("id") or ""), False))
            elif kind == "settings_get":
                await ws.send_text(json.dumps({"type": "settings", **_public_settings()}))
            elif kind == "settings_set":
                ok = await set_setting(
                    str(msg.get("key") or ""),
                    msg.get("value"),
                    str(msg.get("pin") or ""),
                    is_local,
                )
                if not ok:
                    await ws.send_text(json.dumps({
                        "type": "settings_error",
                        "text": "PIN required or invalid setting, Boss.",
                    }))
            elif kind == "phone_audio":
                track(process_phone_audio(str(msg.get("audio") or ""), ws))
            elif kind == "feedback":
                ts = float(msg.get("timestamp") or 0)
                score = int(msg.get("score") or 0)
                response_id = str(msg.get("response_id") or "")
                if score and (response_id or ts):
                    saved = await asyncio.to_thread(
                        experience_store.set_feedback,
                        score,
                        response_id,
                        ts,
                    )
                    await ws.send_text(json.dumps({"type": "feedback_saved", "saved": saved}))
            elif kind == "set_mode":
                valid = {"local", "openrouter"}
                cleaned = str(msg.get("mode") or "").strip().lower()
                if cleaned in valid:
                    openrouter_client.set_mode(cleaned)
                    _save_runtime_reasoning_mode(cleaned)
                    await ws.send_text(
                        json.dumps(
                            {
                                "type": "mode",
                                "reasoning": "openrouter" if openrouter_client.enabled else "local",
                                "cloud_model": openrouter_client.model,
                            }
                        )
                    )
    except Exception:
        pass
    finally:
        clients.discard(ws)


def run() -> None:
    from core import config

    uvicorn.run(app, host=config.HOST, port=config.PORT, log_level="warning")
