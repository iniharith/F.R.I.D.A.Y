import socket
import sys
import os
import webbrowser

from core import config
from core.hud.server import run


def _local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def preflight() -> None:
    if config.MODEL_FILE is None or not config.MODEL_FILE.is_file():
        sys.exit("[FRIDAY] Qwen2.5-VL-3B model is missing. Run INSTALL-FRIDAY.bat to repair the local bundle.")
    if config.MMPROJ_FILE is None or not config.MMPROJ_FILE.is_file():
        sys.exit("[FRIDAY] The matching Qwen vision projector is missing.")
    print(f"[FRIDAY] brain   : {config.MODEL_FILE.name} (offline)")
    print(f"[FRIDAY] vision  : {config.MMPROJ_FILE.name} (offline)")
    cloud = config.OPENROUTER_MODEL if config.CLOUD_REASONING_ENABLED else "disabled (local only)"
    print(f"[FRIDAY] cloud   : {cloud}")
    if config.STT_MODEL_DIR.exists():
        print(f"[FRIDAY] hearing : {config.STT_MODEL_DIR.name} (offline)")
    else:
        print("[FRIDAY] hearing : speech model missing; text chat still works")
    if config.MEMORY_MODEL_DIR.exists():
        print(f"[FRIDAY] memory  : {config.MEMORY_MODEL_DIR.name} (local semantic)")
    else:
        print("[FRIDAY] memory  : keyword fallback; semantic model missing")
    print("[FRIDAY] hands   : balanced whitelist + confirmation")
    local_voice = config.TTS_LOCAL_MODEL.exists() and config.TTS_LOCAL_VOICES.exists()
    if config.TTS_MODE.lower() == "emily":
        try:
            socket.create_connection(("speech.platform.bing.com", 443), timeout=3).close()
            print("[FRIDAY] voice   : online Microsoft en-IE Emily")
        except OSError:
            fallback = f"local neural {config.TTS_LOCAL_VOICE}" if local_voice else "Windows SAPI"
            print(f"[FRIDAY] voice   : Emily offline; using {fallback}")
    elif local_voice:
        print(f"[FRIDAY] voice   : local neural {config.TTS_LOCAL_VOICE} (offline)")
    else:
        print("[FRIDAY] voice   : local model missing; using Windows SAPI")


def main() -> None:
    preflight()
    local = _local_ip()
    url = f"http://127.0.0.1:{config.PORT}"
    print(f"[FRIDAY] hud     : {url}")
    print(f"[FRIDAY] phone   : http://{local}:{config.PORT}  (same Wi-Fi)")
    if os.environ.get("FRIDAY_NO_BROWSER") != "1":
        webbrowser.open(url)
    run()


if __name__ == "__main__":
    main()
