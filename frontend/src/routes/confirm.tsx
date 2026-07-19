import { createFileRoute } from "@tanstack/react-router";
import { ClientOnly } from "@tanstack/react-router";
import { createElement, lazy, Suspense, useCallback, useEffect, useState } from "react";
import { createSpec, getSpec, confirmSpec } from "@/lib/api";

const ELEVENLABS_SCRIPT_SRC = "https://elevenlabs.io/convai-widget/index.js";
const ELEVENLABS_AGENT_ID = "agent_1301kxwfxc93e9nsct5kdekedv8x";

const LeafletMap = lazy(() => import("@/components/LeafletMap"));

export const Route = createFileRoute("/confirm")({
  head: () => ({
    meta: [
      { title: "Confirm Spec — The Negotiator" },
      { name: "description", content: "Review and confirm your move spec before we call movers." },
    ],
  }),
  component: ConfirmPage,
});

type Source = "voice_interview" | "document_upload";
type PinKind = "origin" | "destination";

type Spec = {
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
};

const initialSpec: Spec = {
  origin_address: "1425 Elm Street, Apt 4B, Brooklyn, NY 11201",
  origin_floor: 4,
  origin_has_elevator: false,
  origin_lat: null,
  origin_lng: null,
  destination_address: "88 Beacon Hill Rd, Boston, MA 02108",
  destination_floor: 2,
  destination_has_elevator: true,
  destination_lat: null,
  destination_lng: null,
  move_date: "2026-08-14",
  date_flexible: true,
  num_trips: 2,
  num_bags: 18,
  notes: "No elevator at origin. Street parking only, permit required by building super.",
  source: "voice_interview",
};

// Default map view centers if the user hasn't dropped pins yet.
const ORIGIN_FALLBACK = { lat: 40.6958, lng: -73.9936 };
const DEST_FALLBACK = { lat: 42.3588, lng: -71.0707 };

function Label({ children }: { children: React.ReactNode }) {
  return <label className="text-sm font-medium text-foreground">{children}</label>;
}

const inputCls =
  "mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring";

// Shared Nominatim forward-geocode: used for manual typing, voice-assistant fills,
// and document_upload parsed addresses. Updates the pin lat/lng on the spec.
async function geocodeAndSetPin(
  kind: PinKind,
  address: string,
  setSpec: React.Dispatch<React.SetStateAction<Spec>>,
) {
  try {
    console.log(`[geocode] forward ${kind} →`, address);
    const res = await fetch(
      `https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(address)}&format=json&limit=1`,
      { headers: { Accept: "application/json" } },
    );
    console.log(`[geocode] forward ${kind} status`, res.status);
    if (!res.ok) return;
    const data = (await res.json()) as Array<{ lat: string; lon: string }>;
    if (!data.length) {
      console.warn(`[geocode] forward ${kind}: no results for`, address);
      return;
    }
    const lat = parseFloat(data[0].lat);
    const lng = parseFloat(data[0].lon);
    if (Number.isNaN(lat) || Number.isNaN(lng)) return;
    setSpec((s) => {
      if (kind === "origin") {
        if (s.origin_lat === lat && s.origin_lng === lng) return s;
        console.log("[geocode] origin pin updated", { lat, lng });
        return { ...s, origin_lat: lat, origin_lng: lng };
      }
      if (s.destination_lat === lat && s.destination_lng === lng) return s;
      console.log("[geocode] destination pin updated", { lat, lng });
      return { ...s, destination_lat: lat, destination_lng: lng };
    });
  } catch (err) {
    console.warn(`[geocode] forward ${kind} failed`, err);
  }
}


function ConfirmPage() {
  const [spec, setSpec] = useState<Spec>(initialSpec);
  const [mode, setMode] = useState<"voice" | "manual">("voice");
  const [confirmed, setConfirmed] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (typeof document === "undefined") return;
    if (document.querySelector(`script[src="${ELEVENLABS_SCRIPT_SRC}"]`)) return;
    const s = document.createElement("script");
    s.src = ELEVENLABS_SCRIPT_SRC;
    s.async = true;
    document.body.appendChild(s);
  }, []);
  const [jobSpecId, setJobSpecId] = useState<string | null>(null);
  const [distanceMiles, setDistanceMiles] = useState<number | null>(null);
  const [distanceUnavailable, setDistanceUnavailable] = useState(false);

  const set = <K extends keyof Spec>(k: K, v: Spec[K]) => setSpec((s) => ({ ...s, [k]: v }));

  const onPinChange = useCallback(async (kind: PinKind, lat: number, lng: number) => {
    console.log("[geocode] pin dragged", { kind, lat, lng });
    setSpec((s) => {
      const next =
        kind === "origin"
          ? { ...s, origin_lat: lat, origin_lng: lng }
          : { ...s, destination_lat: lat, destination_lng: lng };
      console.log("[geocode] pin state updated", {
        origin_lat: next.origin_lat,
        origin_lng: next.origin_lng,
        destination_lat: next.destination_lat,
        destination_lng: next.destination_lng,
      });
      return next;
    });
    try {
      // Note: browsers forbid setting the User-Agent header on fetch; it's set
      // automatically by the browser and Nominatim accepts a valid Referer instead.
      const url = `https://nominatim.openstreetmap.org/reverse?format=json&lat=${lat}&lon=${lng}&zoom=18&addressdetails=1`;
      const res = await fetch(url, { headers: { Accept: "application/json" } });
      console.log("[geocode] reverse response", { kind, status: res.status });
      if (!res.ok) return;
      const data = (await res.json()) as { display_name?: string };
      console.log("[geocode] reverse data", { kind, display_name: data.display_name });
      const address = data.display_name;
      if (!address) return;
      setSpec((s) =>
        kind === "origin"
          ? { ...s, origin_address: address }
          : { ...s, destination_address: address },
      );
    } catch (err) {
      console.warn("[geocode] reverse failed", err);
    }
  }, []);

  // Debounced forward-geocoding: whenever origin_address / destination_address change
  // — whether the user typed them, the voice assistant filled them in, or a parsed
  // document populated them (source: "document_upload") — look the address up on
  // Nominatim and move the corresponding map pin + lat/lng.
  useEffect(() => {
    const address = spec.origin_address.trim();
    if (!address) return;
    const handle = setTimeout(() => {
      geocodeAndSetPin("origin", address, setSpec);
    }, 800);
    return () => clearTimeout(handle);
  }, [spec.origin_address]);

  useEffect(() => {
    const address = spec.destination_address.trim();
    if (!address) return;
    const handle = setTimeout(() => {
      geocodeAndSetPin("destination", address, setSpec);
    }, 800);
    return () => clearTimeout(handle);
  }, [spec.destination_address]);


  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setDistanceMiles(null);
    setDistanceUnavailable(false);
    try {
      console.log("[submit] POST /api/specs body", {
        origin_lat: spec.origin_lat,
        origin_lng: spec.origin_lng,
        destination_lat: spec.destination_lat,
        destination_lng: spec.destination_lng,
        full: spec,
      });
      const submitSpec: Spec = {
        ...spec,
        source: mode === "voice" ? "voice_interview" : "document_upload",
      };
      const created = await createSpec(submitSpec);
      setJobSpecId(created.job_spec_id);
      if (typeof window !== "undefined") {
        window.localStorage.setItem("negotiator.job_spec_id", created.job_spec_id);
      }
      const confirmed = await confirmSpec(created.job_spec_id);
      setDistanceMiles(confirmed.distance_miles);
      setConfirmed(true);
      console.log("Confirm Spec response:", confirmed);
    } finally {
      setSubmitting(false);
    }
  };

  // Poll for distance_miles up to 5 attempts (~5 seconds).
  useEffect(() => {
    if (!jobSpecId || distanceMiles != null) return;
    let attempts = 0;
    let timeoutId: ReturnType<typeof setTimeout> | null = null;
    let cancelled = false;
    const tick = async () => {
      attempts++;
      const s = await getSpec(jobSpecId);
      if (cancelled) return;
      if (s.distance_miles != null) {
        setDistanceMiles(s.distance_miles);
      } else if (attempts >= 5) {
        setDistanceUnavailable(true);
      } else {
        timeoutId = setTimeout(tick, 1000);
      }
    };
    tick();
    return () => {
      cancelled = true;
      if (timeoutId) clearTimeout(timeoutId);
    };
  }, [jobSpecId, distanceMiles]);



  return (
    <div>
      <div className="mb-8">
        <h1 className="text-3xl font-bold tracking-tight text-foreground">Confirm Spec</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Double-check your move details. The Negotiator will use these when calling movers.
        </p>
      </div>

      <div className="mb-6 inline-flex rounded-md border border-border bg-card p-1">
        <button
          type="button"
          onClick={() => setMode("voice")}
          className={`px-4 py-2 text-sm font-medium rounded ${
            mode === "voice"
              ? "bg-primary text-primary-foreground"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          Talk to our assistant
        </button>
        <button
          type="button"
          onClick={() => setMode("manual")}
          className={`px-4 py-2 text-sm font-medium rounded ${
            mode === "manual"
              ? "bg-primary text-primary-foreground"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          Fill out manually
        </button>
      </div>

      {mode === "voice" && (
        <div className="mb-6 rounded-lg border border-border bg-card p-6">
          <h2 className="text-lg font-semibold text-foreground">Talk to our assistant</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Our voice assistant will interview you about your move. Your answers populate the same
            spec below — switch to “Fill out manually” anytime to review and edit.
          </p>
          <div className="mt-4">
            {createElement("elevenlabs-convai", { "agent-id": ELEVENLABS_AGENT_ID })}
          </div>
          <div className="mt-6 flex items-center justify-between border-t border-border pt-4">
            <p className="text-xs text-muted-foreground">
              Once you're done chatting, confirm to send the spec to the Negotiator.
            </p>
            <button
              type="button"
              onClick={() => onSubmit({ preventDefault: () => {} } as React.FormEvent)}
              disabled={submitting}
              className="inline-flex items-center justify-center rounded-md bg-primary px-5 py-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-60"
            >
              {submitting ? "Submitting…" : "Confirm Spec"}
            </button>
          </div>
        </div>
      )}

      {confirmed && (
        <div className="mb-6 rounded-md border border-primary/30 bg-accent px-4 py-3 text-sm text-primary">
          Spec confirmed. Job ID: <span className="font-mono">{jobSpecId}</span>. The Negotiator will start calling movers.
        </div>
      )}


      <form
        onSubmit={onSubmit}
        className={`space-y-6 rounded-lg border border-border bg-card p-6 ${mode === "voice" ? "hidden" : ""}`}
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-xs uppercase tracking-wide text-muted-foreground">Source</span>
            <span className="inline-flex items-center rounded-full border border-primary/30 bg-accent px-2.5 py-0.5 text-xs font-medium text-primary">
              {mode === "voice" ? "voice_interview" : "document_upload"}
            </span>
          </div>
          <div className="text-sm text-muted-foreground">
            Distance:{" "}
            <span className="font-medium text-foreground">
              {distanceUnavailable
                ? "Distance unavailable — please set both map pins"
                : distanceMiles == null
                ? "calculating…"
                : `${distanceMiles} miles`}
            </span>
          </div>
        </div>

        <div>
          <Label>Map (drag pins to set coordinates)</Label>
          <div className="mt-2">
            <ClientOnly
              fallback={
                <div className="flex h-72 w-full items-center justify-center rounded-md border border-border bg-muted text-sm text-muted-foreground">
                  Loading map…
                </div>
              }
            >
              <Suspense
                fallback={
                  <div className="flex h-72 w-full items-center justify-center rounded-md border border-border bg-muted text-sm text-muted-foreground">
                    Loading map…
                  </div>
                }
              >
                <LeafletMap
                  origin={
                    spec.origin_lat != null && spec.origin_lng != null
                      ? { lat: spec.origin_lat, lng: spec.origin_lng }
                      : null
                  }
                  destination={
                    spec.destination_lat != null && spec.destination_lng != null
                      ? { lat: spec.destination_lat, lng: spec.destination_lng }
                      : null
                  }
                  originFallback={ORIGIN_FALLBACK}
                  destFallback={DEST_FALLBACK}
                  onChange={onPinChange}
                />
              </Suspense>
            </ClientOnly>
            <div className="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-xs text-muted-foreground">
              <span>
                Origin:{" "}
                {spec.origin_lat != null && spec.origin_lng != null
                  ? `${spec.origin_lat.toFixed(4)}, ${spec.origin_lng.toFixed(4)}`
                  : "not set (drag pin to set)"}
              </span>
              <span>
                Destination:{" "}
                {spec.destination_lat != null && spec.destination_lng != null
                  ? `${spec.destination_lat.toFixed(4)}, ${spec.destination_lng.toFixed(4)}`
                  : "not set (drag pin to set)"}
              </span>
            </div>
          </div>
        </div>


        <fieldset className="grid gap-4 sm:grid-cols-2">
          <legend className="mb-2 text-sm font-semibold text-foreground">Origin</legend>
          <div className="sm:col-span-2">
            <Label>Origin Address</Label>
            <input
              className={inputCls}
              value={spec.origin_address}
              onChange={(e) => set("origin_address", e.target.value)}
            />
          </div>
          <div>
            <Label>Origin Floor (0 = ground)</Label>
            <input
              type="number"
              min={0}
              className={inputCls}
              value={spec.origin_floor}
              onChange={(e) => set("origin_floor", Number(e.target.value))}
            />
          </div>
          <label className="mt-6 flex items-center gap-2 rounded-md border border-input bg-background px-3 py-2">
            <input
              type="checkbox"
              checked={spec.origin_has_elevator}
              onChange={(e) => set("origin_has_elevator", e.target.checked)}
            />
            <span className="text-sm text-foreground">Has Elevator?</span>
          </label>
        </fieldset>

        <fieldset className="grid gap-4 sm:grid-cols-2">
          <legend className="mb-2 text-sm font-semibold text-foreground">Destination</legend>
          <div className="sm:col-span-2">
            <Label>Destination Address</Label>
            <input
              className={inputCls}
              value={spec.destination_address}
              onChange={(e) => set("destination_address", e.target.value)}
            />
          </div>
          <div>
            <Label>Destination Floor (0 = ground)</Label>
            <input
              type="number"
              min={0}
              className={inputCls}
              value={spec.destination_floor}
              onChange={(e) => set("destination_floor", Number(e.target.value))}
            />
          </div>
          <label className="mt-6 flex items-center gap-2 rounded-md border border-input bg-background px-3 py-2">
            <input
              type="checkbox"
              checked={spec.destination_has_elevator}
              onChange={(e) => set("destination_has_elevator", e.target.checked)}
            />
            <span className="text-sm text-foreground">Has Elevator?</span>
          </label>
        </fieldset>

        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <Label>Move Date</Label>
            <input
              type="date"
              className={inputCls}
              value={spec.move_date}
              onChange={(e) => set("move_date", e.target.value)}
            />
          </div>
          <label className="mt-6 flex items-center gap-2 rounded-md border border-input bg-background px-3 py-2">
            <input
              type="checkbox"
              checked={spec.date_flexible}
              onChange={(e) => set("date_flexible", e.target.checked)}
            />
            <span className="text-sm text-foreground">Flexible Date?</span>
          </label>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <Label>Number of Trips</Label>
            <input
              type="number"
              min={0}
              className={inputCls}
              value={spec.num_trips}
              onChange={(e) => set("num_trips", Number(e.target.value))}
            />
          </div>
          <div>
            <Label>Number of Bags</Label>
            <input
              type="number"
              min={0}
              className={inputCls}
              value={spec.num_bags}
              onChange={(e) => set("num_bags", Number(e.target.value))}
            />
          </div>
        </div>

        <div>
          <Label>Notes (optional)</Label>
          <textarea
            className={`${inputCls} min-h-[96px]`}
            value={spec.notes}
            onChange={(e) => set("notes", e.target.value)}
          />
        </div>

        <div className="flex items-center justify-between border-t border-border pt-4">
          <div className="text-xs text-muted-foreground">
            {jobSpecId ? `job_spec_id: ${jobSpecId}` : "Not yet submitted"}
          </div>
          <button
            type="submit"
            disabled={submitting}
            className="inline-flex items-center justify-center rounded-md bg-primary px-5 py-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-60"
          >
            {submitting ? "Submitting…" : "Confirm Spec"}
          </button>
        </div>

      </form>
    </div>
  );
}
