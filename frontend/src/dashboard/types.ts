/**
 * Mirrors `backend/tools/schema.py`'s non-key attribute names and status
 * vocabularies, and the shapes `backend/lambda/dashboard_api.py`'s four
 * routes return as `data`. Kept in one file, imported everywhere in
 * `dashboard/`, so a field name only has to agree with the backend once.
 */

export type AppointmentStatus = "scheduled" | "cancelled" | "completed" | "no_show";

export type EscalationStatus = "open" | "resolved";

export type EscalationSource = "voice" | "background";

/** Who moved or cancelled an appointment (`schema.RescheduleActor`). The
 * dashboard's "log of autonomous actions" (`project-overview.md` -> Staff
 * Dashboard) is exactly the entries where this is `"agent"`. */
export type RescheduleActor = "agent" | "staff";

export type ReminderChannel = "email";

export type ReminderOutcome = "sent" | "failed";

/** One entry in an appointment's `reschedule_history`
 * (`schema.RescheduleEntry`). `to: null` marks a cancellation -- a move to
 * nowhere. */
export interface RescheduleEntry {
  at: string;
  from: string;
  to: string | null;
  actor: RescheduleActor;
  reason: string | null;
}

/** One entry in an appointment's `reminders` (`schema.ReminderEntry`). */
export interface ReminderEntry {
  at: string;
  channel: ReminderChannel;
  outcome: ReminderOutcome;
}

/** A whole `Appointments` item, as `list_appointments_for_clinic` returns
 * it (`schema.AppointmentAttrs`) -- every status, not filtered to
 * upcoming, since the dashboard's Appointments view is a clinic's whole
 * day, not one patient's future. */
export interface Appointment {
  clinic_id: string;
  appointment_id: string;
  patient_id: string;
  patient_name: string;
  service: string;
  starts_at: string;
  ends_at: string;
  status: AppointmentStatus;
  notes: string | null;
  reminders: ReminderEntry[];
  reschedule_history: RescheduleEntry[];
  created_at: string;
  updated_at: string;
}

/** `GET /appointments` response `data` (`dashboard_api._list_appointments`
 * over `tools.appointments.list_appointments_for_clinic`). */
export interface AppointmentsForDay {
  clinic_id: string;
  date: string;
  timezone: string;
  appointments: Appointment[];
}

/** A whole `Escalations` item (`schema.EscalationAttrs`). `patient_id` and
 * `appointment_id` are back-references stored unverified
 * (`tools.escalations.create_escalation`'s docstring) -- present only when
 * the escalation is about one. */
export interface Escalation {
  clinic_id: string;
  escalation_id: string;
  status: EscalationStatus;
  source: EscalationSource;
  reason: string;
  patient_id?: string;
  appointment_id?: string;
  created_at: string;
  resolved_at?: string;
}
