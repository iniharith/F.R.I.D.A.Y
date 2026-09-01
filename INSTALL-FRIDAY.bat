@echo off
setlocal
cd /d %~dp0

echo ==================================================
echo   F.R.I.D.A.Y. - OFFLINE INSTALLER
echo   (bundled Python - no internet needed)
echo ==================================================
echo.

set "PY=%CD%\.venv\Scripts\python.exe"

echo [0/8] Verifying bundled environment...
if not exist .venv\Scripts\python.exe (
    echo     Creating virtual environment...
    py312\python.exe -m venv .venv
    if errorlevel 1 (echo INSTALL FAILED - cannot create venv & pause & exit /b 1)
)
echo     Repairing relocated virtual environment if needed...
py312\python.exe installer\repair-venv.py
if errorlevel 1 (
    echo     Environment is corrupt - rebuilding it from scratch...
    rmdir /s /q .venv
    py312\python.exe -m venv .venv
    if errorlevel 1 (echo INSTALL FAILED - cannot create venv & pause & exit /b 1)
)
"%PY%" -c "import sys" >nul 2>&1
if errorlevel 1 (echo INSTALL FAILED - virtual environment cannot run & pause & exit /b 1)

echo [1/8] Installing all systems offline...
"%PY%" -m pip install --no-index --find-links=wheels\deps -r requirements.txt
if errorlevel 1 (echo INSTALL FAILED - see messages above & pause & exit /b 1)

echo.
echo [2/8] Verifying GPU bridge...
"%PY%" -c "import torch; ok=torch.cuda.is_available(); print('PyTorch:', torch.__version__, '| CUDA:', torch.version.cuda, '| Device:', torch.cuda.get_device_name(0) if ok else 'CPU fallback')"
"%PY%" -c "import torch; exit(0 if torch.cuda.is_available() else 1)"
if errorlevel 1 (
    echo WARNING: CUDA NOT DETECTED - update the NVIDIA driver, then rerun.
    echo FRIDAY will use the supported CPU fallback and may respond slowly.
)

echo.
echo [3/8] Checking default microphone...
"%PY%" -c "import sounddevice as sd; print('Microphone:', sd.query_devices(kind='input')['name'])"

echo.
echo [4/8] Checking offline semantic memory...
"%PY%" -c "from sentence_transformers import SentenceTransformer; m=SentenceTransformer(r'models\all-MiniLM-L6-v2',device='cpu',local_files_only=True); print('Memory dimensions:', m.get_sentence_embedding_dimension())"
if errorlevel 1 echo WARNING: Semantic model check failed; keyword memory will still work.

echo.
echo [5/8] Checking local neural voice...
"%PY%" -c "from kokoro_onnx import Kokoro; k=Kokoro(r'models\kokoro\kokoro-v1.0.onnx',r'models\kokoro\voices-v1.0.bin'); a,r=k.create('Sistem suara tempatan sudah bersedia.',voice='bf_isabella',speed=1.0,lang='ms'); b,_=k.create('Local voice systems are ready.',voice='bf_isabella',speed=1.0,lang='en-gb'); assert len(a) and len(b); print('Local neural voice: bf_isabella, Malay + English at',r,'Hz')"
if errorlevel 1 echo WARNING: Local neural voice check failed; Windows SAPI will be used.

echo.
echo [6/8] Checking task automation modules...
"%PY%" -c "import importlib.util; assert importlib.util.find_spec('pyautogui'); assert importlib.util.find_spec('send2trash'); print('Task automation: ready')"
if errorlevel 1 echo WARNING: Some task automation modules are unavailable.

echo.
echo.
echo [7/8] Checking local Qwen text and vision...
"%PY%" -c "from core import config; config.MAX_NEW_TOKENS=8; from core.brain.llm import Brain; b=Brain(); b.load(); print('Local brain:', config.MODEL_FILE.name); r=b.describe_image(r'hud\static\icon-192.png','Name the main symbol briefly.'); assert r; print('Local vision: ready')"
if errorlevel 1 (echo INSTALL FAILED - local Qwen model or vision projector is unavailable & pause & exit /b 1)

echo.
echo [8/8] Waking F.R.I.D.A.Y....
echo       (browser opens automatically at http://127.0.0.1:8000)
echo       First launch takes 1-2 minutes to load her brain.
echo       Next time: double-click LAUNCH-FRIDAY.bat
echo.
"%PY%" -m core.main
pause
