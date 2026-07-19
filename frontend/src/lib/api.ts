// Mock/real API module. Switching backends only requires editing these two constants:
export const API_BASE_URL = "http://127.0.0.1:8000/api";
const USE_MOCK = true;

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
  notes: string;
  source: Source;
  distance_miles: number | null;
};

export type Fee = { label: string; amount: number };

export type Quote = {
  company_id: string;
  company: string;
  total: number;
  fees: Fee[];
  differentiators: string[];
  red_flag: string | null;
  transcript_url: string;
  recording_url: string;
};

export type RankedCompany = Quote & { rank: number; recommended: boolean };

export type Report = {
  job_spec_id: string;
  summary: string;
  ranked_companies: RankedCompany[];
};

export type CreateSpecInput = Omit<JobSpec, "job_spec_id" | "distance_miles">;

// ---------- API entrypoints (the only mock/real branching) ----------
export async function createSpec(input: CreateSpecInput): Promise<JobSpec> {
  if (USE_MOCK) return mockCreateSpec(input);

  const res = await fetch(`${API_BASE_URL}/specs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) throw new Error(`createSpec failed: ${res.status}`);
  return res.json();
}

export async function getSpec(id: string): Promise<JobSpec> {
  if (USE_MOCK) return mockGetSpec(id);

  const res = await fetch(`${API_BASE_URL}/specs/${encodeURIComponent(id)}`);
  if (!res.ok) throw new Error(`getSpec failed: ${res.status}`);
  return res.json();
}

export async function confirmSpec(id: string): Promise<JobSpec> {
  if (USE_MOCK) return mockConfirmSpec(id);

  const res = await fetch(
    `${API_BASE_URL}/specs/${encodeURIComponent(id)}/confirm`,
    { method: "POST" },
  );
  if (!res.ok) throw new Error(`confirmSpec failed: ${res.status}`);
  return res.json();
}

export async function getResults(id: string): Promise<Report> {
  if (USE_MOCK) return mockGetResults(id);

  const res = await fetch(`${API_BASE_URL}/results/${encodeURIComponent(id)}`);
  if (!res.ok) throw new Error(`getResults failed: ${res.status}`);
  return res.json();
}

export async function getCompletedCall(id: string, companyId: string): Promise<Quote> {
  if (USE_MOCK) return mockGetCompletedCall(id, companyId);

  const res = await fetch(
    `${API_BASE_URL}/calls/completed/${encodeURIComponent(id)}/${encodeURIComponent(companyId)}`,
    { method: "POST" },
  );
  if (!res.ok) throw new Error(`getCompletedCall failed: ${res.status}`);
  return res.json();
}

// ---------- Mock implementations ----------
const specStore = new Map<string, JobSpec>();
const specCreatedAt = new Map<string, number>();

function genId(prefix: string) {
  return `${prefix}_${Math.random().toString(36).slice(2, 10)}`;
}

function haversineMiles(lat1: number, lng1: number, lat2: number, lng2: number) {
  const R = 3958.8;
  const toRad = (d: number) => (d * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLng = toRad(lng2 - lng1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLng / 2) ** 2;
  return Math.round(2 * R * Math.asin(Math.sqrt(a)));
}

async function mockCreateSpec(input: CreateSpecInput): Promise<JobSpec> {
  await delay(NETWORK_DELAY_MS);
  const job_spec_id = genId("spec");
  const spec: JobSpec = { ...input, job_spec_id, distance_miles: null };
  specStore.set(job_spec_id, spec);
  specCreatedAt.set(job_spec_id, Date.now());
  return spec;
}

async function mockGetSpec(id: string): Promise<JobSpec> {
  await delay(NETWORK_DELAY_MS);
  const spec = specStore.get(id);
  if (!spec) throw new Error(`Spec ${id} not found`);
  const createdAt = specCreatedAt.get(id) ?? 0;
  if (spec.distance_miles == null && Date.now() - createdAt >= DISTANCE_DELAY_MS) {
    const hasCoords =
      spec.origin_lat != null &&
      spec.origin_lng != null &&
      spec.destination_lat != null &&
      spec.destination_lng != null;
    const miles = hasCoords
      ? haversineMiles(
          spec.origin_lat as number,
          spec.origin_lng as number,
          spec.destination_lat as number,
          spec.destination_lng as number,
        ) || 45
      : 45;
    const updated = { ...spec, distance_miles: miles };
    specStore.set(id, updated);
    return updated;
  }
  return spec;
}

async function mockConfirmSpec(id: string): Promise<JobSpec> {
  await delay(NETWORK_DELAY_MS);
  const spec = specStore.get(id);
  if (!spec) throw new Error(`Spec ${id} not found`);
  const hasCoords =
    spec.origin_lat != null &&
    spec.origin_lng != null &&
    spec.destination_lat != null &&
    spec.destination_lng != null;
  const miles =
    spec.distance_miles ??
    (hasCoords
      ? haversineMiles(
          spec.origin_lat as number,
          spec.origin_lng as number,
          spec.destination_lat as number,
          spec.destination_lng as number,
        ) || 45
      : 45);
  const updated = { ...spec, distance_miles: miles };
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

