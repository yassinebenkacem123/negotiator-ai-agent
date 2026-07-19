import { createFileRoute, Link } from "@tanstack/react-router";
import { motion } from "framer-motion";
import { useRef, useState } from "react";
import { Mic, FileUp, CheckCircle2, Loader2 } from "lucide-react";
import { createSpecFromVoice, enrichSpecFromDocument, updateSpec, confirmSpec, findMovers, type JobSpec } from "@/lib/api";

export const Route = createFileRoute("/voice")({
  head: () => ({
    meta: [
      { title: "Voice Intake — The Negotiator" },
      { name: "description", content: "Describe your move by voice, then review before we call movers." },
    ],
  }),
  component: VoicePage,
});

type Step = "call" | "loading" | "review" | "confirmed";

const inputCls =
  "mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring";

function Label({ children }: { children: React.ReactNode }) {
  return <label className="text-sm font-medium text-foreground">{children}</label>;
}

function VoicePage() {
  const [step, setStep] = useState<Step>("call");
  const [transcript, setTranscript] = useState("");
  const [spec, setSpec] = useState<JobSpec | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [enriching, setEnriching] = useState(false);
  const [documentAdded, setDocumentAdded] = useState(false);
  const [discoveryStatus, setDiscoveryStatus] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const set = <K extends keyof JobSpec>(k: K, v: JobSpec[K]) =>
    setSpec((s) => (s ? { ...s, [k]: v } : s));

  const submitTranscript = async () => {
    if (!transcript.trim()) return;
    setError(null);
    setStep("loading");
    try {
      const created = await createSpecFromVoice(transcript);
      setSpec(created);
      if (typeof window !== "undefined") {
        window.localStorage.setItem("negotiator.job_spec_id", created.job_spec_id);
      }
      setStep("review");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
      setStep("call");
    }
  };

  const onDocumentChosen = async (file: File) => {
    if (!spec) return;
    setEnriching(true);
    try {
      const enriched = await enrichSpecFromDocument(spec.job_spec_id, file);
      setSpec(enriched);
      setDocumentAdded(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't read that document.");
    } finally {
      setEnriching(false);
    }
  };

  const onConfirm = async () => {
    if (!spec) return;
    setError(null);
    try {
      await updateSpec(spec.job_spec_id, spec);
      const confirmed = await confirmSpec(spec.job_spec_id);
      try {
        const discovery = await findMovers(spec.job_spec_id);
        setDiscoveryStatus(`Found ${discovery.leads.length} movers near your origin.`);
      } catch (err) {
        setDiscoveryStatus(err instanceof Error ? err.message : "Mover discovery failed.");
      }
      setSpec(confirmed);
      setStep("confirmed");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong confirming your spec.");
    }
  };

  return (
    <div className="py-10">
      <>
        {step === "call" && (
          <motion.div
            key="call"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -12 }}
            transition={{ duration: 0.3 }}
            className="max-w-xl"
          >
            <div className="flex items-center gap-3">
              <motion.div
                animate={{ scale: [1, 1.08, 1] }}
                transition={{ duration: 1.8, repeat: Infinity, ease: "easeInOut" }}
                className="flex h-12 w-12 items-center justify-center rounded-full bg-primary/10 text-primary"
              >
                <Mic className="h-6 w-6" />
              </motion.div>
              <div>
                <h1 className="text-2xl font-bold tracking-tight text-foreground">Voice Intake</h1>
                <p className="text-sm text-muted-foreground">
                  The live call widget goes here — talk it through with our AI estimator.
                </p>
              </div>
            </div>

            <div className="mt-6 rounded-lg border border-dashed border-border bg-card p-6">
              <p className="text-sm text-muted-foreground">
                <span className="font-medium text-foreground">Standing in for the live call:</span>{" "}
                paste or type a transcript below to try the review flow end to end. Once the real
                voice call is wired up, this box is replaced by the live conversation.
              </p>
              <textarea
                className={`${inputCls} mt-3 min-h-[160px] font-mono text-xs`}
                placeholder="Agent: Hi, I'm calling to help build your moving estimate. Where are you moving from?..."
                value={transcript}
                onChange={(e) => setTranscript(e.target.value)}
              />
              {error && <p className="mt-2 text-sm text-destructive">{error}</p>}
              <button
                onClick={submitTranscript}
                disabled={!transcript.trim()}
                className="mt-4 inline-flex items-center gap-2 rounded-md bg-primary px-5 py-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
              >
                Build my spec from this transcript
              </button>
            </div>
          </motion.div>
        )}

        {step === "loading" && (
          <motion.div
            key="loading"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="flex flex-col items-center justify-center py-24 text-center"
          >
            <motion.div animate={{ rotate: 360 }} transition={{ duration: 1, repeat: Infinity, ease: "linear" }}>
              <Loader2 className="h-8 w-8 text-primary" />
            </motion.div>
            <p className="mt-4 text-sm text-muted-foreground">Listening back and building your spec…</p>
          </motion.div>
        )}

        {step === "review" && spec && (
          <motion.div
            key="review"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -12 }}
            transition={{ duration: 0.3 }}
          >
            <h1 className="text-2xl font-bold tracking-tight text-foreground">Review your spec</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Here's what we heard. Fix anything that's wrong before we start calling movers.
            </p>

            <details className="mt-6 rounded-lg border border-border bg-card">
              <summary className="cursor-pointer px-4 py-3 text-sm font-medium text-foreground">
                Call transcript
              </summary>
              <div className="max-h-56 overflow-y-auto whitespace-pre-wrap border-t border-border p-4 font-mono text-xs text-muted-foreground">
                {spec.intake_transcript}
              </div>
            </details>

            <div className="mt-6 space-y-4 rounded-lg border border-border bg-card p-6">
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="sm:col-span-2">
                  <Label>Origin Address</Label>
                  <input className={inputCls} value={spec.origin_address} onChange={(e) => set("origin_address", e.target.value)} />
                </div>
                <div className="sm:col-span-2">
                  <Label>Destination Address</Label>
                  <input className={inputCls} value={spec.destination_address} onChange={(e) => set("destination_address", e.target.value)} />
                </div>
                <div>
                  <Label>Move Date</Label>
                  <input type="date" className={inputCls} value={spec.move_date} onChange={(e) => set("move_date", e.target.value)} />
                </div>
                <div>
                  <Label>Number of Trips</Label>
                  <input type="number" min={0} className={inputCls} value={spec.num_trips} onChange={(e) => set("num_trips", Number(e.target.value))} />
                </div>
                <div>
                  <Label>Number of Bags</Label>
                  <input type="number" min={0} className={inputCls} value={spec.num_bags} onChange={(e) => set("num_bags", Number(e.target.value))} />
                </div>
                <div>
                  <Label>Origin Floor (0 = ground)</Label>
                  <input type="number" min={0} className={inputCls} value={spec.origin_floor} onChange={(e) => set("origin_floor", Number(e.target.value))} />
                </div>
                <div className="sm:col-span-2">
                  <Label>Notes</Label>
                  <textarea className={`${inputCls} min-h-[80px]`} value={spec.notes ?? ""} onChange={(e) => set("notes", e.target.value)} />
                </div>
              </div>
            </div>

            <div className="mt-4 rounded-lg border border-dashed border-border bg-card p-5">
              <div className="flex items-center gap-2">
                <FileUp className="h-4 w-4 text-primary" />
                <span className="text-sm font-medium text-foreground">Add a document</span>
                <span className="inline-flex items-center rounded-full bg-accent px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-primary">
                  Optional
                </span>
              </div>
              <p className="mt-1 text-sm text-muted-foreground">
                Got an existing quote or inventory list? Upload it to fill in anything the call
                missed — or skip this and confirm below as-is, nothing here is required.
              </p>
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*,application/pdf"
                className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) onDocumentChosen(file);
                }}
              />
              <button
                onClick={() => fileInputRef.current?.click()}
                disabled={enriching}
                className="mt-3 inline-flex items-center gap-2 rounded-md border border-input bg-background px-4 py-2 text-sm font-medium text-foreground hover:bg-accent disabled:opacity-60"
              >
                {enriching ? "Reading document…" : documentAdded ? "Add another document" : "Upload a document"}
              </button>
              {documentAdded && (
                <motion.p initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="mt-2 text-sm text-primary">
                  Document details merged in below.
                </motion.p>
              )}
            </div>

            {error && <p className="mt-4 text-sm text-destructive">{error}</p>}

            <div className="mt-6 flex justify-end">
              <button
                onClick={onConfirm}
                className="inline-flex items-center gap-2 rounded-md bg-primary px-6 py-3 text-sm font-semibold text-primary-foreground hover:bg-primary/90"
              >
                Confirm spec & find movers
              </button>
            </div>
          </motion.div>
        )}

        {step === "confirmed" && spec && (
          <motion.div
            key="confirmed"
            initial={{ opacity: 0, scale: 0.96 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
            className="flex flex-col items-center py-20 text-center"
          >
            <motion.div
              initial={{ scale: 0 }}
              animate={{ scale: 1 }}
              transition={{ delay: 0.1, type: "spring", stiffness: 200, damping: 12 }}
            >
              <CheckCircle2 className="h-16 w-16 text-primary" />
            </motion.div>
            <h1 className="mt-4 text-2xl font-bold text-foreground">Spec confirmed</h1>
            <p className="mt-2 max-w-md text-sm text-muted-foreground">
              The Negotiator has your confirmed spec. Job ID:{" "}
              <span className="font-mono">{spec.job_spec_id}</span>
            </p>
            {discoveryStatus && <p className="mt-2 text-sm text-muted-foreground">{discoveryStatus}</p>}
            <div className="mt-6 flex gap-3">
              <Link to="/calls" className="rounded-md bg-primary px-5 py-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/90">
                Watch live calls
              </Link>
              <Link to="/report" className="rounded-md border border-input bg-background px-5 py-2.5 text-sm font-medium text-foreground hover:bg-accent">
                Go to report
              </Link>
            </div>
          </motion.div>
        )}
      </>
    </div>
  );
}
