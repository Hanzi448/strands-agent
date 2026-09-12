/**
 * The clinics a patient can call, keyed by the `clinic_id` values the
 * backend scopes everything by. Names match `seed/clinic_data.py`.
 *
 * This is the interim answer to the "public clinic-listing route?"
 * Open Question in progress-tracker.md: a static registry is fine for
 * a two-clinic demo and wrong the moment clinics are added in
 * DynamoDB -- do not extend this pattern, resolve the question.
 */

export interface Clinic {
  readonly id: string;
  readonly name: string;
  /** One line of demo copy shown under the name in the picker. */
  readonly tagline: string;
}

export const DEMO_CLINICS: readonly Clinic[] = [
  {
    id: "clinic-dental",
    name: "Bright Smile Dental",
    tagline: "Dental appointments, reschedules, and questions",
  },
  {
    id: "clinic-cosmetic",
    name: "Lumiere Aesthetics",
    tagline: "Cosmetic consultations and bookings",
  },
];
