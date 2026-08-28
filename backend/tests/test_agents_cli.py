"""Tests for the local text interface in `agents/cli.py`.

This module is the thinnest layer in the repo -- read a line, hand it to
the agent, print what comes back -- so what is worth pinning is not the
loop but the four ways it could quietly ruin a session someone is paying
a model for.

*One call, one conversation.* Every turn goes to the same `Agent`, the
one thing in the tree that remembers. A loop that rebuilt it per line
would start the patient again from nothing on every turn, which reads on
screen almost exactly like a model that forgot -- so the agent's identity
is asserted, not just the printed text.

*The operator's controls are not turns.* `exit` hangs up, EOF hangs up, a
blank line is a slip. None of them may reach the model: the first would
be a wasted call, the last would spend one on nothing at all.

*A failed turn is not a failed call.* A throttle costs one answer; the
conversation so far is still in the agent and the next line must still
reach it.

*A call that cannot be opened says why.* This is the layer whose reader
is a developer, so unlike `results.py` it prints the tool layer's message
in full -- including the `ConfigurationError` text that names the broken
attribute.

The last section drives the loop over a real Orchestrator with a scripted
model and fake tables, so what is typed at the prompt is proved to reach
`backend/tools/` and come back as a printed line. Nothing here reaches
Bedrock.
"""

from __future__ import annotations

import io
import logging
from typing import Any

import pytest

from agents.cli import (
    AGENT_PREFIX,
    ERROR_PREFIX,
    EXIT_OK,
    EXIT_START_FAILED,
    MODEL_ENV,
    OPENING_TURN,
    PATIENT_PROMPT,
    TURN_FAILED_MESSAGE,
    Options,
    main,
    parse_args,
    run_call,
)
from agents.orchestrator import build_orchestrator
from tests.test_orchestrator import dental_session, tables  # noqa: F401
from tests.test_scheduling_agent import ScriptedModel, WEDNESDAY
from tools.errors import ConfigurationError, NotFoundError

DENTAL = "clinic-dental"


class FakeAgent:
    """Stands in for the Orchestrator: records its turns, replays answers.

    An answer may be an exception, which is raised instead of returned --
    that is how a throttled model call, or an operator's Ctrl-C, is
    spelled here. `BaseException` rather than `Exception`, because
    `KeyboardInterrupt` is not the latter and the two must not be handled
    alike.
    """

    def __init__(self, *answers: str | BaseException) -> None:
        self.answers: list[str | BaseException] = list(answers)
        self.turns: list[str] = []

    def __call__(self, turn: str) -> str:
        self.turns.append(turn)
        answer = self.answers.pop(0) if self.answers else "..."
        if isinstance(answer, BaseException):
            raise answer
        return answer


def drive(
    agent: Any, typed: str, *, opening_turn: str | None = None
) -> str:
    """Run one call over `typed` and return everything printed."""
    writer = io.StringIO()
    run_call(
        agent,
        reader=io.StringIO(typed),
        writer=writer,
        opening_turn=opening_turn,
    )
    return writer.getvalue()


# --------------------------------------------------------------------------
# The command line
# --------------------------------------------------------------------------


def test_a_clinic_is_chosen_before_the_call_not_during_it() -> None:
    """The operator stands in for the browser here: the clinic arrives
    from outside the conversation, as `architecture.md` -> Auth and
    Access Model requires, and nothing said later can change it."""
    assert parse_args([DENTAL]) == Options(
        clinic_id=DENTAL, model=None, opening_turn=OPENING_TURN, verbose=False
    )


def test_a_call_with_no_clinic_is_refused() -> None:
    """There is no default clinic, and guessing one would book a real
    appointment in the wrong diary."""
    with pytest.raises(SystemExit):
        parse_args([])


def test_the_model_can_be_named_on_the_command_line() -> None:
    """The open question is the *value*; this is the one place that
    chooses it, and it threads to all three agents from here."""
    assert parse_args([DENTAL, "--model", "a-model-id"]).model == "a-model-id"


def test_the_model_falls_back_to_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """So a deployment can set it once rather than per invocation."""
    monkeypatch.setenv(MODEL_ENV, "env-model")
    assert parse_args([DENTAL]).model == "env-model"


def test_an_explicit_model_beats_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Trying a second model for one call must not mean unsetting a
    variable first."""
    monkeypatch.setenv(MODEL_ENV, "env-model")
    assert parse_args([DENTAL, "--model", "typed"]).model == "typed"


@pytest.mark.parametrize("value", ["", "   "])
def test_a_blank_environment_variable_is_not_a_model(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """An empty export is how a shell profile spells "unset", and passing
    `""` to Strands would fail as a model id rather than defaulting."""
    monkeypatch.setenv(MODEL_ENV, value)
    assert parse_args([DENTAL]).model is None


def test_the_greeting_can_be_left_to_the_operator() -> None:
    """The other arm of the "who speaks the greeting" open question: with
    no opening turn the agent says nothing until spoken to."""
    assert parse_args([DENTAL, "--no-greeting"]).opening_turn is None


def test_verbose_is_off_by_default() -> None:
    """A refusal is logged at INFO and can carry what a patient said, so
    it is asked for rather than assumed."""
    assert parse_args([DENTAL]).verbose is False
    assert parse_args([DENTAL, "-v"]).verbose is True


# --------------------------------------------------------------------------
# The loop
# --------------------------------------------------------------------------


def test_the_agent_speaks_first_when_given_an_opening_turn() -> None:
    """A Strands agent says nothing until it is spoken to, so without
    this the patient meets a silent prompt."""
    agent = FakeAgent("Dental clinic, how can I help?")
    output = drive(agent, "", opening_turn=OPENING_TURN)

    assert agent.turns == [OPENING_TURN]
    assert f"{AGENT_PREFIX}Dental clinic, how can I help?" in output


def test_no_opening_turn_means_no_model_call_before_the_first_line() -> None:
    agent = FakeAgent()
    drive(agent, "", opening_turn=None)
    assert agent.turns == []


def test_every_typed_line_is_one_turn_in_order() -> None:
    agent = FakeAgent("first", "second")
    output = drive(agent, "when are you free?\nWednesday please\n")

    assert agent.turns == ["when are you free?", "Wednesday please"]
    assert output.count(AGENT_PREFIX) == 2
    assert f"{AGENT_PREFIX}first" in output
    assert f"{AGENT_PREFIX}second" in output


def test_the_whole_call_goes_to_one_agent() -> None:
    """The Orchestrator is where the conversation accumulates. Rebuilding
    it per line would look like a model that forgot the patient's name --
    so this asserts the object, not the transcript."""
    agent = FakeAgent("a", "b", "c")
    drive(agent, "one\ntwo\n", opening_turn=OPENING_TURN)
    assert len(agent.turns) == 3


def test_an_answer_is_printed_without_its_trailing_newline() -> None:
    """An `AgentResult` renders with one, and this text is a spoken line
    in the voice layer rather than a paragraph."""
    agent = FakeAgent("Booked for nine o'clock.\n")
    assert f"{AGENT_PREFIX}Booked for nine o'clock.\n" in drive(agent, "book it\n")


def test_a_blank_line_is_not_a_turn() -> None:
    """Enter on an empty line is a slip; sending it would spend a model
    call to tell the agent nothing."""
    agent = FakeAgent("only answer")
    drive(agent, "\n   \nhello\n")
    assert agent.turns == ["hello"]


def test_a_prompt_is_written_before_every_read() -> None:
    """Including the one that meets end of input -- otherwise a typed
    line appears with nothing in front of it."""
    assert drive(FakeAgent("a", "b"), "one\ntwo\n").count(PATIENT_PROMPT) == 3


@pytest.mark.parametrize("word", ["exit", "quit", "EXIT", "  quit  "])
def test_hanging_up_is_not_something_the_model_hears(word: str) -> None:
    """These are the operator's controls. A model asked to answer "quit"
    costs a call and may well try to book something."""
    agent = FakeAgent()
    drive(agent, f"{word}\nnever read\n")
    assert agent.turns == []


def test_a_sentence_containing_exit_is_still_a_turn() -> None:
    """Whole-line match only: a patient can say the word."""
    agent = FakeAgent("answer")
    drive(agent, "I have to exit the building by five\n")
    assert agent.turns == ["I have to exit the building by five"]


def test_end_of_input_ends_the_call() -> None:
    """Ctrl-D, or a piped script running out."""
    agent = FakeAgent("answer")
    drive(agent, "hello\n")
    assert agent.turns == ["hello"]


# --------------------------------------------------------------------------
# When a turn fails
# --------------------------------------------------------------------------


def test_a_failed_turn_does_not_end_the_call() -> None:
    """A throttle costs one answer. Everything said so far is still in
    the agent's messages, and dropping the call would throw it away."""
    agent = FakeAgent(RuntimeError("throttled"), "still here")
    output = drive(agent, "one\ntwo\n")

    assert agent.turns == ["one", "two"]
    assert f"{ERROR_PREFIX}{TURN_FAILED_MESSAGE}" in output
    assert f"{AGENT_PREFIX}still here" in output


def test_a_failed_turn_is_logged_with_its_stack(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The screen gets a line; the log gets the cause. A swallowed
    exception here is a bug nobody can see."""
    with caplog.at_level(logging.ERROR):
        drive(FakeAgent(RuntimeError("throttled")), "one\n")
    assert "throttled" in caplog.text


def test_the_error_line_is_not_mistakable_for_the_clinic_speaking() -> None:
    """It is prefixed as an error, not as the agent -- otherwise a
    transcript reads as though the clinic said it."""
    output = drive(FakeAgent(RuntimeError("boom")), "one\n")
    assert AGENT_PREFIX not in output


def test_ctrl_c_ends_the_call_rather_than_raising() -> None:
    """Interrupting a slow answer is how a real session ends. It must not
    print a traceback over the transcript."""
    output = drive(FakeAgent(KeyboardInterrupt()), "one\n")
    assert AGENT_PREFIX not in output


def test_ctrl_c_during_the_greeting_ends_the_call_too() -> None:
    """The first answer is the slowest -- a cold model and a system
    prompt -- so it is the one most likely to be interrupted."""
    agent = FakeAgent(KeyboardInterrupt())
    drive(agent, "never read\n", opening_turn=OPENING_TURN)
    assert agent.turns == [OPENING_TURN]


# --------------------------------------------------------------------------
# Opening the call
# --------------------------------------------------------------------------


def test_an_unknown_clinic_is_reported_and_nothing_is_read(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`start_call` validates before the greeting, so the interface never
    gets as far as a prompt."""
    monkeypatch.setattr(
        "agents.cli.start_call",
        lambda *_, **__: (_ for _ in ()).throw(NotFoundError("No such clinic.")),
    )
    assert main(["clinic-nope"]) == EXIT_START_FAILED
    assert "No such clinic." in capsys.readouterr().err


def test_a_broken_config_is_printed_in_full(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The opposite of `results.py`: the reader here is a developer, and
    the attribute path is the whole point of the message."""
    message = "clinic-dental: services[checkup].duration_minutes is not a number."
    monkeypatch.setattr(
        "agents.cli.start_call",
        lambda *_, **__: (_ for _ in ()).throw(ConfigurationError(message)),
    )
    assert main([DENTAL]) == EXIT_START_FAILED
    assert message in capsys.readouterr().err


def test_a_credential_failure_is_named_not_swallowed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Everything between this process and the clinics table surfaces
    here, before anyone has said anything. `progress-tracker.md` records
    that the voice stack's failure mode is a silent hang; this one is
    not allowed to be."""
    monkeypatch.setattr(
        "agents.cli.start_call",
        lambda *_, **__: (_ for _ in ()).throw(
            RuntimeError("Unable to locate credentials")
        ),
    )
    assert main([DENTAL]) == EXIT_START_FAILED
    error = capsys.readouterr().err
    assert "RuntimeError" in error
    assert "Unable to locate credentials" in error


def test_the_clinic_and_model_reach_start_call(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The one place the model is chosen, and the one place the clinic
    is."""
    seen: dict[str, Any] = {}

    def fake_start(clinic_id: str, model: Any = None) -> FakeAgent:
        seen["clinic_id"] = clinic_id
        seen["model"] = model
        return FakeAgent("hello")

    monkeypatch.setattr("agents.cli.start_call", fake_start)
    monkeypatch.setattr("sys.stdin", io.StringIO(""))

    assert main([DENTAL, "--model", "a-model-id", "--no-greeting"]) == EXIT_OK
    assert seen == {"clinic_id": DENTAL, "model": "a-model-id"}
    capsys.readouterr()


def test_a_call_runs_from_main_to_the_prompt(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """End to end through the entry point: stdin in, transcript out."""
    agent = FakeAgent("Dental clinic, how can I help?", "Wednesday, then.")
    monkeypatch.setattr("agents.cli.start_call", lambda *_, **__: agent)
    monkeypatch.setattr("sys.stdin", io.StringIO("Wednesday please\n"))

    assert main([DENTAL]) == EXIT_OK
    output = capsys.readouterr().out
    assert agent.turns == [OPENING_TURN, "Wednesday please"]
    assert DENTAL in output
    assert f"{AGENT_PREFIX}Wednesday, then." in output


# --------------------------------------------------------------------------
# Over the real agent tree
# --------------------------------------------------------------------------


def test_a_typed_line_reaches_the_tool_layer_and_comes_back(tables) -> None:  # noqa: F811
    """The point of the unit: one line typed at the prompt travels front
    desk -> scheduling assistant -> `backend/tools/` against fake tables,
    and the answer is printed. The scripted model stands in for all three
    agents, so a routing change shows up as a script that no longer
    fits."""
    tables()
    model = ScriptedModel(
        (
            "tool",
            ("scheduling_assistant", {"request": "check-up on Wednesday, any time"}),
        ),
        ("tool", ("check_availability", {"date": WEDNESDAY, "service": "checkup"})),
        ("text", "Quarter past nine or half past are free on Wednesday."),
        ("text", "We have quarter past nine or half past. Which suits you?"),
    )
    agent = build_orchestrator(dental_session(), model)

    output = drive(agent, "when are you free on Wednesday?\n")

    assert f"{AGENT_PREFIX}We have quarter past nine or half past." in output
    assert [request["tool_names"] for request in model.requests][0] == [
        "scheduling_assistant",
        "escalation_assistant",
    ]
    assert agent.messages[0]["content"][0]["text"] == (
        "when are you free on Wednesday?"
    )
