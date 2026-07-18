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

## 2. Ranked Report — `GET /api/results/{job_spec_id}` and websocket `ws /api/results/ws/{job_spec_id}`

Both return the same shape — the websocket pushes this automatically every time a call completes, so the frontend can use one type for both the initial fetch and live updates.

**`Report` object:**

| Field | Type | Notes |
|---|---|---|
| `job_spec_id` | string | |
| `ranked_companies` | array of `RankedCompany` | sorted, cheapest → most expensive, red-flagged ones pushed to the end |
| `summary` | string | plain-language paragraph naming the recommended company |

**`RankedCompany` object (each item in `ranked_companies`):**

| Field | Type | Notes |
|---|---|---|
| `company_id` | string | |
| `final_price` | number | negotiated price if one exists, else the original quote |
| `rank` | integer | 1 = best; starts at 1 |
| `differentiators` | array of strings | e.g. `["full insurance", "money-back guarantee"]` |
| `red_flag` | boolean | `true` if 30%+ below median and not a confirmed/successful negotiation |

---

## 3. Individual Call Result — `POST /api/calls/completed/{job_spec_id}/{company_id}`

Returns a `Quote` object (useful if the frontend wants to show per-call detail, e.g. a transcript/recording drill-down, not just the aggregate report):

| Field | Type | Notes |
|---|---|---|
| `company_id` | string | |
| `call_id` | string | |
| `initial_price` | number \| null | |
| `negotiated_price` | number \| null | |
| `negotiation_successful` | boolean | |
| `fees` | object | dynamic keys, e.g. `{"fuel_surcharge": 50, "stairs_fee": 30}` |
| `differentiators` | array of strings | |
| `outcome` | string | one of: `"quote"`, `"callback_scheduled"`, `"declined"`, `"no_answer"`, `"outside_hours_skipped"` |
| `transcript_url` | string \| null | |
| `recording_url` | string \| null | |
| `red_flag` | boolean | set later by ranking, `false` at extraction time |

---

## Notes for frontend integration

- **Map picker for addresses**: give the user a map to drop a pin for point A and point B (in addition to or instead of typing the address). Send the pin coordinates as `origin_lat`/`origin_lng` and `destination_lat`/`destination_lng` in the `POST /api/specs` body. Do **not** calculate or send `distance_miles` yourself — the backend computes it server-side from the coordinates and returns it in the response. If a user skips the map and only types an address, leave the lat/lng fields `null`; `distance_miles` will come back `null` too in that case.
- Poll `GET /api/results/{job_spec_id}` once on page load, then switch to the websocket for live updates — don't poll repeatedly.
- `final_price` in the ranked report is always the number to display as "the price" — don't re-derive it from `initial_price`/`negotiated_price` yourself, that logic already happened server-side.
- Companies with `outcome: "no_answer"` or `"outside_hours_skipped"` won't appear in `ranked_companies` yet (no price to rank) — if you want to show "still trying" state for those, that data currently only exists via P2's call-status endpoints, not P3's report endpoint. Flag this to P2 if you need a combined view.
