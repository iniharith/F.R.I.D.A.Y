from __future__ import annotations

import asyncio
import functools
import os
import re
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path

from core import config

try:
    import edge_tts
except ImportError:
    edge_tts = None

try:
    import miniaudio
except ImportError:
    miniaudio = None

try:
    import numpy as np
    import sounddevice as sd
except ImportError:
    np = None
    sd = None

_SPLIT = re.compile(r"(?<=[.!?])\s+")
_LOCAL_ENGINE = None
_LOCAL_LOCK = threading.RLock()
_SAPI_SCRIPT = (
    "Add-Type -AssemblyName System.Speech; "
    "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
    "$s.SelectVoiceByHints([System.Speech.Synthesis.VoiceGender]::Female); "
    "$s.Rate = 1; $s.Speak($env:FRIDAY_TTS_TEXT)"
)
_TIMEOUT = object()


def split_sentences(text: str) -> list[str]:
    return [p.strip() for p in _SPLIT.split(text) if p.strip()]


def speech_chunks(text: str, max_chars: int = 420) -> list[str]:
    chunks: list[str] = []
    current = ""
    for sentence in split_sentences(text) or [text.strip()]:
        candidate = f"{current} {sentence}".strip()
        if current and len(candidate) > max_chars:
            chunks.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def local_voice_ready() -> bool:
    return (
        np is not None
        and sd is not None
        and config.TTS_LOCAL_MODEL.is_file()
        and config.TTS_LOCAL_VOICES.is_file()
    )


def detect_speech_language(text: str) -> str:
    return "en-gb"


def synthesize_local(text: str) -> tuple["np.ndarray", int] | None:
    global _LOCAL_ENGINE
    if not local_voice_ready():
        return None
    try:
        with _LOCAL_LOCK:
            if _LOCAL_ENGINE is None:
                from kokoro_onnx import Kokoro

                _LOCAL_ENGINE = Kokoro(
                    str(config.TTS_LOCAL_MODEL),
                    str(config.TTS_LOCAL_VOICES),
                )
            samples, sample_rate = _LOCAL_ENGINE.create(
                text,
                voice=config.TTS_LOCAL_VOICE,
                speed=config.TTS_LOCAL_SPEED,
                lang=detect_speech_language(text),
            )
        audio = np.asarray(samples, dtype=np.float32)
        return audio.reshape(-1, 1), int(sample_rate)
    except Exception as exc:
        print(f"[FRIDAY] local neural voice unavailable: {exc.__class__.__name__}")
        return None


async def synthesize_online(text: str) -> tuple["np.ndarray", int] | None:
    if edge_tts is None or miniaudio is None or np is None:
        return None
    tmp = Path(tempfile.gettempdir()) / f"friday-{uuid.uuid4().hex}.mp3"
    try:
        await edge_tts.Communicate(text, config.TTS_ONLINE_VOICE).save(str(tmp))
        decoded = miniaudio.decode_file(
            str(tmp), output_format=miniaudio.SampleFormat.SIGNED16
        )
        audio = np.frombuffer(bytes(decoded.samples), dtype=np.int16)
        return audio.reshape(-1, decoded.nchannels), decoded.sample_rate
    except Exception as exc:
        print(f"[FRIDAY] online voice unavailable: {exc.__class__.__name__}")
        return None
    finally:
        tmp.unlink(missing_ok=True)


def _play(
    audio: "np.ndarray",
    rate: int,
    cancel: threading.Event,
    on_volume: callable | None = None,
) -> None:
    if sd is None or np is None:
        return
    audio = np.asarray(audio)
    if audio.ndim == 1:
        audio = audio.reshape(-1, 1)
    if audio.dtype not in (np.dtype("float32"), np.dtype("int16")):
        audio = audio.astype(np.float32)
    if audio.dtype == np.dtype("int16"):
        audio = audio.astype(np.float32) / 32768.0
    peak = float(np.abs(audio).max()) if audio.size else 0.0
    if peak > 0.0:
        target = 0.92
        if peak < target:
            audio = audio * (target / peak)
        audio = np.clip(audio, -1.0, 1.0)
    channels = audio.shape[1]
    with sd.OutputStream(
        samplerate=rate,
        channels=channels,
        dtype=str(audio.dtype),
    ) as stream:
        for start in range(0, len(audio), 2048):
            if cancel.is_set():
                break
            chunk = audio[start : start + 2048]
            if on_volume:
                rms = np.sqrt(np.mean(chunk**2)) if chunk.size > 0 else 0
                on_volume(float(rms))
            stream.write(chunk)


class Speaker:
    def __init__(self) -> None:
        self.enabled = True
        self._active = threading.Event()
        self._cancel = threading.Event()
        self._process: subprocess.Popen | None = None
        self._process_lock = threading.Lock()

    @property
    def speaking(self) -> bool:
        return self._active.is_set()

    def stop(self) -> None:
        self._cancel.set()
        try:
            sd.stop()
        except Exception:
            pass
        with self._process_lock:
            if self._process is not None and self._process.poll() is None:
                self._process.terminate()

    def _sapi_speak(self, text: str, cancel: threading.Event) -> None:
        env = os.environ.copy()
        env["FRIDAY_TTS_TEXT"] = text
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        process = subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-Command", _SAPI_SCRIPT],
            env=env,
            creationflags=flags,
        )
        with self._process_lock:
            self._process = process
        while process.poll() is None and not cancel.is_set():
            time.sleep(0.05)
        if cancel.is_set() and process.poll() is None:
            process.terminate()
        with self._process_lock:
            if self._process is process:
                self._process = None

    async def _speak_text(
        self,
        text: str,
        cancel: threading.Event,
        on_volume: callable | None = None,
    ) -> None:
        try:
            loop = asyncio.get_running_loop()
            if config.TTS_MODE.lower() == "emily":
                result = await synthesize_online(text)
                if result is None:
                    result = await loop.run_in_executor(None, synthesize_local, text)
            else:
                result = await loop.run_in_executor(None, synthesize_local, text)
            if cancel.is_set():
                return
            if result is None:
                await loop.run_in_executor(
                    None,
                    functools.partial(self._sapi_speak, text, cancel),
                )
                return
            audio, rate = result
            await loop.run_in_executor(
                None,
                functools.partial(_play, audio, rate, cancel, on_volume),
            )
        except Exception as exc:
            print(f"[FRIDAY] speech error: {exc.__class__.__name__}: {exc}")

    async def speak(self, text: str, on_volume: callable | None = None) -> None:
        if not self.enabled or not text.strip():
            return
        self.stop()
        cancel = threading.Event()
        self._cancel = cancel
        self._active.set()
        try:
            for chunk in speech_chunks(text):
                if cancel.is_set():
                    break
                await self._speak_text(chunk, cancel, on_volume)
        finally:
            self._active.clear()

    async def speak_stream(
        self,
        queue: asyncio.Queue,
        cancel: threading.Event,
        on_volume: callable | None = None,
        on_started: callable | None = None,
    ) -> None:
        """Speak complete sentences as they arrive, pipelining synthesis with playback."""
        if not self.enabled:
            return
        self.stop()
        cancel = cancel or threading.Event()
        sentq: asyncio.Queue = asyncio.Queue()
        started = False
        self._cancel = threading.Event()
        self._active.set()

        async def producer() -> None:
            buffer = ""
            try:
                while True:
                    try:
                        piece = await asyncio.wait_for(queue.get(), timeout=0.5)
                    except asyncio.TimeoutError:
                        piece = _TIMEOUT
                    if cancel.is_set():
                        break
                    if piece is _TIMEOUT:
                        if buffer.strip():
                            await sentq.put(buffer)
                            buffer = ""
                        continue
                    if piece is None:
                        break
                    buffer += str(piece)
                    sentences = split_sentences(buffer)
                    if sentences:
                        if re.search(r"[.!?]\s*$", buffer):
                            ready, buffer = sentences, ""
                        else:
                            ready, buffer = sentences[:-1], sentences[-1]
                        for sentence in ready:
                            if cancel.is_set():
                                break
                            await sentq.put(sentence)
                if buffer.strip() and not cancel.is_set():
                    await sentq.put(buffer)
            finally:
                await sentq.put(None)

        producer_task = asyncio.ensure_future(producer())

        async def synthesize(sentence: str):
            result = await asyncio.to_thread(synthesize_local, sentence)
            return result

        async def play_audio(audio, rate):
            await asyncio.to_thread(functools.partial(_play, audio, rate, self._cancel, on_volume))

        play_task = None
        try:
            while True:
                sentence = await sentq.get()
                if sentence is None:
                    break
                if cancel.is_set():
                    break
                if not started:
                    started = True
                    if on_started:
                        on_started()
                result = await synthesize(sentence)
                if cancel.is_set():
                    break
                if result is None:
                    if play_task is not None:
                        await play_task
                    await asyncio.to_thread(
                        functools.partial(self._sapi_speak, sentence, self._cancel)
                    )
                    continue
                audio, rate = result
                if play_task is not None:
                    await play_task
                play_task = asyncio.ensure_future(play_audio(audio, rate))
            if play_task is not None:
                await play_task
        finally:
            if not producer_task.done():
                producer_task.cancel()
            self._active.clear()
