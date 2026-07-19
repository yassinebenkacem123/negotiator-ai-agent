import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { getCompletedCall, getResults, type Quote, type RankedCompany } from "@/lib/api";

export const Route = createFileRoute("/calls")({
  head: () => ({
    meta: [
      { title: "Live Calls — The Negotiator" },
      { name: "description", content: "See live negotiation calls with moving companies." },
    ],
  }),
  component: CallsPage,
});

type Style = "real" | "stonewaller" | "hard-sell";
type Status = "calling" | "completed" | "no answer";

type CallRow = {
  company_id: string;
  company: string;
  style: Style;
  status: Status;
  duration: string;
};

const styleBadge: Record<Style, string> = {
  real: "bg-accent text-primary border-primary/30",
  stonewaller: "bg-muted text-muted-foreground border-border",
  "hard-sell": "bg-destructive/10 text-destructive border-destructive/30",
};

const statusBadge: Record<Status, string> = {
  calling: "bg-accent text-primary",
  completed: "bg-secondary text-secondary-foreground",
  "no answer": "bg-muted text-muted-foreground",
};

function StatusDot({ status }: { status: Status }) {
  if (status === "calling") {
    return (
      <span className="relative inline-flex h-2 w-2">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-75" />
        <span className="relative inline-flex h-2 w-2 rounded-full bg-primary" />
      </span>
    );
  }
  return (
    <span
      className={`inline-flex h-2 w-2 rounded-full ${
        status === "completed" ? "bg-primary" : "bg-muted-foreground"
      }`}
    />
  );
}

// Deterministic mapping from company traits to a display call row.
function toCallRow(c: RankedCompany, i: number): CallRow {
  const style: Style = c.red_flag ? "hard-sell" : i === 2 ? "stonewaller" : "real";
  const status: Status =
    style === "stonewaller" ? "no answer" : i === 3 ? "calling" : "completed";
  const duration =
    status === "no answer"
      ? "0:14"
      : status === "calling"
        ? "2:03"
        : `${5 + i}:${(11 + i * 7) % 60 < 10 ? "0" : ""}${(11 + i * 7) % 60}`;
  return { company_id: c.company_id, company: c.company, style, status, duration };
}

function CallsPage() {
  const [calls, setCalls] = useState<CallRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Quote | null>(null);
  const [loadingQuote, setLoadingQuote] = useState<string | null>(null);

  useEffect(() => {
    const id =
      (typeof window !== "undefined" && window.localStorage.getItem("negotiator.job_spec_id")) ||
      "spec_demo";
    getResults(id)
      .then((r) => setCalls(r.ranked_companies.map(toCallRow)))
      .finally(() => setLoading(false));
  }, []);

  const onPlay = async (row: CallRow) => {
    const id =
      (typeof window !== "undefined" && window.localStorage.getItem("negotiator.job_spec_id")) ||
      "spec_demo";
    setLoadingQuote(row.company_id);
    try {
      const quote = await getCompletedCall(id, row.company_id);
      setSelected(quote);
    } finally {
      setLoadingQuote(null);
    }
  };

  return (
    <div>
      <div className="mb-8 flex items-end justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-foreground">Live Calls</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Negotiations in progress. Tap play to review recordings.
          </p>
        </div>
        <div className="text-sm text-muted-foreground">
          {calls.filter((c) => c.status === "calling").length} in progress ·{" "}
          {calls.filter((c) => c.status === "completed").length} completed
        </div>
      </div>

      {loading ? (
        <p className="text-sm text-muted-foreground">Loading calls…</p>
      ) : (
        <div className="overflow-hidden rounded-lg border border-border bg-card">
          <table className="w-full text-sm">
            <thead className="bg-secondary text-secondary-foreground">
              <tr>
                <th className="px-4 py-3 text-left font-medium">Company</th>
                <th className="px-4 py-3 text-left font-medium">Negotiation style</th>
                <th className="px-4 py-3 text-left font-medium">Status</th>
                <th className="px-4 py-3 text-left font-medium">Duration</th>
                <th className="px-4 py-3 text-right font-medium">Recording</th>
              </tr>
            </thead>
            <tbody>
              {calls.map((c) => (
                <tr key={c.company_id} className="border-t border-border">
                  <td className="px-4 py-3 font-medium text-foreground">{c.company}</td>
                  <td className="px-4 py-3">
                    <span
                      className={`inline-flex rounded-full border px-2.5 py-0.5 text-xs font-medium capitalize ${styleBadge[c.style]}`}
                    >
                      {c.style}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`inline-flex items-center gap-2 rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${statusBadge[c.status]}`}
                    >
                      <StatusDot status={c.status} />
                      {c.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-muted-foreground">{c.duration}</td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={() => onPlay(c)}
                      disabled={c.status !== "completed" || loadingQuote === c.company_id}
                      className="inline-flex items-center gap-1.5 rounded-md border border-input bg-background px-3 py-1.5 text-xs font-medium text-foreground hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
                        <path d="M8 5v14l11-7z" />
                      </svg>
                      {loadingQuote === c.company_id ? "Loading…" : "Play"}
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
              <div className="mt-1 text-lg font-semibold text-foreground">{selected.company}</div>
            </div>
            <button
              onClick={() => setSelected(null)}
              className="text-xs text-muted-foreground hover:text-foreground"
            >
              Close
            </button>
          </div>
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <div>
              <div className="text-xs font-medium text-muted-foreground">Differentiators</div>
              <ul className="mt-1 list-disc pl-5 text-sm text-foreground">
                {selected.differentiators.map((d, i) => (
                  <li key={i}>{d}</li>
                ))}
              </ul>
            </div>
            <div>
              <div className="text-xs font-medium text-muted-foreground">Total quote</div>
              <div className="mt-1 text-2xl font-bold text-foreground">
                ${selected.total.toLocaleString()}
              </div>
              {selected.red_flag && (
                <div className="mt-2 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
                  {selected.red_flag}
                </div>
              )}
            </div>
          </div>
          <div className="mt-4 flex gap-3 text-sm">
            <a href={selected.transcript_url} className="text-primary underline-offset-2 hover:underline">
              View transcript
            </a>
            <a href={selected.recording_url} className="text-primary underline-offset-2 hover:underline">
              Listen to recording
            </a>
          </div>
        </div>
      )}
    </div>
  );
}
