import { useEffect, useState } from "react";

import { DashboardApp } from "@/dashboard/DashboardApp";
import { VoiceApp } from "@/voice/VoiceApp";

// `architecture.md` -> Stack: one SPA serves both the patient voice UI
// (`frontend/src/voice/`) and the staff dashboard
// (`frontend/src/dashboard/`). Hash routing keeps the split inside one
// static bundle with no router dependency and no server rewrites --
// `#/voice` is the patient surface, everything else is the dashboard.
type Surface = "dashboard" | "voice";

function surfaceFromHash(hash: string): Surface {
  return hash === "#/voice" ? "voice" : "dashboard";
}

export default function App() {
  const [surface, setSurface] = useState<Surface>(() =>
    surfaceFromHash(window.location.hash),
  );

  useEffect(() => {
    const onHashChange = () => setSurface(surfaceFromHash(window.location.hash));
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  return surface === "voice" ? <VoiceApp /> : <DashboardApp />;
}
