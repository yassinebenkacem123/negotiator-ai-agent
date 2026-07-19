// Mock/real API module. Switching backends only requires editing VITE_API_BASE_URL.
const DEFAULT_BACKEND_BASE_URL = "https://5a0b-160-178-38-22.ngrok-free.app";
const configuredBackendBaseUrl =
  import.meta.env.VITE_API_BASE_URL?.trim() || DEFAULT_BACKEND_BASE_URL;
export const BACKEND_BASE_URL = configuredBackendBaseUrl.replace(/\/+$/, "");
export const API_BASE_URL = BACKEND_BASE_URL.endsWith("/api")
  ? BACKEND_BASE_URL
  : `${BACKEND_BASE_URL}/api`;
const API_HEADERS = { "ngrok-skip-browser-warning": "true" };
const JSON_HEADERS = { ...API_HEADERS, "Content-Type": "application/json" };
const USE_MOCK = false;

const NETWORK_DELAY_MS = 800;
const DISTANCE_DELAY_MS = 3000;

function delay(ms: number) {
  return new Promise((r) => setTimeout(r, ms));
}

export type Source = "voice_interview" | "document_upload";

export type JobSpec = {
  job_spec_id: string;
  origin_address: string;
  origin_floor: number;
  origin_has_elevator: boolean;
  origin_lat: number | null;
  origin_lng: number | null;
  destination_address: string;
  destination_floor: number;
  destination_has_elevator: boolean;
  destination_lat: number | null;
  destination_lng: number | null;
  move_date: string;
  date_flexible: boolean;
  num_trips: number;
  num_bags: number;
  notes: string | null;
  source: Source;
  distance_miles: number | null;
  confirmed_by_user: boolean;
  intake_transcript?: string | null;
};

export type Fee = { label: string; amount: number };

export type Quote = {
  company_id: string;
  company: string;
  call_id?: string;
  initial_price?: number | null;
  negotiated_price?: number | null;
  negotiation_successful?: boolean;
  total: number | null;
  final_price?: number | null;
  fees: Fee[];
  differentiators: string[];
  outcome?: string;
  red_flag: string | null;
  transcript_url: string | null;
  recording_url: string | null;
};

export type RankedCompany = Omit<Quote, "total"> & { total: number; final_price?: number; rank: number; recommended: boolean };

export type Report = {
  job_spec_id: string;
  summary: string;
  ranked_companies: RankedCompany[];
};

export type CreateSpecInput = Omit<JobSpec, "job_spec_id" | "distance_miles" | "confirmed_by_user"> &
  Partial<Pick<JobSpec, "confirmed_by_user">>;
export type DraftSpecInput = Omit<CreateSpecInput, "origin_lat" | "origin_lng" | "destination_lat" | "destination_lng"> &
  Partial<Pick<CreateSpecInput, "origin_lat" | "origin_lng" | "destination_lat" | "destination_lng">>;

export type Lead = {
  company_id: string;
  name: string;
  phone_number: string | null;
  address: string | null;
  email: string | null;
  website: string | null;
  working_hours: Record<string, string>;
  source_url: string | null;
  city: string;
};

export type DiscoveryResult = {
  job_spec_id: string;
  leads: Lead[];
};

export type StartNegotiatingResult = {
  job_spec_id: string;
  results: Array<{
    company_id: string;
    status: string;
    call_sid?: string;
  }>;
};

export type CallStatus = {
  company_id: string;
  company_name: string;
  phone_number: string | null;
  state: string;
  started_at: string | null;
  call_duration_seconds: number | null;
  outcome: string | null;
  failure_message: string | null;
  call_id: string | null;
  call_sid: string | null;
  transcript_url: string | null;
  recording_url: string | null;
};

export type StoredCall = {
  id: number;
  call_id: string;
  conversation_id: string;
  job_spec_id: string;
  company_id: string;
  company_name: string;
  company_phone: string | null;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  duration_seconds: number | null;
  transcript: Array<{ role: string; message?: string | null; time_in_call_secs?: number | null }>;
  transcript_url: string | null;
  recording_url: string | null;
  initial_price: number | null;
  negotiated_price: number | null;
  negotiation_successful: boolean;
  fees: Record<string, number | string | boolean | null>;
  differentiators: string[];
  outcome: string | null;
  red_flag: boolean;
  created_at: string;
  updated_at: string;
};

export type StartTestOutboundResult = {
  job_spec_id: string;
  status: string;
  call_sid: string;
  company: Lead;
  prepared_call: {
    agent_id: string;
    job_spec_id: string;
    company_id: string;
    company_name: string;
    to_number: string;
    dynamic_variables: Record<string, string>;
  };
};

export type CallsResult = {
  calls: StoredCall[];
};

export type CallStatusesResult = {
  job_spec_id: string;
  calls: CallStatus[];
};

export function reportWebSocketUrl(id: string) {
  const wsBase = BACKEND_BASE_URL.replace(/^https:\/\//, "wss://").replace(/^http:\/\//, "ws://");
  return `${wsBase}/api/results/ws/${encodeURIComponent(id)}`;
}

// ---------- API entrypoints (the only mock/real branching) ----------
export async function createSpec(input: CreateSpecInput): Promise<JobSpec> {
  if (USE_MOCK) return mockCreateSpec(input);

  const res = await fetch(`${API_BASE_URL}/specs`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(input),
  });
  if (!res.ok) throw new Error(`createSpec failed: ${res.status}`);
  return res.json();
}

export async function getSpec(id: string): Promise<JobSpec> {
  if (USE_MOCK) return mockGetSpec(id);

  const res = await fetch(`${API_BASE_URL}/specs/${encodeURIComponent(id)}`, {
    headers: API_HEADERS,
  });
  if (!res.ok) throw new Error(`getSpec failed: ${res.status}`);
  return res.json();
}

export async function updateSpec(id: string, spec: CreateSpecInput): Promise<JobSpec> {
  if (USE_MOCK) return mockUpdateSpec(id, spec);

  const res = await fetch(`${API_BASE_URL}/specs/${encodeURIComponent(id)}`, {
    method: "PUT",
    headers: JSON_HEADERS,
    body: JSON.stringify(spec),
  });
  if (!res.ok) throw new Error(`updateSpec failed: ${res.status}`);
  return res.json();
}

export async function createSpecFromVoice(transcript: string): Promise<JobSpec> {
  if (USE_MOCK) return mockCreateSpecFromVoice(transcript);

  const res = await fetch(`${API_BASE_URL}/specs/from-voice`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ transcript }),
  });
  if (!res.ok) throw new Error(`createSpecFromVoice failed: ${res.status}`);
  return res.json();
}

export async function createSpecFromDocument(file: File): Promise<JobSpec> {
  if (USE_MOCK) return mockCreateSpecFromDocument();

  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch(`${API_BASE_URL}/specs/from-document`, {
    method: "POST",
    headers: API_HEADERS,
    body: formData,
  });
  if (!res.ok) throw new Error(`createSpecFromDocument failed: ${res.status}`);
  return res.json();
}

export async function enrichSpecFromDocument(id: string, file: File): Promise<JobSpec> {
  if (USE_MOCK) return mockGetSpec(id);

  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch(
    `${API_BASE_URL}/specs/${encodeURIComponent(id)}/enrich-from-document`,
    { method: "POST", headers: API_HEADERS, body: formData },
  );
  if (!res.ok) throw new Error(`enrichSpecFromDocument failed: ${res.status}`);
  return res.json();
}

export async function confirmSpec(id: string): Promise<JobSpec> {
  if (USE_MOCK) return mockConfirmSpec(id);

  const res = await fetch(
    `${API_BASE_URL}/specs/${encodeURIComponent(id)}/confirm`,
    { method: "POST", headers: API_HEADERS },
  );
  if (!res.ok) throw new Error(`confirmSpec failed: ${res.status}`);
  return res.json();
}

export async function findMovers(id: string): Promise<DiscoveryResult> {
  const res = await fetch(
    `${API_BASE_URL}/search/find-movers/${encodeURIComponent(id)}`,
    { method: "POST", headers: API_HEADERS },
  );
  if (!res.ok) throw new Error(`findMovers failed: ${res.status}`);
  return res.json();
}

export async function startNegotiating(id: string): Promise<StartNegotiatingResult> {
  const res = await fetch(
    `${API_BASE_URL}/calls/start-negotiating/${encodeURIComponent(id)}?stream_webhook_base_url=${encodeURIComponent(BACKEND_BASE_URL)}`,
    { method: "POST", headers: API_HEADERS },
  );
  if (!res.ok) throw new Error(`startNegotiating failed: ${res.status}`);
  return res.json();
}

export async function startTestOutbound(id: string): Promise<StartTestOutboundResult> {
  const res = await fetch(
    `${API_BASE_URL}/calls/start-test/${encodeURIComponent(id)}`,
    { method: "POST", headers: API_HEADERS },
  );
  if (!res.ok) {
    const payload = await res.json().catch(() => null);
    throw new Error(payload?.detail || `startTestOutbound failed: ${res.status}`);
  }
  return res.json();
}

export async function getResults(id: string): Promise<Report> {
  if (USE_MOCK) return mockGetResults(id);

  const res = await fetch(`${API_BASE_URL}/results/${encodeURIComponent(id)}`, {
    headers: API_HEADERS,
  });
  if (!res.ok) throw new Error(`getResults failed: ${res.status}`);
  return res.json();
}

export async function getCompletedCall(id: string, companyId: string): Promise<Quote> {
  if (USE_MOCK) return mockGetCompletedCall(id, companyId);

  const res = await fetch(
    `${API_BASE_URL}/calls/completed/${encodeURIComponent(id)}/${encodeURIComponent(companyId)}`,
    { method: "POST", headers: API_HEADERS },
  );
  if (!res.ok) throw new Error(`getCompletedCall failed: ${res.status}`);
  return res.json();
}

export async function getCallStatuses(id: string): Promise<CallStatusesResult> {
  const res = await fetch(`${API_BASE_URL}/calls/status/${encodeURIComponent(id)}`, {
    headers: API_HEADERS,
  });
  if (!res.ok) throw new Error(`getCallStatuses failed: ${res.status}`);
  return res.json();
}

export async function getCalls(filters: {
  job_spec_id?: string;
  company_id?: string;
  status?: string;
  outcome?: string;
} = {}): Promise<CallsResult> {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value) params.set(key, value);
  });
  const suffix = params.toString() ? `?${params.toString()}` : "";
  const res = await fetch(`${API_BASE_URL}/calls${suffix}`, { headers: API_HEADERS });
  if (!res.ok) throw new Error(`getCalls failed: ${res.status}`);
  return res.json();
}

export async function getCall(callId: string): Promise<StoredCall> {
  const res = await fetch(`${API_BASE_URL}/calls/${encodeURIComponent(callId)}`, {
    headers: API_HEADERS,
  });
  if (!res.ok) throw new Error(`getCall failed: ${res.status}`);
  return res.json();
}

// ---------- Mock implementations ----------
const specStore = new Map<string, JobSpec>();
const specCreatedAt = new Map<string, number>();

function genId(prefix: string) {
  return `${prefix}_${Math.random().toString(36).slice(2, 10)}`;
}

async function mockCreateSpec(input: CreateSpecInput): Promise<JobSpec> {
  await delay(NETWORK_DELAY_MS);
  const job_spec_id = genId("spec");
  const spec: JobSpec = { ...input, job_spec_id, distance_miles: null, confirmed_by_user: false };
  specStore.set(job_spec_id, spec);
  specCreatedAt.set(job_spec_id, Date.now());
  return spec;
}

async function mockUpdateSpec(id: string, spec: CreateSpecInput): Promise<JobSpec> {
  await delay(NETWORK_DELAY_MS);
  const updated = { ...spec, job_spec_id: id, distance_miles: null, confirmed_by_user: false };
  specStore.set(id, updated);
  return updated;
}

async function mockCreateSpecFromVoice(transcript: string): Promise<JobSpec> {
  await delay(NETWORK_DELAY_MS);
  const job_spec_id = genId("voicespec");
  const spec: JobSpec = {
    job_spec_id,
    origin_address: "6161 Brookshire Blvd, Charlotte, NC 28216",
    origin_floor: 3,
    origin_has_elevator: false,
    origin_lat: null,
    origin_lng: null,
    destination_address: "1425 Elm Street, Rock Hill, SC 29730",
    destination_floor: 0,
    destination_has_elevator: false,
    destination_lat: null,
    destination_lng: null,
    move_date: "2026-08-08",
    date_flexible: true,
    num_trips: 1,
    num_bags: 24,
    notes: "",
    source: "voice_interview",
    distance_miles: null,
    confirmed_by_user: false,
    intake_transcript: transcript,
  };
  specStore.set(job_spec_id, spec);
  specCreatedAt.set(job_spec_id, Date.now());
  return spec;
}

async function mockCreateSpecFromDocument(): Promise<JobSpec> {
  await delay(NETWORK_DELAY_MS);
  const job_spec_id = genId("docspec");
  const spec: JobSpec = {
    job_spec_id,
    origin_address: "6161 Brookshire Blvd, Charlotte, NC 28216",
    origin_floor: 0,
    origin_has_elevator: false,
    origin_lat: null,
    origin_lng: null,
    destination_address: "1425 Elm Street, Rock Hill, SC 29730",
    destination_floor: 0,
    destination_has_elevator: false,
    destination_lat: null,
    destination_lng: null,
    move_date: "2026-08-08",
    date_flexible: true,
    num_trips: 1,
    num_bags: 24,
    notes: "",
    source: "document_upload",
    distance_miles: null,
    confirmed_by_user: false,
  };
  specStore.set(job_spec_id, spec);
  specCreatedAt.set(job_spec_id, Date.now());
  return spec;
}

async function mockGetSpec(id: string): Promise<JobSpec> {
  await delay(NETWORK_DELAY_MS);
  const spec = specStore.get(id);
  if (!spec) throw new Error(`Spec ${id} not found`);
  const createdAt = specCreatedAt.get(id) ?? 0;
  if (spec.distance_miles == null && Date.now() - createdAt >= DISTANCE_DELAY_MS) return spec;
  return spec;
}

async function mockConfirmSpec(id: string): Promise<JobSpec> {
  await delay(NETWORK_DELAY_MS);
  const spec = specStore.get(id);
  if (!spec) throw new Error(`Spec ${id} not found`);
  const updated = { ...spec, confirmed_by_user: true };
  specStore.set(id, updated);
  return updated;
}

const mockCompanies: Array<{
  company_id: string;
  company: string;
  total: number;
  fees: Fee[];
  differentiators: string[];
  red_flag: string | null;
}> = [
  {
    company_id: "blue-ox",
    company: "Blue Ox Movers",
    total: 2340,
    fees: [
      { label: "Base labor (3 movers, 6 hrs)", amount: 1620 },
      { label: "Truck & mileage", amount: 540 },
      { label: "Stairs surcharge (3 flights)", amount: 120 },
      { label: "Fuel", amount: 60 },
    ],
    differentiators: ["Fully itemized", "Confirmed stairs cost upfront", "Licensed & insured"],
    red_flag: null,
  },
  {
    company_id: "harbor-point",
    company: "Harbor Point Moving",
    total: 2510,
    fees: [
      { label: "Base labor", amount: 1700 },
      { label: "Truck & mileage", amount: 580 },
      { label: "Long carry", amount: 150 },
      { label: "Fuel", amount: 80 },
    ],
    differentiators: ["Free wardrobe boxes", "Same-crew guarantee"],
    red_flag: null,
  },
  {
    company_id: "metro-relo",
    company: "Metro Relocation Co.",
    total: 3180,
    fees: [
      { label: "Flat rate (bundled)", amount: 2900 },
      { label: "Materials (unspecified)", amount: 180 },
      { label: "Fuel surcharge", amount: 100 },
    ],
    differentiators: ["Binding estimate"],
    red_flag: "Refused to itemize; pushed a 'binding estimate' with vague overage clause.",
  },
  {
    company_id: "swiftvan",
    company: "SwiftVan Logistics",
    total: 2790,
    fees: [
      { label: "Base labor", amount: 1900 },
      { label: "Truck & mileage", amount: 620 },
      { label: "Piano handling", amount: 200 },
      { label: "Fuel", amount: 70 },
    ],
    differentiators: ["Specialty item experience"],
    red_flag: null,
  },
];

async function mockGetResults(id: string): Promise<Report> {
  await delay(NETWORK_DELAY_MS);
  const sorted = [...mockCompanies].sort((a, b) => a.total - b.total);
  const ranked_companies: RankedCompany[] = sorted.map((c, i) => ({
    ...c,
    rank: i + 1,
    recommended: i === 0,
    transcript_url: `#transcript-${c.company_id}`,
    recording_url: `#recording-${c.company_id}`,
  }));
  const cheapest = ranked_companies[0];
  const runnerUp = ranked_companies[1];
  const summary = `${cheapest.company} is the cheapest by $${runnerUp.total - cheapest.total} vs. the next option, itemized every fee without pushback, and confirmed the stairs and long-carry costs upfront. No red flags in the transcript — a real negotiator on the other end, not a hard-sell.`;
  return { job_spec_id: id, summary, ranked_companies };
}

async function mockGetCompletedCall(id: string, companyId: string): Promise<Quote> {
  await delay(NETWORK_DELAY_MS);
  const c = mockCompanies.find((m) => m.company_id === companyId) ?? mockCompanies[0];
  return {
    company_id: c.company_id,
    company: c.company,
    total: c.total,
    fees: c.fees,
    differentiators: c.differentiators,
    red_flag: c.red_flag,
    transcript_url: `#transcript-${c.company_id}-${id}`,
    recording_url: `#recording-${c.company_id}-${id}`,
  };
}

