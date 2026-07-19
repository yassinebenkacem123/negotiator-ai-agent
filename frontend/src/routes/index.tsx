import { createFileRoute, Link } from "@tanstack/react-router";
import { motion } from "framer-motion";
import { Mic, FileText, Phone, ListChecks } from "lucide-react";

export const Route = createFileRoute("/")({
  component: Index,
});

const fadeUp = {
  hidden: { opacity: 0, y: 16 },
  show: (delay = 0) => ({
    opacity: 1,
    y: 0,
    transition: { duration: 0.5, delay, ease: [0.22, 1, 0.36, 1] },
  }),
};

function Index() {
  return (
    <div className="py-10">
      <motion.div
        initial="hidden"
        animate="show"
        className="max-w-2xl"
      >
        <motion.span
          custom={0}
          variants={fadeUp}
          className="inline-flex items-center gap-1.5 rounded-full bg-accent px-3 py-1 text-xs font-medium text-primary"
        >
          <span className="relative flex h-1.5 w-1.5">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-75" />
            <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-primary" />
          </span>
          AI-powered move negotiations
        </motion.span>

        <motion.h1
          custom={0.08}
          variants={fadeUp}
          className="mt-4 text-4xl font-bold tracking-tight text-foreground sm:text-5xl"
        >
          Tell us about your move.
          <br />
          <span className="text-primary">We'll get you the best deal.</span>
        </motion.h1>

        <motion.p custom={0.16} variants={fadeUp} className="mt-4 text-lg text-muted-foreground">
          Describe your move by voice or a quick form. The Negotiator calls real moving
          companies, negotiates on your behalf, and hands you a ranked report with a
          recommended deal — every fee itemized, every red flag caught.
        </motion.p>

        <motion.div custom={0.24} variants={fadeUp} className="mt-8 flex flex-wrap gap-3">
          <Link to="/start">
            <motion.span
              whileHover={{ scale: 1.03 }}
              whileTap={{ scale: 0.98 }}
              className="inline-flex items-center gap-2 rounded-md bg-primary px-6 py-3 text-sm font-semibold text-primary-foreground shadow-sm hover:bg-primary/90"
            >
              Get started
              <motion.span
                animate={{ x: [0, 4, 0] }}
                transition={{ duration: 1.4, repeat: Infinity, ease: "easeInOut" }}
              >
                →
              </motion.span>
            </motion.span>
          </Link>
          <Link
            to="/report"
            className="inline-flex items-center justify-center rounded-md border border-input bg-background px-6 py-3 text-sm font-medium text-foreground transition-colors hover:bg-accent"
          >
            See sample report
          </Link>
        </motion.div>
      </motion.div>

      <motion.div
        initial="hidden"
        whileInView="show"
        viewport={{ once: true, margin: "-80px" }}
        className="mt-20 grid gap-4 sm:grid-cols-4"
      >
        {[
          { icon: Mic, n: "1", t: "Tell us your move", d: "By voice or a quick form + document." },
          { icon: Phone, n: "2", t: "We call movers", d: "Real outbound calls, real negotiation." },
          { icon: ListChecks, n: "3", t: "We negotiate", d: "Fees itemized, red flags flagged." },
          { icon: FileText, n: "4", t: "Pick a deal", d: "Ranked quotes, clear recommendation." },
        ].map((s, i) => (
          <motion.div
            key={s.n}
            custom={i * 0.08}
            variants={fadeUp}
            whileHover={{ y: -4 }}
            className="group rounded-lg border border-border bg-card p-5 transition-shadow hover:shadow-md"
          >
            <div className="flex items-center justify-between">
              <div className="text-sm font-mono text-accent-foreground/70">Step {s.n}</div>
              <s.icon className="h-4 w-4 text-primary transition-transform group-hover:scale-110" />
            </div>
            <div className="mt-2 font-semibold text-foreground">{s.t}</div>
            <div className="mt-1 text-sm text-muted-foreground">{s.d}</div>
          </motion.div>
        ))}
      </motion.div>
    </div>
  );
}
