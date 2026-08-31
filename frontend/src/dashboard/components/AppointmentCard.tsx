import { useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";

import { Card, CardContent } from "@/shared/components/ui/card";
import { Badge } from "@/shared/components/ui/badge";
import type { Appointment, AppointmentStatus } from "@/dashboard/types";

const STATUS_BADGE: Record<AppointmentStatus, { label: string; variant: "success" | "neutral" | "warning" | "error" }> = {
  scheduled: { label: "Scheduled", variant: "success" },
  completed: { label: "Completed", variant: "neutral" },
  cancelled: { label: "Cancelled", variant: "neutral" },
  no_show: { label: "No-show", variant: "error" },
};

function localTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

/** The agent's own moves on this appointment -- `project-overview.md` ->
 * Staff Dashboard: "View a simple log of autonomous actions the agent has
 * taken." Kept inline per appointment rather than as a separate page:
 * `architecture.md` -> Storage Model already derives the log from exactly
 * these two lists, and every entry here already belongs to the
 * appointment it is shown under. */
function AgentActivity({ appointment }: { appointment: Appointment }) {
  const moves = appointment.reschedule_history.filter((entry) => entry.actor === "agent");
  const reminders = appointment.reminders;
  if (moves.length === 0 && reminders.length === 0) return null;

  return (
    <ul className="mt-2 flex flex-col gap-1 border-t border-[var(--border-default)] pt-2 text-xs text-[var(--text-muted)]">
      {reminders.map((entry, i) => (
        <li key={`reminder-${i}`}>
          {localTime(entry.at)} — reminder {entry.outcome === "sent" ? "sent" : "failed to send"}
        </li>
      ))}
      {moves.map((entry, i) => (
        <li key={`move-${i}`}>
          {localTime(entry.at)} —{" "}
          {entry.to === null
            ? "agent cancelled this appointment"
            : `agent rescheduled to ${localTime(entry.to)}`}
          {entry.reason ? ` (${entry.reason})` : ""}
        </li>
      ))}
    </ul>
  );
}

export function AppointmentCard({ appointment }: { appointment: Appointment }) {
  const [expanded, setExpanded] = useState(false);
  const status = STATUS_BADGE[appointment.status];
  const hasActivity =
    appointment.reminders.length > 0 ||
    appointment.reschedule_history.some((entry) => entry.actor === "agent");

  return (
    <Card>
      <CardContent className="flex flex-col gap-2 p-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-sm font-semibold text-[var(--text-primary)]">
              {appointment.patient_name}
            </p>
            <p className="text-xs text-[var(--text-muted)]">
              {localTime(appointment.starts_at)} – {localTime(appointment.ends_at)} ·{" "}
              {appointment.service}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant={status.variant}>{status.label}</Badge>
            {hasActivity && (
              <button
                type="button"
                aria-label="Toggle agent activity"
                className="text-[var(--text-muted)] hover:text-[var(--text-primary)]"
                onClick={() => setExpanded((v) => !v)}
              >
                {expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
              </button>
            )}
          </div>
        </div>
        {appointment.notes && (
          <p className="text-xs text-[var(--text-muted)]">{appointment.notes}</p>
        )}
        {expanded && <AgentActivity appointment={appointment} />}
      </CardContent>
    </Card>
  );
}
