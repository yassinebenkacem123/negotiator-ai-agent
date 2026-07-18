# Backend Smoke Test — Status (P3)

## Bug found & fixed
All four vendor clients (`tavily_client.py`, `eleven_client.py`, `openai_client.py`, `twilio_client.py`) instantiated their SDK client **at import time**, which meant the whole app crashed on startup unless *every* API key was set — even for endpoints that don't need them. Fixed with lazy `@lru_cache` initialization: the client is only created (and only fails) the first time it's actually used.

## Verified working

| Check | Result |
|---|---|
| App imports cleanly | ✅ |
| `GET /health` | ✅ 200 |
| `POST /api/specs` (incl. `origin_lat`/`lng`, `destination_lat`/`lng`) | ✅ `distance_miles` auto-computed server-side |
| `POST /api/specs/{id}/confirm` | ✅ |
| `GET /api/specs/{id}` | ✅ |
| `GET /api/results/{id}` (empty state) | ✅ correct "No quotes collected yet." |
| 404 handling on unknown `job_spec_id` | ✅ |
| `ranking.py` red-flag + sort logic (unit-tested directly with sample `Quote` data) | ✅ — matches the mock `Report` already sent to P4 |

### Sample verified request/response

`POST /api/specs`:
```json
{
  "job_spec_id": "",
  "origin_address": "Rock Hill, SC",
  "origin_floor": 2,
  "origin_has_elevator": false,
  "origin_lat": 34.9249,
  "origin_lng": -81.0251,
  "destination_address": "Charlotte, NC",
  "destination_floor": 0,
  "destination_has_elevator": true,
  "destination_lat": 35.2271,
  "destination_lng": -80.8431,
  "move_date": "2026-08-08",
  "date_flexible": true,
  "num_trips": 1,
  "num_bags": 15,
  "source": "voice_interview",
  "confirmed_by_user": false
}
```
→ returns the same object with `job_spec_id` generated and `distance_miles: 23.3` computed.

Note: `distance_miles` is straight-line (Haversine), not driving distance — fine for a v1, flag if precision matters later.

### Ranking unit test

Input: three quotes at $1,850 (negotiated), $2,100, $950.
Output:
```json
{
  "job_spec_id": "job_123",
  "ranked_companies": [
    { "company_id": "co_001", "final_price": 1850.0, "rank": 1, "differentiators": ["full insurance"], "red_flag": false },
    { "company_id": "co_002", "final_price": 2100.0, "rank": 2, "differentiators": ["same-day availability"], "red_flag": false },
    { "company_id": "co_003", "final_price": 950.0, "rank": 3, "differentiators": [], "red_flag": true }
  ],
  "summary": "Recommended: company co_001 at $1,850. 1 quote(s) flagged as suspiciously low and excluded from the top pick."
}
```
$950 is 49% below the $1,850 median (over the 30% `red_flag_below_median_pct` threshold in `config.py`) and correctly gets `red_flag: true`, dropped to last place despite being cheapest.

## Now also verified (with real OpenAI key)

**`extraction.py` live test** — realistic negotiation transcript in, correct structured `Quote` out:
- Correctly extracted `initial_price: 2000` → `negotiated_price: 1850`, `negotiation_successful: true`
- Correctly itemized `fees: {fuel_surcharge: 50, stairs_fee: 30}`
- Correctly pulled differentiators: `["fully insured", "money-back guarantee if anything gets damaged"]`
- No fabricated data — only what was actually said in the transcript

**Full HTTP + websocket path, end to end:**
1. `POST /api/specs` → job spec created
2. Client connects to `ws /api/results/ws/{job_spec_id}`
3. `POST /api/calls/completed/{job_spec_id}/co_001` with a transcript → 200, structured `Quote` returned
4. Websocket **automatically received** the updated ranked `Report` within the same request — no polling required

This confirms P4 can build against the websocket now instead of only polling, if they prefer.

## Second bug found & fixed: Windows timezone support
`telephony.py`'s working-hours gate uses `zoneinfo.ZoneInfo`, which has no timezone database on Windows by default (unlike Linux/macOS) — this would have crashed with `ZoneInfoNotFoundError` the first time anyone on Windows tried to place a call. Fixed by adding `tzdata` to `requirements.txt`.

## Edge case sweep (all passed)

| Test | Result |
|---|---|
| `POST /api/specs` missing required field | ✅ 422 |
| Confirm/get on nonexistent `job_spec_id` | ✅ 404 |
| Spec with only origin lat/lng (no destination) | ✅ `distance_miles: null`, no crash |
| Working hours: no `working_hours` on file | ✅ defaults to **cannot call** (fail-safe) |
| Working hours: within listed hours | ✅ can call |
| Working hours: outside listed hours | ✅ cannot call |
| Working hours: day not listed in schedule | ✅ cannot call |
| Ranking: empty quote list | ✅ "No quotes collected yet." |
| Ranking: quotes clustered near median | ✅ none incorrectly flagged |
| Ranking: negotiated price far below median | ✅ **not** flagged (real negotiation exempted, only unverified lowballs are) |
| Geo: identical origin/destination point | ✅ `0.0` miles, no crash |

## Live Tavily discovery test (real API key, real web data)

Ran `search_service.find_movers("Charlotte, NC")` against the actual Tavily API — no mocks.

**Bug/gap #3 found and fixed:** `working_hours` was always `{}` even for real companies, because (a) Tavily's default search only returns short snippets with no hours info, and (b) most moving-company websites don't list hours in scrapeable text at all. Fixed in two steps:
1. Switched `tavily_client.py` to `include_raw_content=True` — pulls full page text instead of the snippet. Verified this alone recovers real hours when a site actually states them (confirmed on "All My Sons Moving": `"Monday - Thursday: 7AM-9PM..."` correctly extracted via an OpenAI pass in `search_service._extract_working_hours`).
2. Added `default_working_hours` (Mon–Sat 08:00–18:00) as a documented fallback lever in `config.py`, used only when extraction finds nothing — otherwise the working-hours gate would silently skip most real companies (its fail-safe treats unknown hours as "don't call"). This is a real accuracy/call-volume tradeoff, decided explicitly, not a silent guess.

**Final verified result** — 7 real Charlotte-area movers found, real phone numbers, all now correctly gated as callable:
- 6 companies got the fallback default hours (no hours published on their sites)
- 1 company (All My Sons Moving) got its **actual real hours**, correctly parsed from page text
- All 7 correctly evaluate as callable at a sample Wednesday 10am timestamp via `telephony.is_within_working_hours`

Also improved lead quality as a side effect of the raw-content switch: went from 3 results (one being a Yelp listicle page, not a real company) to 7 results (6 of 7 are real individual moving companies with their own phone numbers).

## Status: P3's backend track is complete
All planned work (`api/`, `services/`, `clients/`, `models/`, `playbook/`) is built, self-checked against the SRP rules, verified live against a real OpenAI key, and stress-tested against edge cases. Two real bugs found and fixed along the way (eager client init crashing without all keys; missing Windows tzdata). Remaining work is integration-dependent on P1 (ElevenLabs agents) and P2 (Tavily/Twilio), not on P3.

Local server running on `http://127.0.0.1:8000` (uvicorn) for anyone who wants to poke at it directly.
