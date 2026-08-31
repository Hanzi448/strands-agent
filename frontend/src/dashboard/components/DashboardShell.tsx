import { useState } from "react";

import { Sidebar, type DashboardTab } from "@/dashboard/components/Sidebar";
import { TopBar } from "@/dashboard/components/TopBar";
import { AppointmentsView } from "@/dashboard/components/AppointmentsView";
import { EscalationsView } from "@/dashboard/components/EscalationsView";
import type { StaffUser } from "@/dashboard/lib/auth";

interface DashboardShellProps {
  user: StaffUser;
  onSignOut: () => void;
}

/** `ui-context.md` -> Layout Patterns: "Standard admin-dashboard layout" --
 * sidebar + top bar + content area. */
export function DashboardShell({ user, onSignOut }: DashboardShellProps) {
  const [tab, setTab] = useState<DashboardTab>("appointments");

  return (
    <div className="flex min-h-screen flex-col">
      <TopBar user={user} onSignOut={onSignOut} />
      <div className="flex flex-1">
        <Sidebar active={tab} onSelect={setTab} />
        <main className="flex-1 p-6">
          {tab === "appointments" && <AppointmentsView />}
          {tab === "escalations" && <EscalationsView />}
          {tab === "settings" && (
            <p className="text-sm text-[var(--text-muted)]">
              Nothing configurable here yet.
            </p>
          )}
        </main>
      </div>
    </div>
  );
}
