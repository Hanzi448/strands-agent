import { DashboardApp } from "@/dashboard/DashboardApp";

// `architecture.md` -> Stack: one SPA serves both the patient voice UI
// (`frontend/src/voice/`) and the staff dashboard (`frontend/src/dashboard/`).
// `voice/` does not exist yet (`progress-tracker.md` -> Next Up #1 is still
// blocked on a real deploy), so this entry point mounts the dashboard
// directly rather than inventing a router for a second surface that isn't
// built. Splitting the two by route is `frontend/src/voice/`'s own task.
export default function App() {
  return <DashboardApp />;
}
