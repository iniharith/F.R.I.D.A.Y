====================================================================
 F.R.I.D.A.Y. - HYBRID PERSONAL AI AGENT
 Local tools, memory, voice and vision with optional cloud reasoning
====================================================================

THIS FOLDER IS SELF-CONTAINED
  py312\                         portable Python
  wheels\deps\                   every dependency incl. PyTorch CUDA 12.8
  models\qwen2.5-vl-3b-instruct-gguf\ local Qwen vision brain + matched projector
  models\faster-whisper-base.en\ offline English speech recognition
  models\all-MiniLM-L6-v2\       offline semantic memory search
  models\kokoro\                  offline neural speech + voices
  core\                          brain, ear, voice, memory and HUD code
  hud\                           orb + Grok-style chat panel

--------------------------------------------------------------------
SETUP AT HOME - NO INTERNET NEEDED
--------------------------------------------------------------------
 1. Copy this folder to the laptop SSD, e.g. C:\friday-kit.
    Do not run it from the USB drive.
 2. Double-click INSTALL-FRIDAY.bat. This is the supported setup method;
    the previously generated large Setup EXE was cancelled and deleted.
      - installs entirely from wheels\
      - checks CUDA and your default microphone
      - opens http://127.0.0.1:8000
 3. First launch can take 1-2 minutes while local models load.

 Later launches: LAUNCH-FRIDAY.bat
 Windows command HUD: dist-launcher\FRIDAY-HUD.exe
   Keep the EXE in dist-launcher beside this kit; it is a secure companion
   launcher and uses this folder's models and .venv.
 Stop: close the console window (Ctrl+C first is cleaner).

  OPTIONAL LARGE-AGENT REASONING (OPENROUTER)
   FRIDAY always defaults to local mode, even when a cloud key exists. To use
   an online model for a session after explicitly selecting OpenRouter in the
   launcher configuration:
   for conversation, planning, coding and native function calls:

   1. Create a NEW key at https://openrouter.ai/settings/keys
   2. Double-click CONFIGURE-OPENROUTER.bat and paste the key into the hidden
      prompt. The key is stored in your Windows user environment, never here.
   3. Fully close and restart FRIDAY.
   4. Open http://127.0.0.1:8000/health and verify:
        "reasoning": "openrouter"

   Default cloud model:
     z-ai/glm-5.3-flash (reasoning enabled)

   Override it before launch with the Windows user environment variable:
     FRIDAY_OPENROUTER_MODEL

   Set FRIDAY_REASONING_MODE=local or run DISABLE-CLOUD-REASONING.bat to force
   offline Qwen. OpenRouter errors, quota failures and network outages
   automatically fall back to the local model.

   OPTIONAL FALLBACK PROVIDER (HERMES PORTAL)
   When OpenRouter is rate limited (429), out of credits (402), rejects the
   key, times out or has an outage (5xx), FRIDAY automatically retries the
   same request on Hermes Portal using the same model (z-ai/glm-5.3-flash):

   1. Create a NEW key at https://portal.nousresearch.com
   2. Double-click CONFIGURE-HERMES.bat and paste the key. The key is stored
      as HERMES_API_KEY in your Windows user environment.
   3. Fully close and restart FRIDAY.

   The HUD shows a "Cloud failover" notice whenever Hermes answers instead of
   OpenRouter. Disable the failover with FRIDAY_CLOUD_FALLBACK=false, or point
   it elsewhere with FRIDAY_HERMES_URL / FRIDAY_HERMES_MODEL.

   Privacy: cloud mode sends the current request, relevant conversation
   history, selected memory context and attached images to OpenRouter (or
   Hermes Portal during a failover). Tool execution remains local. Reading
   files for a cloud tool loop, writes, shell commands, camera/screen access,
   deletion and other sensitive actions require HUD confirmation. GLM
   reasoning_details are preserved across follow-up turns.

  GPU ACCELERATION
   The bundled llama.cpp CUDA runtime supports NVIDIA RTX 3050.
   Qwen2.5-VL-3B-Instruct uses Q4_K_M GGUF plus a matched Q8_0 vision projector.
   The default 4096-token context is tuned for the laptop's 4 GB VRAM.

  Recommended:
   * RTX 3050 4 GB: supported; measured local text and vision inference pass
   * RTX 3050 6/8 GB: supported; smoother and more model layers stay on GPU
   * NVIDIA driver: keep it current enough for CUDA 12.8

  Verify after setup:
    .venv\Scripts\python.exe -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"

--------------------------------------------------------------------
HOW TO USE FRIDAY
--------------------------------------------------------------------
 First-time setup:
  1. Keep the complete friday-kit folder on an internal SSD.
  2. Double-click INSTALL-FRIDAY.bat.
  3. Wait while the offline dependencies, CUDA, microphone, memory and
     voice systems are checked.
  4. Allow Windows microphone and private-network access if prompted.
  5. Wait for the HUD to open. The first model load can take 1-2 minutes.

 Normal launch:
  1. Double-click dist-launcher\FRIDAY-HUD.exe.
  2. If the HUD cannot start the backend, run LAUNCH-HUD.bat instead to
     see diagnostic messages.
  3. Wait until the HUD reports that FRIDAY is online.

 Text chat:
  1. Click the message box at the bottom of the HUD.
  2. Type a request, then press Enter or click Send.
  3. Use the Stop button to interrupt a long response.
  4. Use thumbs-up or thumbs-down to teach FRIDAY your response style.

 Voice control:
  1. Make sure the microphone button is enabled.
  2. Say "Friday" followed by your request, or say "Friday", wait for
     the activation sound, and speak within 8 seconds.
  3. Say "Friday, confirm" when an approved sensitive action asks for
     confirmation. You can also approve or reject it in the HUD.
  4. Use headphones to prevent FRIDAY from hearing her own voice.

 Android connection:
  1. Connect the Windows computer and Android phone to the same trusted
     Wi-Fi network.
  2. Start FRIDAY on Windows.
  3. Open CONFIG -> NETWORK in the Windows HUD.
  4. Scan the QR code with the phone camera.
  5. Tap the F.R.I.D.A.Y. link. The app saves the protected connection
     details and connects automatically. Use Manual setup only if needed.
  6. The mobile HUD shows system/model status and provides laptop mic
     mute/unmute, Local/OpenRouter mode and safe runtime tuning controls.

 Memory and preferences:
  1. Say "Remember that ..." to save an important fact explicitly.
  2. Click the brain icon to inspect or forget saved facts.
  3. Run EXPORT-MEMORY.bat to create a backup.
  4. Close FRIDAY before running RESET-MEMORY.bat.

 Closing FRIDAY:
  1. Close the HUD window.
  2. If a backend console remains open, press Ctrl+C before closing it.

--------------------------------------------------------------------
VOICE CONTROL
--------------------------------------------------------------------
 One breath:  "Friday, terangkan ralat Python ini."
 Two parts:   say "Friday", wait for the green orb/chime, then give
              the command within 8 seconds.

 The microphone starts ON. Click the microphone icon to mute/unmute.
 Click the square Stop button to interrupt a response manually.
 Talking while FRIDAY is thinking or speaking also interrupts her.

 IMPORTANT: wear headphones for reliable barge-in. Without them, the
 microphone can hear FRIDAY's speakers and mistake her voice for yours.

Speech recognition and the default neural voice are fully offline.
  FRIDAY always speaks English. Input is transcribed as English and the
  Kokoro bf_isabella voice uses British-English phonemization. It runs
  on CPU and takes no VRAM from FRIDAY's brain.

 Microsoft's exact en-IE Emily Neural model is proprietary and hosted;
 Microsoft does not provide it as a downloadable local voice. To use
 Emily online instead, set TTS_MODE = "emily" in core\config.py. If the
 connection fails, FRIDAY automatically returns to local bf_isabella.

 If the microphone is wrong or unavailable:
  1. Windows Settings -> Privacy -> Microphone -> allow desktop apps.
  2. Double-click CHECK-AUDIO.bat to list available devices.
  3. Put its numeric ID into MIC_DEVICE in core\config.py.

--------------------------------------------------------------------
SMART MEMORY
--------------------------------------------------------------------
 FRIDAY automatically captures durable statements such as:
   "My name is Alex."
   "I prefer Python over JavaScript."
   "My GPU is an RTX 3050."
   "Remember that the printer is upstairs."

 Relevant facts and previous-session notes are retrieved semantically
 and inserted privately into future conversations. Normal small talk is
 not treated as a permanent fact.

 Click the brain icon in the HUD to inspect every stored fact. Each item
 has a FORGET button and asks for confirmation before removal.

 Privacy rules:
  * Passwords, tokens, PINs, private keys and payment data are rejected.
  * Sensitive messages are not written to session transcripts.
  * Facts stay in friday.db; rated responses and learned preferences stay
    in learning.db. Electron stores both under its per-user app data folder.

 Backup/inspection:
  * EXPORT-MEMORY.bat exports facts and adaptive-learning data.
  * RESET-MEMORY.bat erases both databases after typing DELETE ALL.
  * Close FRIDAY before running RESET-MEMORY.bat.

--------------------------------------------------------------------
TASK EXECUTION
--------------------------------------------------------------------
 Safe actions run immediately:
  * Open approved apps: Chrome, Edge, Firefox, Notepad, Calculator,
    Explorer, PowerShell, Terminal, VS Code, Spotify, Steam and others.
  * Open approved websites or a complete http/https address.
  * Search the web and check weather (internet required).
  * Set persistent timers/reminders and list pending reminders.
  * Raise/lower/mute volume, take screenshots, search common folders.

 Actions requiring HUD approval or voice "Friday, confirm":
  * Read clipboard text.
  * Type into the active window (3-second focus delay).
  * Close applications, sleep/restart/shut down Windows.
  * Move one explicitly named file to the Recycle Bin.
  * Cancel every pending timer/reminder.

  Safety boundaries:
   * Shell commands are available only after showing the command and receiving approval.
  * Applications and websites use fixed whitelists.
  * Folder deletion and permanent deletion are disabled.
  * Windows, Program Files, the home root and friday-kit are protected.
  * Shutdown/restart includes a 10-second abort window.

 Examples:
   "Friday, open Visual Studio Code."
   "Friday, set a timer for 20 minutes."
   "Friday, remind me in 2 hours to call Sam."
   "Friday, find file quarterly report."
   "Friday, what is the weather in Dublin?"
   "Friday, read my clipboard."  (asks for confirmation)

 --------------------------------------------------------------------
 ADAPTIVE LEARNING
 --------------------------------------------------------------------
 FRIDAY learns local communication preferences such as language, answer
 length, tone and form of address. Thumbs-up/down feedback is attached to
 a stable response ID and guides similar future replies. This does not
 retrain model weights or override tool confirmations and safety rules.

 Android pairing:
  1. Start FRIDAY from the Windows HUD.
  2. Open CONFIG -> NETWORK and scan the displayed QR code.
  3. Tap the F.R.I.D.A.Y. link to save and connect automatically.
  4. Keep both devices on the same trusted Wi-Fi network. Manual IP, port
     and token entry remains available as a fallback.

--------------------------------------------------------------------
 LOCAL MODEL BUNDLE
--------------------------------------------------------------------
 The verified default pair is:
   models\qwen2.5-vl-3b-instruct-gguf\Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf
   models\qwen2.5-vl-3b-instruct-gguf\mmproj-Qwen2.5-VL-3B-Instruct-Q8_0.gguf
 MODEL-SOURCE.json records the repository revision, sizes and SHA-256 hashes.
 A custom GGUF can be selected with FRIDAY_MODEL_PATH only when its matching
 projector is also selected with FRIDAY_MMPROJ_PATH.

 --------------------------------------------------------------------
 HERMES-STYLE AGENT FEATURES
 --------------------------------------------------------------------
 FRIDAY uses a typed canonical tool registry, native OpenRouter schemas,
 multi-step tool loops, bounded parallel calls, one-use confirmation grants,
 episodic session recall, persistent reminders and local procedural skills.
 Skills follow the agentskills layout: skills\<name>\SKILL.md. User-created
 skills can also live under the FRIDAY data directory's skills folder. Skills
 never override safety rules or confirmation gates.

--------------------------------------------------------------------
PHASES
--------------------------------------------------------------------
 [DONE] Phase 1 - HUD, streaming text chat, spoken replies
 [DONE] Phase 2 - "Friday" activation, mic STT, mute, stop, barge-in
 [DONE] Phase 3 - smart memory, semantic recall, sessions, memory drawer
 [DONE] Phase 4 - task tools, reminders, safety boundaries, confirmation
 [DONE] Phase 5 - adaptive learning, Windows HUD and Android command link
 [DONE] Phase 6 - local Qwen camera, screen and attachment vision
 [DONE] Phase 7 - canonical tools, procedural skills and explicit cloud routing

--------------------------------------------------------------------
TROUBLESHOOTING
--------------------------------------------------------------------
  * CUDA available: False       -> update the NVIDIA driver and rerun
                                    INSTALL-FRIDAY.bat; CPU fallback remains available
 * Microphone unavailable      -> Windows microphone privacy + device check
 * FRIDAY triggers herself     -> use headphones; lower speaker volume
 * Windows SAPI voice is heard -> rerun INSTALL-FRIDAY.bat; check models\kokoro files
 * Memory does not capture     -> say "Remember that ..." explicitly
 * Wrong fact stored           -> brain icon -> FORGET
 * App cannot be opened        -> install it or add its path in core\hands\tools.py
 * Weather/search unavailable  -> those two tools require internet
 * Confirmation expired        -> repeat the original request
 * Slow first response         -> normal; Qwen loads once per launch
 * Port 8000 busy              -> edit HOST/PORT in core\config.py
====================================================================
