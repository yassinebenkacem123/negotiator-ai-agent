import { createFileRoute, Link } from "@tanstack/react-router";

export const Route = createFileRoute("/")({
  component: Index,
});

function Index() {
  return (
    <div className="py-12">
      <div className="max-w-2xl">
        <span className="inline-block rounded-full bg-accent px-3 py-1 text-xs font-medium text-primary">
          AI-powered move negotiations
        </span>
        <h1 className="mt-4 text-4xl font-bold tracking-tight text-foreground sm:text-5xl">
          Let The Negotiator get you the best moving deal.
        </h1>
        <p className="mt-4 text-lg text-muted-foreground">
          Confirm your job spec, and we'll call moving companies, negotiate on your behalf,
          and hand you a ranked report with a recommended deal.
        </p>
        <div className="mt-8 flex flex-wrap gap-3">
          <Link
            to="/confirm"
            className="inline-flex items-center justify-center rounded-md bg-primary px-5 py-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            Start with your spec
          </Link>
          <Link
            to="/report"
            className="inline-flex items-center justify-center rounded-md border border-input bg-background px-5 py-2.5 text-sm font-medium text-foreground hover:bg-accent"
          >
            See sample report
          </Link>
        </div>
      </div>

      <div className="mt-16 grid gap-4 sm:grid-cols-3">
        {[
          { n: "1", t: "Confirm spec", d: "Review and edit your move details." },
          { n: "2", t: "We call", d: "Live negotiation with each mover." },
          { n: "3", t: "Pick a deal", d: "Ranked quotes with a clear recommendation." },
        ].map((s) => (
          <div key={s.n} className="rounded-lg border border-border bg-card p-5">
            <div className="text-sm font-mono text-accent-foreground/70">Step {s.n}</div>
            <div className="mt-1 font-semibold text-foreground">{s.t}</div>
            <div className="mt-1 text-sm text-muted-foreground">{s.d}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
