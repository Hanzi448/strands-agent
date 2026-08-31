"""The seed CLI: write the two demo clinics into a deployed environment.

`progress-tracker.md` -> Next Up #2. Four independent steps -- clinics,
sample appointments, FAQ documents, staff accounts -- run in that order
(appointments need their clinic to exist first; FAQ and staff accounts
depend on neither the clinics step nor each other, but running them after
it keeps one linear log for a human watching this run rather than an
interleaved one).

Every write goes through the same layer a real call or a real dashboard
login would: `tools.booking.book_appointment` for appointments,
`aws_io.ensure_staff_account` for Cognito, so nothing seeded is a shape
the running system could not have produced itself.

Run from the repository root, against whichever deployment
`$CLINICPILOT_ENV` (and the table/bucket/pool env vars) names -- the same
resolution `tools.dynamo` and `seed.aws_io` use:

    python -m seed.run_seed --dry-run
    python -m seed.run_seed

`--dry-run` touches no AWS service at all -- it only reads this package's
own data modules -- which is the only mode this environment can actually
run (`progress-tracker.md` -> Session Notes: no AWS credentials here). A
real run needs credentials, the five stacks deployed, and
`$CLINICPILOT_STAFF_USER_POOL_ID` / `$CLINICPILOT_STAFF_DEMO_PASSWORD` /
one `$CLINICPILOT_KB_ID_...` per clinic set from `cdk deploy`'s outputs.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Final

from tools import booking, scheduling
from tools.dynamo import clinics_table
from tools.errors import ConfigurationError
from tools.schema import DATE_FORMAT, ClinicAttrs

from . import aws_io, clinic_data, faq_content, sample_data
from .sample_data import LOOKAHEAD_DAYS, SampleAppointment

logger = logging.getLogger(__name__)

STEPS: Final[tuple[str, ...]] = ("clinics", "appointments", "faq", "staff")

EXIT_OK: Final[int] = 0
EXIT_STEP_FAILED: Final[int] = 1


@dataclass(frozen=True)
class Options:
    """One invocation of the seed CLI.

    Attributes:
        skip: Step names (from `STEPS`) to leave out of this run.
        dry_run: If true, print what each requested step would do and
            touch no AWS service -- the only mode usable without
            credentials.
        verbose: Whether to log at `INFO`.
    """

    skip: frozenset[str]
    dry_run: bool
    verbose: bool


def parse_args(argv: Sequence[str] | None = None) -> Options:
    """Read the command line into an `Options`.

    Args:
        argv: Arguments without the program name. `None` reads
            `sys.argv[1:]`.

    Returns:
        The options for this run.

    Raises:
        SystemExit: On a usage error or `--help`, as argparse does.
    """
    parser = argparse.ArgumentParser(
        prog="python -m seed.run_seed",
        description=(
            "Seed the two demo clinics: config, sample appointments, FAQ"
            " documents, and staff Cognito accounts."
        ),
    )
    parser.add_argument(
        "--skip",
        choices=STEPS,
        action="append",
        default=[],
        metavar="STEP",
        help=f"Leave out one step (repeatable). One of: {', '.join(STEPS)}.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what each requested step would do; call no AWS service.",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Log at INFO instead of WARNING."
    )
    args = parser.parse_args(argv)
    return Options(skip=frozenset(args.skip), dry_run=args.dry_run, verbose=args.verbose)


# --------------------------------------------------------------------------
# Step: clinics
# --------------------------------------------------------------------------


def seed_clinics() -> list[str]:
    """Write the two demo `Clinics` items. Idempotent: `put_item` overwrites.

    Returns:
        The clinic ids written, dental then cosmetic.
    """
    table = clinics_table()
    written: list[str] = []
    for build_item in clinic_data.DEMO_CLINICS:
        item = build_item()
        table.put_item(Item=item)
        written.append(item[ClinicAttrs.CLINIC_ID])
    return written


# --------------------------------------------------------------------------
# Step: sample appointments
# --------------------------------------------------------------------------


def _target_date(days_ahead: int, today: date) -> str:
    """`days_ahead` from `today`, as the `YYYY-MM-DD` `check_availability` takes.

    `today` is UTC rather than each clinic's own timezone: this only has
    to land on the right side of midnight for a demo, and
    `check_availability` itself checks `LOOKAHEAD_DAYS` more days from
    there, so a clinic whose local date is briefly a day ahead or behind
    UTC still gets an offerable slot in the window.
    """
    return (today + timedelta(days=days_ahead)).strftime(DATE_FORMAT)


def book_sample_appointment(
    clinic_id: str, spec: SampleAppointment, *, today: date | None = None
) -> dict[str, Any]:
    """Book one sample appointment through the real availability/booking path.

    Args:
        clinic_id: The clinic to book against -- must already exist
            (`seed_clinics` runs first).
        spec: What to book.
        today: The date `spec.days_ahead` is counted from. `None` reads
            the real current date; a test passes a fixed one so the spec's
            `slot_index` lands on a predictable weekday instead of
            whatever day the suite happens to run on.

    Raises:
        ToolError: If the clinic does not exist yet or the requested
            service is unknown.
        ConfigurationError: If `check_availability` offers nothing at all
            in the window this spec searches -- a spec whose `days_ahead`
            lands on a run of closed days, most likely.
    """
    target_date = _target_date(spec.days_ahead, today or date.today())
    availability = scheduling.check_availability(
        clinic_id, target_date, spec.service_id, days=LOOKAHEAD_DAYS
    )
    slots = availability["slots"]
    if not slots:
        raise ConfigurationError(
            f"No offerable slots for {clinic_id}/{spec.service_id} in the"
            f" {LOOKAHEAD_DAYS} days from {target_date}; adjust its"
            " sample_data.SampleAppointment.days_ahead."
        )
    slot = slots[min(spec.slot_index, len(slots) - 1)]
    return booking.book_appointment(
        clinic_id=clinic_id,
        starts_at=slot["starts_at"],
        service=spec.service_id,
        patient_name=spec.patient_name,
        patient_phone=spec.patient_phone,
        patient_email=spec.patient_email,
        notes=spec.notes,
    )


def seed_sample_appointments(*, today: date | None = None) -> list[dict[str, Any]]:
    """Book every sample appointment in `sample_data.SAMPLE_APPOINTMENTS_BY_CLINIC`.

    Not idempotent: `book_appointment` has no notion of "this sample was
    already seeded", so a second run books a second, distinct set of
    appointments for the same sample patients (naturally deduplicated
    only at the *patient* level, via `tools.patients.find_patient`'s
    phone-and-name match). Intended to run once against a freshly
    deployed, empty environment.

    Args:
        today: Passed straight to `book_sample_appointment`; `None` reads
            the real current date.

    Returns:
        Every `book_appointment` result, in seeding order.
    """
    booked: list[dict[str, Any]] = []
    for clinic_id, specs in sample_data.SAMPLE_APPOINTMENTS_BY_CLINIC.items():
        for spec in specs:
            booked.append(book_sample_appointment(clinic_id, spec, today=today))
    return booked


# --------------------------------------------------------------------------
# Step: FAQ documents
# --------------------------------------------------------------------------


def seed_faq() -> dict[str, str]:
    """Upload every clinic's sample FAQ documents and start ingestion.

    Returns:
        `{clinic_id: ingestion_job_id}`.
    """
    bucket = aws_io.kb_bucket_name()
    jobs: dict[str, str] = {}
    for clinic_id, documents in faq_content.FAQ_DOCUMENTS_BY_CLINIC.items():
        aws_io.upload_faq_documents(bucket, clinic_id, documents)
        kb_id = aws_io.resolve_knowledge_base_id(clinic_id)
        jobs[clinic_id] = aws_io.start_kb_ingestion(kb_id)
    return jobs


# --------------------------------------------------------------------------
# Step: staff accounts
# --------------------------------------------------------------------------


def _staff_email(clinic_id: str) -> str:
    """`staff+clinic-dental@clinicpilot.demo` -- one obvious address per clinic."""
    return f"staff+{clinic_id}@clinicpilot.demo"


def seed_staff_accounts() -> dict[str, str]:
    """Create (or confirm) one staff Cognito account per demo clinic.

    Returns:
        `{email: "created" | "already_exists"}`.
    """
    pool_id = aws_io.staff_user_pool_id()
    password = aws_io.staff_demo_password()
    results: dict[str, str] = {}
    for clinic_id in (clinic_data.DENTAL_CLINIC_ID, clinic_data.COSMETIC_CLINIC_ID):
        email = _staff_email(clinic_id)
        results[email] = aws_io.ensure_staff_account(
            pool_id, email=email, password=password, clinic_id=clinic_id
        )
    return results


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------


def _print_dry_run(options: Options) -> None:
    """Describe every requested step without calling AWS.

    Plain `print()` rather than a `writer` parameter defaulted to
    `sys.stdout`: that default is bound once, at import time, so it would
    print past a test's `capsys` redirect -- `print()`'s own default looks
    `sys.stdout` up fresh on every call instead.
    """
    if "clinics" not in options.skip:
        names = [build()[ClinicAttrs.NAME] for build in clinic_data.DEMO_CLINICS]
        print(f"clinics: would write {', '.join(names)}")
    if "appointments" not in options.skip:
        count = sum(len(specs) for specs in sample_data.SAMPLE_APPOINTMENTS_BY_CLINIC.values())
        print(f"appointments: would book {count} sample appointments")
    if "faq" not in options.skip:
        for clinic_id, documents in faq_content.FAQ_DOCUMENTS_BY_CLINIC.items():
            print(
                f"faq: would upload {len(documents)} documents for {clinic_id}"
                " and start one ingestion job"
            )
    if "staff" not in options.skip:
        emails = [
            _staff_email(clinic_id)
            for clinic_id in (clinic_data.DENTAL_CLINIC_ID, clinic_data.COSMETIC_CLINIC_ID)
        ]
        print(f"staff: would ensure accounts for {', '.join(emails)}")


def main(argv: Sequence[str] | None = None) -> int:
    """Run every requested step in order, continuing past a failed one.

    Returns:
        `EXIT_OK` if every requested step succeeded; `EXIT_STEP_FAILED` if
        any raised -- the log line above it names which and why.
    """
    options = parse_args(argv)
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO if options.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if options.dry_run:
        _print_dry_run(options)
        return EXIT_OK

    failed: list[str] = []

    if "clinics" not in options.skip:
        failed += _run_step("clinics", lambda: print(f"clinics: wrote {seed_clinics()}"))
    if "appointments" not in options.skip:
        failed += _run_step(
            "appointments",
            lambda: print(f"appointments: booked {len(seed_sample_appointments())}"),
        )
    if "faq" not in options.skip:
        failed += _run_step("faq", lambda: print(f"faq: started ingestion {seed_faq()}"))
    if "staff" not in options.skip:
        failed += _run_step("staff", lambda: print(f"staff: {seed_staff_accounts()}"))

    if failed:
        print(f"!! failed step(s): {', '.join(failed)} -- see the logged error(s) above.")
        return EXIT_STEP_FAILED
    return EXIT_OK


def _run_step(name: str, action: Callable[[], None]) -> list[str]:
    """Run one step, logging and continuing rather than aborting the run.

    Catches every exception, not just `tools.errors.ToolError`: a step can
    just as easily fail on a botocore credentials/network error, which is
    not part of that vocabulary (`agents/cli.py`'s `main` draws the same
    distinction between the two). A failure in one step (say, FAQ
    ingestion, because a Knowledge Base id is not yet configured) must not
    stop an independent one (staff accounts) from still being seeded -- a
    human re-running this after fixing one problem should not have to wait
    through steps that already succeeded, but should also not be left
    guessing which of several steps needs re-running.

    Returns:
        `[name]` if `action` raised, `[]` if it succeeded.
    """
    try:
        action()
    except Exception as error:  # noqa: BLE001 - see docstring
        logger.exception("%s failed", name)
        print(f"!! {name}: {type(error).__name__}: {error}", file=sys.stderr)
        return [name]
    return []


if __name__ == "__main__":
    raise SystemExit(main())
