import math
import queue
import re
import threading
import time
from collections import deque
from collections.abc import Callable

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel
from scipy.signal import resample_poly

from core import config

try:
    import onnxruntime as ort
    _VAD_AVAILABLE = True
except ImportError:
    ort = None
    _VAD_AVAILABLE = False

Emit = Callable[[str, object], None]


class VoiceListener:
    def __init__(
        self,
        emit: Emit,
        is_interruptible: Callable[[], bool],
        interrupt: Callable[[], None],
    ) -> None:
        self.emit = emit
        self.is_interruptible = is_interruptible
        self.interrupt = interrupt
        self.enabled = config.MIC_DEFAULT_ON
        self._stop = threading.Event()
        self._frames: queue.Queue[bytes] = queue.Queue(maxsize=100)
        self._thread: threading.Thread | None = None
        self._model: WhisperModel | None = None
        self._armed_until = 0.0
        self._vad_session = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        self._clear_frames()
        self.emit("mic", enabled)
        if not enabled:
            self._armed_until = 0.0
            self.emit("state", "idle")

    def toggle(self) -> bool:
        self.set_enabled(not self.enabled)
        return self.enabled

    def _clear_frames(self) -> None:
        while True:
            try:
                self._frames.get_nowait()
            except queue.Empty:
                break

    def _callback(self, indata, frames, time_info, status) -> None:
        if not self.enabled or self._stop.is_set():
            return
        data = bytes(indata)
        try:
            self._frames.put_nowait(data)
        except queue.Full:
            try:
                self._frames.get_nowait()
                self._frames.put_nowait(data)
            except queue.Empty:
                pass

    def _run(self) -> None:
        try:
            self.emit("voice_status", "Loading offline speech recognition")
            self._model = WhisperModel(
                str(config.STT_MODEL_DIR),
                device="cpu",
                compute_type="int8",
                cpu_threads=config.STT_CPU_THREADS,
            )
            self._vad_session = None
            if _VAD_AVAILABLE:
                try:
                    from pathlib import Path as _Path
                    vad_model_path = _Path(config.MODELS_DIR) / "silero_vad" / "silero_vad.onnx"
                    if vad_model_path.is_file():
                        self._vad_session = ort.InferenceSession(str(vad_model_path))
                        self.emit("voice_status", "VAD (Voice Activity Detection) ready")
                    else:
                        self.emit("voice_status", "VAD model missing; using offline RMS detection")
                except Exception:
                    self._vad_session = None
            device = sd.query_devices(config.MIC_DEVICE, kind="input")
            sample_rate = int(device.get("default_samplerate") or 16000)
            blocksize = max(1, int(sample_rate * config.MIC_FRAME_SECONDS))
            self.emit("voice_status", f"Microphone ready: {device['name']}")
            with sd.RawInputStream(
                device=config.MIC_DEVICE,
                samplerate=sample_rate,
                blocksize=blocksize,
                channels=1,
                dtype="int16",
                callback=self._callback,
            ):
                self.emit("mic", self.enabled)
                self._capture_loop(sample_rate, blocksize)
        except Exception as exc:
            self.enabled = False
            self.emit("mic", False)
            self.emit("error", f"Microphone unavailable: {exc}")

    def _capture_loop(self, sample_rate: int, blocksize: int) -> None:
        frame_seconds = blocksize / sample_rate
        preroll_size = max(2, math.ceil(config.MIC_PREROLL_SECONDS / frame_seconds))
        preroll: deque[bytes] = deque(maxlen=preroll_size)
        recording: list[bytes] = []
        noise_floor = 90.0
        speech_frames = 0
        silent_frames = 0
        interrupted = False

        while not self._stop.is_set():
            if not self.enabled:
                recording.clear()
                preroll.clear()
                self._clear_frames()
                time.sleep(0.1)
                continue
            if self._armed_until and time.monotonic() >= self._armed_until:
                self._armed_until = 0.0
                if not self.is_interruptible():
                    self.emit("state", "idle")
            try:
                frame = self._frames.get(timeout=0.2)
            except queue.Empty:
                continue

            samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
            rms = float(np.sqrt(np.mean(samples * samples))) if samples.size else 0.0

            if not recording:
                noise_floor = (noise_floor * 0.97) + (min(rms, 1000.0) * 0.03)
                threshold = max(config.MIC_MIN_RMS, noise_floor * 2.8)
                if self.is_interruptible():
                    threshold = max(
                        threshold,
                        noise_floor * config.MIC_BARGE_IN_MULTIPLIER,
                    )
                preroll.append(frame)
                is_speech = rms >= threshold
                if not is_speech and self._vad_session is not None:
                    samples_for_vad = np.frombuffer(frame, dtype=np.int16).astype(np.float32) / 32768.0
                    is_speech = self._is_speech_vad(samples_for_vad, sample_rate)
                if is_speech:
                    speech_frames += 1
                    if speech_frames >= 2:
                        recording = list(preroll)
                        silent_frames = 0
                        interrupted = self.is_interruptible()
                        if interrupted:
                            self.interrupt()
                        self.emit("state", "listening")
                else:
                    speech_frames = 0
                continue

            recording.append(frame)
            threshold = max(config.MIC_MIN_RMS, noise_floor * 2.2)
            if rms >= threshold:
                silent_frames = 0
            else:
                silent_frames += 1

            duration = len(recording) * frame_seconds
            silence = silent_frames * frame_seconds
            complete = (
                duration >= config.MIC_MAX_SPEECH_SECONDS
                or (
                    duration >= config.MIC_MIN_SPEECH_SECONDS
                    and silence >= config.MIC_SILENCE_SECONDS
                )
            )
            if not complete:
                continue

            keep = len(recording) - silent_frames if silent_frames else len(recording)
            captured = b"".join(recording[: max(keep, 1)])
            recording = []
            preroll.clear()
            speech_frames = 0
            silent_frames = 0

            text = self._transcribe(captured, sample_rate)
            self._handle_transcript(text, interrupted)
            interrupted = False

    def _transcribe(self, audio_bytes: bytes, sample_rate: int) -> str:
        if self._model is None:
            return ""
        audio = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        if sample_rate != 16000:
            divisor = math.gcd(sample_rate, 16000)
            audio = resample_poly(audio, 16000 // divisor, sample_rate // divisor)
        segments, _ = self._model.transcribe(
            audio,
            language=config.STT_LANGUAGE,
            beam_size=3,
            vad_filter=False,
            condition_on_previous_text=False,
        )
        return " ".join(segment.text.strip() for segment in segments).strip()

    def _is_speech_vad(self, audio_float32: "np.ndarray", sample_rate: int) -> bool:
        """Use Silero VAD to detect speech. Returns True if speech detected."""
        if self._vad_session is None or len(audio_float32) == 0:
            return False
        try:
            if sample_rate != 16000:
                from scipy.signal import resample_poly
                import math
                divisor = math.gcd(sample_rate, 16000)
                audio_float32 = resample_poly(audio_float32, 16000 // divisor, sample_rate // divisor)
            chunk_size = 512
            if len(audio_float32) < chunk_size:
                audio_float32 = np.pad(audio_float32, (0, chunk_size - len(audio_float32)))
            audio_input = audio_float32[:chunk_size].reshape(1, -1).astype(np.float32)
            ort_inputs = {
                "input": audio_input,
                "h": np.zeros((1, 2, 64), dtype=np.float32),
                "c": np.zeros((1, 2, 64), dtype=np.float32),
                "sr": np.array([16000], dtype=np.int64),
            }
            output = self._vad_session.run(None, ort_inputs)
            speech_prob = float(output[0][0])
            return speech_prob > config.VAD_THRESHOLD
        except Exception:
            return False

    def _handle_transcript(self, text: str, interrupted: bool) -> None:
        if not text:
            self.emit("state", "idle")
            return
        self.emit("transcript", text)
        wake = re.compile(rf"\b{re.escape(config.WAKE_WORD)}\b", re.IGNORECASE)
        has_wake = bool(wake.search(text))
        command = wake.sub("", text).strip(" ,.!?-:")
        armed = time.monotonic() < self._armed_until

        if has_wake and not command:
            self._armed_until = time.monotonic() + config.WAKE_WINDOW_SECONDS
            self.emit("wake", config.WAKE_WORD)
            self.emit("state", "awake")
            return
        if has_wake or armed or interrupted:
            self._armed_until = 0.0
            self.emit("command", command if has_wake else text)
            return
        self.emit("state", "idle")
