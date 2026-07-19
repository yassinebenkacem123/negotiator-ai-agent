"""
WebSocket Media Stream Bridge — Twilio ↔ Whisper STT ↔ GPT-4o ↔ ElevenLabs TTS.

Real-time voice engine. Four concurrent asyncio tasks per call:

    1. _twilio_message_loop()        — receives audio from Twilio
    2. _tts_receive_loop()           — receives PCM 22050Hz from ElevenLabs
    3. _send_tts_audio_to_twilio()   — μ‑law 8000Hz back to Twilio
    4. _transcribe_and_respond()     — Whisper → GPT‑4o stream → ElevenLabs TTS
      (fire-and-forget per utterance, guarded against overlap)

Architecture decisions documented inline — see the three Challenge markers.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import re
import time
from typing import Any, Optional

try:
    import audioop                       # Python < 3.13 (stdlib)
except ModuleNotFoundError:
    import audioop_lts as audioop        # Python ≥ 3.13 (PyPI audioop-lts)

import numpy as np
import websockets
from fastapi import WebSocket, WebSocketDisconnect
from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants  —  everything that CAN vary per deployment lives in config.py
# ---------------------------------------------------------------------------

TWILIO_SAMPLE_RATE  = 8000          # μ‑law  (Twilio → us)
PCM_SAMPLE_RATE     = 16000         # 16‑bit  (us → Whisper)
PCM_SAMPLE_WIDTH    = 2             # bytes / sample
ELEVENLABS_SAMPLE_RATE = 22050      # 16‑bit  (ElevenLabs → us)

WHISPER_MODEL = "whisper-1"
GPT_MODEL     = "gpt-4o"

SYSTEM_PROMPT = (
    "You are an AI negotiator calling a home‑improvement provider on behalf of "
    "a customer. Be polite, professional and persistent. Identify yourself as an "
    "AI if asked; never claim to be human. Keep responses short — one or two "
    "sentences. After you get a price, ask if there is flexibility. If they "
    "will not budge, accept, thank them, and end with a clear summary."
)

# ---------------------------------------------------------------------------
# Audio helpers  (Challenge 3 — correct format chain, all in‑process)
# ---------------------------------------------------------------------------

def ulaw_to_pcm(ulaw_bytes: bytes) -> bytes:
    """μ‑law 8 kHz → 16‑bit PCM 16 kHz  (in → Whisper)."""
    lin_8k  = audioop.ulaw2lin(ulaw_bytes, 2)
    lin_16k = audioop.ratecv(lin_8k, 2, 1, TWILIO_SAMPLE_RATE, PCM_SAMPLE_RATE, None)[0]
    return lin_16k


def lin22050_to_ulaw8000(pcm_22050: bytes) -> bytes:
    """16‑bit PCM 22 050 Hz → μ‑law 8 kHz  (ElevenLabs → Twilio).

    Uses a crude low‑pass filter (adjacent‑sample averaging) before the 2.75×
    downscale so frequencies above the 4 kHz Nyquist limit are attenuated
    instead of aliasing into the output.
    """
    arr = np.frombuffer(pcm_22050, dtype=np.int16).astype(np.float64)
    # simple moving‑average low‑pass (kernel width ≈ 6 samples @ 22 050 Hz)
    kernel = np.ones(6) / 6.0
    filtered = np.convolve(arr, kernel, mode="same").astype(np.int16)
    pcm_8k = audioop.ratecv(filtered.tobytes(), 2, 1, ELEVENLABS_SAMPLE_RATE, TWILIO_SAMPLE_RATE, None)[0]
    return audioop.lin2ulaw(pcm_8k, 2)


def _rms_energy(pcm_16: bytes) -> float:
    """Peak‑normalised RMS over a 20 ms window (≈320 samples @ 16 kHz)."""
    arr = np.frombuffer(pcm_16, dtype=np.int16).astype(np.float64)
    if arr.size == 0:
        return 0.0
    peak = float(np.abs(arr).max()) or 1.0
    return float(np.sqrt(np.mean(arr ** 2))) / peak


# ---------------------------------------------------------------------------
# VAD buffer  (Challenge 2 helper)
# ---------------------------------------------------------------------------

class VADBuffer:
    """Accumulates audio, fires "should transcribe" after trailing silence."""

    def __init__(self) -> None:
        self._buf = bytearray()
        self._silence = 0
        self._speaking = False

    def feed(self, pcm: bytes) -> None:
        e = _rms_energy(pcm)
        if e > (settings.vad_energy_threshold / 32768.0):       # ratio, not raw
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
# ElevenLabs TTS  (Challenge 1 — streaming input)
# ---------------------------------------------------------------------------

class TTSSession:
    """One long‑lived ElevenLabs streaming‑TTS WebSocket.

    Text is fed via *speak_chunk()* as it arrives (streaming GPT‑4o tokens).
    Audio chunks are pushed onto *audio_queue* for a dedicated sender task.
    The connection stays open across multiple utterances.
    """

    def __init__(self) -> None:
        self.ws: Any = None
        self.audio_queue: asyncio.Queue[Optional[bytes]] = asyncio.Queue()
        self._connected = False
        self._bos_needed = True
        self._ws_dead = False       # set when the WS closes unexpectedly

    # ── lifecycle ────────────────────────────────────────────────

    async def connect(self) -> None:
        url = (
            f"wss://api.elevenlabs.io/v1/text-to-speech/"
            f"{settings.elevenlabs_voice_id}"
            f"/stream-input?model_id=eleven_turbo_v2_5"
            f"&optimize_streaming_latency=4"
            f"&output_format=pcm_22050"
        )
        self.ws = await websockets.connect(
            url,
            extra_headers={"xi-api-key": settings.elevenlabs_api_key},
        )
        self._connected = True
        self._ws_dead = False

    async def close(self) -> None:
        self._connected = False
        self._ws_dead = True
        if self.ws:
            try:
                # EOS that also signals the WS handler to unwind
                await self.ws.send(json.dumps({"text": "", "flush": True}))
                await self.ws.close()
            except Exception:
                pass
        # unblock anyone waiting on the queue
        await self.audio_queue.put(None)

    # ── streaming  ───────────────────────────────────────────────

    async def speak_chunk(self, text: str) -> None:
        """Send a (possibly partial) text buffer to be synthesised.

        ElevenLabs' streaming TTS requires phrase‑level input for natural
        prosody — the caller (StreamHandler) is responsible for buffering
        GPT‑4o tokens until a natural break before calling this method.
        """
        if not self._connected:
            raise RuntimeError("TTS not connected")
        if self._bos_needed:
            await self.ws.send(json.dumps({
                "text": " ",
                "voice_settings": {"stability": 0.4, "similarity_boost": 0.8},
            }))
            self._bos_needed = False
        await self.ws.send(json.dumps({
            "text": text,
            "try_trigger_generation": True,
        }))

    async def end_utterance(self) -> None:
        """Send a close‑of‑utterance marker so the TTS flushes its output."""
        if self._connected:
            await self.ws.send(json.dumps({"text": ""}))
        self._bos_needed = True

    async def interrupt(self) -> None:
        """Stop current generation and prepare for a new utterance."""
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

    # ── receiver (background task) ────────────────────────────────

    async def receive_loop(self) -> None:
        """Push audio chunks onto audio_queue for the call's lifetime."""
        if not self._connected:
            return
        try:
            async for msg in self.ws:
                data = json.loads(msg)
                if "audio" in data and data["audio"]:
                    await self.audio_queue.put(base64.b64decode(data["audio"]))
                if data.get("is_final"):
                    await self.audio_queue.put(None)   # utterance boundary
                # continue — next utterance arrives on same WS
        except Exception:
            pass
        finally:
            self._ws_dead = True
            await self.audio_queue.put(None)


# ---------------------------------------------------------------------------
# StreamHandler — one Twilio call
# ---------------------------------------------------------------------------

class StreamHandler:
    """Per‑call orchestrator.

    ── Challenge 1 (streaming) ──
    GPT‑4o response is streamed token‑by‑token. Tokens are buffered until a
    natural phrase boundary (~80 chars or end‑of‑sentence), then flushed to
    ElevenLabs. This preserves natural prosody while keeping first‑word
    latency under 500 ms.

    ── Challenge 2 (interruption) ──
    While the AI is speaking every incoming chunk is VAD‑analysed. If the
    remote party produces sustained speech (≥ 300 ms), we:
        1.  Cancel the GPT‑4o streaming Task.
        2.  Clear Twilio's playback buffer.
        3.  Interrupt ElevenLabs TTS.
        4.  Drain the audio queue.
        5.  Reset the VAD buffer so the human's speech is captured cleanly.
    An echo‑guard (300 ms after each audio send) prevents the AI's own voice
    from triggering false interrupts.

    ── Challenge 3 (encoding) ──
    See the two module‑level converters — everything is in‑process audioop +
    numpy, no subprocess / ffmpeg needed.
    """

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

        # Audio pipeline
        self.vad           = VADBuffer()
        self.tts: Optional[TTSSession] = None
        self._openai       = AsyncOpenAI(api_key=settings.openai_api_key)

        # Conversation state
        self._history: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        self._running      = True

        # Interrupt / back‑pressure guards
        self._playing      = False          # True while TTS audio is being sent
        self._sending      = asyncio.Event()  # set when audio chunks are flowing
        self._drained      = asyncio.Event()  # set when send loop finishes utterance
        self._drained.set()                   # start drained
        self._last_audio_sent: float = 0.0
        self._resp_task: Optional[asyncio.Task] = None   # current GPT‑4o stream

        # Interrupt VAD — need sustained speech before we react
        self._intr_frames = 0

        # Call summary
        self._summary: dict[str, Any] = {
            "transcript_segments": [],
            "final_price": None,
            "outcome": "unknown",
        }

    # ── Public entry ────────────────────────────────────────────────

    async def run(self) -> dict[str, Any]:
        self.tts = TTSSession()
        await self.tts.connect()

        recv  = asyncio.create_task(self._tts_receive_loop())
        send  = asyncio.create_task(self._send_loop())

        try:
            await self._twilio_loop()
        except WebSocketDisconnect:
            logger.info(f"[{self.company}] WebSocket disconnect")
        except Exception:
            logger.exception(f"[{self.company}] stream fatal")
        finally:
            self._running = False
            # Shutdown cascade  (fixes #1 — deadlock on call end)
            if self.tts:
                await self.tts.close()
            await asyncio.gather(recv, send, return_exceptions=True)
            await self._cleanup()

        return self._summary

    # ── Twilio message loop ─────────────────────────────────────────

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
        greeting = (
            f"Hello, I am an AI assistant calling about {self.service}. "
            f"Am I speaking with someone from {self.company}?"
        )
        await self._speak_one(greeting)

    # ── Audio input ─────────────────────────────────────────────────

    async def _on_audio(self, b64_payload: str) -> None:
        ulaw = base64.b64decode(b64_payload)
        pcm  = ulaw_to_pcm(ulaw)

        now  = time.monotonic()

        # ── Echo guard (#12) — ignore our own voice for echo_guard_ms ──
        if now - self._last_audio_sent < (settings.echo_guard_ms / 1000.0):
            return

        energy = _rms_energy(pcm)

        # ── Interrupt (#2, #8) — sustained speech while AI is playing ──
        speech_thresh = settings.vad_energy_threshold / 32768.0
        if self._playing and energy > speech_thresh:
            self._intr_frames += 1
            if self._intr_frames >= settings.interrupt_min_frames:
                logger.info(f"[{self.company}] INTERRUPT after {self._intr_frames} frames")
                await self._do_interrupt()
                self._intr_frames = 0
                self.vad.feed(pcm)          # capture what they're saying now
                return
        else:
            self._intr_frames = 0

        if self._playing:
            return

        if self._resp_task and not self._resp_task.done():
            return    # already processing an utterance (#3)

        self.vad.feed(pcm)
        if self.vad.ready():
            data = self.vad.flush()
            if data:
                self._resp_task = asyncio.create_task(self._transcribe_and_respond(data))

    # ── Interrupt (Challenge 2) ─────────────────────────────────────

    async def _do_interrupt(self) -> None:
        self._playing = False

        # 1. Cancel in‑flight GPT‑4o streaming task
        if self._resp_task and not self._resp_task.done():
            self._resp_task.cancel()
            self._resp_task = None

        # 2. Clear Twilio's playback buffer (immediate silence on far end)
        try:
            await self.ws.send_json({"event": "clear", "streamSid": self.stream_sid})
        except Exception:
            pass

        # 3. Stop ElevenLabs generation
        if self.tts:
            await self.tts.interrupt()
            while not self.tts.audio_queue.empty():
                try:
                    self.tts.audio_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

        # 4. Reset VAD so the human's speech is captured fresh
        self.vad.reset()

        # 5. Let the LLM know it was cut off  (#5 — preserves context)
        self._history.append({
            "role": "system",
            "content": "You were interrupted. Acknowledge and let them speak.",
        })
        # If the cancelled stream had already appended a partial assistant
        # entry it will be incoherent — drop entries added during *this*
        # utterance's streaming window?  Safer to leave the system marker
        # and let the LLM sort it out.

    # ── STT + LLM stream ────────────────────────────────────────────

    async def _transcribe_and_respond(self, audio_data: bytes) -> None:
        try:
            transcript = await self._whisper(audio_data)
            if not transcript or not transcript.strip():
                return
            logger.info(f"[{self.company}] ▶ {transcript}")
            self._summary["transcript_segments"].append({"role": "user", "text": transcript})
            await self._llm_stream_to_tts(transcript)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception(f"[{self.company}] transcribe error")

    async def _whisper(self, pcm_data: bytes) -> str:
        import wave
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

    # ── LLM streaming → TTS  (Challenge 1) ──────────────────────────

    async def _llm_stream_to_tts(self, user_text: str) -> None:
        """Stream GPT‑4o response tokens; buffer to phrase boundaries; feed TTS."""

        self._history.append({"role": "user", "content": user_text})

        collected: list[str] = []       # final full response
        tts_buffer: str   = ""          # chars accumulated before flushing to TTS
        first            = True

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

                # Flush to TTS when we hit a natural break  (#4 fix)
                if _is_phrase_boundary(tts_buffer):
                    await self.tts.speak_chunk(tts_buffer)
                    tts_buffer = ""

            # Drain any leftover characters
            if tts_buffer:
                await self.tts.speak_chunk(tts_buffer)

        except asyncio.CancelledError:
            # (#5) Append whatever we captured so history stays balanced
            if collected:
                partial = "".join(collected) + " [interrupted]"
                self._history.append({"role": "assistant", "content": partial})
            raise   # let the task's outer handler catch it

        full = "".join(collected)
        self._history.append({"role": "assistant", "content": full})
        self._summary["transcript_segments"].append({"role": "assistant", "text": full})
        logger.info(f"[{self.company}] ◀ {full[:150]}")

        # Close the TTS utterance
        if self.tts:
            await self.tts.end_utterance()

        # Un-mark playing once audio is actually drained  (#2 fix)
        try:
            await asyncio.wait_for(self._drained.wait(), timeout=30.0)
        except asyncio.TimeoutError:
            pass
        self._playing = False

        if self._is_goodbye(full):
            await self._end_call()

    # ── TTS background tasks ────────────────────────────────────────

    async def _tts_receive_loop(self) -> None:
        """Feeds audio_queue from the ElevenLabs WebSocket."""
        await self.tts.receive_loop()

    async def _send_loop(self) -> None:
        """Takes audio from the queue, converts, sends to Twilio."""
        while True:
            await self._sending.wait()          # only block when there is work
            try:
                chunk = await asyncio.wait_for(self.tts.audio_queue.get(), timeout=30.0)
            except asyncio.TimeoutError:
                if self.tts and self.tts.is_dead:
                    return
                continue

            if chunk is None:
                # End of utterance — signal that we are drained  (#2 fix)
                self._sending.clear()
                self._drained.set()
                continue

            ulaw = lin22050_to_ulaw8000(chunk)
            payload = base64.b64encode(ulaw).decode("ascii")
            now = time.monotonic()

            try:
                await self.ws.send_json({
                    "event": "media",
                    "streamSid": self.stream_sid,
                    "media": {"payload": payload},
                })
            except Exception:
                return

            # Timestamp for echo guard  (#12)
            self._last_audio_sent = time.monotonic()
            # Small sleep so twilio media packets are paced
            await asyncio.sleep(0.0)

    # ── Greeting — simple non‑streaming path ────────────────────────

    async def _speak_one(self, text: str) -> None:
        """Speak a short text (initial greeting) — blocking until audio drains."""
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

    # ── Call end (#6)  ──────────────────────────────────────────────

    async def _end_call(self) -> None:
        """Close the WebSocket — this actually hangs up the call."""
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
        # Final price extraction
        if self._summary["transcript_segments"]:
            full = " ".join(s["text"] for s in self._summary["transcript_segments"])
            m = re.search(r"\$(\d{2,4})(?:\.(\d{2}))?", full)
            if m:
                d, c = int(m.group(1)), int(m.group(2) or 0)
                self._summary["final_price"] = float(f"{d}.{c:02d}")
            self._summary["outcome"] = "completed"


# ---------------------------------------------------------------------------
# Phrase‑boundary helper  (#4 — buffer tokens before feeding TTS)
# ---------------------------------------------------------------------------

_SENTENCE_END = frozenset(".!?\n")
_CLAUSE_END   = frozenset(",;:-")


def _is_phrase_boundary(text: str) -> bool:
    """Return True when *text* should be flushed to ElevenLabs.

    Triggers on: end‑of‑sentence punctuation, comma/clause markers after
    enough characters, or a hard character limit.
    """
    if not text:
        return False
    if text[-1] in _SENTENCE_END:
        return True
    if len(text) >= settings.tts_chunk_buffer_chars:
        if text[-1] in _CLAUSE_END:
            return True
        if len(text) >= settings.tts_chunk_buffer_chars * 1.5:
            return True   # hard cap — flush regardless
    return False


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
