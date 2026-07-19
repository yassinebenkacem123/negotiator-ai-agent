import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { getCall, getCalls, type StoredCall } from "@/lib/api";

export const Route = createFileRoute("/calls")({
  head: () => ({
    meta: [
      { title: "Live Calls - The Negotiator" },
      { name: "description", content: "See completed negotiation calls with moving companies." },
    ],
  }),
  component: CallsPage,
});

function money(value: number | null) {
  return value == null ? "-" : value.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
}

function duration(seconds: number | null) {
  if (seconds == null) return "-";
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs < 10 ? "0" : ""}${secs}`;
}

function CallsPage() {
  const [calls, setCalls] = useState<StoredCall[]>([]);
  const [selected, setSelected] = useState<StoredCall | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const jobSpecId =
    (typeof window !== "undefined" && window.localStorage.getItem("negotiator.job_spec_id")) ||
    undefined;

  useEffect(() => {
    let cancelled = false;
    getCalls({ job_spec_id: jobSpecId })
      .then((response) => {
        if (!cancelled) setCalls(response.calls);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not load calls.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [jobSpecId]);

  const openDetail = async (call: StoredCall) => {
    setDetailLoading(call.call_id);
    try {
      setSelected(await getCall(call.call_id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load call detail.");
    } finally {
      setDetailLoading(null);
    }
  };

  return (
    <div>
      <div className="mb-8 flex items-end justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-foreground">Live Calls</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Persisted ElevenLabs call conversations and extracted quote details.
          </p>
        </div>
        <div className="text-sm text-muted-foreground">{calls.length} stored calls</div>
      </div>

      {error && <p className="mb-4 text-sm text-destructive">{error}</p>}

      {loading ? (
        <p className="text-sm text-muted-foreground">Loading calls...</p>
      ) : calls.length === 0 ? (
        <div className="rounded-lg border border-border bg-card p-8 text-center text-sm text-muted-foreground">
          No outbound calls have been stored yet.
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-border bg-card">
          <table className="w-full text-sm">
            <thead className="bg-secondary text-secondary-foreground">
              <tr>
                <th className="px-4 py-3 text-left font-medium">Company</th>
                <th className="px-4 py-3 text-left font-medium">Phone</th>
                <th className="px-4 py-3 text-left font-medium">Status</th>
                <th className="px-4 py-3 text-left font-medium">Outcome</th>
                <th className="px-4 py-3 text-left font-medium">Initial</th>
                <th className="px-4 py-3 text-left font-medium">Negotiated</th>
                <th className="px-4 py-3 text-left font-medium">Duration</th>
                <th className="px-4 py-3 text-left font-medium">Transcript</th>
                <th className="px-4 py-3 text-left font-medium">Recording</th>
                <th className="px-4 py-3 text-right font-medium">Details</th>
              </tr>
            </thead>
            <tbody>
              {calls.map((call) => (
                <tr key={call.call_id} className="border-t border-border">
                  <td className="px-4 py-3 font-medium text-foreground">{call.company_name || call.company_id}</td>
                  <td className="px-4 py-3 font-mono text-xs text-muted-foreground">{call.company_phone || "-"}</td>
                  <td className="px-4 py-3 capitalize text-muted-foreground">{call.status}</td>
                  <td className="px-4 py-3 text-muted-foreground">{call.outcome?.replaceAll("_", " ") ?? "-"}</td>
                  <td className="px-4 py-3 font-mono text-xs">{money(call.initial_price)}</td>
                  <td className="px-4 py-3 font-mono text-xs">{money(call.negotiated_price)}</td>
                  <td className="px-4 py-3 font-mono text-xs text-muted-foreground">{duration(call.duration_seconds)}</td>
                  <td className="px-4 py-3 text-xs text-muted-foreground">{call.transcript.length > 0 ? "Available" : "Pending"}</td>
                  <td className="px-4 py-3 text-xs text-muted-foreground">{call.recording_url ? "Available" : "Pending"}</td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={() => openDetail(call)}
                      disabled={detailLoading === call.call_id}
                      className="rounded-md border border-input bg-background px-3 py-1.5 text-xs font-medium text-foreground hover:bg-accent disabled:opacity-60"
                    >
                      {detailLoading === call.call_id ? "Loading..." : "Open"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {selected && (
        <div className="mt-6 rounded-lg border border-border bg-card p-6">
          <div className="flex items-start justify-between">
            <div>
              <div className="text-xs uppercase tracking-wide text-muted-foreground">Call detail</div>
              <div className="mt-1 text-lg font-semibold text-foreground">{selected.company_name}</div>
              <div className="mt-1 font-mono text-xs text-muted-foreground">{selected.company_phone}</div>
              <div className="mt-1 font-mono text-xs text-muted-foreground">{selected.call_id}</div>
            </div>
            <button onClick={() => setSelected(null)} className="text-xs text-muted-foreground hover:text-foreground">
              Close
            </button>
          </div>

          <div className="mt-5 grid gap-5 md:grid-cols-2">
            <div>
              <div className="text-xs font-medium text-muted-foreground">Negotiation result</div>
              <div className="mt-1 text-sm text-foreground">
                {selected.negotiation_successful ? "Negotiated successfully" : "No negotiated reduction recorded"}
              </div>
              <div className="mt-4 text-xs font-medium text-muted-foreground">Fees</div>
              <div className="mt-1 space-y-1 text-sm">
                {Object.keys(selected.fees).length === 0 ? (
                  <div className="text-muted-foreground">No itemized fees stored.</div>
                ) : (
                  Object.entries(selected.fees).map(([label, amount]) => (
                    <div key={label} className="flex justify-between gap-4">
                      <span>{label}</span>
                      <span className="font-mono">{typeof amount === "number" ? money(amount) : String(amount)}</span>
                    </div>
                  ))
                )}
              </div>
              <div className="mt-4 text-xs font-medium text-muted-foreground">Differentiators</div>
              {selected.differentiators.length === 0 ? (
                <p className="mt-1 text-sm text-muted-foreground">None stored.</p>
              ) : (
                <ul className="mt-1 list-disc pl-5 text-sm text-foreground">
                  {selected.differentiators.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              )}
            </div>

            <div>
              <div className="text-xs font-medium text-muted-foreground">Transcript</div>
              {selected.transcript.length === 0 ? (
                <p className="mt-1 text-sm text-muted-foreground">Transcript is not available.</p>
              ) : (
                <div className="mt-2 max-h-80 overflow-y-auto rounded-md border border-border bg-background p-3 text-sm">
                  {selected.transcript.map((turn, index) => (
                    <p key={index} className="mb-2">
                      <span className="font-medium capitalize">{turn.role}:</span> {turn.message ?? ""}
                    </p>
                  ))}
                </div>
              )}

              <div className="mt-4 text-xs font-medium text-muted-foreground">Recording</div>
              {selected.recording_url ? (
                <audio className="mt-2 w-full" controls src={selected.recording_url} />
              ) : (
                <p className="mt-1 text-sm text-muted-foreground">Recording is not available.</p>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
