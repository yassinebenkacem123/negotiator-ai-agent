# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Hack_Nation_Negotiator — Backend (FastAPI)

## Business Purpose

An AI-powered engine that searches for home improvement providers, calls them via AI voice agents, negotiates pricing, and returns the best deal.

### Core Flow

```
1. 🔍 Search (Tavily)         → Find providers + extract phone numbers
2. 📞 Call (Twilio)            → Outbound call with TwiML <Stream>
3. 🗣️ Negotiate (Whisper→GPT→TTS) → Real-time audio conversation via WebSocket
4. 💾 Store                    → Final price extracted & stored
5. 🏆 Compare                  → Best price returned to user
```

## Real-Time Voice Pipeline (stream_handler.py)

The heart of the telephony system. One WebSocket connection per call:

```
Twilio ──base64 μ-law──→ StreamHandler
                              │
                     ┌───────┴───────┐
                     ▼               ▼
               OpenAI Whisper   ElevenLabs TTS
               (transcription)  (voice synthesis)
                     │               │
                     ▼               │
                GPT-4o (response)    │
                     │               │
                     └───────┬───────┘
                             ▼
                        Twilio ← μ-law audio
```

### Key classes in `services/stream_handler.py`:

- **`VADBuffer`** — VAD-based utterance segmentation with peak-normalised RMS energy. Triggers transcription after trailing silence or max buffer age (configurable in `config.py`).
- **`TTSSession`** — Long-lived ElevenLabs streaming TTS WebSocket. Accepts phrase-level text chunks (GPT-4o tokens are buffered to ~80 chars or sentence boundaries before feeding). Audio pushed to `AudioQueue` for the send loop. Handles interrupt recovery via `_bos_needed` flag.
- **`StreamHandler`** — Per-connection orchestrator. Four concurrent asyncio tasks:
  1. `_twilio_loop()` — receives events from Twilio (start/media/stop)
  2. `_tts_receive_loop()` — ElevenLabs → `audio_queue`
  3. `_send_loop()` — `audio_queue` → μ-law conversion → Twilio
  4. `_transcribe_and_respond()` — fire-and-forget per utterance, guarded by `_resp_task`

### Three Critical Properties

**Streaming (latency fix):** GPT-4o uses `stream=True`. Tokens are buffered to natural phrase boundaries (sentence end, comma, or ~120 chars hard cap) before being flushed to ElevenLabs — preserves prosody while keeping first-word latency low.

**Interruption (barge-in):** `_on_audio()` always runs VAD even while the AI is speaking. If the far side produces *sustained* speech (≥6 consecutive frames ≈300ms), `_do_interrupt()` fires: cancels the GPT-4o streaming Task, sends `clear` to Twilio, interrupts ElevenLabs TTS, drains the audio queue, resets VAD buffer, and appends an interruption marker to conversation history.

**Echo defense:** An echo guard (300ms window after each `send_json` to Twilio) prevents the AI's own voice from triggering false interrupts. The `_playing` flag stays True until the `_drained` Event is set by the send loop after consuming the utterance-final `None` sentinel.

### Phrase boundary buffering (GPT-4o tokens → ElevenLabs TTS)

Tokens are accumulated until `_is_phrase_boundary()` returns True, which triggers on:
- End-of-sentence punctuation (`.!?`)
- Comma/clause markers after reaching ~80 chars buffer
- Hard cap at ~120 chars regardless

This preserves natural ElevenLabs prosody while keeping the per-token streaming path for low latency.

### Audio format chain:
```
Twilio in:  μ-law 8kHz → audioop → PCM 16kHz → Whisper API
Twilio out: ElevenLabs PCM 22kHz → numpy low-pass filter → audioop → μ-law 8kHz
```
The 22kHz→8kHz downscale uses a numpy convolution low-pass filter (6-sample moving average) to attenuate frequencies above the 4kHz Nyquist limit before `audioop.ratecv` resampling, preventing metallic aliasing artifacts.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Health check |
| `POST` | `/api/specs` | Create a job spec |
| `POST` | `/api/specs/{id}/confirm` | Confirm spec |
| `POST` | `/api/search/find-movers/{job_spec_id}` | Tavily search for providers |
| `GET` | `/api/search/leads/{job_spec_id}` | Get stored leads |
| `POST` | `/api/calls/start-negotiating/{job_spec_id}` | Start batch calls |
| `GET` | `/api/calls/stream/{company_id}` | TwiML for WebSocket stream |
| `POST` | `/api/calls/completed/{job_spec_id}/{company_id}` | Call completion webhook |
| `GET` | `/api/results/{job_spec_id}` | Get ranked report |
| `WS` | `/api/results/ws/{job_spec_id}` | Live report updates |
| `WS` | `/media-stream/{company_name}` | **Twilio audio stream** |
| `GET` | `/twiml/{company_name}` | TwiML with `wss_url` param |

## Dependencies

- `requirements.txt` — FastAPI, uvicorn, Tavily, ElevenLabs, Twilio, OpenAI, websockets, numpy, tzdata

## Commands

- **Run:** `uvicorn app.main:app --reload`
- **Install:** `pip install -r requirements.txt`

## Key Design Rules

- **Async/await** for all external API calls (Whisper, GPT-4o, ElevenLabs TTS WebSocket)
- **Pydantic models** for all data shapes (`models/`)
- **Config in `config.py`** — never hardcode API keys or thresholds
- **SRP**: clients = vendor wrappers, services = business logic, api = thin routes
- **Lazy client init** — SDK clients created on first use (`@lru_cache`), not at import time