import { createFileRoute } from "@tanstack/react-router";
import { createElement, useEffect } from "react";

const ELEVENLABS_SCRIPT_SRC = "https://elevenlabs.io/convai-widget/index.js";
const ELEVENLABS_AGENT_ID = "agent_1301kxwfxc93e9nsct5kdekedv8x";

export const Route = createFileRoute("/voice-intake")({
  head: () => ({
    meta: [
      { title: "Voice Intake — The Negotiator" },
      { name: "description", content: "Start your move with a quick voice conversation with our AI assistant." },
    ],
  }),
  component: VoiceIntakePage,
});

function VoiceIntakePage() {
  useEffect(() => {
    if (typeof document === "undefined") return;
    if (document.querySelector(`script[src="${ELEVENLABS_SCRIPT_SRC}"]`)) return;

    const s = document.createElement("script");
    s.src = ELEVENLABS_SCRIPT_SRC;
    s.async = true;
    document.body.appendChild(s);
  }, []);

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-3xl font-bold tracking-tight text-foreground">Voice Intake</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Tell our AI assistant about your move. It will build your spec and send it to The Negotiator.
        </p>
      </div>

      <div className="rounded-lg border border-border bg-card p-6">
        <div className="mb-4">
          <h2 className="text-lg font-semibold text-foreground">Talk to our assistant</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Allow microphone access when prompted. The conversation is handled by the widget below.
          </p>
        </div>
        <div className="mt-4">
          {createElement("elevenlabs-convai", { "agent-id": ELEVENLABS_AGENT_ID })}
        </div>
      </div>
    </div>
  );
}
