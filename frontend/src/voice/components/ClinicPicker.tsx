import { Building2, Phone } from "lucide-react";

import type { Clinic } from "../lib/clinics";
import { DEMO_CLINICS } from "../lib/clinics";

interface ClinicPickerProps {
  onChoose: (clinic: Clinic) => void;
}

export function ClinicPicker({ onChoose }: ClinicPickerProps) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-8 bg-[var(--bg-base)] px-4">
      <div className="text-center">
        <h1 className="font-sans text-2xl font-semibold text-[var(--text-primary)]">
          Who are you calling?
        </h1>
        <p className="mt-1 text-sm text-[var(--text-muted)]">
          Pick a clinic to speak with its AI front desk.
        </p>
      </div>
      <div className="grid w-full max-w-md gap-3">
        {DEMO_CLINICS.map((clinic) => (
          <button
            key={clinic.id}
            type="button"
            onClick={() => onChoose(clinic)}
            className="flex items-center justify-between rounded-xl border border-[var(--border-default)] bg-[var(--bg-surface)] px-4 py-4 text-left transition-colors hover:border-[var(--accent-primary)]"
          >
            <span className="flex items-center gap-3">
              <Building2 className="h-5 w-5 text-[var(--accent-primary)]" />
              <span>
                <span className="block font-medium text-[var(--text-primary)]">
                  {clinic.name}
                </span>
                <span className="block text-sm text-[var(--text-muted)]">{clinic.tagline}</span>
              </span>
            </span>
            <Phone className="h-5 w-5 text-[var(--text-muted)]" />
          </button>
        ))}
      </div>
    </div>
  );
}
