import { useState } from "react";

import { ClinicPicker } from "./components/ClinicPicker";
import { VoiceScreen } from "./components/VoiceScreen";
import type { Clinic } from "./lib/clinics";

/**
 * The patient surface: pick a clinic, then carry the call. Mounted at
 * `#/voice` (see App.tsx); the dashboard stays at `#/` and below.
 */
export function VoiceApp() {
  const [clinic, setClinic] = useState<Clinic | null>(null);

  return clinic === null ? (
    <ClinicPicker onChoose={setClinic} />
  ) : (
    <VoiceScreen clinic={clinic} onExit={() => setClinic(null)} />
  );
}
