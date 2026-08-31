import { CalendarDays, AlertTriangle, Settings } from "lucide-react";

import { cn } from "@/shared/lib/utils";

export type DashboardTab = "appointments" | "escalations" | "settings";

const NAV_ITEMS: { tab: DashboardTab; label: string; icon: typeof CalendarDays }[] = [
  { tab: "appointments", label: "Appointments", icon: CalendarDays },
  { tab: "escalations", label: "Escalations", icon: AlertTriangle },
  { tab: "settings", label: "Settings", icon: Settings },
];

interface SidebarProps {
  active: DashboardTab;
  onSelect: (tab: DashboardTab) => void;
}

/** `ui-context.md` -> Layout Patterns: "Staff dashboard: left sidebar
 * (navigation: Appointments, Escalations, Settings) + main content area". */
export function Sidebar({ active, onSelect }: SidebarProps) {
  return (
    <nav className="flex w-56 shrink-0 flex-col gap-1 border-r border-[var(--border-default)] bg-[var(--bg-surface)] p-3">
      {NAV_ITEMS.map(({ tab, label, icon: Icon }) => (
        <button
          key={tab}
          type="button"
          onClick={() => onSelect(tab)}
          className={cn(
            "flex items-center gap-2 rounded-md px-3 py-2 text-left text-sm font-medium transition-colors",
            active === tab
              ? "bg-[var(--bg-accent-primary-wash)] text-[var(--accent-primary)]"
              : "text-[var(--text-muted)] hover:bg-[var(--bg-base)] hover:text-[var(--text-primary)]",
          )}
        >
          <Icon className="h-5 w-5" />
          {label}
        </button>
      ))}
    </nav>
  );
}
