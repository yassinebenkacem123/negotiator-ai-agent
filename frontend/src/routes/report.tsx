import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { getResults, type RankedCompany, type Report } from "@/lib/api";

export const Route = createFileRoute("/report")({
  head: () => ({
    meta: [
      { title: "Report — The Negotiator" },
      { name: "description", content: "Ranked quotes and a recommended deal." },
    ],
  }),
  component: ReportPage,
});

function currency(n: number) {
  return n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
}

function Row({ quote }: { quote: RankedCompany }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <tr className={`border-t border-border ${quote.recommended ? "bg-accent/40" : ""}`}>
        <td className="px-4 py-3 text-sm font-mono text-muted-foreground">#{quote.rank}</td>
        <td className="px-4 py-3">
          <div className="font-medium text-foreground">{quote.company}</div>
          {quote.recommended && (
            <div className="mt-0.5 text-xs font-medium text-primary">Recommended</div>
          )}
        </td>
        <td className="px-4 py-3 font-semibold text-foreground">{currency(quote.total)}</td>
        <td className="px-4 py-3">
          {quote.red_flag ? (
            <span className="inline-flex items-center gap-1 rounded-full border border-destructive/30 bg-destructive/10 px-2.5 py-0.5 text-xs font-medium text-destructive">
              Red flag
            </span>
          ) : (
            <span className="text-xs text-muted-foreground">—</span>
          )}
        </td>
        <td className="px-4 py-3 text-right">
          <div className="inline-flex gap-2">
            <a
              href={quote.transcript_url}
              className="rounded-md border border-input bg-background px-3 py-1.5 text-xs font-medium text-foreground hover:bg-accent"
            >
              Transcript
            </a>
            <button
              onClick={() => setOpen((o) => !o)}
              className="rounded-md border border-input bg-background px-3 py-1.5 text-xs font-medium text-foreground hover:bg-accent"
            >
              {open ? "Hide fees" : "Itemized fees"}
            </button>
          </div>
        </td>
      </tr>
      {open && (
        <tr className="border-t border-border bg-secondary/40">
          <td />
          <td colSpan={4} className="px-4 py-3">
            {quote.red_flag && (
              <div className="mb-3 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
                <span className="font-semibold">Why the red flag:</span> {quote.red_flag}
              </div>
            )}
            {quote.differentiators.length > 0 && (
              <div className="mb-3 flex flex-wrap gap-1.5">
                {quote.differentiators.map((d, i) => (
                  <span
                    key={i}
                    className="inline-flex rounded-full border border-border bg-background px-2 py-0.5 text-xs text-muted-foreground"
                  >
                    {d}
                  </span>
                ))}
              </div>
            )}
            <table className="w-full text-sm">
              <tbody>
                {quote.fees.map((f, i) => (
                  <tr key={i} className="border-b border-border/60 last:border-0">
                    <td className="py-1.5 text-muted-foreground">{f.label}</td>
                    <td className="py-1.5 text-right font-mono text-foreground">{currency(f.amount)}</td>
                  </tr>
                ))}
                <tr>
                  <td className="pt-2 text-sm font-semibold text-foreground">Total</td>
                  <td className="pt-2 text-right font-mono font-semibold text-foreground">
                    {currency(quote.total)}
                  </td>
                </tr>
              </tbody>
            </table>
          </td>
        </tr>
      )}
    </>
  );
}

function ReportPage() {
  const [report, setReport] = useState<Report | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const id =
      (typeof window !== "undefined" && window.localStorage.getItem("negotiator.job_spec_id")) ||
      "spec_demo";
    getResults(id)
      .then(setReport)
      .finally(() => setLoading(false));
  }, []);

  if (loading || !report) {
    return (
      <div>
        <h1 className="text-3xl font-bold tracking-tight text-foreground">Report</h1>
        <p className="mt-4 text-sm text-muted-foreground">Loading quotes…</p>
      </div>
    );
  }

  const recommended = report.ranked_companies.find((c) => c.recommended) ?? report.ranked_companies[0];

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-3xl font-bold tracking-tight text-foreground">Report</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Ranked quotes from {report.ranked_companies.length} movers, negotiated on your behalf.
        </p>
      </div>

      <div className="mb-8 rounded-xl border border-primary/30 bg-gradient-to-br from-accent to-secondary p-6">
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-primary">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 2l2.6 6.9L22 10l-5.5 4.8L18.2 22 12 18.3 5.8 22l1.7-7.2L2 10l7.4-1.1L12 2z" />
          </svg>
          Recommended Deal
        </div>
        <div className="mt-2 flex flex-wrap items-baseline gap-3">
          <div className="text-2xl font-bold text-foreground">{recommended.company}</div>
          <div className="text-2xl font-bold text-primary">{currency(recommended.total)}</div>
        </div>
        <p className="mt-3 max-w-3xl text-sm text-foreground/80">{report.summary}</p>
      </div>

      <div className="overflow-hidden rounded-lg border border-border bg-card">
        <table className="w-full text-sm">
          <thead className="bg-secondary text-secondary-foreground">
            <tr>
              <th className="px-4 py-3 text-left font-medium">Rank</th>
              <th className="px-4 py-3 text-left font-medium">Company</th>
              <th className="px-4 py-3 text-left font-medium">Total</th>
              <th className="px-4 py-3 text-left font-medium">Flags</th>
              <th className="px-4 py-3 text-right font-medium">Details</th>
            </tr>
          </thead>
          <tbody>
            {report.ranked_companies.map((q) => (
              <Row key={q.company_id} quote={q} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
