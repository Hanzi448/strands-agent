import { LogOut } from "lucide-react";

import { Button } from "@/shared/components/ui/button";
import type { StaffUser } from "@/dashboard/lib/auth";

interface TopBarProps {
  user: StaffUser;
  onSignOut: () => void;
}

/** `ui-context.md` -> Layout Patterns: "top bar with clinic name and
 * logged-in user". The dashboard never chooses a clinic -- the signed-in
 * account's own `custom:clinic_id` claim is all there is
 * (`architecture.md` -> Auth and Access Model), so this shows the id
 * rather than a name the API does not currently return. */
export function TopBar({ user, onSignOut }: TopBarProps) {
  return (
    <header className="flex items-center justify-between border-b border-[var(--border-default)] bg-[var(--bg-surface)] px-6 py-3">
      <div>
        <p className="text-sm font-semibold text-[var(--text-primary)]">ClinicPilot</p>
        <p className="text-xs text-[var(--text-muted)]">Clinic: {user.clinicId}</p>
      </div>
      <div className="flex items-center gap-3">
        <p className="text-sm text-[var(--text-muted)]">{user.email}</p>
        <Button variant="outline" size="sm" onClick={onSignOut}>
          <LogOut className="h-4 w-4" />
          Sign out
        </Button>
      </div>
    </header>
  );
}
