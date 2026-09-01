import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("FRIDAY_DATA_DIR", BASE_DIR))
DATA_DIR.mkdir(parents=True, exist_ok=True)
PERSONA_FILE = BASE_DIR / "persona" / "friday.txt"
MODELS_DIR = BASE_DIR / "models"
DB_PATH = DATA_DIR / "friday.db"
STT_MODEL_DIR = MODELS_DIR / "faster-whisper-base.en"
MEMORY_MODEL_DIR = MODELS_DIR / "all-MiniLM-L6-v2"
TTS_LOCAL_MODEL = MODELS_DIR / "kokoro" / "kokoro-v1.0.onnx"
TTS_LOCAL_VOICES = MODELS_DIR / "kokoro" / "voices-v1.0.bin"

TTS_MODE = os.environ.get("FRIDAY_TTS_MODE", "local")
TTS_LOCAL_VOICE = os.environ.get("FRIDAY_TTS_LOCAL_VOICE", "bf_isabella")
TTS_DEFAULT_LANGUAGE = os.environ.get("FRIDAY_TTS_LANGUAGE", "en-gb")
TTS_LOCAL_SPEED = 1.0
TTS_ONLINE_VOICE = "en-GB-SoniaNeural"

HOST = os.environ.get("FRIDAY_HOST", "127.0.0.1")
PORT = int(os.environ.get("FRIDAY_PORT", "8000"))
PAIRING_TOKEN = os.environ.get("FRIDAY_PAIRING_TOKEN", "")

REASONING_MODE = os.environ.get("FRIDAY_REASONING_MODE", "local").strip().lower()
if REASONING_MODE not in {"local", "openrouter"}:
    REASONING_MODE = "local"
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "").strip()
OPENROUTER_MODEL = os.environ.get(
    "FRIDAY_OPENROUTER_MODEL", "z-ai/glm-5.3-flash"
).strip()
OPENROUTER_BASE_URL = os.environ.get(
    "FRIDAY_OPENROUTER_URL", "https://openrouter.ai/api/v1"
).rstrip("/")
OPENROUTER_TIMEOUT = float(os.environ.get("FRIDAY_OPENROUTER_TIMEOUT", "120"))
OPENROUTER_MAX_TOKENS = int(os.environ.get("FRIDAY_CLOUD_MAX_TOKENS", "2048"))
HERMES_API_KEY = os.environ.get("HERMES_API_KEY", "").strip()
HERMES_BASE_URL = os.environ.get(
    "FRIDAY_HERMES_URL", "https://inference-api.nousresearch.com/v1"
).rstrip("/")
HERMES_MODEL = os.environ.get("FRIDAY_HERMES_MODEL", "z-ai/glm-5.3-flash").strip()
CLOUD_FALLBACK_ENABLED = os.environ.get("FRIDAY_CLOUD_FALLBACK", "true").lower() in (
    "1",
    "true",
    "yes",
    "on",
)
CLOUD_REASONING_ENABLED = (
    bool(OPENROUTER_API_KEY or HERMES_API_KEY) and REASONING_MODE == "openrouter"
)
OPENROUTER_REASONING_ENABLED = os.environ.get(
    "FRIDAY_OPENROUTER_REASONING", "true"
).lower() in ("1", "true", "yes", "on")

PREFERRED_MODEL_SUBSTRINGS = ["qwen2.5-vl-3b", "qwen", "gemma", "friday"]
DEFAULT_MODEL_DIR = MODELS_DIR / "qwen2.5-vl-3b-instruct-gguf"
DEFAULT_STOCK_MODEL = DEFAULT_MODEL_DIR / "Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf"
DEFAULT_MMPROJ_MODEL = (
    DEFAULT_MODEL_DIR / "mmproj-Qwen2.5-VL-3B-Instruct-Q8_0.gguf"
)

GGUF_MAIN_KW = ("mmproj", "projector")
GGUF_CLIP_KW = ("mmproj", "projector", "clip")
GGUF_N_CTX = int(os.environ.get("FRIDAY_GGUF_N_CTX", "4096"))
GGUF_N_GPU_LAYERS = int(os.environ.get("FRIDAY_GGUF_N_GPU_LAYERS", "40"))
GGUF_FLASH_ATTN = os.environ.get("FRIDAY_GGUF_FLASH_ATTN", "true").lower() in (
    "1",
    "true",
    "yes",
    "on",
)

MAX_NEW_TOKENS = int(os.environ.get("FRIDAY_MAX_NEW_TOKENS", "768"))
MAX_INPUT_TOKENS = int(os.environ.get("FRIDAY_MAX_INPUT_TOKENS", "4096"))

# Qwen-style native thinking; only used on the transformers (non-GGUF) path.
ENABLE_THINKING = os.environ.get("FRIDAY_ENABLE_THINKING", "true").lower() in (
    "1",
    "true",
    "yes",
    "on",
)
# Attention backend for the transformers fallback path.
ATTENTION_IMPL = os.environ.get("FRIDAY_ATTENTION_IMPL", "flash_attention_2")
TORCH_COMPILE = os.environ.get("FRIDAY_TORCH_COMPILE", "false").lower() in (
    "1",
    "true",
    "yes",
    "on",
)

# Decoding / sampling. Tightened defaults stop small 4B models from
# repeating, rambling, breaking or producing garbled output.
GEN_TEMPERATURE = float(os.environ.get("FRIDAY_TEMPERATURE", "0.35"))
GEN_TOP_P = float(os.environ.get("FRIDAY_TOP_P", "0.85"))
GEN_TOP_K = int(os.environ.get("FRIDAY_TOP_K", "40"))
GEN_MIN_P = float(os.environ.get("FRIDAY_MIN_P", "0.05"))
GEN_REPEAT_PENALTY = float(os.environ.get("FRIDAY_REPEAT_PENALTY", "1.08"))
GEN_FREQUENCY_PENALTY = float(os.environ.get("FRIDAY_FREQUENCY_PENALTY", "0.0"))
GEN_PRESENCE_PENALTY = float(os.environ.get("FRIDAY_PRESENCE_PENALTY", "0.0"))
GEN_NO_REPEAT_NGRAM = int(os.environ.get("FRIDAY_NO_REPEAT_NGRAM", "0"))
CONTEXT_HISTORY_TURNS = int(os.environ.get("FRIDAY_CONTEXT_TURNS", "10"))
MEMORY_CONTEXT_FACTS = int(os.environ.get("FRIDAY_MEMORY_FACTS", "6"))
MEMORY_CONTEXT_EPISODES = int(os.environ.get("FRIDAY_MEMORY_EPISODES", "2"))

# Agentic loop limits.
AGENT_MAX_STEPS = int(os.environ.get("FRIDAY_AGENT_MAX_STEPS", "10"))
# Roll old turns into a summary once the message stack exceeds this many messages.
AGENT_SUMMARY_TRIGGER = int(os.environ.get("FRIDAY_AGENT_SUMMARY_TRIGGER", "14"))
# Allowed malformed/truncated tool-call regeneration attempts per request.
AGENT_MAX_RETRIES = int(os.environ.get("FRIDAY_AGENT_MAX_RETRIES", "3"))

TASK_CONFIRM_SECONDS = 60.0
TASK_SEARCH_ROOTS = (
    Path.home() / "Desktop",
    Path.home() / "Documents",
    Path.home() / "Downloads",
)
CAPTURES_DIR = DATA_DIR / "captures"
SETTINGS_FILE = DATA_DIR / "hud-settings.json"
# Default for the HUD "Auto-accept permissions" toggle (can be changed live in the HUD).
AUTO_ACCEPT_TOOLS = os.environ.get("FRIDAY_AUTO_ACCEPT", "false").lower() in (
    "1",
    "true",
    "yes",
    "on",
)

WAKE_WORD = os.environ.get("FRIDAY_WAKE_WORD", "friday")
STT_LANGUAGE = "en"
WAKE_WINDOW_SECONDS = float(os.environ.get("FRIDAY_WAKE_WINDOW", "8"))
MIC_DEFAULT_ON = os.environ.get("FRIDAY_MIC_DEFAULT_ON", "true").lower() == "true"
MIC_DEVICE: int | str | None = None
MIC_FRAME_SECONDS = 0.1
MIC_PREROLL_SECONDS = 0.4
MIC_MIN_RMS = float(os.environ.get("FRIDAY_MIC_MIN_RMS", "280"))
MIC_SILENCE_SECONDS = 0.8
MIC_MIN_SPEECH_SECONDS = 0.35
MIC_MAX_SPEECH_SECONDS = 15.0
MIC_BARGE_IN_MULTIPLIER = 4.0
STT_CPU_THREADS = max(2, min(6, (os.cpu_count() or 4) - 1))

GUARDIAN_INTERVAL_SECONDS = float(os.environ.get("FRIDAY_GUARDIAN_INTERVAL", "30"))
GUARDIAN_CPU_THRESHOLD = float(os.environ.get("FRIDAY_GUARDIAN_CPU", "85"))
GUARDIAN_RAM_THRESHOLD = float(os.environ.get("FRIDAY_GUARDIAN_RAM", "90"))
GUARDIAN_TEMP_THRESHOLD = float(os.environ.get("FRIDAY_GUARDIAN_TEMP", "85"))
VAD_THRESHOLD = float(os.environ.get("FRIDAY_VAD_THRESHOLD", "0.5"))


def find_gguf_main(directory: Path) -> Path | None:
    if not directory.is_dir():
        return None
    ggufs = []
    for f in sorted(directory.iterdir()):
        if f.is_file() and f.suffix.lower() == ".gguf":
            name = f.name.lower()
            if any(kw in name for kw in GGUF_MAIN_KW):
                continue
            ggufs.append(f)
    return ggufs[0] if ggufs else None


def find_gguf_mmproj(directory: Path) -> Path | None:
    if not directory.is_dir():
        return None
    for f in sorted(directory.iterdir()):
        if f.is_file() and f.suffix.lower() == ".gguf":
            name = f.name.lower()
            if "mmproj" in name or "projector" in name:
                return f
    return None


def find_mmproj_file(model_dir: Path | None) -> Path | None:
    configured = os.environ.get("FRIDAY_MMPROJ_PATH", "").strip()
    if configured:
        path = Path(configured).expanduser()
        return path if path.is_file() else None
    if model_dir is not None:
        local = find_gguf_mmproj(model_dir)
        if local is not None:
            return local
    return None


def find_model_dir() -> Path | None:
    candidates: list[Path] = []
    if MODELS_DIR.exists():
        for d in sorted(MODELS_DIR.iterdir()):
            if not d.is_dir():
                continue
            config_file = d / "config.json"
            if config_file.exists():
                try:
                    model_config = json.loads(config_file.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    model_config = {}
                architectures = model_config.get("architectures") or []
                if any("ForCausalLM" in architecture for architecture in architectures):
                    candidates.append(d)
            elif find_gguf_main(d) is not None:
                candidates.append(d)
    if not candidates:
        return None
    for sub in PREFERRED_MODEL_SUBSTRINGS:
        for d in candidates:
            if sub in d.name.lower():
                return d
    return candidates[0]


_configured_model = os.environ.get("FRIDAY_MODEL_PATH", "").strip()
MODEL_FILE = Path(_configured_model).expanduser() if _configured_model else None
if MODEL_FILE is None and DEFAULT_STOCK_MODEL.is_file():
    MODEL_FILE = DEFAULT_STOCK_MODEL
if MODEL_FILE is not None and not MODEL_FILE.is_file():
    MODEL_FILE = None

MODEL_DIR = MODEL_FILE.parent if MODEL_FILE is not None else find_model_dir()
MODEL_IS_GGUF = (
    MODEL_FILE is not None and MODEL_FILE.suffix.lower() == ".gguf"
) or (MODEL_DIR is not None and find_gguf_main(MODEL_DIR) is not None)
MMPROJ_FILE = find_mmproj_file(MODEL_DIR) if MODEL_IS_GGUF else None
