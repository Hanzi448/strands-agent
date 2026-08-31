import { useEffect, useState } from "react";

import { Input } from "@/shared/components/ui/input";
import { Label } from "@/shared/components/ui/label";
import { listAppointments } from "@/dashboard/lib/dashboardApi";
import type { AppointmentsForDay } from "@/dashboard/types";
import { AppointmentCard } from "@/dashboard/components/AppointmentCard";

/** `project-overview.md` -> Staff Dashboard: "View today's/upcoming
 * appointments." Defaults to the clinic's own current local day by
 * leaving `date` unset on the first load -- `list_appointments_for_clinic`
 * resolves that itself from the clinic's stored timezone, not the
 * browser's. */
export function AppointmentsView() {
  const [date, setDate] = useState<string | undefined>(undefined);
  const [day, setDay] = useState<AppointmentsForDay | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    listAppointments(date)
      .then((result) => {
        if (!cancelled) setDay(result);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [date]);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-[var(--text-primary)]">Appointments</h1>
        <div className="flex items-center gap-2">
          <Label htmlFor="appointment-date" className="text-xs text-[var(--text-muted)]">
            Day{day ? ` (${day.timezone})` : ""}
          </Label>
          <Input
            id="appointment-date"
            type="date"
            className="w-40"
            value={date ?? day?.date ?? ""}
            onChange={(e) => setDate(e.target.value)}
          />
        </div>
      </div>

      {loading && <p className="text-sm text-[var(--text-muted)]">Loading…</p>}
      {error && <p className="text-sm text-[var(--state-error)]">{error}</p>}
      {!loading && !error && day && day.appointments.length === 0 && (
        <p className="text-sm text-[var(--text-muted)]">
          No appointments on {day.date}.
        </p>
      )}
      <div className="flex flex-col gap-2">
        {day?.appointments.map((appointment) => (
          <AppointmentCard key={appointment.appointment_id} appointment={appointment} />
        ))}
      </div>
    </div>
  );
}
