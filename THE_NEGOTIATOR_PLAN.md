# The Negotiator — Business Plan & 15h Execution Roadmap (v2)

**Challenge:** ElevenLabs × Hack-Nation — "The Negotiator"
**Vertical:** Residential moving only — point A to point B, local/regional. This is not a generic multi-vertical platform: every module (intake fields, discovery, negotiation playbook, ranking tags) is built specifically for residential movers, not as swappable config for other markets.

---

## 1. Business Plan (short)

### Problem
Residential moving has no online price transparency. Quotes for an identical local move can range 3–5x between companies, sight-unseen estimates are **40% more likely** to end in a bill above quote (FMCSA), and nobody has the hours to find local movers, call each one, describe the same move, and negotiate.

### Solution
A voice-agent pipeline that does what a savvy shopper would do, at scale, for a single residential move:
1. **Voice/document intake** → structured job spec (address A, address B, date, trip count, bag count)
2. **Automated discovery** of residential movers in the user's area (no pre-supplied list required)
3. **Working-hours-aware outbound calls** → each company gets the same pitch, gets negotiated with
4. **Ranking**: cheapest → most expensive, annotated with each company's differentiators (insurance, guarantee, safety claims)

### Market
$20B+ US moving industry, 16,851 companies averaging 6.2 employees — phone-and-paper operations that will never build online quoting, but all answer the phone.

### Business model (mention in pitch)
- B2C: success fee (% of savings vs. first quote) or flat fee per residential move negotiated
- B2B: SaaS licensing to relocation companies, insurance adjusters, real-estate agencies bundling a "moving concierge" for their clients
- Data flywheel: every call improves the local residential-moving price-benchmark dataset

### Why now
Voice agents (ElevenLabs) have crossed the latency/naturalness threshold needed to sound like a real caller.

---

## 2. Tools We Have Credits/Access For — How Each Is Used

| Tool | Role in this project |
|---|---|
| **ElevenLabs Agents** | Core requirement. Powers the Estimator's voice interview and the Caller's outbound negotiation calls. Handles TTS/STT, turn-taking, interruption handling, tool-calling mid-call. |
| **OpenAI (GPT + vision)** | Optional document/bill intake (parse into job-spec JSON), negotiation reasoning support, structured-output extraction fallback from transcripts. |
| **Tavily** (+ **IP-API**) | Discovery module: IP-API resolves the user's city/area; Tavily web-searches for residential moving companies in that area and pulls phone number + working hours per company — the call list of local movers is *found*, not supplied. |
| **Lovable** | Frontend: intake confirmation screen, live discovery/call-progress dashboard, final ranked-comparison report. |
| **Emdash** | Run multiple coding agents in parallel across the 4 workstreams. |
| **Woz** | Claude Code / Cursor performance tooling for faster iteration across all tracks. |

---

## 3. System Architecture

Backend is a single **Python/FastAPI** service (owned primarily by P3, extended by P2/P1 for their pieces), organized by strict single-responsibility layers: `api/` (thin routes) → `services/` (business logic) → `clients/` (vendor SDK wrappers) → `models/` (Pydantic schemas). `config.py` centralizes every swappable lever (thresholds, tactics list, credentials) so no logic is hardcoded inline.

```
backend/
├── app/
│   ├── main.py                # App init & router mounting only
│   ├── config.py              # Central config: thresholds, credentials, levers
│   ├── store.py                # In-memory state (job_specs, leads, quotes) — swap for DB later
│   ├── api/                   # Thin routes: validate request, call service, return
│   │   ├── specs.py           # Job spec CRUD + confirmation
│   │   ├── search.py          # Lead sourcing trigger (Tavily)
│   │   ├── calls.py           # Call orchestration loop + call-completed webhook
│   │   └── results.py         # Ranked report GET + websocket for live updates
│   ├── services/              # Business logic (SRP)
│   │   ├── search_service.py  # Lead discovery: query Tavily, extract phone numbers
│   │   ├── voice_service.py   # Conversation design: injects job_spec + playbook into agent context
│   │   ├── telephony.py       # Connectivity: places calls, working-hours gate
│   │   ├── extraction.py      # Transcript -> structured Quote via OpenAI
│   │   └── ranking.py         # Median/red-flag math, cheapest -> most expensive sort
│   ├── clients/                # Vendor SDK wrappers only, no business logic
│   │   ├── tavily_client.py
│   │   ├── eleven_client.py
│   │   ├── openai_client.py
│   │   └── twilio_client.py
│   ├── playbook/
│   │   └── negotiation_playbook.py  # Negotiation tactics as data, not hardcoded in prompts
│   └── models/                # Pydantic schemas
│       ├── job_spec.py
│       ├── lead.py
│       └── quote.py
└── requirements.txt
```

### Data flow
1. **Estimator agent (P1, ElevenLabs)** runs the voice interview → calls `POST /api/specs` → job spec stored → user confirms via `POST /api/specs/{id}/confirm`
2. **Frontend (P4)** triggers `POST /api/search/find-movers/{job_spec_id}?city=...` → `search_service.py` queries Tavily, extracts phone numbers, stores leads
3. **Frontend** triggers `POST /api/calls/start-negotiating/{job_spec_id}` → loops leads, skips any outside working hours (`telephony.is_within_working_hours`), places calls via Twilio, injects job spec + negotiation playbook into the **Caller agent (P1, ElevenLabs)** via `voice_service.py`
4. When a call ends, a webhook hits `POST /api/calls/completed/{job_spec_id}/{company_id}` with the transcript → `extraction.py` calls OpenAI to produce a structured `Quote` → stored → report broadcast over websocket
5. **Frontend (P4)** reads `GET /api/results/{job_spec_id}` or listens on `ws /api/results/ws/{job_spec_id}` for the live ranked report (`ranking.py`: median comparison, red-flag tagging, cheapest → most expensive sort)

### Ownership, unambiguous
- **P1** — ElevenLabs agents (Estimator + Caller conversation design), consumes `voice_service.py`'s context payload. Needs the **ElevenLabs key** (+ Twilio if handling the stream bridge directly).
- **P2** — `search_service.py` (Tavily + IP-API discovery) and the working-hours/scheduling logic in `telephony.py`. Needs **Tavily, IP-API, Twilio** keys.
- **P3** — Everything else: `api/`, `config.py`, `store.py`, `extraction.py`, `ranking.py`, `playbook/`. Needs the **OpenAI key**.
- **P4** — Lovable frontend, calls the REST endpoints and connects to the results websocket. No backend key needed beyond whatever Lovable itself requires.

**Swap points (why this structure matters):** change Tavily → Google Places by editing only `tavily_client.py`; change negotiation aggressiveness by editing only `negotiation_playbook.py` / `config.py`; change the voice/accent by editing only `eleven_client.py`. Routes in `api/` never change for any of these.

### Job-spec schema (Estimator output — kept intentionally minimal for v2)
```json
{
  "vertical": "residential_moving",
  "origin_address": "string",
  "origin_floor": 0,
  "origin_has_elevator": false,
  "origin_lat": 34.9249,
  "origin_lng": -81.0251,
  "destination_address": "string",
  "destination_floor": 0,
  "destination_has_elevator": false,
  "destination_lat": 35.2271,
  "destination_lng": -80.8431,
  "distance_miles": 45.2,
  "move_date": "2026-08-08",
  "date_flexible": true,
  "num_trips": 1,
  "num_bags": 15,
  "notes": "optional free text, e.g. from bill/document upload",
  "source": "voice_interview | document_upload",
  "confirmed_by_user": true
}
```

### Company schema (Discovery module output)
```json
{
  "company_id": "string",
  "name": "string",
  "phone_number": "string",
  "working_hours": { "mon": "08:00-18:00", "tue": "08:00-18:00", "...": "..." },
  "source_url": "string",
  "city": "string"
}
```

### Quote/negotiation result schema (Caller output, per company)
```json
{
  "company_id": "string",
  "call_id": "string",
  "initial_price": 0,
  "negotiated_price": 0,
  "negotiation_successful": true,
  "differentiators": ["full insurance", "money-back guarantee", "same-day availability"],
  "outcome": "quote | callback_scheduled | declined | no_answer | outside_hours_skipped",
  "transcript_url": "string",
  "recording_url": "string"
}
```

### Ranking output schema
```json
{
  "job_spec_id": "string",
  "ranked_companies": [
    { "company_id": "string", "final_price": 0, "rank": 1, "differentiators": ["..."] }
  ],
  "summary": "plain-language paragraph explaining the recommendation"
}
```

---

## 4. 15-Hour Timeline

| Time | Milestone |
|---|---|
| H0–H1 | Lock job-spec v2 + company schema + quote schema together. Split API keys (ElevenLabs, OpenAI, Tavily, IP-API). Set up Emdash workspace + repo. |
| H1–H4 | **Parallel build 1**: A = Estimator voice interview (address A/B, date, trip count, bag count); B = IP-API + Tavily discovery producing `companies.json`; C = negotiation playbook v1 draft + ranking schema; D = Lovable UI skeleton (intake screen + company list view) |
| H4–H7 | **Parallel build 2**: A = Caller agent wired to C's negotiation playbook; B = working-hours gate + call queue/scheduler feeding the Caller; C = refine negotiation tactics + differentiator-tag extraction from transcripts; D = wire intake UI to real job-spec output, start live company-list view |
| **H7** | **Checkpoint 1** — single full loop works on one real/role-played company: discover → check hours → call → negotiate → log price |
| H7–H10 | Scale to N companies via the queue; build the ranking module (cheapest → most expensive + tags); UI shows live call progress across all companies |
| H10–H12 | Hardening: no-answer, voicemail, outside-hours auto-skip-and-requeue, failed negotiation still logs original price and moves to next company automatically |
| **H12** | **Checkpoint 2 — full loop**: intake → discovery → N calls (hours-gated) → ranked report, at least one call shows a real negotiated price drop |
| H12–H14 | Demo rehearsal; record backup calls/recordings in case live discovery or calls are flaky during presentation |
| H14–H15 | Buffer, README, submission |

---

## 5. Task Assignment — 4 Members

### P1 — Voice & Conversation Engineer (ElevenLabs lead)
- Build **Estimator** agent: voice interview collecting origin/destination address, move date, number of trips, number of bags — confirmed by user (`POST /api/specs`, `POST /api/specs/{id}/confirm`) before locking the spec
- Build **Caller** agent: opens with AI disclosure, pitches the job spec identically to every company, executes negotiation using the context `services/voice_service.py` injects (job spec + `playbook/negotiation_playbook.py`)
- Implement graceful friction handling (interruptions, "someone will call you back", refusal to negotiate — captures price anyway and moves on)
- Use **Emdash** to run/supervise agent-building in parallel with own testing

### P2 — Discovery & Telephony Backend Engineer
- Flesh out `services/search_service.py`: IP-API to resolve the user's city, Tavily search for residential movers, extract phone number + working hours per lead
- Extend `services/telephony.py`: the working-hours gate (`is_within_working_hours`) already exists as a function — turn it into a proper queue/scheduler that requeues skipped companies instead of dropping them
- Wire `clients/twilio_client.py` to real Twilio credentials and the actual stream-bridging webhook
- Ensure `api/calls.py`'s orchestration loop logs every outcome (quote / callback / declined / no_answer / outside_hours_skipped) via `store.py`

### P3 — Backend & Negotiation Logic Engineer
- Own `backend/app/` end to end: `api/`, `config.py`, `store.py`, `models/`, `services/extraction.py`, `services/ranking.py`, `playbook/negotiation_playbook.py`
- Negotiation playbook is a separate config file (`playbook/negotiation_playbook.py`) the Caller agent's context is built from — extend with more tactics/resources as they come in
- `extraction.py`: transcript → structured `Quote` via OpenAI, no invented data
- `ranking.py`: median comparison, red-flag threshold from `config.py`, cheapest → most expensive sort, differentiator tags carried through to the final `Report`

### P4 — Frontend/Product/Demo Lead
- Build UI in **Lovable**: intake confirmation screen, live view of discovered companies + call progress (open/closed/calling/done), final ranked table with transcripts/recordings and differentiator tags — reads `GET /api/results/{job_spec_id}` and the `/api/results/ws/{job_spec_id}` websocket for live updates
- Optional: bill/document upload parsed via **OpenAI vision** into the same job-spec schema (nice-to-have, cut first if time is short)
- Own the demo script and rehearsal — must show a real price negotiated down live; capture backup recordings in case a live call fails during the demo
- Write the README / submission narrative tying back to the business plan
- Use **Woz** for fast iteration/debugging on Lovable-generated code

---

## 6. Success Checklist (must-hit before submission)

- [ ] Job-spec confirmed by user (address A/B, date, trips, bags) and reused verbatim across all calls
- [ ] Company list generated automatically via IP-API + web search — not manually supplied
- [ ] Calls only fire within each company's working hours; outside-hours companies are skipped/requeued, not called
- [ ] At least one real/role-played negotiation where the price is measurably lowered during the call
- [ ] Companies where negotiation doesn't succeed still appear in the final ranking with their original price
- [ ] AI discloses itself when asked; never invents a price, a competing bid, or a fake claim
- [ ] Every call ends in a structured outcome (quote / callback / declined / no_answer / outside_hours_skipped)
- [ ] Final report ranks all companies cheapest → most expensive with differentiator tags and plain-language summary
- [ ] Negotiation playbook is a separate config file, not hardcoded — easy to extend as more residential-moving negotiation tactics are added
