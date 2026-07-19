# Frontend API Contract — P3's Endpoints

Exact field names returned by the backend, for the Lovable frontend (P4) to build against. All responses are JSON.

---

## 1. Job Spec — `POST /api/specs`, `GET /api/specs/{job_spec_id}`, `POST /api/specs/{job_spec_id}/confirm`

Returns a `JobSpec` object:

| Field | Type | Notes |
|---|---|---|
| `job_spec_id` | string | UUID, generated on create |
| `origin_address` | string | |
| `origin_floor` | integer | 0 = ground floor |
| `origin_has_elevator` | boolean | |
| `origin_lat` | number \| null | from map pin selection |
| `origin_lng` | number \| null | from map pin selection |
| `destination_address` | string | |
| `destination_floor` | integer | 0 = ground floor |
| `destination_has_elevator` | boolean | |
| `destination_lat` | number \| null | from map pin selection |
| `destination_lng` | number \| null | from map pin selection |
| `distance_miles` | number \| null | **server-computed** — send lat/lng, don't compute or send this yourself; it's null until both points are set |
| `move_date` | string | e.g. `"2026-08-08"` |
| `date_flexible` | boolean | |
| `num_trips` | integer | |
| `num_bags` | integer | |
| `notes` | string \| null | free text, optional |
| `source` | string | `"voice_interview"` or `"document_upload"` |
| `confirmed_by_user` | boolean | `false` until `/confirm` is called |

---

## 1.5 Discovery — `POST /api/search/find-movers/{job_spec_id}`

No query parameters, no body. The only location input the pipeline needs is `origin_address`, already on the confirmed job spec — city is detected from it server-side. Returns:
```json
{ "job_spec_id": "string", "leads": [ { "company_id": "...", "name": "...", "phone_number": "...", "address": "...", "email": "...", "website": "...", "working_hours": {...}, "source_url": "...", "city": "..." } ] }
```
`GET /api/search/leads/{job_spec_id}` returns the same `leads` array on its own if you need to re-fetch it later.

---

## 2. Ranked Report — `GET /api/results/{job_spec_id}` and websocket `ws /api/results/ws/{job_spec_id}`

Both return the same shape — the websocket pushes this automatically every time a call completes, so the frontend can use one type for both the initial fetch and live updates.

**`Report` object:**

| Field | Type | Notes |
|---|---|---|
| `job_spec_id` | string | |
| `ranked_companies` | array of `RankedCompany` | sorted, cheapest → most expensive, red-flagged ones pushed to the end |
| `summary` | string | plain-language paragraph naming the recommended company |

**`RankedCompany` object (each item in `ranked_companies`)** — matches `frontend/src/lib/api.ts`'s `Quote & {rank, recommended}` type exactly:

| Field | Type | Notes |
|---|---|---|
| `company_id` | string | |
| `company` | string | company name |
| `total` | number | the price to display — negotiated price if one exists and negotiation succeeded, else the original quote. Never re-derive this yourself. |
| `fees` | array of `{label, amount}` | e.g. `[{"label": "fuel surcharge", "amount": 40}]` |
| `differentiators` | array of strings | e.g. `["full insurance", "money-back guarantee"]` |
| `red_flag` | string \| null | an explanation string when flagged (e.g. `"49% below the median..."`), `null` otherwise — not a boolean |
| `transcript_url` | string \| null | |
| `recording_url` | string \| null | |
| `rank` | integer | 1 = best; starts at 1 |
| `recommended` | boolean | `true` on exactly one entry (the top non-flagged pick) |

---

## 3. Individual Call Result — `POST /api/calls/completed/{job_spec_id}/{company_id}`

**Dual-purpose, matching how the frontend already calls it:**
- **Call it with no body** (as `frontend/src/lib/api.ts`'s `getCompletedCall` does) → read-only fetch of the already-stored `Quote` for that company. Returns 404 if no call has completed yet for that company.
- **Call it with `call_id` + `transcript` query params** (+ optional `recording_url`) → telephony webhook mode: runs OpenAI extraction, stores the result, and broadcasts the updated report over the websocket. This is what P1/P2's calling pipeline uses after a real call ends — the frontend shouldn't need this mode.

Returns a `Quote` object:

| Field | Type | Notes |
|---|---|---|
| `company_id` | string | |
| `company` | string | company name, resolved from the discovered lead |
| `call_id` | string | |
| `initial_price` | number \| null | |
| `negotiated_price` | number \| null | |
| `negotiation_successful` | boolean | |
| `total` | number \| null | the number to display — same value/logic as `RankedCompany.total` |
| `fees` | array of `{label, amount}` | |
| `differentiators` | array of strings | |
| `outcome` | string | one of: `"quote"`, `"callback_scheduled"`, `"declined"`, `"no_answer"`, `"outside_hours_skipped"` |
| `transcript_url` | string \| null | not wired yet — always `null` currently |
| `recording_url` | string \| null | |
| `red_flag` | string \| null | `null` until the ranking pass runs (ranking sets this, not extraction) |

---

## Notes for frontend integration

- **Map picker for addresses**: give the user a map to drop a pin for point A and point B (in addition to or instead of typing the address). Send the pin coordinates as `origin_lat`/`origin_lng` and `destination_lat`/`destination_lng` in the `POST /api/specs` body. Do **not** calculate or send `distance_miles` yourself — the backend computes it server-side from the coordinates and returns it in the response. If a user skips the map and only types an address, leave the lat/lng fields `null`; `distance_miles` will come back `null` too in that case.
- Poll `GET /api/results/{job_spec_id}` once on page load, then switch to the websocket for live updates — don't poll repeatedly.
- Companies with `outcome: "no_answer"` or `"outside_hours_skipped"` won't appear in `ranked_companies` yet (no price to rank) — if you want to show "still trying" state for those, that data currently only exists via P2's call-status endpoints, not P3's report endpoint. Flag this to P2 if you need a combined view.
- **Flip `USE_MOCK` to `false` in `frontend/src/lib/api.ts`** once you're ready to hit the real backend — shapes now match exactly, verified live against real OpenAI extraction and the websocket broadcast path.
