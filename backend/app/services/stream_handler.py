"""
WebSocket Media Stream Bridge -- Twilio <-> Whisper STT <-> GPT-4o <-> ElevenLabs TTS.

Real-time voice engine. Four concurrent asyncio tasks per call.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import re
import time
import wave
from typing import Any, Optional

import numpy as np
import websockets
from fastapi import WebSocket, WebSocketDisconnect
from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TWILIO_SAMPLE_RATE  = 8000
PCM_SAMPLE_RATE     = 16000
PCM_SAMPLE_WIDTH    = 2
ELEVENLABS_SAMPLE_RATE = 22050
WHISPER_MODEL = "whisper-1"
GPT_MODEL     = "gpt-4o"

SYSTEM_PROMPT = (
    "You are an AI negotiator calling a home-improvement provider on behalf of "
    "a customer. Be polite, professional and persistent. Identify yourself as an "
    "AI if asked; never claim to be human. Keep responses short - one or two "
    "sentences. After you get a price, ask if there is flexibility. If they "
    "will not budge, accept, thank them, and end with a clear summary."
)

# ---------------------------------------------------------------------------
# Audio helpers
# ---------------------------------------------------------------------------

try:
    import audioop
except ModuleNotFoundError:
    import audioop_lts as audioop


def ulaw_to_pcm(ulaw_bytes: bytes) -> bytes:
    lin_8k  = audioop.ulaw2lin(ulaw_bytes, 2)
    lin_16k = audioop.ratecv(lin_8k, 2, 1, TWILIO_SAMPLE_RATE, PCM_SAMPLE_RATE, None)[0]
    return lin_16k


def lin22050_to_ulaw8000(pcm_22050: bytes) -> bytes:
    arr = np.frombuffer(pcm_22050, dtype=np.int16).astype(np.float64)
    kernel = np.ones(6) / 6.0
    filtered = np.convolve(arr, kernel, mode="same").astype(np.int16)
    pcm_8k = audioop.ratecv(filtered.tobytes(), 2, 1, ELEVENLABS_SAMPLE_RATE, TWILIO_SAMPLE_RATE, None)[0]
    return audioop.lin2ulaw(pcm_8k, 2)


def _rms_energy(pcm_16: bytes) -> float:
    arr = np.frombuffer(pcm_16, dtype=np.int16).astype(np.float64)
    if arr.size == 0:
        return 0.0
    peak = float(np.abs(arr).max()) or 1.0
    return float(np.sqrt(np.mean(arr ** 2))) / peak


class VADBuffer:
    def __init__(self) -> None:
        self._buf = bytearray()
        self._silence = 0
        self._speaking = False

    def feed(self, pcm: bytes) -> None:
        e = _rms_energy(pcm)
        if e > (settings.vad_energy_threshold / 32768.0):
            self._buf.extend(pcm)
            self._silence = 0
            self._speaking = True
        elif self._speaking:
            self._silence += 1
            self._buf.extend(pcm)

    def ready(self) -> bool:
        if not self._speaking:
            return False
        if self._silence >= settings.vad_silence_frames_max:
            return True
        dur = len(self._buf) / (PCM_SAMPLE_RATE * PCM_SAMPLE_WIDTH)
        if dur >= settings.vad_max_buffer_secs:
            return True
        return False

    def flush(self) -> Optional[bytes]:
        if not self._buf:
            return None
        d = bytes(self._buf)
        self._buf.clear()
        self._silence = 0
        self._speaking = False
        return d

    def reset(self) -> None:
        self._buf.clear()
        self._silence = 0
        self._speaking = False


# ---------------------------------------------------------------------------
# ElevenLabs TTS
# ---------------------------------------------------------------------------

class TTSSession:
    def __init__(self) -> None:
        self.ws: Any = None
        self.audio_queue: asyncio.Queue[Optional[bytes]] = asyncio.Queue()
        self._connected = False
        self._bos_needed = True
        self._ws_dead = False

    async def connect(self) -> None:
        url = (
            f"wss://api.elevenlabs.io/v1/text-to-speech/"
            f"{settings.elevenlabs_voice_id}"
            f"/stream-input?model_id=eleven_turbo_v2_5"
            f"&optimize_streaming_latency=4"
            f"&output_format=pcm_22050"
        )
        self.ws = await websockets.connect(url)
        self._connected = True
        self._ws_dead = False

    async def close(self) -> None:
        self._connected = False
        self._ws_dead = True
        if self.ws:
            try:
                await self.ws.send(json.dumps({"text": "", "flush": True}))
                await self.ws.close()
            except Exception:
                pass
        await self.audio_queue.put(None)

    async def speak_chunk(self, text: str) -> None:
        if not self._connected:
            raise RuntimeError("TTS not connected")
        if self._bos_needed:
            await self.ws.send(json.dumps({
                "text": " ",
                "voice_settings": {"stability": 0.4, "similarity_boost": 0.8},
                "xi_api_key": settings.elevenlabs_api_key,
            }))
            self._bos_needed = False
        await self.ws.send(json.dumps({
            "text": text,
            "try_trigger_generation": True,
        }))

    async def end_utterance(self) -> None:
        if self._connected:
            await self.ws.send(json.dumps({"text": ""}))
        self._bos_needed = True

    async def interrupt(self) -> None:
        if not self._connected:
            return
        try:
            await self.ws.send(json.dumps({"text": "", "flush": True}))
            self._bos_needed = True
        except Exception:
            pass

    @property
    def is_dead(self) -> bool:
        return self._ws_dead

    async def receive_loop(self) -> None:
        if not self._connected:
            return
        try:
            async for msg in self.ws:
                data = json.loads(msg)
                if "audio" in data and data["audio"]:
                    await self.audio_queue.put(base64.b64decode(data["audio"]))
                if data.get("is_final"):
                    await self.audio_queue.put(None)
        except Exception:
            pass
        finally:
            self._ws_dead = True
            await self.audio_queue.put(None)


# ---------------------------------------------------------------------------
# Phrase-boundary helper
# ---------------------------------------------------------------------------

_SENTENCE_END = frozenset(".!?\n")
_CLAUSE_END   = frozenset(",;:-")


def _is_phrase_boundary(text: str) -> bool:
    if not text:
        return False
    if text[-1] in _SENTENCE_END:
        return True
    if len(text) >= settings.tts_chunk_buffer_chars:
        if text[-1] in _CLAUSE_END:
            return True
        if len(text) >= settings.tts_chunk_buffer_chars * 1.5:
            return True
    return False


# ---------------------------------------------------------------------------
# StreamHandler -- one Twilio call
# ---------------------------------------------------------------------------

class StreamHandler:
    def __init__(
        self,
        websocket: WebSocket,
        stream_sid: str,
        call_sid: str,
        company_name: str = "Provider",
        service_description: str = "home improvement services",
    ) -> None:
        self.ws            = websocket
        self.stream_sid    = stream_sid
        self.call_sid      = call_sid
        self.company       = company_name
        self.service       = service_description

        self.vad           = VADBuffer()
        self.tts: Optional[TTSSession] = None
        self._openai       = AsyncOpenAI(api_key=settings.openai_api_key)

        self._history: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        self._running      = True

        self._playing      = False
        self._sending      = asyncio.Event()
        self._drained      = asyncio.Event()
        self._drained.set()
        self._last_audio_sent: float = 0.0
        self._resp_task: Optional[asyncio.Task] = None
        self._intr_frames = 0

        self._summary: dict[str, Any] = {
            "transcript_segments": [],
            "final_price": None,
            "outcome": "unknown",
        }

    # -- Public entry --

    async def run(self) -> dict[str, Any]:
        self.tts = TTSSession()
        try:
            await self.tts.connect()
        except Exception:
            logger.exception(f"[{self.company}] TTS connect failed -- check ELEVENLABS_API_KEY")
            self.tts = None

        recv = None
        send = None
        if self.tts:
            recv = asyncio.create_task(self._tts_receive_loop())
            send = asyncio.create_task(self._send_loop())

        try:
            await self._twilio_loop()
        except WebSocketDisconnect:
            logger.info(f"[{self.company}] WebSocket disconnect")
        except Exception:
            logger.exception(f"[{self.company}] stream fatal")
        finally:
            self._running = False
            if self.tts:
                await self.tts.close()
            tasks = [t for t in (recv, send) if t is not None]
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            await self._cleanup()

        return self._summary

    # -- Twilio message loop --

    async def _twilio_loop(self) -> None:
        while self._running:
            try:
                raw = await self.ws.receive_text()
            except WebSocketDisconnect:
                return
            msg = json.loads(raw)
            event = msg.get("event", "")

            if event == "connected":
                pass
            elif event == "start":
                self.stream_sid = msg["streamSid"]
                self.call_sid   = msg["start"]["callSid"]
                logger.info(f"[{self.company}] stream start  sid={self.stream_sid}")
                asyncio.create_task(self._greet())
            elif event == "media":
                await self._on_audio(msg["media"]["payload"])
            elif event == "stop":
                logger.info(f"[{self.company}] stream stop")
                self._running = False
                return

    async def _greet(self) -> None:
        if not self.tts:
            logger.warning(f"[{self.company}] TTS not available -- skipping greeting")
            return
        greeting = (
            f"Hello, I am an AI assistant calling about {self.service}. "
            f"Am I speaking with someone from {self.company}?"
        )
        await self._speak_one(greeting)

    # -- Audio input --

    async def _on_audio(self, b64_payload: str) -> None:
        ulaw = base64.b64decode(b64_payload)
        pcm  = ulaw_to_pcm(ulaw)
        now  = time.monotonic()

        if now - self._last_audio_sent < (settings.echo_guard_ms / 1000.0):
            return

        energy = _rms_energy(pcm)
        speech_thresh = settings.vad_energy_threshold / 32768.0

        if self._playing and energy > speech_thresh:
            self._intr_frames += 1
            if self._intr_frames >= settings.interrupt_min_frames:
                logger.info(f"[{self.company}] INTERRUPT after {self._intr_frames} frames")
                await self._do_interrupt()
                self._intr_frames = 0
                self.vad.feed(pcm)
                return
        else:
            self._intr_frames = 0

        if self._playing:
            return

        if self._resp_task and not self._resp_task.done():
            return

        self.vad.feed(pcm)
        if self.vad.ready():
            data = self.vad.flush()
            if data:
                self._resp_task = asyncio.create_task(self._transcribe_and_respond(data))

    # -- Interrupt --

    async def _do_interrupt(self) -> None:
        self._playing = False
        if self._resp_task and not self._resp_task.done():
            self._resp_task.cancel()
            self._resp_task = None
        try:
            await self.ws.send_json({"event": "clear", "streamSid": self.stream_sid})
        except Exception:
            pass
        if self.tts:
            await self.tts.interrupt()
            while not self.tts.audio_queue.empty():
                try:
                    self.tts.audio_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
        self.vad.reset()
        self._history.append({
            "role": "system",
            "content": "You were interrupted. Acknowledge and let them speak.",
        })

    # -- STT + LLM stream --

    async def _transcribe_and_respond(self, audio_data: bytes) -> None:
        try:
            transcript = await self._whisper(audio_data)
            if not transcript or not transcript.strip():
                return
            logger.info(f"[{self.company}] > {transcript}")
            self._summary["transcript_segments"].append({"role": "user", "text": transcript})
            await self._llm_stream_to_tts(transcript)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception(f"[{self.company}] transcribe error")

    async def _whisper(self, pcm_data: bytes) -> str:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(PCM_SAMPLE_WIDTH)
            wf.setframerate(PCM_SAMPLE_RATE)
            wf.writeframes(pcm_data)
        buf.seek(0)
        r = await self._openai.audio.transcriptions.create(
            model=WHISPER_MODEL, file=("audio.wav", buf, "audio/wav"), language="en",
        )
        return r.text.strip()

    # -- LLM streaming -> TTS --

    async def _llm_stream_to_tts(self, user_text: str) -> None:
        self._history.append({"role": "user", "content": user_text})
        collected: list[str] = []
        tts_buffer: str = ""
        first = True

        stream = await self._openai.chat.completions.create(
            model=GPT_MODEL,
            messages=self._history,
            temperature=0.7,
            max_tokens=300,
            stream=True,
        )

        try:
            async for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                token = delta.content if delta else None
                if not token:
                    continue
                collected.append(token)
                tts_buffer += token
                if first:
                    self._playing = True
                    self._drained.clear()
                    self._sending.set()
                    first = False
                if _is_phrase_boundary(tts_buffer) and self.tts:
                    await self.tts.speak_chunk(tts_buffer)
                    tts_buffer = ""
            if tts_buffer and self.tts:
                await self.tts.speak_chunk(tts_buffer)
        except asyncio.CancelledError:
            if collected:
                partial = "".join(collected) + " [interrupted]"
                self._history.append({"role": "assistant", "content": partial})
            raise

        full = "".join(collected)
        self._history.append({"role": "assistant", "content": full})
        self._summary["transcript_segments"].append({"role": "assistant", "text": full})
        logger.info(f"[{self.company}] < {full[:150]}")

        if self.tts:
            await self.tts.end_utterance()

        try:
            await asyncio.wait_for(self._drained.wait(), timeout=30.0)
        except asyncio.TimeoutError:
            pass
        self._playing = False

        if self._is_goodbye(full):
            await self._end_call()

    # -- TTS background tasks --

    async def _tts_receive_loop(self) -> None:
        if self.tts:
            await self.tts.receive_loop()

    async def _send_loop(self) -> None:
        while True:
            try:
                await asyncio.wait_for(self._sending.wait(), timeout=1.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                if not self._running:
                    return
                continue
            await asyncio.wait_for(self._sending.wait(), timeout=1.0)
            if not self.tts:
                await asyncio.sleep(0.1)
                continue
            try:
                chunk = await asyncio.wait_for(self.tts.audio_queue.get(), timeout=30.0)
            except asyncio.TimeoutError:
                if self.tts.is_dead:
                    return
                continue
            if chunk is None:
                self._sending.clear()
                self._drained.set()
                continue
            ulaw = lin22050_to_ulaw8000(chunk)
            payload = base64.b64encode(ulaw).decode("ascii")
            try:
                await self.ws.send_json({
                    "event": "media",
                    "streamSid": self.stream_sid,
                    "media": {"payload": payload},
                })
            except Exception:
                return
            self._last_audio_sent = time.monotonic()
            await asyncio.sleep(0.0)

    # -- Greeting --

    async def _speak_one(self, text: str) -> None:
        if not self.tts:
            return
        self._playing = True
        self._drained.clear()
        self._sending.set()
        await self.tts.speak_chunk(text)
        await self.tts.end_utterance()
        try:
            await asyncio.wait_for(self._drained.wait(), timeout=30.0)
        except asyncio.TimeoutError:
            pass
        self._playing = False

    # -- Call end --

    async def _end_call(self) -> None:
        self._running = False
        try:
            await self.ws.close()
        except Exception:
            pass

    @staticmethod
    def _is_goodbye(text: str) -> bool:
        lo = text.lower()
        return any(p in lo for p in [
            "goodbye", "thank you for your time", "have a great day",
            "thanks for your help",
        ])

    async def _cleanup(self) -> None:
        if self._summary["transcript_segments"]:
            full = " ".join(s["text"] for s in self._summary["transcript_segments"])
            m = re.search(r"\$(\d{2,4})(?:\.(\d{2}))?", full)
            if m:
                d, c = int(m.group(1)), int(m.group(2) or 0)
                self._summary["final_price"] = float(f"{d}.{c:02d}")
            self._summary["outcome"] = "completed"


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

async def handle_media_stream(
    websocket: WebSocket,
    company_name: str = "Provider",
    service_description: str = "home improvement services",
) -> dict[str, Any]:
    await websocket.accept()
    handler = StreamHandler(
        websocket=websocket,
        stream_sid="",
        call_sid="",
        company_name=company_name,
        service_description=service_description,
    )
    return await handler.run()
