"""Tests for `reschedule_appointment` and `cancel_appointment`.

Three properties carry the weight here.

*Whose appointment it is.* A phone number alone finds a household, not a
person, so every "can this caller change this appointment?" case is
asserted directly -- a right number with a wrong name, another patient's
appointment id, an appointment that is already cancelled. Each of those
must reach the same dead end, and must leave the table untouched.

*That a move does not block itself.* The appointment being moved still
sits in the table at its old time while its new time is being checked, so
moving a 30-minute cleaning by 15 minutes is the case that fails if
`exclude_appointment_id` is not threaded all the way through
`scheduling._booked_spans`.

*That the write is one atomic, guarded update.* The fake table below
actually applies the `UpdateExpression` it is given, rather than only
recording it, so a malformed expression or a missing `if_not_exists` fails
here instead of in a deployed Lambda. The clinic fixtures are the demo
configs from `architecture.md`, imported from `test_scheduling` rather than
restated, so the suites cannot drift apart.

Time is pinned: `utc_now_iso` is monkeypatched, because "upcoming" is
relative to now and a suite whose fixtures silently fall into the past
would stop testing anything.
"""

from __future__ import annotations

from typing import Any

import pytest
from botocore.exceptions import ClientError

from tests.test_booking import FakePatientsTable
from tests.test_scheduling import (
    COSMETIC_ID,
    DENTAL_ID,
    FakeClinicsTable,
    cosmetic_clinic,
    dental_clinic,
)
from tools import appointments, patients, scheduling
from tools.errors import (
    ConfigurationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from tools.schema import RescheduleActor

# Pinned "now". 2026-07-01 is a Wednesday in British Summer Time, so the
# dental clinic's 09:00 local is 08:00Z -- the offset is visible in every
# assertion below rather than accidentally an identity.
NOW = "2026-06-30T12:00:00Z"
NINE = "2026-07-01T08:00:00Z"
NINE_FIFTEEN = "2026-07-01T08:15:00Z"
NINE_THIRTY = "2026-07-01T08:30:00Z"
TEN = "2026-07-01T09:00:00Z"
NEXT_DAY_TEN = "2026-07-02T09:00:00Z"
# 2026-07-05 is a Sunday (the dental clinic never opens); 2026-07-08 is its
# seeded staff-training closure.
SUNDAY_NINE = "2026-07-05T08:00:00Z"
CLOSURE_NINE = "2026-07-08T08:00:00Z"

PATIENT_ID = "pat_dana"
HOUSEMATE_ID = "pat_sam"
STRANGER_ID = "pat_alex"
# The stored form: digits only, as `normalise_phone` writes it.
PHONE = "15551234567"
NAME = "Dana Okafor"
HOUSEMATE_NAME = "Sam Okafor"


# --------------------------------------------------------------------------
# Fixture items
# --------------------------------------------------------------------------


def patient(
    patient_id: str = PATIENT_ID, name: str = NAME, phone: str = PHONE
) -> dict[str, Any]:
    """One `Patients` item, as `_create_patient` writes it."""
    return {
        "clinic_id": DENTAL_ID,
        "patient_id": patient_id,
        "name": name,
        "phone": phone,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }


def booked(
    appointment_id: str,
    starts_at: str,
    ends_at: str,
    *,
    patient_id: str = PATIENT_ID,
    service: str = "checkup",
    status: str = "scheduled",
    clinic_id: str = DENTAL_ID,
    **extra: Any,
) -> dict[str, Any]:
    """One `Appointments` item, as `book_appointment` writes it."""
    item: dict[str, Any] = {
        "clinic_id": clinic_id,
        "appointment_id": appointment_id,
        "clinic_patient": f"{clinic_id}#{patient_id}",
        "patient_id": patient_id,
        "patient_name": NAME,
        "service": service,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "status": status,
        "reminders": [],
        "reschedule_history": [],
        "created_at": "2026-06-01T00:00:00Z",
        "updated_at": "2026-06-01T00:00:00Z",
    }
    item.update(extra)
    return item


# --------------------------------------------------------------------------
# A fake `Appointments` table that actually stores things
# --------------------------------------------------------------------------


def _split_top_level(text: str) -> list[str]:
    """Split on commas that are not inside parentheses."""
    parts: list[str] = []
    depth = 0
    current = ""
    for character in text:
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        if character == "," and depth == 0:
            parts.append(current)
            current = ""
            continue
        current += character
    parts.append(current)
    return [part.strip() for part in parts]


def _matches(item: dict[str, Any], condition: Any) -> bool:
    """Evaluate a boto3 `Key(...)` condition against one item."""
    expression = condition.get_expression()
    operator = expression["operator"]
    operands = expression["values"]
    if operator == "AND":
        return all(_matches(item, operand) for operand in operands)
    actual = str(item.get(operands[0].name, ""))
    if operator == "=":
        return actual == operands[1]
    if operator == ">=":
        return actual >= operands[1]
    if operator == "BETWEEN":
        return operands[1] <= actual <= operands[2]
    raise AssertionError(f"unsupported key operator {operator!r}")


class FakeAppointmentStore:
    """Queries and updates over one list of items, as DynamoDB would.

    Deliberately more than a recorder. Both key conditions are evaluated,
    so a query aimed at the wrong index key returns nothing rather than
    everything, and `update_item` applies its own `UpdateExpression`, so
    the history append is asserted against what the expression actually
    does rather than against what it was meant to say.
    """

    def __init__(self, *items: dict[str, Any]) -> None:
        self.items = [dict(item) for item in items]
        self.queries: list[dict[str, Any]] = []
        self.updates: list[dict[str, Any]] = []
        # Set to simulate another session changing the row first.
        self.fail_condition = False

    def query(self, **kwargs: Any) -> dict[str, Any]:
        self.queries.append(kwargs)
        matched = [
            dict(item)
            for item in self.items
            if _matches(item, kwargs["KeyConditionExpression"])
        ]
        matched.sort(key=lambda item: str(item.get("starts_at", "")))
        return {"Items": matched}

    def update_item(self, **kwargs: Any) -> dict[str, Any]:
        self.updates.append(kwargs)
        if self.fail_condition:
            raise ClientError(
                {
                    "Error": {
                        "Code": "ConditionalCheckFailedException",
                        "Message": "The conditional request failed",
                    }
                },
                "UpdateItem",
            )
        self._apply(kwargs)
        return {}

    def stored(self, appointment_id: str) -> dict[str, Any]:
        return next(
            item for item in self.items if item["appointment_id"] == appointment_id
        )

    def _apply(self, kwargs: dict[str, Any]) -> None:
        key = kwargs["Key"]
        item = next(
            candidate
            for candidate in self.items
            if candidate["clinic_id"] == key["clinic_id"]
            and candidate["appointment_id"] == key["appointment_id"]
        )
        names = kwargs["ExpressionAttributeNames"]
        values = kwargs["ExpressionAttributeValues"]
        expression = kwargs["UpdateExpression"]
        assert expression.startswith("SET ")
        for assignment in _split_top_level(expression[len("SET ") :]):
            target, separator, source = assignment.partition(" = ")
            assert separator, f"unparseable assignment {assignment!r}"
            item[names[target]] = _evaluate(source, item, names, values)


def _evaluate(
    source: str, item: dict[str, Any], names: dict[str, str], values: dict[str, Any]
) -> Any:
    """Evaluate the right-hand side of one `SET` assignment."""
    source = source.strip()
    if source.startswith(":"):
        return values[source]
    if source.startswith("#"):
        return item.get(names[source])
    function, separator, rest = source.partition("(")
    assert separator and rest.endswith(")"), f"unparseable value {source!r}"
    arguments = _split_top_level(rest[:-1])
    if function == "list_append":
        left = _evaluate(arguments[0], item, names, values)
        right = _evaluate(arguments[1], item, names, values)
        return list(left) + list(right)
    if function == "if_not_exists":
        current = _evaluate(arguments[0], item, names, values)
        fallback = _evaluate(arguments[1], item, names, values)
        return fallback if current is None else current
    raise AssertionError(f"unsupported update function {function!r}")


@pytest.fixture
def tables(monkeypatch: pytest.MonkeyPatch):
    """Point every table accessor the change path touches at a fake.

    `scheduling` and `patients` are patched as well as `appointments`,
    because a reschedule reaches DynamoDB through all three -- which is the
    point: this module owns no availability rule and no identity rule.
    """

    def install(
        *,
        appointment_items: list[dict[str, Any]] | None = None,
        patient_items: list[dict[str, Any]] | None = None,
        clinics: FakeClinicsTable | None = None,
        now: str = NOW,
    ) -> tuple[FakeClinicsTable, FakeAppointmentStore, FakePatientsTable]:
        clinics = clinics or FakeClinicsTable(dental_clinic(), cosmetic_clinic())
        store = FakeAppointmentStore(*(appointment_items or []))
        patients_fake = FakePatientsTable(*(patient_items or [patient()]))
        monkeypatch.setattr(scheduling, "clinics_table", lambda: clinics)
        monkeypatch.setattr(scheduling, "appointments_table", lambda: store)
        monkeypatch.setattr(appointments, "appointments_table", lambda: store)
        monkeypatch.setattr(patients, "patients_table", lambda: patients_fake)
        monkeypatch.setattr(appointments, "utc_now_iso", lambda: now)
        return clinics, store, patients_fake

    return install


def move(**overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "clinic_id": DENTAL_ID,
        "patient_phone": PHONE,
        "patient_name": NAME,
        "new_starts_at": TEN,
    }
    kwargs.update(overrides)
    return appointments.reschedule_appointment(**kwargs)


def drop(**overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "clinic_id": DENTAL_ID,
        "patient_phone": PHONE,
        "patient_name": NAME,
    }
    kwargs.update(overrides)
    return appointments.cancel_appointment(**kwargs)


def one_checkup() -> list[dict[str, Any]]:
    """Dana has a single 09:00 check-up coming up."""
    return [booked("apt_one", NINE, NINE_FIFTEEN)]


# --------------------------------------------------------------------------
# The tenant boundary
# --------------------------------------------------------------------------


@pytest.mark.parametrize("clinic_id", ["", "   ", None])
@pytest.mark.parametrize("tool", ["reschedule", "cancel"])
def test_blank_clinic_id_fails_before_any_read(clinic_id, tool, tables) -> None:
    """`code-standards.md`: the tenant check runs *before anything else*."""
    clinics, store, patients_fake = tables(appointment_items=one_checkup())
    with pytest.raises(ValidationError):
        (move if tool == "reschedule" else drop)(clinic_id=clinic_id)
    assert clinics.requested == []
    assert store.queries == []
    assert store.updates == []


def test_by_patient_query_is_keyed_on_the_clinic_patient_composite(tables) -> None:
    """The index key is itself clinic-scoped (`architecture.md` -> #1).

    `appointment_history_for_patient` queries the whole partition -- one
    equality condition, not an AND with a `starts_at` range -- and filters
    to `scheduled`/upcoming in Python (see its docstring), so the recorded
    condition is the partition-key equality itself.
    """
    _, store, _ = tables(appointment_items=one_checkup())
    drop()
    by_patient = next(
        query for query in store.queries if query["IndexName"] == "by-patient"
    )
    condition = by_patient["KeyConditionExpression"].get_expression()
    assert condition["operator"] == "="
    assert condition["values"][1] == f"{DENTAL_ID}#{PATIENT_ID}"


def test_another_clinics_appointment_is_invisible(tables) -> None:
    """The same patient id under a different clinic is a different key."""
    _, store, _ = tables(
        appointment_items=[
            booked("apt_other", NINE, NINE_FIFTEEN, clinic_id=COSMETIC_ID)
        ]
    )
    with pytest.raises(NotFoundError):
        drop()
    assert store.updates == []


# --------------------------------------------------------------------------
# Argument validation
# --------------------------------------------------------------------------


def test_unparseable_new_start_is_rejected(tables) -> None:
    tables(appointment_items=one_checkup())
    with pytest.raises(ValidationError):
        move(new_starts_at="next Tuesday-ish")


@pytest.mark.parametrize("name", ["", "   ", None])
def test_patient_name_is_required(name, tables) -> None:
    """The name is half the identity rule, so it is not optional."""
    _, store, _ = tables(appointment_items=one_checkup())
    with pytest.raises(ValidationError):
        drop(patient_name=name)
    assert store.updates == []


def test_actor_outside_the_vocabulary_is_rejected(tables) -> None:
    _, store, _ = tables(appointment_items=one_checkup())
    with pytest.raises(ValidationError):
        drop(actor="the receptionist")
    assert store.updates == []


def test_over_long_reason_is_rejected(tables) -> None:
    """A model pasting a transcript into `reason` does not reach the table."""
    _, store, _ = tables(appointment_items=one_checkup())
    with pytest.raises(ValidationError):
        drop(reason="x" * 2001)
    assert store.updates == []


def test_unknown_clinic_is_not_found(tables) -> None:
    _, store, _ = tables(appointment_items=one_checkup())
    with pytest.raises(NotFoundError):
        drop(clinic_id="clinic-nowhere")
    assert store.updates == []


# --------------------------------------------------------------------------
# Whose appointment it is
# --------------------------------------------------------------------------


def test_unknown_phone_finds_nothing_and_writes_nothing(tables) -> None:
    _, store, patients_fake = tables(appointment_items=one_checkup())
    with pytest.raises(NotFoundError):
        drop(patient_phone="15559998888")
    assert store.updates == []
    # A read must not register anyone: `find_patient` is the read-only half
    # of the identity rule.
    assert patients_fake.puts == []


def test_right_number_wrong_name_cannot_touch_the_appointment(tables) -> None:
    """The household case: a shared number is not an identity."""
    _, store, _ = tables(appointment_items=one_checkup())
    with pytest.raises(NotFoundError) as raised:
        drop(patient_name=HOUSEMATE_NAME)
    assert HOUSEMATE_NAME in str(raised.value)
    assert store.updates == []


def test_a_housemates_appointment_is_not_reachable(tables) -> None:
    """Two patients, one number: each sees only their own appointments."""
    _, store, _ = tables(
        appointment_items=[booked("apt_sam", NINE, NINE_FIFTEEN, patient_id=HOUSEMATE_ID)],
        patient_items=[
            patient(),
            patient(HOUSEMATE_ID, HOUSEMATE_NAME),
        ],
    )
    with pytest.raises(NotFoundError):
        drop()
    assert store.updates == []


def test_name_matching_ignores_case_and_spacing(tables) -> None:
    """Speech-derived names, compared the way `patients` compares them."""
    _, store, _ = tables(appointment_items=one_checkup())
    result = drop(patient_name="  dana   okafor ")
    assert result["status"] == "cancelled"
    assert store.stored("apt_one")["status"] == "cancelled"


def test_past_appointments_are_not_upcoming(tables) -> None:
    _, store, _ = tables(
        appointment_items=[booked("apt_old", "2026-06-01T08:00:00Z", "2026-06-01T08:15:00Z")]
    )
    with pytest.raises(NotFoundError):
        drop()
    assert store.updates == []


def test_a_cancelled_appointment_cannot_be_cancelled_again(tables) -> None:
    """It is not upcoming, so it is not reachable -- one rule, not two."""
    _, store, _ = tables(
        appointment_items=[booked("apt_one", NINE, NINE_FIFTEEN, status="cancelled")]
    )
    with pytest.raises(NotFoundError):
        drop()
    assert store.updates == []


def test_several_upcoming_appointments_refuse_and_name_themselves(tables) -> None:
    """Taking the soonest would cancel the wrong one, silently."""
    _, store, _ = tables(
        appointment_items=[
            booked("apt_one", NINE, NINE_FIFTEEN),
            booked("apt_two", NEXT_DAY_TEN, "2026-07-02T09:30:00Z", service="cleaning"),
        ]
    )
    with pytest.raises(ConflictError) as raised:
        drop()
    message = str(raised.value)
    assert "apt_one" in message and "apt_two" in message
    # The service names and local times, so the agent can ask in one turn.
    assert "Check-up" in message and "Dental cleaning" in message
    assert "09:00 on 2026-07-01" in message and "10:00 on 2026-07-02" in message
    assert store.updates == []


def test_naming_the_appointment_resolves_the_ambiguity(tables) -> None:
    _, store, _ = tables(
        appointment_items=[
            booked("apt_one", NINE, NINE_FIFTEEN),
            booked("apt_two", NEXT_DAY_TEN, "2026-07-02T09:30:00Z", service="cleaning"),
        ]
    )
    result = drop(appointment_id="apt_two")
    assert result["appointment_id"] == "apt_two"
    assert store.stored("apt_two")["status"] == "cancelled"
    assert store.stored("apt_one")["status"] == "scheduled"


def test_long_ambiguity_list_is_truncated(tables) -> None:
    """A voice agent reading six appointments aloud has stopped helping."""
    _, store, _ = tables(
        appointment_items=[
            booked(f"apt_{index}", f"2026-07-0{index}T08:00:00Z", f"2026-07-0{index}T08:15:00Z")
            for index in (1, 2, 3, 6)
        ]
    )
    with pytest.raises(ConflictError) as raised:
        drop()
    message = str(raised.value)
    assert "has 4 upcoming appointments" in message
    assert "and 1 more" in message
    assert "apt_6" not in message


def test_another_patients_appointment_id_is_not_found(tables) -> None:
    """A guessed id must not reach a row it does not own."""
    _, store, _ = tables(
        appointment_items=[
            booked("apt_mine", NINE, NINE_FIFTEEN),
            booked("apt_theirs", TEN, "2026-07-01T09:15:00Z", patient_id=STRANGER_ID),
        ]
    )
    with pytest.raises(NotFoundError):
        drop(appointment_id="apt_theirs")
    assert store.updates == []
    assert store.stored("apt_theirs")["status"] == "scheduled"


def test_a_cancelled_appointment_id_is_not_found(tables) -> None:
    _, store, _ = tables(
        appointment_items=[
            booked("apt_one", NINE, NINE_FIFTEEN),
            booked("apt_gone", TEN, "2026-07-01T09:15:00Z", status="cancelled"),
        ]
    )
    with pytest.raises(NotFoundError):
        drop(appointment_id="apt_gone")
    assert store.updates == []


# --------------------------------------------------------------------------
# Rescheduling
# --------------------------------------------------------------------------


def test_reschedule_moves_the_appointment_and_says_where_it_was(tables) -> None:
    _, store, _ = tables(appointment_items=one_checkup())
    result = move(new_starts_at=TEN, reason="Patient asked to move it")

    assert result["starts_at"] == TEN
    assert result["ends_at"] == "2026-07-01T09:15:00Z"
    assert result["local_start"] == "10:00"
    assert result["local_end"] == "10:15"
    assert result["date"] == "2026-07-01"
    # Still scheduled: a move is not a status (`architecture.md`).
    assert result["status"] == "scheduled"
    assert result["previous"] == {
        "date": "2026-07-01",
        "starts_at": NINE,
        "ends_at": NINE_FIFTEEN,
        "local_start": "09:00",
        "local_end": "09:15",
    }
    assert result["patient"]["patient_id"] == PATIENT_ID
    assert result["patient"]["is_new"] is False

    stored = store.stored("apt_one")
    assert stored["starts_at"] == TEN
    assert stored["ends_at"] == "2026-07-01T09:15:00Z"
    assert stored["status"] == "scheduled"
    assert stored["updated_at"] == NOW


def test_reschedule_appends_one_history_entry(tables) -> None:
    """The dashboard's action log is derived from exactly this list."""
    _, store, _ = tables(appointment_items=one_checkup())
    move(new_starts_at=TEN, reason="Patient asked to move it")

    assert store.stored("apt_one")["reschedule_history"] == [
        {
            "at": NOW,
            "from": NINE,
            "to": TEN,
            "actor": "agent",
            "reason": "Patient asked to move it",
        }
    ]


def test_history_appends_rather_than_replaces(tables) -> None:
    _, store, _ = tables(
        appointment_items=[
            booked(
                "apt_one",
                NINE,
                NINE_FIFTEEN,
                reschedule_history=[
                    {
                        "at": "2026-06-02T09:00:00Z",
                        "from": "2026-07-01T07:00:00Z",
                        "to": NINE,
                        "actor": "staff",
                        "reason": "Dentist was ill",
                    }
                ],
            )
        ]
    )
    move(new_starts_at=TEN)
    history = store.stored("apt_one")["reschedule_history"]
    assert len(history) == 2
    assert history[0]["actor"] == "staff"
    assert history[1]["to"] == TEN


def test_history_append_survives_an_item_without_the_list(tables) -> None:
    """A seeded or hand-written item has no `reschedule_history` attribute."""
    item = booked("apt_one", NINE, NINE_FIFTEEN)
    del item["reschedule_history"]
    _, store, _ = tables(appointment_items=[item])
    move(new_starts_at=TEN)
    assert len(store.stored("apt_one")["reschedule_history"]) == 1


def test_actor_defaults_to_agent_and_staff_can_be_recorded(tables) -> None:
    """The log's whole point is separating the agent's moves from staff's."""
    _, store, _ = tables(appointment_items=one_checkup())
    move(new_starts_at=TEN, actor=RescheduleActor.STAFF)
    assert store.stored("apt_one")["reschedule_history"][0]["actor"] == "staff"


def test_moving_by_less_than_one_service_length_is_allowed(tables) -> None:
    """The self-exclusion case: the old booking must not block the new one.

    A 30-minute cleaning at 09:00 moved to 09:15 overlaps its own current
    span, so this fails unless `exclude_appointment_id` reaches
    `scheduling._booked_spans`.
    """
    _, store, _ = tables(
        appointment_items=[booked("apt_one", NINE, NINE_THIRTY, service="cleaning")]
    )
    result = move(new_starts_at=NINE_FIFTEEN)
    assert result["starts_at"] == NINE_FIFTEEN
    assert result["ends_at"] == "2026-07-01T08:45:00Z"
    assert store.stored("apt_one")["starts_at"] == NINE_FIFTEEN


def test_the_service_length_is_preserved_across_a_move(tables) -> None:
    """A move changes *when*, never *what* -- so never how long."""
    _, store, _ = tables(
        appointment_items=[booked("apt_one", NINE, NINE_THIRTY, service="cleaning")]
    )
    result = move(new_starts_at=TEN)
    assert result["ends_at"] == "2026-07-01T09:30:00Z"
    assert result["service"]["duration_minutes"] == 30
    assert store.stored("apt_one")["service"] == "cleaning"


def test_moving_to_the_same_time_is_refused(tables) -> None:
    """A no-op move would put a phantom entry in the staff action log."""
    _, store, _ = tables(appointment_items=one_checkup())
    with pytest.raises(ConflictError) as raised:
        move(new_starts_at=NINE)
    assert "already at 09:00 on 2026-07-01" in str(raised.value)
    assert store.updates == []


def test_moving_onto_another_patients_slot_is_refused_with_alternatives(tables) -> None:
    _, store, _ = tables(
        appointment_items=[
            booked("apt_one", NINE, NINE_FIFTEEN),
            booked("apt_theirs", TEN, "2026-07-01T09:15:00Z", patient_id=STRANGER_ID),
        ]
    )
    with pytest.raises(ConflictError) as raised:
        move(new_starts_at=TEN)
    message = str(raised.value)
    assert "cannot move that appointment to 10:00 on 2026-07-01" in message
    assert "Still free that day" in message
    assert store.updates == []
    assert store.stored("apt_one")["starts_at"] == NINE


def test_moving_to_a_closed_day_is_refused(tables) -> None:
    _, store, _ = tables(appointment_items=one_checkup())
    with pytest.raises(ConflictError) as raised:
        move(new_starts_at=SUNDAY_NINE)
    assert "nothing else free that day" in str(raised.value)
    assert store.updates == []


def test_moving_onto_a_closure_is_refused(tables) -> None:
    _, store, _ = tables(appointment_items=one_checkup())
    with pytest.raises(ConflictError):
        move(new_starts_at=CLOSURE_NINE)
    assert store.updates == []


def test_moving_off_the_slot_grid_is_refused(tables) -> None:
    """The write does not round a time to a nearby offerable one."""
    _, store, _ = tables(appointment_items=one_checkup())
    with pytest.raises(ConflictError):
        move(new_starts_at="2026-07-01T08:07:00Z")
    assert store.updates == []


def test_moving_to_another_day_works(tables) -> None:
    _, store, _ = tables(appointment_items=one_checkup())
    result = move(new_starts_at=NEXT_DAY_TEN)
    assert result["date"] == "2026-07-02"
    assert result["local_start"] == "10:00"
    assert store.stored("apt_one")["starts_at"] == NEXT_DAY_TEN


def test_notes_are_carried_through_untouched(tables) -> None:
    _, store, _ = tables(
        appointment_items=[
            booked("apt_one", NINE, NINE_FIFTEEN, notes="Sensitive to cold")
        ]
    )
    result = move(new_starts_at=TEN)
    assert result["notes"] == "Sensitive to cold"
    assert store.stored("apt_one")["notes"] == "Sensitive to cold"


def test_a_service_the_clinic_dropped_is_a_configuration_fault(tables) -> None:
    """Nobody supplied this value, so it is not a `ValidationError`."""
    _, store, _ = tables(
        appointment_items=[booked("apt_one", NINE, NINE_FIFTEEN, service="whitening")]
    )
    with pytest.raises(ConfigurationError):
        move(new_starts_at=TEN)
    assert store.updates == []


def test_a_dropped_service_still_lets_the_agent_ask_which_appointment(tables) -> None:
    """The "which one?" message degrades to the id rather than failing."""
    _, store, _ = tables(
        appointment_items=[
            booked("apt_one", NINE, NINE_FIFTEEN, service="whitening"),
            booked("apt_two", NEXT_DAY_TEN, "2026-07-02T09:15:00Z"),
        ]
    )
    with pytest.raises(ConflictError) as raised:
        drop()
    assert "whitening at 09:00 on 2026-07-01" in str(raised.value)


def test_a_winter_move_renders_its_own_offset(tables) -> None:
    """Europe/London in January is UTC+0, in July UTC+1 -- same clinic."""
    _, store, _ = tables(
        appointment_items=[
            booked("apt_one", "2026-01-07T09:00:00Z", "2026-01-07T09:15:00Z")
        ],
        now="2026-01-05T12:00:00Z",
    )
    result = move(new_starts_at="2026-01-07T10:00:00Z")
    assert result["local_start"] == "10:00"
    assert result["previous"]["local_start"] == "09:00"


def test_a_cosmetic_clinic_move_follows_its_own_config(tables) -> None:
    """The same code, a different clinic item, a different answer."""
    _, store, _ = tables(
        appointment_items=[
            booked(
                "apt_one",
                "2026-07-01T09:00:00Z",
                "2026-07-01T10:00:00Z",
                service="consult",
                clinic_id=COSMETIC_ID,
            )
        ],
        patient_items=[{**patient(), "clinic_id": COSMETIC_ID}],
    )
    result = move(clinic_id=COSMETIC_ID, new_starts_at="2026-07-01T13:00:00Z")
    # 30-minute grid, 60-minute consult: 14:00 local, ending at 15:00.
    assert result["local_start"] == "14:00"
    assert result["local_end"] == "15:00"
    # And a time off that clinic's grid is refused, though it is on the
    # dental clinic's.
    with pytest.raises(ConflictError):
        move(clinic_id=COSMETIC_ID, new_starts_at="2026-07-01T13:15:00Z")


# --------------------------------------------------------------------------
# Cancelling
# --------------------------------------------------------------------------


def test_cancel_sets_the_status_and_reads_back_what_was_cancelled(tables) -> None:
    _, store, _ = tables(appointment_items=one_checkup())
    result = drop(reason="Patient is away that week")

    assert result["status"] == "cancelled"
    assert result["appointment_id"] == "apt_one"
    assert result["clinic_id"] == DENTAL_ID
    assert result["starts_at"] == NINE
    assert result["local_start"] == "09:00"
    assert result["local_end"] == "09:15"
    assert result["date"] == "2026-07-01"
    assert result["service"]["name"] == "Check-up"
    assert result["reason"] == "Patient is away that week"
    assert result["patient"]["patient_id"] == PATIENT_ID

    stored = store.stored("apt_one")
    assert stored["status"] == "cancelled"
    assert stored["updated_at"] == NOW
    # History, not deletion: the clinic keeps its record.
    assert stored["starts_at"] == NINE


def test_cancel_records_a_move_to_nowhere(tables) -> None:
    _, store, _ = tables(appointment_items=one_checkup())
    drop(reason="Patient is away that week")
    assert store.stored("apt_one")["reschedule_history"] == [
        {
            "at": NOW,
            "from": NINE,
            "to": None,
            "actor": "agent",
            "reason": "Patient is away that week",
        }
    ]


def test_cancel_without_a_reason_still_logs_who_did_it(tables) -> None:
    _, store, _ = tables(appointment_items=one_checkup())
    result = drop()
    entry = store.stored("apt_one")["reschedule_history"][0]
    assert entry["reason"] is None
    assert entry["actor"] == "agent"
    assert result["reason"] is None


def test_cancelling_frees_the_slot(tables) -> None:
    """The property that matters to the next caller, end to end."""
    _, store, _ = tables(appointment_items=one_checkup())
    before = scheduling.check_availability(DENTAL_ID, "2026-07-01", "checkup")
    assert "09:00" not in [slot["local_start"] for slot in before["slots"]]

    drop()

    after = scheduling.check_availability(DENTAL_ID, "2026-07-01", "checkup")
    assert "09:00" in [slot["local_start"] for slot in after["slots"]]


def test_rescheduling_frees_the_old_time_and_takes_the_new_one(tables) -> None:
    _, store, _ = tables(appointment_items=one_checkup())
    move(new_starts_at=TEN)
    offered = [
        slot["local_start"]
        for slot in scheduling.check_availability(DENTAL_ID, "2026-07-01", "checkup")[
            "slots"
        ]
    ]
    assert "09:00" in offered
    assert "10:00" not in offered


# --------------------------------------------------------------------------
# The write itself
# --------------------------------------------------------------------------


@pytest.mark.parametrize("tool", ["reschedule", "cancel"])
def test_the_update_is_conditional_on_the_state_that_was_read(tool, tables) -> None:
    """Two sessions changing one appointment resolve to a single winner."""
    _, store, _ = tables(appointment_items=one_checkup())
    (move if tool == "reschedule" else drop)(
        **({"new_starts_at": TEN} if tool == "reschedule" else {})
    )
    update = store.updates[0]
    names = update["ExpressionAttributeNames"]
    values = update["ExpressionAttributeValues"]
    condition = update["ConditionExpression"]
    status_alias = next(alias for alias, name in names.items() if name == "status")
    start_alias = next(alias for alias, name in names.items() if name == "starts_at")
    assert f"{status_alias} = :scheduled" in condition
    assert f"{start_alias} = :read_start" in condition
    assert values[":scheduled"] == "scheduled"
    assert values[":read_start"] == NINE


@pytest.mark.parametrize("tool", ["reschedule", "cancel"])
def test_the_update_is_keyed_on_the_clinic_and_the_appointment(tool, tables) -> None:
    _, store, _ = tables(appointment_items=one_checkup())
    (move if tool == "reschedule" else drop)(
        **({"new_starts_at": TEN} if tool == "reschedule" else {})
    )
    assert store.updates[0]["Key"] == {
        "clinic_id": DENTAL_ID,
        "appointment_id": "apt_one",
    }


@pytest.mark.parametrize("tool", ["reschedule", "cancel"])
def test_a_lost_race_becomes_a_conflict_not_a_crash(tool, tables) -> None:
    """Someone else moved or cancelled it between the read and the write."""
    _, store, _ = tables(appointment_items=one_checkup())
    store.fail_condition = True
    with pytest.raises(ConflictError) as raised:
        (move if tool == "reschedule" else drop)(
            **({"new_starts_at": TEN} if tool == "reschedule" else {})
        )
    assert "changed while this call was in progress" in str(raised.value)


@pytest.mark.parametrize("tool", ["reschedule", "cancel"])
def test_an_unrelated_client_error_is_not_swallowed(tool, tables, monkeypatch) -> None:
    """Only a failed condition becomes a `ConflictError`."""
    _, store, _ = tables(appointment_items=one_checkup())

    def throttled(**kwargs: Any) -> dict[str, Any]:
        raise ClientError(
            {"Error": {"Code": "ProvisionedThroughputExceededException"}}, "UpdateItem"
        )

    monkeypatch.setattr(store, "update_item", throttled)
    with pytest.raises(ClientError):
        (move if tool == "reschedule" else drop)(
            **({"new_starts_at": TEN} if tool == "reschedule" else {})
        )


def test_each_change_is_a_single_update(tables) -> None:
    """The move and its history entry cannot land separately."""
    _, store, _ = tables(appointment_items=one_checkup())
    move(new_starts_at=TEN)
    assert len(store.updates) == 1


# --------------------------------------------------------------------------
# The shared lookup
# --------------------------------------------------------------------------


def test_find_upcoming_appointments_returns_them_earliest_first(tables) -> None:
    _, store, _ = tables(
        appointment_items=[
            booked("apt_two", NEXT_DAY_TEN, "2026-07-02T09:15:00Z"),
            booked("apt_one", NINE, NINE_FIFTEEN),
            booked("apt_done", "2026-06-01T08:00:00Z", "2026-06-01T08:15:00Z"),
            booked("apt_gone", TEN, "2026-07-01T09:15:00Z", status="cancelled"),
        ]
    )
    found = appointments.find_upcoming_appointments(DENTAL_ID, PHONE, NAME)
    assert [item["appointment_id"] for item in found] == ["apt_one", "apt_two"]


def test_find_upcoming_appointments_is_empty_for_an_unknown_caller(tables) -> None:
    """Not an error: "nobody by that name" and "nothing booked" are one answer."""
    tables(appointment_items=one_checkup())
    assert appointments.find_upcoming_appointments(DENTAL_ID, PHONE, "Someone Else") == []


def test_find_upcoming_appointments_pages(tables) -> None:
    """The by-patient query is paginated like every other one in this layer."""
    _, store, _ = tables(appointment_items=one_checkup())
    calls = {"count": 0}
    real_query = store.query

    def paged(**kwargs: Any) -> dict[str, Any]:
        response = real_query(**kwargs)
        calls["count"] += 1
        if calls["count"] == 1 and kwargs["IndexName"] == "by-patient":
            return {"Items": [], "LastEvaluatedKey": {"page": 0}}
        return response

    store.query = paged  # type: ignore[method-assign]
    found = appointments.find_upcoming_appointments(DENTAL_ID, PHONE, NAME)
    assert [item["appointment_id"] for item in found] == ["apt_one"]


# --------------------------------------------------------------------------
# The dashboard's clinic-wide, one-day list
# --------------------------------------------------------------------------

# NINE and TEN are both 2026-07-01 local for the dental clinic (BST, so
# 08:00Z/09:00Z are 09:00/10:00 local); NEXT_DAY_TEN is the day after.
JULY_FIRST = "2026-07-01"
JULY_SECOND = "2026-07-02"


@pytest.mark.parametrize("clinic_id", ["", "   ", None])
def test_list_appointments_blank_clinic_id_fails_before_any_read(clinic_id, tables) -> None:
    clinics, store, _ = tables(appointment_items=one_checkup())
    with pytest.raises(ValidationError):
        appointments.list_appointments_for_clinic(clinic_id, JULY_FIRST)
    assert clinics.requested == []
    assert store.queries == []


def test_list_appointments_unknown_clinic_is_not_found(tables) -> None:
    tables(appointment_items=[], clinics=FakeClinicsTable(dental_clinic()))
    with pytest.raises(NotFoundError):
        appointments.list_appointments_for_clinic("clinic-nope", JULY_FIRST)


def test_list_appointments_is_scoped_to_the_requested_clinic(tables) -> None:
    """`architecture.md` -> Invariants #1: the query cannot reach another tenant."""
    _, store, _ = tables(
        appointment_items=[
            booked("apt_dental", NINE, NINE_FIFTEEN),
            booked("apt_cosmetic", NINE, NINE_FIFTEEN, clinic_id=COSMETIC_ID),
        ]
    )
    result = appointments.list_appointments_for_clinic(DENTAL_ID, JULY_FIRST)
    assert [item["appointment_id"] for item in result["appointments"]] == ["apt_dental"]
    assert result["clinic_id"] == DENTAL_ID
    assert result["date"] == JULY_FIRST
    assert result["timezone"] == "Europe/London"

    assert store.queries[0]["IndexName"] == "by-start-time"
    condition = store.queries[0]["KeyConditionExpression"].get_expression()
    assert condition["operator"] == "AND"


def test_list_appointments_returns_soonest_first_any_status(tables) -> None:
    _, store, _ = tables(
        appointment_items=[
            booked("apt_two", TEN, "2026-07-01T09:15:00Z", status="cancelled"),
            booked("apt_one", NINE, NINE_FIFTEEN),
        ]
    )
    result = appointments.list_appointments_for_clinic(DENTAL_ID, JULY_FIRST)
    # A cancelled appointment is still listed -- unlike
    # `upcoming_appointments_for_patient`, this is a review list, not a
    # "what can this caller still change" one.
    assert [item["appointment_id"] for item in result["appointments"]] == [
        "apt_one",
        "apt_two",
    ]


def test_list_appointments_a_different_days_appointment_is_excluded(tables) -> None:
    tables(
        appointment_items=[
            booked("apt_first", NINE, NINE_FIFTEEN),
            booked("apt_second", NEXT_DAY_TEN, "2026-07-02T09:15:00Z"),
        ]
    )
    first_day = appointments.list_appointments_for_clinic(DENTAL_ID, JULY_FIRST)
    assert [item["appointment_id"] for item in first_day["appointments"]] == ["apt_first"]

    second_day = appointments.list_appointments_for_clinic(DENTAL_ID, JULY_SECOND)
    assert [item["appointment_id"] for item in second_day["appointments"]] == ["apt_second"]


def test_list_appointments_defaults_to_the_clinics_current_local_date(tables) -> None:
    """No `date` given -- the dashboard opens on "today", clinic-local.

    `now` (2026-06-30T12:00:00Z) is 2026-06-30 local for the dental
    clinic; NINE, the day after, must not appear in the default listing.
    """
    _, store, _ = tables(
        appointment_items=[
            booked("apt_today", "2026-06-30T11:00:00Z", "2026-06-30T11:15:00Z"),
            booked("apt_tomorrow", NINE, NINE_FIFTEEN),
        ],
        now=NOW,
    )
    result = appointments.list_appointments_for_clinic(DENTAL_ID)
    assert result["date"] == "2026-06-30"
    assert [item["appointment_id"] for item in result["appointments"]] == ["apt_today"]


def test_list_appointments_limit_caps_the_result(tables) -> None:
    tables(
        appointment_items=[
            booked("apt_one", NINE, NINE_FIFTEEN),
            booked("apt_two", TEN, "2026-07-01T09:15:00Z"),
        ]
    )
    result = appointments.list_appointments_for_clinic(DENTAL_ID, JULY_FIRST, limit=1)
    assert [item["appointment_id"] for item in result["appointments"]] == ["apt_one"]


@pytest.mark.parametrize("limit", [0, -1, 201, "not-a-number"])
def test_list_appointments_limit_out_of_range_is_rejected(limit, tables) -> None:
    tables(appointment_items=one_checkup())
    with pytest.raises(ValidationError):
        appointments.list_appointments_for_clinic(DENTAL_ID, JULY_FIRST, limit=limit)


def test_list_appointments_unparseable_date_is_rejected(tables) -> None:
    tables(appointment_items=one_checkup())
    with pytest.raises(ValidationError):
        appointments.list_appointments_for_clinic(DENTAL_ID, "not-a-date")
