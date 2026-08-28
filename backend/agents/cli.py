"""The local text interface: one keyboard, one call, no microphone.

The first thing in this repo that drives a conversation from outside a
test. Everything below `start_call` has been exercised by scripted models
against fake tables; nothing has yet put the three system prompts in
front of a real one. That is what this module is for -- typing at the
Orchestrator is the only way to find out whether "ask for the patient's
name and phone number before booking" survives contact with a model that
was not written to obey it.

It is an *interface*, and holds nothing else. It reads a line, hands it
to the agent, prints what comes back. There is no clinic logic here, no
tool call, and no prompt text: a rule that lived in this file would be a
rule the voice layer does not get (`code-standards.md` -> General, one
concern per layer).

**Errors read differently here than in `results.py`.** That module hides
a `ConfigurationError` from the model, because its message quotes
internal attribute paths and the model has a microphone open. The reader
of this module is a developer with a keyboard, and the offending
attribute path is exactly what they need, so it is printed in full. Same
exception, two audiences.

**A credential fault surfaces before the greeting.** `start_call` reads
the clinic row from DynamoDB, so a missing profile, a wrong region or an
unseeded table fails on the way in rather than three turns into a
booking. That is worth having in the layer where a human is watching:
`progress-tracker.md` records that the voice stack's known failure mode
is a silent hang on bad credentials.

Run it from `backend/`:

    python -m agents.cli clinic-dental

Ctrl-D (Ctrl-Z then Enter on Windows), Ctrl-C, or typing `exit` ends the
call. Those are the *operator's* way out and are never sent to the model
-- a patient saying "goodbye" is an ordinary turn, and what the agent
does with it is part of what this interface exists to show.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, TextIO

from strands import Agent

from tools.errors import ToolError

from .orchestrator import start_call

logger = logging.getLogger(__name__)

# Which text model the Orchestrator and both sub-agents reason with.
# Still an open question in `progress-tracker.md`: `architecture.md` ->
# Stack names Nova Sonic for the voice layer and nothing for the text
# agents. Unset means "whatever Strands defaults to", which is a working
# default and not a decision -- so the value is chosen here, at the
# interface, rather than baked into an agent definition. When it is
# settled it belongs in `architecture.md`, and this is the line that
# reads it.
MODEL_ENV: Final[str] = "CLINICPILOT_TEXT_MODEL"

# The turn that opens the call. A Strands `Agent` says nothing until it
# is spoken to, and the Orchestrator's prompt tells it to open with the
# clinic's name -- so something has to prompt the first turn. Sending a
# stage direction rather than a greeting of our own is what keeps the
# greeting the *model's*: this is the experiment the "who speaks the
# greeting" open question asks for, and `--no-greeting` is its other arm.
OPENING_TURN: Final[str] = (
    "[The patient has just been connected and is waiting for you to speak.]"
)

# What the operator types to hang up. Matched on a whole line only, so a
# patient turn that happens to contain the word is still a turn.
EXIT_WORDS: Final[frozenset[str]] = frozenset({"exit", "quit"})

PATIENT_PROMPT: Final[str] = "you> "
AGENT_PREFIX: Final[str] = "clinic> "
ERROR_PREFIX: Final[str] = "!! "

# A turn that raised is not a call that ended: a throttle or a dropped
# connection costs one answer, and everything said so far is still in the
# agent's `messages`. The detail goes to the log, which is where a stack
# trace belongs.
TURN_FAILED_MESSAGE: Final[str] = (
    "that turn did not complete -- see the logged error above."
    " The call is still open; try again, or type exit."
)

LOG_FORMAT: Final[str] = "%(levelname)s %(name)s: %(message)s"

EXIT_OK: Final[int] = 0
EXIT_START_FAILED: Final[int] = 1


@dataclass(frozen=True)
class Options:
    """One invocation of the interface.

    Attributes:
        clinic_id: The clinic this call is pinned to. Given on the command
            line because the operator stands in for the browser, which is
            where it comes from in the real system (`architecture.md` ->
            Auth and Access Model). Nothing in the conversation can change
            it.
        model: The model id for all three agents, or `None` to leave the
            Strands default.
        opening_turn: The turn to send before reading any input, or `None`
            to wait for the operator to speak first.
        verbose: Whether to log at `INFO`, the level a tool wrapper
            records a refusal at (`results.py`).
    """

    clinic_id: str
    model: str | None
    opening_turn: str | None
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
        prog="python -m agents.cli",
        description=(
            "Talk to a clinic's front-desk agent from the keyboard."
            " It reads and writes the same DynamoDB tables the voice"
            " agent will: anything booked here is really booked."
        ),
    )
    parser.add_argument(
        "clinic_id",
        help="The clinic to answer for, e.g. clinic-dental.",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get(MODEL_ENV, "").strip() or None,
        help=(
            "Model id for the Orchestrator and both sub-agents"
            f" (default: ${MODEL_ENV}, or the Strands default if unset)."
        ),
    )
    parser.add_argument(
        "--no-greeting",
        action="store_true",
        help=(
            "Wait for you to speak first, instead of opening the call with"
            " a turn that leaves the greeting to the agent."
        ),
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Log tool refusals as well as errors.",
    )
    args = parser.parse_args(argv)
    return Options(
        clinic_id=args.clinic_id,
        model=args.model,
        opening_turn=None if args.no_greeting else OPENING_TURN,
        verbose=args.verbose,
    )


def take_turn(agent: Agent, turn: str, writer: TextIO) -> None:
    """Send one turn and print the answer.

    A failure is caught rather than raised: the model call is the one
    thing in this loop that talks to a network, and losing a whole
    conversation to a throttle would throw away every turn spent on it.

    Args:
        agent: The call's Orchestrator, which holds the conversation.
        turn: What the patient said.
        writer: Where the answer is printed.
    """
    try:
        answer = str(agent(turn)).strip()
    except KeyboardInterrupt:
        # The operator hanging up mid-answer. `run_call` ends the call.
        raise
    except Exception:
        logger.exception("the agent failed on this turn")
        _write(writer, f"{ERROR_PREFIX}{TURN_FAILED_MESSAGE}")
        return
    _write(writer, f"{AGENT_PREFIX}{answer}")


def run_call(
    agent: Agent,
    *,
    reader: TextIO,
    writer: TextIO,
    opening_turn: str | None = OPENING_TURN,
) -> None:
    """Read turns until the operator hangs up.

    Args:
        agent: The call's Orchestrator. Built once and kept, because it is
            where the conversation accumulates -- a second one would start
            the patient again from nothing.
        reader: Where patient turns are read, a line at a time. An empty
            read is end of input and ends the call.
        writer: Where the agent's answers are printed.
        opening_turn: Sent before the first read, so the agent speaks
            first. `None` waits for the operator instead.
    """
    try:
        # Inside the guard: Ctrl-C during the greeting is an operator
        # hanging up on a slow first answer, not a crash.
        if opening_turn:
            take_turn(agent, opening_turn, writer)
        while True:
            _write(writer, PATIENT_PROMPT, newline=False)
            line = reader.readline()
            if not line:  # EOF: Ctrl-D, or a piped script running out.
                _write(writer, "")
                return
            turn = line.strip()
            if not turn:
                # Not sent. An empty turn costs a model call and tells it
                # nothing, and Enter on an empty line is a slip.
                continue
            if turn.lower() in EXIT_WORDS:
                return
            take_turn(agent, turn, writer)
    except KeyboardInterrupt:
        _write(writer, "")


def main(argv: Sequence[str] | None = None) -> int:
    """Open a call for one clinic and run it until the operator stops.

    Args:
        argv: Arguments without the program name. `None` reads
            `sys.argv[1:]`.

    Returns:
        `EXIT_OK` when the call ended normally; `EXIT_START_FAILED` if the
        call could never be opened -- an unknown clinic, an unusable
        config, or no credentials for the tables.
    """
    options = parse_args(argv)
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO if options.verbose else logging.WARNING,
        format=LOG_FORMAT,
    )
    try:
        agent = start_call(options.clinic_id, options.model)
    except ToolError as error:
        # Printed in full, attribute paths and all -- see the module
        # docstring on why this is not what `results.py` does.
        print(f"{ERROR_PREFIX}{error.message}", file=sys.stderr)
        return EXIT_START_FAILED
    except Exception as error:
        # Credentials, region, network: everything between this process
        # and the clinics table. Named rather than swallowed, because
        # nobody has said anything yet and the cause is the only useful
        # output.
        print(
            f"{ERROR_PREFIX}could not open a call for {options.clinic_id!r}:"
            f" {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return EXIT_START_FAILED
    print(
        f"Call open for clinic {options.clinic_id!r}."
        " Type exit, or press Ctrl-D, to hang up."
    )
    run_call(
        agent,
        reader=sys.stdin,
        writer=sys.stdout,
        opening_turn=options.opening_turn,
    )
    return EXIT_OK


def _write(writer: TextIO, text: str, *, newline: bool = True) -> None:
    """Write and flush, so a prompt appears before the read that follows it."""
    writer.write(f"{text}\n" if newline else text)
    writer.flush()


if __name__ == "__main__":
    raise SystemExit(main())
