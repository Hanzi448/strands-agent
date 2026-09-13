import { useEffect } from "react";
import { PhoneOff } from "lucide-react";

import { Button } from "@/shared/components/ui/button";
import type { Clinic } from "../lib/clinics";
import { useVoiceCall } from "../useVoiceCall";
import { TranscriptPanel } from "./TranscriptPanel";
import { VoiceOrb, type OrbStatus } from "./VoiceOrb";

interface VoiceScreenProps {
  clinic: Clinic;
  onExit: () => void;
}

export function VoiceScreen({ clinic, onExit }: VoiceScreenProps) {
  const call = useVoiceCall(clinic.id);

  // Connect when the screen opens, tear down when it closes. Both are
  // stable useCallbacks, so this runs once per mount.
  useEffect(() => {
    void call.connect();
    return () => call.disconnect();
  }, [call.connect, call.disconnect]);

  // The mic is live for the whole call, so "listening" is the ambient
  // state — the agent speaking is the thing worth showing when both
  // are true (the greeting, an answer).
  const orbStatus: OrbStatus = call.errorMessage !== null
    ? "error"
    : !call.isConnected
      ? "connecting"
      : call.isSpeaking
        ? "speaking"
        : call.isRecording
          ? "listening"
          : "ready";

  const handleOrbClick = () => {
    if (call.isRecording) call.stopRecording();
    else void call.startRecording();
  };

  return (
    <div className="flex min-h-screen flex-col bg-[var(--bg-base)]">
      <header className="flex items-center justify-between border-b border-[var(--border-default)] bg-[var(--bg-surface)] px-4 py-2">
        <span className="font-sans text-sm font-medium text-[var(--text-primary)]">
          {clinic.name}
        </span>
        <Button variant="ghost" size="sm" onClick={onExit}>
          <PhoneOff className="h-4 w-4" />
          End call
        </Button>
      </header>
      <main className="flex flex-1 flex-col items-center justify-center gap-8 px-4 py-8">
        <VoiceOrb status={orbStatus} onClick={handleOrbClick} />
        {call.errorMessage !== null && (
          <p className="max-w-md text-center text-sm text-[var(--state-error)]">
            {call.errorMessage}
          </p>
        )}
        <TranscriptPanel turns={call.transcript.turns} live={call.transcript.live} />
      </main>
    </div>
  );
}
