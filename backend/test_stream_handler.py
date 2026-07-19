"""
test_stream_handler.py — Standalone test for the Twilio → Whisper → GPT‑4o → ElevenLabs pipeline.

TWO MODES — run with the matching flag:

  MODE 1 (WebSocket — needs the server running):
      python test_stream_handler.py ws

      Connects to ws://localhost:8000/media-stream/test, sends the Twilio
      handshake, waits for the AI greeting, sends silence so the AI can
      finish speaking, then closes. Captured audio is saved to WAV.

  MODE 2 (Direct API — no server needed, just your .env keys):
      python test_stream_handler.py direct

      Sends a test message to GPT‑4o with the negotiation system prompt,
      takes the response, synthesises it via ElevenLabs TTS, saves to
      test_output_direct.wav.  Purely validates the STT→LLM→TTS chain in isolation.
"""

import asyncio
import base64
import io
import json
import os
import sys
import wave

TWILIO_SAMPLE_RATE = 8000  # µ‑law, 8 kHz


def ulaw_to_linear16(ulaw_bytes: bytes) -> bytes:
    import audioop
    return audioop.ulaw2lin(ulaw_bytes, 2)


def _make_silence_ulaw(duration_ms: int = 20) -> bytes:
    sample_count = int(TWILIO_SAMPLE_RATE * duration_ms / 1000)
    return b"\xff" * sample_count


# ── MODE 1: WebSocket test ─────────────────────────────────────────────

async def ws_test(host: str = "ws://localhost:8000") -> None:
    print(f"Connecting to {host}/media-stream/test ...")

    import websockets

    all_audio_chunks: list[bytes] = []
    stream_sid = f"test-{os.urandom(4).hex()}"
    call_sid = f"CA{os.urandom(16).hex()}"
    running = True

    async def sender(ws) -> None:
        """Background: send silence chunks to keep the stream alive."""
        silence = _make_silence_ulaw(20)
        try:
            while running:
                payload = base64.b64encode(silence).decode("ascii")
                await ws.send(json.dumps({
                    "event": "media",
                    "streamSid": stream_sid,
                    "media": {"payload": payload},
                }))
                await asyncio.sleep(0.02)  # 20ms — real-time pacing
        except Exception:
            pass

    async with websockets.connect(
        f"{host}/media-stream/test",
        max_size=2**24,
        ping_interval=20,
        close_timeout=5,
    ) as ws:
        # 1. Handshake — "connected" then "start"
        await ws.send(json.dumps({"event": "connected", "protocol": "Call", "version": "1.0.0"}))
        await ws.send(json.dumps({
            "event": "start",
            "streamSid": stream_sid,
            "start": {
                "streamSid": stream_sid,
                "accountSid": "ACtest",
                "callSid": call_sid,
                "tracks": ["inbound"],
                "mediaFormat": {
                    "encoding": "audio/x-mulaw",
                    "sampleRate": 8000,
                    "channels": 1,
                },
            },
        }))
        print(f"  → handshake done (callSid={call_sid})")

        # 2. Launch the sender in background
        send_task = asyncio.create_task(sender(ws))

        # 3. Listen for the AI's response — the server should send
        #    audio chunks (the greeting) via its _send_loop
        print("  → listening for AI greeting (8 s timeout) ...")
        try:
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=8.0)
                msg = json.loads(raw)
                if msg.get("event") == "media":
                    chunk = base64.b64decode(msg["media"]["payload"])
                    all_audio_chunks.append(chunk)
                    sys.stdout.write(".")
                    sys.stdout.flush()
                elif msg.get("event") == "stop":
                    break
        except asyncio.TimeoutError:
            print("  (timeout — no more audio from server)")

        running = False
        send_task.cancel()
        try:
            await send_task
        except asyncio.CancelledError:
            pass

        print(f"\n  → received {len(all_audio_chunks)} audio chunks")

    _save_to_wav(all_audio_chunks, "test_output_ws.wav")


# ── MODE 2: Direct API test ────────────────────────────────────────────

async def direct_test() -> None:
    from openai import AsyncOpenAI
    import websockets

    api_key = os.getenv("OPENAI_API_KEY", "")
    eleven_key = os.getenv("ELEVENLABS_API_KEY", "")
    voice_id = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")

    print(f"  OpenAI key:   {'✅ set' if api_key else '❌ missing'}")
    print(f"  ElevenLabs:   {'✅ set' if eleven_key else '❌ missing'}")
    print(f"  Voice ID:     {voice_id}")

    if not api_key or not eleven_key:
        print("ERROR: Both OPENAI_API_KEY and ELEVENLABS_API_KEY must be set.")
        return

    client = AsyncOpenAI(api_key=api_key)

    SYSTEM_PROMPT = (
        "You are an AI negotiator calling a home‑improvement provider on behalf of "
        "a customer. Be polite, professional and persistent. Identify yourself as an "
        "AI if asked; never claim to be human. Keep responses short — one or two "
        "sentences."
    )

    # ── Test 1 — GPT‑4o ──
    print("\n─── Test 1: GPT‑4o response ───")
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "Hello, is this the right number for moving services?"},
    ]
    resp = await client.chat.completions.create(
        model="gpt-4o", messages=messages, temperature=0.7, max_tokens=200,
    )
    reply = resp.choices[0].message.content.strip()
    print(f"  GPT‑4o says:  {reply}")

    # ── Test 2 — ElevenLabs TTS ──
    print("\n─── Test 2: ElevenLabs TTS synthesis ───")
    tts_url = (
        f"wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        f"/stream-input?model_id=eleven_turbo_v2_5"
        f"&optimize_streaming_latency=4"
        f"&output_format=pcm_22050"
    )
    try:
        async with websockets.connect(
            tts_url,
            extra_headers={"xi-api-key": eleven_key},
        ) as tts_ws:
            # BOS
            await tts_ws.send(json.dumps({
                "text": " ",
                "voice_settings": {"stability": 0.4, "similarity_boost": 0.8},
            }))
            # Speak
            short_text = reply[:250]
            await tts_ws.send(json.dumps({
                "text": short_text,
                "try_trigger_generation": True,
            }))
            await tts_ws.send(json.dumps({"text": ""}))  # EOS

            pcm_chunks: list[bytes] = []
            async for msg in tts_ws:
                data = json.loads(msg)
                if "audio" in data and data["audio"]:
                    pcm_chunks.append(base64.b64decode(data["audio"]))
                if data.get("is_final"):
                    break

        out_path = "test_output_direct.wav"
        wf = wave.open(out_path, "wb")
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(22050)
        wf.writeframes(b"".join(pcm_chunks))
        wf.close()
        total_bytes = sum(len(c) for c in pcm_chunks)
        print(f"  TTS audio saved → {out_path}  ({len(pcm_chunks)} chunks, {total_bytes} bytes)")

        if total_bytes > 0:
            print("\n✅ All direct tests passed — listen to test_output_direct.wav")
        else:
            print("\n⚠️  TTS returned zero audio bytes — check your ElevenLabs key + voice ID.")
    except Exception as e:
        print(f"  ❌ ElevenLabs TTS failed: {e}")


# ── Utility ─────────────────────────────────────────────────────────────

def _save_to_wav(chunks: list[bytes], path: str) -> None:
    if not chunks:
        print("  (no audio received — nothing to save)")
        return
    combined = b"".join(chunks)
    pcm = ulaw_to_linear16(combined)
    wf = wave.open(path, "wb")
    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(TWILIO_SAMPLE_RATE)
    wf.writeframes(pcm)
    wf.close()
    total = len(combined)
    duration_s = total / TWILIO_SAMPLE_RATE
    print(f"  audio saved → {path}  ({len(chunks)} chunks, {total} bytes, {duration_s:.1f}s)")


# ── Main ────────────────────────────────────────────────────────────────

def _load_dotenv() -> None:
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.isfile(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key, val = key.strip(), val.strip()
                if key and key not in os.environ:
                    os.environ[key] = val


if __name__ == "__main__":
    _load_dotenv()

    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    host = sys.argv[2] if len(sys.argv) > 2 else "ws://localhost:8000"

    if mode == "ws":
        print("=== Twilio WebSocket simulation ===\n")
        asyncio.run(ws_test(host))
    elif mode == "direct":
        print("=== Direct API test (GPT‑4o + ElevenLabs TTS) ===\n")
        asyncio.run(direct_test())
    else:
        print(__doc__)
        print("USAGE:")
        print("  python test_stream_handler.py ws       # start the server first!")
        print("  python test_stream_handler.py direct   # no server needed")
        print("  python test_stream_handler.py ws wss://abc.ngrok.io   # remote server")