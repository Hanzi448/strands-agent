import { describe, expect, it } from "vitest";

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
} from "@/dashboard/lib/settingsForm";

/** The shape `GET /settings` returns, as the dental clinic's seed
 * config would produce it. */
function config(): ClinicConfig {
  return {
    name: "Bright Smile Dental",
    timezone: "Europe/London",
    hours: {
      mon: [{ open: "09:00", close: "13:00" }, { open: "14:00", close: "17:30" }],
      tue: [{ open: "09:00", close: "17:00" }],
      wed: [],
      thu: [{ open: "09:00", close: "17:00" }],
      fri: [{ open: "09:00", close: "17:00" }],
      sat: [{ open: "09:00", close: "12:00" }],
      sun: [],
    },
    closures: [{ date: "2026-12-25", label: "Christmas Day" }],
    services: [
      { id: "checkup", name: "Check-up", duration_minutes: 15 },
      { id: "cleaning", name: "Dental cleaning", duration_minutes: 30 },
    ],
    slot_minutes: 15,
  };
}

describe("WEEKDAYS", () => {
  it("is all seven keys, mon-first, matching the backend's WEEKDAY_KEYS", () => {
    expect([...WEEKDAYS]).toEqual(["mon", "tue", "wed", "thu", "fri", "sat", "sun"]);
  });
});

describe("interval editing", () => {
  it("adds a full-day interval to the chosen weekday without touching the rest", () => {
    const updated = addInterval(config(), "wed");
    expect(updated.hours.wed).toEqual([{ open: "09:00", close: "17:00" }]);
    expect(updated.hours.mon).toHaveLength(2);
    // Immutability: the original is untouched, so React sees a new object.
    expect(config().hours.wed).toEqual([]);
  });

  it("removes the interval at the index, not just the last one", () => {
    const updated = removeInterval(config(), "mon", 0);
    expect(updated.hours.mon).toEqual([{ open: "14:00", close: "17:30" }]);
  });

  it("edits one end of one interval", () => {
    const updated = setIntervalField(config(), "sat", 0, "close", "13:00");
    expect(updated.hours.sat[0]).toEqual({ open: "09:00", close: "13:00" });
    expect(updated.hours.sun).toEqual([]);
  });
});

describe("closure editing", () => {
  it("adds a blank closure to fill in", () => {
    const updated = addClosure(config());
    expect(updated.closures).toHaveLength(2);
    expect(updated.closures[1]).toEqual({ date: "", label: "" });
  });

  it("patches one closure and removes the right one", () => {
    let updated = updateClosure(config(), 0, { label: "Christmas" });
    expect(updated.closures[0].date).toBe("2026-12-25");
    updated = addClosure(updated);
    updated = removeClosure(updated, 0);
    expect(updated.closures).toEqual([{ date: "", label: "" }]);
  });
});

describe("service editing", () => {
  it("adds a blank service to fill in", () => {
    const updated = addService(config());
    expect(updated.services).toHaveLength(3);
    expect(updated.services[2]).toEqual({ id: "", name: "", duration_minutes: 30 });
  });

  it("patches one field of one service immutably", () => {
    const original = config();
    const updated = updateService(original, 0, { duration_minutes: 20 });
    expect(updated.services[0].duration_minutes).toBe(20);
    expect(original.services[0].duration_minutes).toBe(15);
  });

  it("removes the service at the index", () => {
    const updated = removeService(config(), 1);
    expect(updated.services.map((s) => s.id)).toEqual(["checkup"]);
  });
});

describe("slot_minutes", () => {
  it("sets the value as a number, not the input element's string", () => {
    const updated = setSlotMinutes(config(), "20");
    expect(updated.slot_minutes).toBe(20);
  });
});

describe("toPayload", () => {
  it("sends exactly the four editable fields", () => {
    expect(toPayload(config())).toEqual({
      hours: config().hours,
      closures: config().closures,
      services: config().services,
      slot_minutes: 15,
    });
  });
});
