import { useEffect, useState } from "react";

import { Button } from "@/shared/components/ui/button";
import { Input } from "@/shared/components/ui/input";
import { Label } from "@/shared/components/ui/label";
import { getClinicConfig, updateClinicConfig } from "@/dashboard/lib/dashboardApi";
import {
  WEEKDAYS,
  addClosure,
  addInterval,
  addService,
  removeClosure,
  removeInterval,
  removeService,
  setIntervalField,
  setSlotMinutes,
  toPayload,
  updateClosure,
  updateService,
  type ClinicConfig,
  type HoursInterval,
  type Weekday,
} from "@/dashboard/lib/settingsForm";

const WEEKDAY_LABELS: Record<Weekday, string> = {
  mon: "Monday",
  tue: "Tuesday",
  wed: "Wednesday",
  thu: "Thursday",
  fri: "Friday",
  sat: "Saturday",
  sun: "Sunday",
};

/** One weekday's intervals: `open`–`close` pairs plus add/remove. An
 * empty list is the honest spelling of "closed that day" -- exactly
 * what the backend's `hours` shape stores. */
function HoursDay({
  weekday,
  intervals,
  onChange,
}: {
  weekday: Weekday;
  intervals: HoursInterval[];
  onChange: (edit: (config: ClinicConfig) => ClinicConfig) => void;
}) {
  return (
    <div className="flex flex-col gap-2 rounded-md border border-[var(--border-default)] p-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-[var(--text-primary)]">
          {WEEKDAY_LABELS[weekday]}
        </span>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => onChange((config) => addInterval(config, weekday))}
        >
          Add hours
        </Button>
      </div>
      {intervals.length === 0 && (
        <p className="text-xs text-[var(--text-muted)]">Closed</p>
      )}
      {intervals.map((interval, index) => (
        <div key={index} className="flex items-center gap-2">
          <Input
            type="time"
            step={300}
            className="w-28"
            aria-label={`${WEEKDAY_LABELS[weekday]} open`}
            value={interval.open}
            onChange={(e) =>
              onChange((config) =>
                setIntervalField(config, weekday, index, "open", e.target.value),
              )
            }
          />
          <span className="text-sm text-[var(--text-muted)]">to</span>
          <Input
            type="time"
            step={300}
            className="w-28"
            aria-label={`${WEEKDAY_LABELS[weekday]} close`}
            value={interval.close}
            onChange={(e) =>
              onChange((config) =>
                setIntervalField(config, weekday, index, "close", e.target.value),
              )
            }
          />
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="text-[var(--state-error)]"
            onClick={() => onChange((config) => removeInterval(config, weekday, index))}
          >
            Remove
          </Button>
        </div>
      ))}
    </div>
  );
}

/** The Settings tab: the clinic's availability config, editable and
 * saved as one whole (`project-overview.md` -> Staff Dashboard; the
 * four editable fields `architecture.md` -> Storage Model fixes).
 * Validation is entirely server-side (`tools.clinics`), so a refused
 * save shows the backend's own message, which names the field. */
export function SettingsView() {
  const [config, setConfig] = useState<ClinicConfig | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getClinicConfig()
      .then((result) => {
        if (!cancelled) setConfig(result);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  /** One edit from any row, applied to the whole config at once. */
  function edit(update: (config: ClinicConfig) => ClinicConfig) {
    setConfig((current) => (current === null ? current : update(current)));
    setSavedAt(null);
  }

  async function save() {
    if (config === null) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await updateClinicConfig(toPayload(config));
      setConfig(updated);
      setSavedAt(new Date().toLocaleTimeString());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save.");
    } finally {
      setSaving(false);
    }
  }

  if (config === null) {
    return (
      <div className="flex flex-col gap-2">
        <h1 className="text-lg font-semibold text-[var(--text-primary)]">Settings</h1>
        {error ? (
          <p className="text-sm text-[var(--state-error)]">{error}</p>
        ) : (
          <p className="text-sm text-[var(--text-muted)]">Loading…</p>
        )}
      </div>
    );
  }

  return (
    <div className="flex max-w-2xl flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-[var(--text-primary)]">Settings</h1>
          <p className="text-sm text-[var(--text-muted)]">
            {config.name} · {config.timezone}
          </p>
        </div>
        <div className="flex items-center gap-3">
          {savedAt && (
            <span className="text-xs text-[var(--state-success)]">Saved at {savedAt}</span>
          )}
          <Button type="button" onClick={save} disabled={saving}>
            {saving ? "Saving…" : "Save changes"}
          </Button>
        </div>
      </div>

      {error && <p className="text-sm text-[var(--state-error)]">{error}</p>}

      <section className="flex flex-col gap-3">
        <h2 className="text-sm font-semibold text-[var(--text-primary)]">Opening hours</h2>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {WEEKDAYS.map((weekday) => (
            <HoursDay
              key={weekday}
              weekday={weekday}
              intervals={config.hours[weekday]}
              onChange={edit}
            />
          ))}
        </div>
      </section>

      <section className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-[var(--text-primary)]">
            Closures (whole days)
          </h2>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => edit(addClosure)}
          >
            Add closure
          </Button>
        </div>
        {config.closures.length === 0 && (
          <p className="text-xs text-[var(--text-muted)]">No closures configured.</p>
        )}
        {config.closures.map((closure, index) => (
          <div key={index} className="flex items-center gap-2">
            <Input
              type="date"
              className="w-44"
              aria-label="Closure date"
              value={closure.date}
              onChange={(e) =>
                edit((current) => updateClosure(current, index, { date: e.target.value }))
              }
            />
            <Input
              className="flex-1"
              aria-label="Closure label"
              placeholder="Label, e.g. Christmas Day"
              value={closure.label}
              onChange={(e) =>
                edit((current) => updateClosure(current, index, { label: e.target.value }))
              }
            />
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="text-[var(--state-error)]"
              onClick={() => edit((current) => removeClosure(current, index))}
            >
              Remove
            </Button>
          </div>
        ))}
      </section>

      <section className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-[var(--text-primary)]">Services</h2>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => edit(addService)}
          >
            Add service
          </Button>
        </div>
        {config.services.map((service, index) => (
          <div key={index} className="flex items-center gap-2">
            <Input
              className="w-36"
              aria-label="Service id"
              placeholder="id"
              value={service.id}
              onChange={(e) =>
                edit((current) => updateService(current, index, { id: e.target.value }))
              }
            />
            <Input
              className="flex-1"
              aria-label="Service name"
              placeholder="Name, e.g. Dental cleaning"
              value={service.name}
              onChange={(e) =>
                edit((current) => updateService(current, index, { name: e.target.value }))
              }
            />
            <Input
              type="number"
              min={1}
              className="w-24"
              aria-label="Service duration in minutes"
              value={service.duration_minutes}
              onChange={(e) =>
                edit((current) =>
                  updateService(current, index, {
                    duration_minutes: Number(e.target.value),
                  }),
                )
              }
            />
            <span className="text-xs text-[var(--text-muted)]">min</span>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="text-[var(--state-error)]"
              onClick={() => edit((current) => removeService(current, index))}
            >
              Remove
            </Button>
          </div>
        ))}
      </section>

      <section className="flex items-center gap-2">
        <Label
          htmlFor="slot-minutes"
          className="text-sm font-medium text-[var(--text-primary)]"
        >
          Slot grid (minutes between offered start times)
        </Label>
        <Input
          id="slot-minutes"
          type="number"
          min={1}
          className="w-24"
          value={config.slot_minutes}
          onChange={(e) => edit((current) => setSlotMinutes(current, e.target.value))}
        />
      </section>
    </div>
  );
}
