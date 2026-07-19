
"""Test script."""
import asyncio, base64, json, os, sys, wave

TWILIO_SAMPLE_RATE = 8000

def _load_dotenv():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.isfile(p):
        for line in open(p):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                if k.strip() and k.strip() not in os.environ:
                    os.environ[k.strip()] = v.strip()

def ulaw_to_linear16(ulaw_bytes):
    try: import audioop
    except ModuleNotFoundError: import audioop_lts as audioop
    return audioop.ulaw2lin(ulaw_bytes, 2)

def _make_silence_ulaw(duration_ms=20):
    count = int(TWILIO_SAMPLE_RATE * duration_ms / 1000)
    return bytes([0xFF]) * count


async def ws_test(host="ws://localhost:8000"):
    import websockets
    print(f"Connecting to {host}/media-stream/test ...")
    all_audio = bytearray()
    stream_sid = "test-" + os.urandom(4).hex()
    call_sid = "CA" + os.urandom(16).hex()
    running = True

    async def sender(ws):
        silence = _make_silence_ulaw(20)
        try:
            while running:
                payload = base64.b64encode(silence).decode("ascii")
                await ws.send(json.dumps({
                    "event": "media", "streamSid": stream_sid,
                    "media": {"payload": payload},
                }))
                await asyncio.sleep(0.02)
        except Exception:
            pass

    try:
        async with websockets.connect(
            f"{host}/media-stream/test",
            max_size=2**24, ping_interval=60, close_timeout=5,
        ) as ws:
            # Wait for server to finish TTS connect (~2s)
            print("  server needs ~2s to connect to ElevenLabs TTS...")
            await asyncio.sleep(2.0)
            print("  sending handshake...")

            await ws.send(json.dumps({
                "event": "connected", "protocol": "Call", "version": "1.0.0",
            }))
            await ws.send(json.dumps({
                "event": "start", "streamSid": stream_sid,
                "start": {
                    "streamSid": stream_sid, "accountSid": "ACtest",
                    "callSid": call_sid, "tracks": ["inbound"],
                    "mediaFormat": {
                        "encoding": "audio/x-mulaw",
                        "sampleRate": 8000, "channels": 1,
                    },
                },
            }))
            print(f"  handshake done (callSid={call_sid})")

            send_task = asyncio.create_task(sender(ws))
            print("  listening for AI greeting (15s timeout) ...")
            try:
                while True:
                    raw = await asyncio.wait_for(ws.recv(), timeout=15.0)
                    msg = json.loads(raw)
                    if msg.get("event") == "media":
                        chunk = base64.b64decode(msg["media"]["payload"])
                        all_audio.extend(chunk)
                        sys.stdout.write(".")
                        sys.stdout.flush()
                    elif msg.get("event") == "stop":
                        break
            except asyncio.TimeoutError:
                print("  (timeout)")

            running = False
            send_task.cancel()
            try:
                await send_task
            except asyncio.CancelledError:
                pass

            print(f"\n  received {len(all_audio)} bytes")
    except Exception as e:
        print(f"  ERROR: {e}")
        return

    if all_audio:
        pcm = ulaw_to_linear16(bytes(all_audio))
        path = "test_output_ws.wav"
        wf = wave.open(path, "wb")
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(TWILIO_SAMPLE_RATE)
        wf.writeframes(pcm)
        wf.close()
        dur = len(all_audio) / TWILIO_SAMPLE_RATE
        print(f"  audio saved -> {path}  ({dur:.1f}s)")
        print("  OPEN IT to hear the AI greeting!")
    else:
        print("  No audio.")
        print("  Check uvicorn terminal for server errors --")
        print("  if it says 'TTS connect failed', ElevenLabs key is wrong.")
        print("  if it says 'stream start sid=', TTS works but audio not sent.")
        print("  if only 'connection open' with nothing else, server crashed.")


async def direct_test():
    from openai import AsyncOpenAI
    import websockets
    api_key = os.getenv("OPENAI_API_KEY", "")
    eleven_key = os.getenv("ELEVENLABS_API_KEY", "")
    voice_id = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
    print(f"  OpenAI:   {'set' if api_key else 'MISSING'}")
    print(f"  ElevenLabs: {'set' if eleven_key else 'MISSING'}")
    if not api_key or not eleven_key:
        print("ERROR: missing keys in .env")
        return

    client = AsyncOpenAI(api_key=api_key)
    print("\n--- Test 1: GPT-4o ---")
    resp = await client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are an AI negotiator. Be concise."},
            {"role": "user", "content": "Hello, is this the right number?"},
        ],
        temperature=0.7, max_tokens=200,
    )
    reply = resp.choices[0].message.content.strip()
    print(f"  {reply}")

    print("\n--- Test 2: ElevenLabs TTS ---")
    tts_url = (
        f"wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        f"/stream-input?model_id=eleven_turbo_v2_5"
        f"&optimize_streaming_latency=4&output_format=pcm_22050"
    )
    try:
        async with websockets.connect(tts_url) as tts_ws:
            # Auth goes in the BOS JSON message
            await tts_ws.send(json.dumps({
                "text": " ",
                "voice_settings": {"stability": 0.4, "similarity_boost": 0.8},
                "xi_api_key": eleven_key,
            }))
            await tts_ws.send(json.dumps({
                "text": reply[:250], "try_trigger_generation": True,
            }))
            await tts_ws.send(json.dumps({"text": ""}))

            pcm_chunks = []
            async for msg in tts_ws:
                data = json.loads(msg)
                if "audio" in data and data["audio"]:
                    pcm_chunks.append(base64.b64decode(data["audio"]))
                if data.get("is_final"):
                    break

        out = "test_output_direct.wav"
        wf = wave.open(out, "wb")
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(22050)
        wf.writeframes(b"".join(pcm_chunks))
        wf.close()
        total = sum(len(c) for c in pcm_chunks)
        print(f"  TTS saved -> {out}  ({total} bytes)")
        if total > 0:
            print("\n  SUCCESS -- listen to test_output_direct.wav")
        else:
            print("\n  WARNING: zero audio bytes")
    except Exception as e:
        print(f"  FAILED: {e}")


if __name__ == "__main__":
    _load_dotenv()
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    host = sys.argv[2] if len(sys.argv) > 2 else "ws://localhost:8000"
    if mode == "ws":
        print("=== WebSocket test ===\n")
        asyncio.run(ws_test(host))
    elif mode == "direct":
        print("=== Direct API test ===\n")
        asyncio.run(direct_test())
    else:
        print(__doc__)
        print("USAGE:  python test_stream_handler.py ws       # uvicorn first!")
        print("        python test_stream_handler.py direct   # no server")
