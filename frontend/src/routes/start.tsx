import { createFileRoute, Link } from "@tanstack/react-router";
import { motion } from "framer-motion";
import { Mic, FileEdit, ArrowRight } from "lucide-react";

export const Route = createFileRoute("/start")({
  head: () => ({
    meta: [
      { title: "Get Started — The Negotiator" },
      { name: "description", content: "Choose how you'd like to describe your move." },
    ],
  }),
  component: StartPage,
});

const cardVariants = {
  hidden: { opacity: 0, y: 20 },
  show: (delay = 0) => ({
    opacity: 1,
    y: 0,
    transition: { duration: 0.5, delay, ease: [0.22, 1, 0.36, 1] },
  }),
};

function StartPage() {
  return (
    <div className="py-10">
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} className="max-w-2xl">
        <h1 className="text-3xl font-bold tracking-tight text-foreground sm:text-4xl">
          How do you want to tell us about your move?
        </h1>
        <p className="mt-3 text-muted-foreground">
          Either way, you'll review and confirm the details before we call a single mover.
        </p>
      </motion.div>

      <div className="mt-10 grid gap-6 sm:grid-cols-2">
        <motion.div custom={0.1} initial="hidden" animate="show" variants={cardVariants}>
          <Link to="/voice" className="group block h-full">
            <motion.div
              whileHover={{ y: -6, boxShadow: "0 12px 32px -12px rgb(0 0 0 / 0.18)" }}
              className="relative flex h-full flex-col overflow-hidden rounded-xl border border-border bg-card p-7"
            >
              <div className="absolute -right-8 -top-8 h-32 w-32 rounded-full bg-primary/10 transition-transform duration-500 group-hover:scale-125" />
              <div className="relative flex h-12 w-12 items-center justify-center rounded-full bg-primary/10 text-primary">
                <Mic className="h-6 w-6" />
              </div>
              <h2 className="relative mt-5 text-xl font-semibold text-foreground">Voice Intake</h2>
              <p className="relative mt-2 flex-1 text-sm text-muted-foreground">
                Talk it through with our AI estimator like you would with a real moving
                consultant. We'll transcribe the call and build your spec automatically —
                you review it before anything is confirmed.
              </p>
              <div className="relative mt-6 inline-flex items-center gap-1.5 text-sm font-medium text-primary">
                Start talking
                <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
              </div>
            </motion.div>
          </Link>
        </motion.div>

        <motion.div custom={0.2} initial="hidden" animate="show" variants={cardVariants}>
          <Link to="/confirm" className="group block h-full">
            <motion.div
              whileHover={{ y: -6, boxShadow: "0 12px 32px -12px rgb(0 0 0 / 0.18)" }}
              className="relative flex h-full flex-col overflow-hidden rounded-xl border border-border bg-card p-7"
            >
              <div className="absolute -right-8 -top-8 h-32 w-32 rounded-full bg-primary/10 transition-transform duration-500 group-hover:scale-125" />
              <div className="relative flex h-12 w-12 items-center justify-center rounded-full bg-primary/10 text-primary">
                <FileEdit className="h-6 w-6" />
              </div>
              <h2 className="relative mt-5 text-xl font-semibold text-foreground">
                Form + Document
              </h2>
              <p className="relative mt-2 flex-1 text-sm text-muted-foreground">
                Fill in the details yourself, and optionally upload a photo or PDF of an
                existing quote or inventory list — we'll pre-fill what we can read from it.
              </p>
              <div className="relative mt-6 inline-flex items-center gap-1.5 text-sm font-medium text-primary">
                Open the form
                <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
              </div>
            </motion.div>
          </Link>
        </motion.div>
      </div>
    </div>
  );
}
