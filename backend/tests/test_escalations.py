"""Tests for `create_escalation`, `list_open_escalations`, `resolve_escalation`.

Three properties carry the weight here, and they are not the same three the
scheduling suites assert.

*An escalation is always recorded.* It is written when everything else has
already failed, so `create_escalation` must not acquire a new way to fail:
a `patient_id` or `appointment_id` that resolves to nothing still produces
a stored item, and no read happens on the way.

*The queue is the newest open items, in an order that does not wobble.*
The cap is applied after the status filter, not by DynamoDB's `Limit`, so
a clinic whose newest items are all resolved still shows the open ones
behind them; items sharing a `created_at` second are ordered by id, so two
identical calls agree.

*Resolving twice is refused, not absorbed.* Both the read-time check and
the conditional write are asserted, because they cover different moments:
one catches a queue the staff member is looking at going stale, the other
catches the seconds while they click.

The fake table below stores items and applies the `UpdateExpression` it is
given rather than only recording it, as `test_appointments`' does, so a
malformed expression fails here instead of in a deployed Lambda. Time is
pinned: `utc_now_iso` is monkeypatched, since `created_at` is the sort key
the queue's order is defined by.
"""

from __future__ import annotations

from typing import Any

import pytest
from botocore.exceptions import ClientError

from tools import escalations
from tools.errors import ConflictError, NotFoundError, ValidationError
from tools.schema import EscalationSource, EscalationStatus

DENTAL_ID = "clinic_dental"
COSMETIC_ID = "clinic_cosmetic"

NOW = "2026-07-01T09:00:00Z"
LATER = "2026-07-01T11:30:00Z"


def escalation(
    escalation_id: str,
    created_at: str = NOW,
    *,
    status: str = EscalationStatus.OPEN.value,
    clinic_id: str = DENTAL_ID,
    source: str = EscalationSource.VOICE.value,
    reason: str = "Patient asked about a refund.",
    **extra: Any,
) -> dict[str, Any]:
    """One `Escalations` item, as `create_escalation` writes it."""
    item: dict[str, Any] = {
        "clinic_id": clinic_id,
        "escalation_id": escalation_id,
        "status": status,
        "source": source,
        "reason": reason,
        "created_at": created_at,
    }
    item.update(extra)
    return item


# --------------------------------------------------------------------------
# A fake `Escalations` table that actually stores things
# --------------------------------------------------------------------------


class FakeEscalationsTable:
    """`get_item`, `query`, `put_item` and `update_item` over one item list.

    The query half honours the index's partition key and `ScanIndexForward`
    and serves the items in fixed-size pages, so pagination and the
    newest-first read are exercised rather than assumed. `update_item`
    applies its own expression, so the aliasing that `status` (a reserved
    word) forces is checked against what it does rather than what it says.
    """

    def __init__(self, *items: dict[str, Any], page_size: int = 25) -> None:
        self.items = [dict(item) for item in items]
        self.page_size = page_size
        self.gets: list[dict[str, Any]] = []
        self.queries: list[dict[str, Any]] = []
        self.puts: list[dict[str, Any]] = []
        self.updates: list[dict[str, Any]] = []
        # Set to simulate another staff member resolving the row first.
        self.fail_condition = False

    def get_item(self, *, Key: dict[str, Any]) -> dict[str, Any]:  # noqa: N803
        self.gets.append(Key)
        item = next(
            (
                candidate
                for candidate in self.items
                if candidate["clinic_id"] == Key["clinic_id"]
                and candidate["escalation_id"] == Key["escalation_id"]
            ),
            None,
        )
        return {"Item": dict(item)} if item is not None else {}

    def query(self, **kwargs: Any) -> dict[str, Any]:
        self.queries.append(kwargs)
        expression = kwargs["KeyConditionExpression"].get_expression()
        assert expression["operator"] == "=", "the queue reads a whole partition"
        clinic_id = expression["values"][1]
        matched = [
            dict(item) for item in self.items if item.get("clinic_id") == clinic_id
        ]
        # Ordered by the index's own sort key, then reversed for a
        # backwards read -- what `ScanIndexForward=False` means.
        matched.sort(key=lambda item: str(item.get("created_at", "")))
        if kwargs.get("ScanIndexForward") is False:
            matched.reverse()

        start = 0 if kwargs.get("ExclusiveStartKey") is None else (
            kwargs["ExclusiveStartKey"]["offset"]
        )
        page = matched[start : start + self.page_size]
        response: dict[str, Any] = {"Items": page}
        if start + self.page_size < len(matched):
            response["LastEvaluatedKey"] = {"offset": start + self.page_size}
        return response

    def put_item(self, **kwargs: Any) -> dict[str, Any]:
        self.puts.append(kwargs)
        self.items.append(dict(kwargs["Item"]))
        return {}

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

    def stored(self, escalation_id: str) -> dict[str, Any]:
        return next(
            item for item in self.items if item["escalation_id"] == escalation_id
        )

    def _apply(self, kwargs: dict[str, Any]) -> None:
        key = kwargs["Key"]
        item = next(
            candidate
            for candidate in self.items
            if candidate["clinic_id"] == key["clinic_id"]
            and candidate["escalation_id"] == key["escalation_id"]
        )
        names = kwargs["ExpressionAttributeNames"]
        values = kwargs["ExpressionAttributeValues"]
        expression = kwargs["UpdateExpression"]
        assert expression.startswith("SET ")
        for assignment in expression[len("SET ") :].split(","):
            target, separator, source = assignment.partition(" = ")
            assert separator, f"unparseable assignment {assignment!r}"
            item[names[target.strip()]] = values[source.strip()]


@pytest.fixture
def table(monkeypatch: pytest.MonkeyPatch):
    """Point `escalations_table` at a fake and pin the clock."""

    def install(
        *items: dict[str, Any], now: str = NOW, page_size: int = 25
    ) -> FakeEscalationsTable:
        fake = FakeEscalationsTable(*items, page_size=page_size)
        monkeypatch.setattr(escalations, "escalations_table", lambda: fake)
        monkeypatch.setattr(escalations, "utc_now_iso", lambda: now)
        return fake

    return install


# --------------------------------------------------------------------------
# The tenant boundary
# --------------------------------------------------------------------------


@pytest.mark.parametrize("clinic_id", ["", "   ", None])
@pytest.mark.parametrize(
    "call",
    [
        lambda clinic_id: escalations.create_escalation(clinic_id, "Refund question."),
        lambda clinic_id: escalations.list_open_escalations(clinic_id),
        lambda clinic_id: escalations.get_escalation(clinic_id, "esc_one"),
        lambda clinic_id: escalations.resolve_escalation(clinic_id, "esc_one"),
    ],
    ids=["create", "list", "get", "resolve"],
)
def test_blank_clinic_id_fails_before_any_access(clinic_id, call, table) -> None:
    """`code-standards.md`: the tenant check runs *before anything else*."""
    fake = table(escalation("esc_one"))
    with pytest.raises(ValidationError):
        call(clinic_id)
    assert fake.gets == []
    assert fake.queries == []
    assert fake.puts == []
    assert fake.updates == []


@pytest.mark.parametrize(
    ("call", "second_argument"),
    [
        (lambda: escalations.create_escalation("", ""), "reason"),
        (lambda: escalations.list_open_escalations("", limit=0), "limit"),
        (lambda: escalations.get_escalation("", ""), "escalation_id"),
        (lambda: escalations.resolve_escalation("", ""), "escalation_id"),
    ],
    ids=["create", "list", "get", "resolve"],
)
def test_the_tenant_check_runs_before_the_other_checks(
    call, second_argument, table
) -> None:
    """"Before doing anything else" includes before validating anything else.

    With every argument bad, the failure must still be the `clinic_id` one:
    that ordering is the boundary `code-standards.md` fixes, and without
    this the two checks could be swapped with no test noticing.
    """
    table()
    with pytest.raises(ValidationError) as error:
        call()
    assert "clinic_id" in str(error.value)
    assert second_argument not in str(error.value)


def test_queue_query_is_partitioned_on_the_clinic(table) -> None:
    """`by-created-at` is keyed on `clinic_id`, so it cannot be widened."""
    fake = table(escalation("esc_dental"), escalation("esc_other", clinic_id=COSMETIC_ID))
    assert [item["escalation_id"] for item in escalations.list_open_escalations(DENTAL_ID)] == [
        "esc_dental"
    ]
    query = fake.queries[0]
    assert query["IndexName"] == "by-created-at"
    assert query["KeyConditionExpression"].get_expression()["values"][1] == DENTAL_ID


def test_another_clinics_escalation_is_simply_not_found(table) -> None:
    """Indistinguishable from one that never existed (`errors.NotFoundError`)."""
    table(escalation("esc_other", clinic_id=COSMETIC_ID))
    with pytest.raises(NotFoundError) as first:
        escalations.get_escalation(DENTAL_ID, "esc_other")
    with pytest.raises(NotFoundError) as second:
        escalations.get_escalation(DENTAL_ID, "esc_never_existed")
    assert str(first.value).replace("esc_other", "X") == str(second.value).replace(
        "esc_never_existed", "X"
    )


def test_resolving_another_clinics_escalation_writes_nothing(table) -> None:
    fake = table(escalation("esc_other", clinic_id=COSMETIC_ID))
    with pytest.raises(NotFoundError):
        escalations.resolve_escalation(DENTAL_ID, "esc_other")
    assert fake.updates == []
    assert fake.stored("esc_other")["status"] == EscalationStatus.OPEN.value


# --------------------------------------------------------------------------
# create_escalation
# --------------------------------------------------------------------------


def test_create_writes_an_open_voice_escalation(table) -> None:
    fake = table()
    result = escalations.create_escalation(DENTAL_ID, "Patient wants a refund.")

    assert result["clinic_id"] == DENTAL_ID
    assert result["escalation_id"].startswith("esc_")
    assert result["status"] == EscalationStatus.OPEN.value
    assert result["source"] == EscalationSource.VOICE.value
    assert result["reason"] == "Patient wants a refund."
    assert result["created_at"] == NOW
    # Returned as written, without a second read.
    assert fake.stored(result["escalation_id"]) == result
    assert fake.gets == []
    assert fake.queries == []


def test_create_guards_against_an_id_collision(table) -> None:
    """A fresh uuid4 cannot collide, so this can only fire on a bug."""
    fake = table()
    escalations.create_escalation(DENTAL_ID, "Refund question.")
    condition = fake.puts[0]["ConditionExpression"].get_expression()
    assert condition["operator"] == "attribute_not_exists"
    assert condition["values"][0].name == "escalation_id"


def test_background_source_is_recorded_not_inferred(table) -> None:
    """The dashboard shows both paths in one queue, so which is which is stored."""
    table()
    result = escalations.create_escalation(
        DENTAL_ID,
        "Third no-show; needs a staff decision.",
        source=EscalationSource.BACKGROUND,
    )
    assert result["source"] == EscalationSource.BACKGROUND.value


def test_source_accepts_the_string_form(table) -> None:
    table()
    result = escalations.create_escalation(DENTAL_ID, "Refund.", source="background")
    assert result["source"] == EscalationSource.BACKGROUND.value


def test_an_unknown_source_is_refused_rather_than_stored(table) -> None:
    fake = table()
    with pytest.raises(ValidationError) as error:
        escalations.create_escalation(DENTAL_ID, "Refund.", source="sms")
    # The message lists the vocabulary, since the caller often guessed.
    assert "voice" in str(error.value) and "background" in str(error.value)
    assert fake.puts == []


def test_back_references_are_stored_when_given(table) -> None:
    table()
    result = escalations.create_escalation(
        DENTAL_ID,
        "Patient disputes the appointment time.",
        patient_id="pat_dana",
        appointment_id="apt_one",
    )
    assert result["patient_id"] == "pat_dana"
    assert result["appointment_id"] == "apt_one"


def test_back_references_are_omitted_rather_than_null(table) -> None:
    """An absent attribute is what "not about a patient" looks like."""
    table()
    result = escalations.create_escalation(DENTAL_ID, "General complaint.")
    assert "patient_id" not in result
    assert "appointment_id" not in result


def test_an_unresolvable_back_reference_still_records_the_escalation(table) -> None:
    """The module's first rule: creating one must not gain a way to fail."""
    fake = table()
    result = escalations.create_escalation(
        DENTAL_ID,
        "Caller referred to a booking we cannot find.",
        patient_id="pat_gone",
        appointment_id="apt_gone",
    )
    assert fake.stored(result["escalation_id"])["patient_id"] == "pat_gone"
    # Nothing was read on the way -- no lookup that could have failed.
    assert fake.gets == []
    assert fake.queries == []


@pytest.mark.parametrize("reason", ["", "   ", None])
def test_an_escalation_with_no_reason_is_refused(reason, table) -> None:
    """A human reads this to decide what to do; an empty one tells them nothing."""
    fake = table()
    with pytest.raises(ValidationError):
        escalations.create_escalation(DENTAL_ID, reason)
    assert fake.puts == []


def test_an_over_long_reason_is_refused(table) -> None:
    """Stops a model pasting a whole transcript into the queue."""
    fake = table()
    with pytest.raises(ValidationError):
        escalations.create_escalation(DENTAL_ID, "x" * 2001)
    assert fake.puts == []


@pytest.mark.parametrize("field", ["patient_id", "appointment_id"])
def test_a_malformed_back_reference_is_refused(field, table) -> None:
    fake = table()
    with pytest.raises(ValidationError) as error:
        escalations.create_escalation(DENTAL_ID, "Refund.", **{field: "   "})
    assert field in str(error.value)
    assert fake.puts == []


# --------------------------------------------------------------------------
# list_open_escalations
# --------------------------------------------------------------------------


def test_the_queue_is_newest_first(table) -> None:
    table(
        escalation("esc_old", "2026-06-28T09:00:00Z"),
        escalation("esc_new", "2026-06-30T09:00:00Z"),
        escalation("esc_middle", "2026-06-29T09:00:00Z"),
    )
    assert [
        item["escalation_id"] for item in escalations.list_open_escalations(DENTAL_ID)
    ] == ["esc_new", "esc_middle", "esc_old"]


def test_the_queue_reads_the_index_backwards(table) -> None:
    """Newest-first is the index read in reverse, not a sort of the partition."""
    fake = table(escalation("esc_one"))
    escalations.list_open_escalations(DENTAL_ID)
    assert fake.queries[0]["ScanIndexForward"] is False


def test_resolved_escalations_are_filtered_out(table) -> None:
    table(
        escalation("esc_open", "2026-06-28T09:00:00Z"),
        escalation(
            "esc_done",
            "2026-06-30T09:00:00Z",
            status=EscalationStatus.RESOLVED.value,
            resolved_at=LATER,
        ),
    )
    assert [
        item["escalation_id"] for item in escalations.list_open_escalations(DENTAL_ID)
    ] == ["esc_open"]


def test_an_unrecognised_status_is_not_shown_as_open(table) -> None:
    """`open` is matched, not `resolved` excluded: bad data leaves the queue clean."""
    table(escalation("esc_weird", status="pending"))
    assert escalations.list_open_escalations(DENTAL_ID) == []


def test_an_empty_queue_is_empty_not_an_error(table) -> None:
    table()
    assert escalations.list_open_escalations(DENTAL_ID) == []


def test_ties_on_created_at_are_broken_by_id(table) -> None:
    """`created_at` is second-precision, so two calls must still agree."""
    same_second = "2026-06-30T09:00:00Z"
    fake = table(
        escalation("esc_a", same_second),
        escalation("esc_b", same_second),
        escalation("esc_c", same_second),
    )
    first = [i["escalation_id"] for i in escalations.list_open_escalations(DENTAL_ID)]
    # The same three items in a different stored order -- which is all
    # DynamoDB guarantees for items sharing a sort key.
    fake.items = [
        escalation("esc_c", same_second),
        escalation("esc_a", same_second),
        escalation("esc_b", same_second),
    ]
    second = [i["escalation_id"] for i in escalations.list_open_escalations(DENTAL_ID)]
    assert first == second == ["esc_c", "esc_b", "esc_a"]


def test_the_queue_pages_through_the_whole_partition(table) -> None:
    """One page of the index is not one answer."""
    fake = table(
        *(
            escalation(f"esc_{index:02d}", f"2026-06-{index + 1:02d}T09:00:00Z")
            for index in range(12)
        ),
        page_size=5,
    )
    assert len(escalations.list_open_escalations(DENTAL_ID)) == 12
    assert len(fake.queries) == 3


def test_the_cap_is_applied_after_the_status_filter(table) -> None:
    """A `Limit` sent to DynamoDB would count scanned items and return nothing.

    Sixty resolved escalations sit in front of three open ones. Every page
    has to be walked to reach them, and the queue must not come back empty
    while the clinic has work outstanding.
    """
    fake = table(
        *(
            escalation(
                f"esc_done_{index:02d}",
                f"2026-07-{index + 1:02d}T09:00:00Z",
                status=EscalationStatus.RESOLVED.value,
            )
            for index in range(30)
        ),
        *(
            escalation(f"esc_open_{index}", f"2026-06-{index + 1:02d}T09:00:00Z")
            for index in range(3)
        ),
        page_size=10,
    )
    found = escalations.list_open_escalations(DENTAL_ID)
    assert [item["escalation_id"] for item in found] == [
        "esc_open_2",
        "esc_open_1",
        "esc_open_0",
    ]
    # No `Limit` is sent: it counts items scanned, not items kept.
    assert all("Limit" not in query for query in fake.queries)


def test_the_limit_bounds_the_result_and_stops_paging_early(table) -> None:
    fake = table(
        *(
            escalation(f"esc_{index:02d}", f"2026-06-{index + 1:02d}T09:00:00Z")
            for index in range(20)
        ),
        page_size=5,
    )
    found = escalations.list_open_escalations(DENTAL_ID, limit=3)
    assert [item["escalation_id"] for item in found] == ["esc_19", "esc_18", "esc_17"]
    # The first page already held enough; the rest of the partition is
    # never read.
    assert len(fake.queries) == 1


def test_the_default_limit_applies_when_none_is_given(table) -> None:
    table(
        *(
            escalation(f"esc_{index:03d}", f"2026-06-{index % 28 + 1:02d}T09:00:00Z")
            for index in range(80)
        ),
        page_size=25,
    )
    assert len(escalations.list_open_escalations(DENTAL_ID)) == (
        escalations.DEFAULT_ESCALATION_LIMIT
    )


@pytest.mark.parametrize("limit", [0, -1, 101, "many", 2.5])
def test_an_out_of_range_limit_is_refused_rather_than_clamped(limit, table) -> None:
    """A caller that asked for 500 has misunderstood; clamping would hide that."""
    fake = table(escalation("esc_one"))
    with pytest.raises(ValidationError):
        escalations.list_open_escalations(DENTAL_ID, limit=limit)
    assert fake.queries == []


def test_the_limit_accepts_a_string_a_model_produced(table) -> None:
    table(escalation("esc_a", "2026-06-01T09:00:00Z"), escalation("esc_b", "2026-06-02T09:00:00Z"))
    assert len(escalations.list_open_escalations(DENTAL_ID, limit="1")) == 1


def test_the_queue_returns_whole_items(table) -> None:
    """The dashboard renders every field; nothing is shaped away here."""
    table(escalation("esc_one", patient_id="pat_dana", appointment_id="apt_one"))
    (found,) = escalations.list_open_escalations(DENTAL_ID)
    assert found["patient_id"] == "pat_dana"
    assert found["appointment_id"] == "apt_one"
    assert found["reason"] == "Patient asked about a refund."
    assert found["source"] == EscalationSource.VOICE.value


# --------------------------------------------------------------------------
# get_escalation
# --------------------------------------------------------------------------


def test_get_reads_one_item_by_key(table) -> None:
    fake = table(escalation("esc_one"))
    assert escalations.get_escalation(DENTAL_ID, "esc_one")["escalation_id"] == "esc_one"
    assert fake.gets == [{"clinic_id": DENTAL_ID, "escalation_id": "esc_one"}]


def test_get_finds_a_resolved_escalation_too(table) -> None:
    """The detail modal opens what the queue no longer lists."""
    table(
        escalation(
            "esc_done", status=EscalationStatus.RESOLVED.value, resolved_at=LATER
        )
    )
    found = escalations.get_escalation(DENTAL_ID, "esc_done")
    assert found["status"] == EscalationStatus.RESOLVED.value


@pytest.mark.parametrize("escalation_id", ["", "   ", None])
def test_a_blank_escalation_id_is_refused(escalation_id, table) -> None:
    fake = table(escalation("esc_one"))
    with pytest.raises(ValidationError):
        escalations.get_escalation(DENTAL_ID, escalation_id)
    assert fake.gets == []


# --------------------------------------------------------------------------
# resolve_escalation
# --------------------------------------------------------------------------


def test_resolve_marks_it_handled_and_stamps_the_time(table) -> None:
    fake = table(escalation("esc_one"), now=LATER)
    result = escalations.resolve_escalation(DENTAL_ID, "esc_one")

    assert result["status"] == EscalationStatus.RESOLVED.value
    assert result["resolved_at"] == LATER
    # The returned view matches what the table now holds -- the update
    # expression is applied by the fake, not merely recorded.
    stored = fake.stored("esc_one")
    assert stored["status"] == EscalationStatus.RESOLVED.value
    assert stored["resolved_at"] == LATER


def test_resolve_keeps_the_record_rather_than_deleting_it(table) -> None:
    fake = table(escalation("esc_one", reason="Patient wants a refund."))
    result = escalations.resolve_escalation(DENTAL_ID, "esc_one")
    assert result["reason"] == "Patient wants a refund."
    assert result["created_at"] == NOW
    assert len(fake.items) == 1


def test_a_resolved_escalation_leaves_the_queue(table) -> None:
    table(escalation("esc_one"))
    escalations.resolve_escalation(DENTAL_ID, "esc_one")
    assert escalations.list_open_escalations(DENTAL_ID) == []


def test_resolving_a_missing_escalation_writes_nothing(table) -> None:
    fake = table()
    with pytest.raises(NotFoundError):
        escalations.resolve_escalation(DENTAL_ID, "esc_nope")
    assert fake.updates == []


def test_resolving_twice_is_refused(table) -> None:
    """Two staff on one queue: the second must hear that it is already done."""
    fake = table(escalation("esc_one"), now=LATER)
    escalations.resolve_escalation(DENTAL_ID, "esc_one")
    with pytest.raises(ConflictError) as error:
        escalations.resolve_escalation(DENTAL_ID, "esc_one")
    assert "already resolved" in str(error.value)
    assert LATER in str(error.value)
    # One write, from the first call only.
    assert len(fake.updates) == 1


def test_a_lost_race_is_a_conflict_not_a_silent_overwrite(table) -> None:
    """The row went resolved between this call's read and its write."""
    fake = table(escalation("esc_one"))
    fake.fail_condition = True
    with pytest.raises(ConflictError) as error:
        escalations.resolve_escalation(DENTAL_ID, "esc_one")
    assert "someone else" in str(error.value)


def test_the_write_is_conditioned_on_the_escalation_still_being_open(table) -> None:
    fake = table(escalation("esc_one"))
    escalations.resolve_escalation(DENTAL_ID, "esc_one")
    update = fake.updates[0]
    names = update["ExpressionAttributeNames"]
    condition = update["ConditionExpression"]
    assert names[condition.split(" = ")[0]] == "status"
    assert update["ExpressionAttributeValues"][condition.split(" = ")[1]] == (
        EscalationStatus.OPEN.value
    )


def test_status_is_written_through_an_alias(table) -> None:
    """`status` is a DynamoDB reserved word; inline would fail only when deployed."""
    fake = table(escalation("esc_one"))
    escalations.resolve_escalation(DENTAL_ID, "esc_one")
    expression = fake.updates[0]["UpdateExpression"]
    assert "status" not in expression.replace("#status", "")
    assert fake.updates[0]["ExpressionAttributeNames"]["#status"] == "status"


def test_any_other_client_error_propagates(table, monkeypatch) -> None:
    """Only a failed condition means "already resolved"; the rest are faults."""
    fake = table(escalation("esc_one"))

    def throttled(**kwargs: Any) -> dict[str, Any]:
        raise ClientError(
            {"Error": {"Code": "ProvisionedThroughputExceededException"}}, "UpdateItem"
        )

    monkeypatch.setattr(fake, "update_item", throttled)
    with pytest.raises(ClientError):
        escalations.resolve_escalation(DENTAL_ID, "esc_one")


# --------------------------------------------------------------------------
# End to end
# --------------------------------------------------------------------------


def test_raised_then_queued_then_resolved(table) -> None:
    """The whole escalation lifecycle over one table."""
    fake = table()
    created = escalations.create_escalation(
        DENTAL_ID, "Patient wants a refund.", patient_id="pat_dana"
    )

    (queued,) = escalations.list_open_escalations(DENTAL_ID)
    assert queued["escalation_id"] == created["escalation_id"]
    assert queued["patient_id"] == "pat_dana"

    resolved = escalations.resolve_escalation(DENTAL_ID, created["escalation_id"])
    assert resolved["status"] == EscalationStatus.RESOLVED.value
    assert resolved["reason"] == "Patient wants a refund."
    assert escalations.list_open_escalations(DENTAL_ID) == []
    # Nothing was deleted: it is still there to read afterwards.
    still_there = escalations.get_escalation(DENTAL_ID, created["escalation_id"])
    assert still_there["status"] == EscalationStatus.RESOLVED.value
    assert len(fake.items) == 1
