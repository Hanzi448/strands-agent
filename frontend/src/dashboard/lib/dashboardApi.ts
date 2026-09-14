import { apiRequest } from "@/shared/lib/api";
import { getIdToken } from "@/dashboard/lib/auth";
import type { ClinicConfig, ClinicConfigPayload } from "@/dashboard/lib/settingsForm";
import type { AppointmentsForDay, Escalation } from "@/dashboard/types";

/**
 * One function per route of `backend/lambda/dashboard_api.py`'s
 * `_ROUTES` -- `code-standards.md` -> TypeScript/React: "`dashboard/`
 * components own REST calls to the dashboard API". `clinic_id` is never a
 * parameter here: every route derives it from the caller's own Cognito
 * token server-side (`architecture.md` -> Auth and Access Model), so
 * there is nothing for this client to pass or for a compromised frontend
 * to override.
 */

const baseUrl = import.meta.env.VITE_DASHBOARD_API_URL;

async function authorizedRequest<T>(
  path: string,
  options: {
    method?: "GET" | "POST" | "PUT";
    query?: Record<string, string | number | undefined>;
    body?: unknown;
  } = {},
): Promise<T> {
  const token = await getIdToken();
  if (!token) {
    throw new Error("Not signed in.");
  }
  return apiRequest<T>({ baseUrl, path, token, ...options });
}

/** `GET /appointments` -- one clinic-local day's appointments, any status.
 * Omit `date` for the clinic's current local day. */
export function listAppointments(date?: string): Promise<AppointmentsForDay> {
  return authorizedRequest<AppointmentsForDay>("/appointments", { query: { date } });
}

/** `GET /escalations` -- the open-escalation queue, newest first. */
export function listEscalations(): Promise<Escalation[]> {
  return authorizedRequest<Escalation[]>("/escalations");
}

/** `GET /escalations/{escalation_id}` -- one escalation's full detail, for
 * the dashboard's detail modal. */
export function getEscalation(escalationId: string): Promise<Escalation> {
  return authorizedRequest<Escalation>(
    `/escalations/${encodeURIComponent(escalationId)}`,
  );
}

/** `POST /escalations/{escalation_id}/resolve` -- the "Mark Resolved"
 * action. Not idempotent server-side: resolving twice raises, which
 * surfaces here as a rejected promise. */
export function resolveEscalation(escalationId: string): Promise<Escalation> {
  return authorizedRequest<Escalation>(
    `/escalations/${encodeURIComponent(escalationId)}/resolve`,
    { method: "POST" },
  );
}

/** `GET /settings` -- the clinic config the Settings tab edits. */
export function getClinicConfig(): Promise<ClinicConfig> {
  return authorizedRequest<ClinicConfig>("/settings");
}

/** `PUT /settings` -- save the edited config. Full replacement: the
 * server validates every field (`tools.clinics.update_clinic_config`)
 * and refuses the whole save on any malformed one, so a rejected
 * promise carries the field-level message to show next to the form. */
export function updateClinicConfig(config: ClinicConfigPayload): Promise<ClinicConfig> {
  return authorizedRequest<ClinicConfig>("/settings", {
    method: "PUT",
    body: config,
  });
}
