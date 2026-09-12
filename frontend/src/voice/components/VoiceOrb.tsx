import { Loader2, Mic, PhoneOff, Volume2 } from "lucide-react";

import type { LucideIcon } from "lucide-react";

export type OrbStatus = "connecting" | "ready" | "listening" | "speaking" | "error";

const ORB_STYLES: Record<OrbStatus, string> = {
  connecting:
    "border-[var(--border-default)] bg-[var(--bg-surface)] text-[var(--text-muted)]",
  ready: "border-transparent bg-[var(--accent-primary)] text-[var(--bg-surface)]",
  listening:
    "border-transparent bg-[var(--accent-primary)] text-[var(--bg-surface)] animate-pulse",
  speaking: "border-transparent bg-[var(--accent-secondary)] text-[var(--bg-surface)]",
  error: "border-transparent bg-[var(--state-error)] text-[var(--bg-surface)]",
};

const ORB_LABELS: Record<OrbStatus, string> = {
  connecting: "Connecting to the clinic…",
  ready: "Tap to speak",
  listening: "Listening — tap to pause",
  speaking: "The clinic is speaking",
  error: "The call failed",
};

const ORB_ICONS: Record<OrbStatus, LucideIcon> = {
  connecting: Loader2,
  ready: Mic,
  listening: Mic,
  speaking: Volume2,
  error: PhoneOff,
};

interface VoiceOrbProps {
  status: OrbStatus;
  onClick: () => void;
}

export function VoiceOrb({ status, onClick }: VoiceOrbProps) {
  const Icon = ORB_ICONS[status];
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={status === "connecting" || status === "error"}
      aria-label={ORB_LABELS[status]}
      className={`flex h-40 w-40 items-center justify-center rounded-full border-2 transition-colors ${ORB_STYLES[status]}`}
    >
      <Icon className={`h-8 w-8 ${status === "connecting" ? "animate-spin" : ""}`} />
    </button>
  );
}
