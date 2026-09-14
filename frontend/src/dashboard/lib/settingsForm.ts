/**
 * Pure form-state helpers for the Settings tab
 * (`ui-context.md` -> Layout Patterns lists Settings in the dashboard's
 * sidebar). Each helper returns a *new* `ClinicConfig` with one edit
 * applied -- React needs a fresh reference to re-render, and the
 * component stays a thin shell over these, the same division the voice
 * UI's `lib/` modules draw.
 *
 * No validation lives here: the backend's
 * `tools/clinics.update_clinic_config` is the single validator
 * (`architecture.md` -> Invariants #3), and duplicating its rules in
 * the browser would only let the two drift. A refused save shows the
 * server's own message, which names the field.
 */

export const WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;

export type Weekday = (typeof WEEKDAYS)[number];

/** One opening interval, clinic-local wall-clock `HH:MM` -- the shape
 * `backend/tools/schema.py`'s `HoursInterval` fixes. */
export interface HoursInterval {
  open: string;
  close: string;
}

export type HoursMap = Record<Weekday, HoursInterval[]>;

/** One whole-day closure (`schema.ClosureAttrs`). */
export interface Closure {
  date: string;
  label: string;
}

/** One offered treatment (`schema.ServiceAttrs`). */
export interface Service {
  id: string;
  name: string;
  duration_minutes: number;
}

/** `GET /settings` response `data` (`dashboard_api._get_settings` over
 * `tools.clinics.get_clinic_config`). `name` and `timezone` are
 * display-only: set at seed time, not editable. */
export interface ClinicConfig {
  name: string;
  timezone: string;
  hours: HoursMap;
  closures: Closure[];
  services: Service[];
  slot_minutes: number;
}

/** `PUT /settings` request body (`dashboard_api._put_settings`) --
 * exactly the four editable fields. */
export type ClinicConfigPayload = Pick<
  ClinicConfig,
  "hours" | "closures" | "services" | "slot_minutes"
>;

/** What a new interval starts as: a full working day, the most common
 * edit being "we now open all day". */
export function newInterval(): HoursInterval {
  return { open: "09:00", close: "17:00" };
}

function editHours(
  config: ClinicConfig,
  weekday: Weekday,
  edit: (intervals: HoursInterval[]) => HoursInterval[],
): ClinicConfig {
  return {
    ...config,
    hours: { ...config.hours, [weekday]: edit(config.hours[weekday]) },
  };
}

/** Append a full-day interval to one weekday. */
export function addInterval(config: ClinicConfig, weekday: Weekday): ClinicConfig {
  return editHours(config, weekday, (intervals) => [...intervals, newInterval()]);
}

/** Drop the interval at `index` from one weekday. */
export function removeInterval(
  config: ClinicConfig,
  weekday: Weekday,
  index: number,
): ClinicConfig {
  return editHours(config, weekday, (intervals) =>
    intervals.filter((_, i) => i !== index),
  );
}

/** Change one end of one interval. */
export function setIntervalField(
  config: ClinicConfig,
  weekday: Weekday,
  index: number,
  field: keyof HoursInterval,
  value: string,
): ClinicConfig {
  return editHours(config, weekday, (intervals) =>
    intervals.map((interval, i) =>
      i === index ? { ...interval, [field]: value } : interval,
    ),
  );
}

/** Append a blank closure for staff to fill in. */
export function addClosure(config: ClinicConfig): ClinicConfig {
  return { ...config, closures: [...config.closures, { date: "", label: "" }] };
}

/** Patch one closure. */
export function updateClosure(
  config: ClinicConfig,
  index: number,
  patch: Partial<Closure>,
): ClinicConfig {
  return {
    ...config,
    closures: config.closures.map((closure, i) =>
      i === index ? { ...closure, ...patch } : closure,
    ),
  };
}

/** Drop the closure at `index`. */
export function removeClosure(config: ClinicConfig, index: number): ClinicConfig {
  return { ...config, closures: config.closures.filter((_, i) => i !== index) };
}

/** Append a blank service for staff to fill in; the duration starts at
 * the demo clinics' commonest value rather than 0, so a save of a
 * half-filled row fails on the empty fields, not on a zero duration. */
export function addService(config: ClinicConfig): ClinicConfig {
  return {
    ...config,
    services: [...config.services, { id: "", name: "", duration_minutes: 30 }],
  };
}

/** Patch one service. */
export function updateService(
  config: ClinicConfig,
  index: number,
  patch: Partial<Service>,
): ClinicConfig {
  return {
    ...config,
    services: config.services.map((service, i) =>
      i === index ? { ...service, ...patch } : service,
    ),
  };
}

/** Drop the service at `index`. */
export function removeService(config: ClinicConfig, index: number): ClinicConfig {
  return { ...config, services: config.services.filter((_, i) => i !== index) };
}

/** Set the slot grid. `<input type="number">` hands its value over as
 * a string; the payload needs the number. */
export function setSlotMinutes(config: ClinicConfig, value: string | number): ClinicConfig {
  return { ...config, slot_minutes: Number(value) };
}

/** The PUT body: the four editable fields, nothing read-only. */
export function toPayload(config: ClinicConfig): ClinicConfigPayload {
  return {
    hours: config.hours,
    closures: config.closures,
    services: config.services,
    slot_minutes: config.slot_minutes,
  };
}
