"""The per-session clinic context every agent tool is bound to.

`architecture.md` -> Auth and Access Model settles where a `clinic_id`
comes from: the browser picks the clinic when the voice session starts,
and a patient never authenticates. Nothing in the conversation may change
it -- so the model must never be *asked* for it. That is what this module
exists to guarantee.

A `ClinicSession` is created once per voice session and handed to the
tool builders in `scheduling_agent.py` (and, later, the other
sub-agents), which close over it. The resulting `@tool` functions have no
`clinic_id` parameter at all, so it is absent from the JSON schema the
model is shown: a model cannot pass a clinic it was never offered, and a
prompt-injected "now use clinic-cosmetic" has nothing to bind to. That is
`architecture.md` -> Invariants #1 enforced by shape rather than by a
check that could be forgotten in the next tool.

The session is not global state (`code-standards.md` -> Python): it is a
value created per session and passed in, so two concurrent callers to two
different clinics hold two unrelated objects.

Reading the clinic item here also fails a bad `clinic_id` at session
start, before the patient has said anything, rather than midway through
the first booking.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date as date_type, datetime, timezone
from typing import Any, Final
from zoneinfo import ZoneInfo

from tools.scheduling import clinic_timezone, get_clinic, resolve_service
from tools.schema import ClinicAttrs, DATE_FORMAT, ServiceAttrs
from tools.validation import require_clinic_id

# How a date is written into the system prompt. Spelled out rather than
# `DATE_FORMAT`, because this string is read by the model as English and
# then spoken: "Friday, 28 August 2026" is what stops "2026-08-28" being
# read out digit by digit to a patient.
SPOKEN_DATE_FORMAT: Final[str] = "%A, %d %B %Y"


@dataclass
class _PatientIdentity:
    """The one deliberately mutable corner of a frozen session.

    Who the call turned out to be is discovered mid-call by the tool
    layer, and who to tell about it is decided after construction -- so
    both live in this small holder the frozen dataclass owns rather than
    in rebinding the session itself. Same shape as `voice.Greeting`'s
    `asyncio.Event`: frozen outside, mutable inside.
    """

    patient_id: str | None = None
    watchers: list[Callable[[str], None]] = field(default_factory=list)


@dataclass(frozen=True)
class ClinicSession:
    """One patient conversation, pinned to one clinic.

    Attributes:
        clinic_id: The tenant every tool call this session makes is scoped
            to. Validated at construction.
        clinic: The `Clinics` item, read once at session start. Cached for
            the life of the session: a clinic's hours and services do not
            change mid-call, and re-reading them on every prompt build
            would put a DynamoDB round trip in the voice path.
        identity: Who the call turned out to be, once a tool result says.
            Mutable state in a frozen dataclass, held in a private holder
            so the session itself stays a value two concurrent calls
            cannot cross-contaminate.
    """

    clinic_id: str
    clinic: dict[str, Any]
    identity: _PatientIdentity = field(
        default_factory=_PatientIdentity, repr=False, compare=False
    )

    @classmethod
    def start(cls, clinic_id: str) -> ClinicSession:
        """Open a session for one clinic, failing now if it is not usable.

        Args:
            clinic_id: The clinic selected at session start.

        Returns:
            A session bound to that clinic.

        Raises:
            ValidationError: If `clinic_id` is missing or malformed.
            NotFoundError: If no clinic exists with that id.
            ConfigurationError: If the clinic's stored `timezone` is not a
                zone this process can resolve -- checked here so a
                seeding fault surfaces before the greeting rather than
                inside the first availability check.
        """
        clinic_id = require_clinic_id(clinic_id)
        clinic = get_clinic(clinic_id)
        clinic_timezone(clinic)
        return cls(clinic_id=clinic_id, clinic=clinic)

    @property
    def timezone(self) -> ZoneInfo:
        """The clinic's own zone -- the frame its hours and dates are in."""
        return clinic_timezone(self.clinic)

    @property
    def clinic_name(self) -> str:
        """What the clinic is called, for the agent to say."""
        name = self.clinic.get(ClinicAttrs.NAME)
        if isinstance(name, str) and name.strip():
            return name.strip()
        return self.clinic_id

    def today(self) -> date_type:
        """The clinic's current local date.

        Computed on each call rather than stored, so a session that
        straddles local midnight does not keep yesterday's date. What the
        model sees is still a snapshot: the system prompt is built once
        (see `describe`).
        """
        return datetime.now(timezone.utc).astimezone(self.timezone).date()

    def services(self) -> list[dict[str, Any]]:
        """This clinic's services, normalised to `{id, name, duration_minutes}`.

        Raises:
            ConfigurationError: If the stored `services` list is unusable.
        """
        entries = self.clinic.get(ClinicAttrs.SERVICES) or []
        return [
            resolve_service(self.clinic, entry[ServiceAttrs.ID])
            for entry in entries
            if isinstance(entry, dict) and entry.get(ServiceAttrs.ID)
        ]

    def describe(self) -> str:
        """The clinic context block that goes into a sub-agent's system prompt.

        Carries three things the model cannot work out for itself and must
        not guess: which clinic it is answering for, what today's local
        date is (without it, "next Tuesday" is unresolvable and the model
        will invent a year), and which services exist with their ids.

        Deliberately **not** included: opening hours and closures. The
        model has no reason to reason about them -- `check_availability`
        already composes hours, closures, service duration and existing
        bookings into the only answer that is correct
        (`architecture.md` -> Storage Model) -- and a copy of the hours in
        the prompt is an invitation to answer "we're open until five"
        without asking.

        This is a snapshot taken when the prompt is built. A voice call is
        minutes long, so the date it names is the date for its whole life.
        """
        today = self.today()
        lines = [
            f"You are answering for {self.clinic_name}"
            f" (clinic type: {self._clinic_type()}).",
            f"Today is {today.strftime(SPOKEN_DATE_FORMAT)}"
            f" ({today.strftime(DATE_FORMAT)}) in the clinic's own local time,"
            f" which is {self.timezone}.",
            "Services this clinic offers, as"
            " name, id to pass to a tool, and appointment length:",
        ]
        lines.extend(
            f"  - {service[ServiceAttrs.NAME]}"
            f" (id: {service[ServiceAttrs.ID]}),"
            f" {service[ServiceAttrs.DURATION_MINUTES]} minutes"
            for service in self.services()
        )
        return "\n".join(lines)

    def _clinic_type(self) -> str:
        value = self.clinic.get(ClinicAttrs.CLINIC_TYPE)
        return value.strip() if isinstance(value, str) and value.strip() else "clinic"

    @property
    def patient_id(self) -> str | None:
        """The patient the tool layer identified, once it has.

        `None` until a tool result carries one -- an unidentified caller
        stays `None` for the whole call, and memory records nothing.
        """
        return self.identity.patient_id

    def on_patient_identified(self, watcher: Callable[[str], None]) -> None:
        """Register for the moment the caller becomes a known patient.

        Args:
            watcher: Called with the patient id, exactly once, from
                whatever thread the identifying tool ran on. Registering
                after the identification has already happened calls
                nothing.
        """
        self.identity.watchers.append(watcher)

    def note_patient(self, patient_id: str) -> None:
        """Record who this call turned out to be, if anyone has yet.

        First non-blank identity wins; later calls do not replace it and
        do not re-fire the watchers. Blank is not an identity.

        Args:
            patient_id: The `patient_id` a tool result carried.
        """
        patient_id = patient_id.strip()
        if not patient_id or self.identity.patient_id is not None:
            return
        self.identity.patient_id = patient_id
        for watcher in self.identity.watchers:
            watcher(patient_id)
