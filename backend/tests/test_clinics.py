"""Tests for `tools/clinics.py`, the staff-editable clinic config.

The Settings tab's whole safety argument is that a bad edit can never
land: `update_clinic_config` validates every field against the shapes
`architecture.md` -> Storage Model fixes for the availability config,
*eagerly*, before any write -- today a malformed config only fails
lazily inside `check_availability`, with a patient on the line, so the
write path is where that failure has to move to.

The clinic fixtures and the read-only fake come from
`test_scheduling.py`, the suite that owns them; the update-capable fake
extends that one the same way `test_appointments.py`'s fake extends its
own read fake. No boto3 client is ever built.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from tools.errors import NotFoundError, ValidationError

from tests.test_scheduling import DENTAL_ID, FakeClinicsTable, dental_clinic

import tools.clinics as clinics
import tools.scheduling as scheduling


# --------------------------------------------------------------------------
# Fakes
# --------------------------------------------------------------------------


class FakeUpdatableClinicsTable(FakeClinicsTable):
    """`update_item` that records the call and applies a plain `SET`.

    The same "apply it, don't assume it" discipline
    `test_appointments.py`'s fake applies: a malformed
    `UpdateExpression` fails here, in a test, rather than in a deployed
    Lambda. Only plain ``#name = :value`` assignments are supported --
    `tools.clinics` has no list appends or conditions to evaluate.
    """

    def __init__(self, *clinic_items: dict[str, Any]) -> None:
        super().__init__(*clinic_items)
        self.updates: list[dict[str, Any]] = []

    def update_item(self, **kwargs: Any) -> dict[str, Any]:  # noqa: N803
        self.updates.append(kwargs)
        names = kwargs["ExpressionAttributeNames"]
        values = kwargs["ExpressionAttributeValues"]
        expression = kwargs["UpdateExpression"]
        assert expression.startswith("SET "), expression
        item = self.items[kwargs["Key"]["clinic_id"]]
        for assignment in expression[len("SET ") :].split(", "):
            target, separator, source = assignment.partition(" = ")
            assert separator, f"unparseable assignment {assignment!r}"
            assert source.startswith(":"), f"unsupported value {source!r}"
            item[names[target]] = values[source]
        return {}


@pytest.fixture
def table(monkeypatch: pytest.MonkeyPatch) -> FakeUpdatableClinicsTable:
    """One dental clinic behind both clinics-table accessors.

    `tools.clinics` reads through `scheduling.get_clinic`, which uses
    *scheduling's* own `clinics_table` import, so patching only
    `clinics.clinics_table` leaves the read hitting real AWS -- the
    same reason `test_scheduling.py`'s `tables` fixture patches its
    module's accessors rather than `tools.dynamo`'s.
    """
    fake = FakeUpdatableClinicsTable(dental_clinic())
    monkeypatch.setattr(clinics, "clinics_table", lambda: fake)
    monkeypatch.setattr(scheduling, "clinics_table", lambda: fake)
    return fake


def valid_config() -> dict[str, Any]:
    """A config the dental clinic could plausibly move to.

    Built from the seeded shape with the Decimals swapped for ints --
    JSON numbers arrive here as `int`, never `Decimal`, because this
    value comes from a browser form rather than a DynamoDB read.
    """
    return {
        "hours": {
            "mon": [{"open": "09:00", "close": "17:00"}],
            "tue": [{"open": "09:00", "close": "17:00"}],
            "wed": [],
            "thu": [{"open": "09:00", "close": "12:00"},
                    {"open": "13:00", "close": "17:00"}],
            "fri": [{"open": "09:00", "close": "17:00"}],
            "sat": [],
            "sun": [],
        },
        "closures": [{"date": "2026-12-25", "label": "Christmas Day"}],
        "services": [
            {"id": "checkup", "name": "Check-up", "duration_minutes": 20},
        ],
        "slot_minutes": 20,
    }


# --------------------------------------------------------------------------
# get_clinic_config
# --------------------------------------------------------------------------


def test_config_read_returns_the_editable_subset(table) -> None:
    config = clinics.get_clinic_config(DENTAL_ID)
    assert config["name"] == "Bright Smile Dental"
    assert config["timezone"] == "Europe/London"
    assert config["hours"]["sat"] == [{"open": "09:00", "close": "12:00"}]
    assert config["closures"] == [{"date": "2026-07-08", "label": "Staff training day"}]
    assert config["slot_minutes"] == 15
    # Durations normalised out of DynamoDB `Decimal`s, so the JSON the
    # dashboard receives needs no special casing.
    assert config["services"][0]["duration_minutes"] == 15


def test_config_read_of_an_unknown_clinic_is_not_found(table) -> None:
    with pytest.raises(NotFoundError):
        clinics.get_clinic_config("clinic-nobody")


def test_config_read_validates_clinic_id_first(table) -> None:
    with pytest.raises(ValidationError, match="clinic_id"):
        clinics.get_clinic_config("  ")
    assert not table.requested


# --------------------------------------------------------------------------
# update_clinic_config: the write
# --------------------------------------------------------------------------


def test_a_valid_config_writes_all_four_fields_and_a_timestamp(table) -> None:
    result = clinics.update_clinic_config(DENTAL_ID, **valid_config())
    assert len(table.updates) == 1
    update = table.updates[0]
    assert update["Key"] == {"clinic_id": DENTAL_ID}
    # Every attribute through a `#name` alias, like `appointments` does
    # for the reserved `status`.
    names = update["ExpressionAttributeNames"]
    values = update["ExpressionAttributeValues"]
    stored = {names[f"#{key[1:]}"]: value for key, value in values.items()}
    assert stored["hours"] == valid_config()["hours"]
    assert stored["closures"] == valid_config()["closures"]
    assert stored["services"] == valid_config()["services"]
    assert stored["slot_minutes"] == 20
    assert stored["updated_at"].endswith("Z")
    # The stored item really carries the new config, not just the old one.
    assert table.items[DENTAL_ID]["slot_minutes"] == 20
    # The return value is the same shape `get_clinic_config` gives, so
    # the dashboard can refresh the form from it directly.
    assert result["name"] == "Bright Smile Dental"
    assert result["timezone"] == "Europe/London"
    assert result["slot_minutes"] == 20
    assert result["services"][0]["duration_minutes"] == 20


def test_the_clinic_must_exist_before_anything_is_written(table) -> None:
    config = valid_config()
    with pytest.raises(NotFoundError):
        clinics.update_clinic_config("clinic-nobody", **config)
    assert not table.updates


def test_clinic_id_is_validated_before_the_config_fields(table) -> None:
    """Every field bad at once still names `clinic_id` -- the tenant
    boundary is checked first, as it is on every tool (`test_escalations.py`
    pins the same ordering for its four functions)."""
    config = valid_config()
    config["slot_minutes"] = 0
    with pytest.raises(ValidationError, match="clinic_id"):
        clinics.update_clinic_config("  ", **config)
    assert not table.updates


def test_a_refused_config_writes_nothing(table) -> None:
    config = valid_config()
    config["hours"]["mon"][0]["close"] = "08:00"  # before it opens
    with pytest.raises(ValidationError):
        clinics.update_clinic_config(DENTAL_ID, **config)
    assert not table.updates
    assert table.items[DENTAL_ID]["slot_minutes"] == Decimal("15")


# --------------------------------------------------------------------------
# update_clinic_config: hours
# --------------------------------------------------------------------------


def test_hours_must_carry_all_seven_weekday_keys(table) -> None:
    config = valid_config()
    del config["hours"]["sun"]
    with pytest.raises(ValidationError, match="sun"):
        clinics.update_clinic_config(DENTAL_ID, **config)


def test_hours_rejects_a_key_that_is_not_a_weekday(table) -> None:
    config = valid_config()
    config["hours"]["funday"] = []
    with pytest.raises(ValidationError, match="funday"):
        clinics.update_clinic_config(DENTAL_ID, **config)


def test_hours_must_be_a_dict_of_lists(table) -> None:
    config = valid_config()
    config["hours"]["mon"] = "09:00-17:00"
    with pytest.raises(ValidationError, match="hours.mon"):
        clinics.update_clinic_config(DENTAL_ID, **config)


def test_an_interval_needs_both_open_and_close_in_hh_mm(table) -> None:
    config = valid_config()
    bad = config["hours"]["mon"][0]
    for key, value in (("open", "9:00"), ("close", None)):
        original = bad.get(key)
        bad[key] = value
        with pytest.raises(ValidationError):
            clinics.update_clinic_config(DENTAL_ID, **config)
        bad[key] = original
    bad["open"] = "25:00"
    with pytest.raises(ValidationError):
        clinics.update_clinic_config(DENTAL_ID, **config)


@pytest.mark.parametrize(
    ("intervals", "why"),
    [
        ([{"open": "12:00", "close": "12:00"}], "close equal to open"),
        ([{"open": "14:00", "close": "12:00"}], "close before open"),
        (
            [
                {"open": "13:00", "close": "17:00"},
                {"open": "09:00", "close": "12:00"},
            ],
            "descending",
        ),
        (
            [
                {"open": "09:00", "close": "14:00"},
                {"open": "13:00", "close": "17:00"},
            ],
            "overlapping",
        ),
    ],
)
def test_interval_ordering_is_enforced(table, intervals, why) -> None:
    config = valid_config()
    config["hours"]["mon"] = intervals
    with pytest.raises(ValidationError):
        clinics.update_clinic_config(DENTAL_ID, **config)
    assert not table.updates


def test_touching_intervals_are_not_overlapping(table) -> None:
    """09:00-12:00 then 12:00-17:00 is a legal working day."""
    config = valid_config()
    config["hours"]["mon"] = [
        {"open": "09:00", "close": "12:00"},
        {"open": "12:00", "close": "17:00"},
    ]
    clinics.update_clinic_config(DENTAL_ID, **config)
    assert len(table.updates) == 1


def test_an_empty_day_is_closed_not_invalid(table) -> None:
    config = valid_config()
    config["hours"]["mon"] = []
    clinics.update_clinic_config(DENTAL_ID, **config)
    assert table.items[DENTAL_ID]["hours"]["mon"] == []


# --------------------------------------------------------------------------
# update_clinic_config: closures
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "closures",
    [
        "closed on Mondays",
        [{"date": "2026-12-25"}],
        [{"label": "Christmas Day"}],
        [{"date": "25/12/2026", "label": "Christmas Day"}],
        [{"date": "2026-12-25", "label": "  "}],
        [
            {"date": "2026-12-25", "label": "Christmas Day"},
            {"date": "2026-12-25", "label": "Also Christmas"},
        ],
    ],
)
def test_bad_closures_are_refused(table, closures) -> None:
    config = valid_config()
    config["closures"] = closures
    with pytest.raises(ValidationError):
        clinics.update_clinic_config(DENTAL_ID, **config)
    assert not table.updates


def test_an_empty_closure_list_clears_the_closures(table) -> None:
    config = valid_config()
    config["closures"] = []
    clinics.update_clinic_config(DENTAL_ID, **config)
    assert table.items[DENTAL_ID]["closures"] == []


# --------------------------------------------------------------------------
# update_clinic_config: services
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "services",
    [
        [],
        "checkup",
        [{"name": "Check-up", "duration_minutes": 20}],
        [{"id": "checkup", "duration_minutes": 20}],
        [{"id": "checkup", "name": "Check-up"}],
        [{"id": "checkup", "name": "Check-up", "duration_minutes": 0}],
        [{"id": "checkup", "name": "Check-up", "duration_minutes": -5}],
        [{"id": "checkup", "name": "Check-up", "duration_minutes": 20.5}],
        [
            {"id": "checkup", "name": "Check-up", "duration_minutes": 20},
            {"id": "checkup", "name": "Check-up again", "duration_minutes": 30},
        ],
    ],
)
def test_bad_services_are_refused(table, services) -> None:
    config = valid_config()
    config["services"] = services
    with pytest.raises(ValidationError):
        clinics.update_clinic_config(DENTAL_ID, **config)
    assert not table.updates


def test_service_durations_may_arrive_as_decimals_or_digit_strings(table) -> None:
    """The same acceptance `validation.require_bounded_int` gives a model
    that read a duration off an item: `Decimal` from DynamoDB, ``"20"``
    from a form that did not parse its own number."""
    config = valid_config()
    config["services"][0]["duration_minutes"] = Decimal("20")
    clinics.update_clinic_config(DENTAL_ID, **config)
    assert table.items[DENTAL_ID]["services"][0]["duration_minutes"] == 20

    config = valid_config()
    config["services"][0]["duration_minutes"] = "25"
    clinics.update_clinic_config(DENTAL_ID, **config)
    assert table.items[DENTAL_ID]["services"][0]["duration_minutes"] == 25


# --------------------------------------------------------------------------
# update_clinic_config: slot_minutes
# --------------------------------------------------------------------------


@pytest.mark.parametrize("slot_minutes", [0, -15, 3.5, "quarter past", None])
def test_bad_slot_minutes_is_refused(table, slot_minutes) -> None:
    config = valid_config()
    config["slot_minutes"] = slot_minutes
    with pytest.raises(ValidationError, match="slot_minutes"):
        clinics.update_clinic_config(DENTAL_ID, **config)
    assert not table.updates
