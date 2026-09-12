import { useEffect, useRef } from "react";

import type { LiveTranscript, TranscriptTurn } from "../lib/transcriptReducer";

interface TranscriptPanelProps {
  turns: readonly TranscriptTurn[];
  live: LiveTranscript | null;
}

const speakerLabel = (role: "user" | "assistant"): string =>
  role === "user" ? "You: " : "Clinic: ";

export function TranscriptPanel({ turns, live }: TranscriptPanelProps) {
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "nearest" });
  }, [turns, live]);

  return (
    <div
      aria-live="polite"
      className="max-h-64 w-full max-w-xl overflow-y-auto rounded-xl border border-[var(--border-default)] bg-[var(--bg-surface)] px-4 py-3"
    >
      {turns.length === 0 && live === null && (
        <p className="text-sm text-[var(--text-muted)]">
          Your conversation will appear here.
        </p>
      )}
      {turns.map((turn, index) => (
        <p
          key={index}
          className={
            turn.role === "user"
              ? "text-sm text-[var(--text-muted)]"
              : "text-sm text-[var(--text-primary)]"
          }
        >
          <span className="font-medium">{speakerLabel(turn.role)}</span>
          {turn.text}
        </p>
      ))}
      {live !== null && (
        <p className="text-sm italic text-[var(--text-muted)]">
          <span className="font-medium not-italic">{speakerLabel(live.role)}</span>
          {live.text}
        </p>
      )}
      <div ref={endRef} />
    </div>
  );
}
