import { describe, expect, it } from "vitest";
import { applyToTranscript, initialTranscript } from "./transcriptReducer";
import type { AgentMessage } from "./agentEvents";

const userPartial = (text: string): AgentMessage => ({
  kind: "transcript",
  text,
  isFinal: false,
  role: "user",
});
const userFinal = (text: string): AgentMessage => ({
  kind: "transcript",
  text,
  isFinal: true,
  role: "user",
});
const assistantPartial = (text: string): AgentMessage => ({
  kind: "transcript",
  text,
  isFinal: false,
  role: "assistant",
});
const assistantFinal = (text: string): AgentMessage => ({
  kind: "transcript",
  text,
  isFinal: true,
  role: "assistant",
});

// The wire behaviour these tests encode was captured live from the
// deployed Nova Sonic runtime (2026-09-14 probe, see
// progress-tracker.md): patient speech arrives as one `is_final` event
// whose text is the COMPLETE utterance (interims, when they come at
// all, are superseded by it); assistant speech arrives only as
// `is_final: false` deltas -- one per sentence block, with significant
// leading whitespace like " \n\nTo get started" -- and no final pass
// or completion event ever follows them.
describe("applyToTranscript", () => {
  it("accumulates consecutive partials for the same role into one live line", () => {
    let state = applyToTranscript(initialTranscript, userPartial("I'd "));
    state = applyToTranscript(state, userPartial("like a "));
    state = applyToTranscript(state, userPartial("cleaning"));
    expect(state.turns).toEqual([]);
    expect(state.live).toEqual({ role: "user", text: "I'd like a cleaning" });
  });

  it("normalises whitespace in deltas, which the model pads with newlines", () => {
    let state = applyToTranscript(
      initialTranscript,
      assistantPartial("Hello, thank you for calling."),
    );
    state = applyToTranscript(
      state,
      assistantPartial(" \n\nTo get started, could you tell me your name?"),
    );
    expect(state.live).toEqual({
      role: "assistant",
      text: "Hello, thank you for calling. To get started, could you tell me your name?",
    });
  });

  it("ignores text that is only whitespace", () => {
    const state = applyToTranscript(initialTranscript, assistantPartial(" \n\t "));
    expect(state).toBe(initialTranscript);
  });

  it("commits a user final as its own complete turn, not appended to its partials", () => {
    // The wire's user final carries the whole utterance; carrying the
    // interim accumulation into it would duplicate every word.
    let state = applyToTranscript(initialTranscript, userPartial("I'd like to"));
    state = applyToTranscript(
      state,
      userFinal("I'd like to book a cleaning please"),
    );
    expect(state.turns).toEqual([
      { role: "user", text: "I'd like to book a cleaning please" },
    ]);
    expect(state.live).toBeNull();
  });

  it("commits the pending assistant reply as a turn when the patient answers", () => {
    // Assistant deltas are never final on this wire -- the reply only
    // becomes a turn when the conversation moves on. Wiping it instead
    // (the old behaviour) made the agent's every reply vanish the
    // moment the patient spoke again.
    let state = applyToTranscript(initialTranscript, assistantPartial("Sure!"));
    state = applyToTranscript(state, assistantPartial("Tuesday at 10?"));
    state = applyToTranscript(state, userFinal("Perfect, thank you"));
    expect(state.turns).toEqual([
      { role: "assistant", text: "Sure! Tuesday at 10?" },
      { role: "user", text: "Perfect, thank you" },
    ]);
    expect(state.live).toBeNull();
  });

  it("commits one role's live line when the other role starts speaking", () => {
    let state = applyToTranscript(initialTranscript, assistantPartial("One moment"));
    state = applyToTranscript(state, userPartial("hello?"));
    expect(state.turns).toEqual([{ role: "assistant", text: "One moment" }]);
    expect(state.live).toEqual({ role: "user", text: "hello?" });
  });

  it("appends each final as its own turn, in order", () => {
    let state = applyToTranscript(initialTranscript, assistantFinal("Sure!"));
    state = applyToTranscript(state, assistantFinal("Tuesday at 10?"));
    expect(state.turns).toEqual([
      { role: "assistant", text: "Sure!" },
      { role: "assistant", text: "Tuesday at 10?" },
    ]);
  });

  it("ignores empty finals so they never create blank turns", () => {
    const state = applyToTranscript(initialTranscript, assistantFinal(""));
    expect(state.turns).toEqual([]);
  });

  it("drops the live partial on interruption without touching past turns", () => {
    let state = applyToTranscript(initialTranscript, assistantFinal("Welcome in, how"));
    state = applyToTranscript(state, assistantPartial(" can I"));
    state = applyToTranscript(state, { kind: "interruption" });
    expect(state.turns).toEqual([{ role: "assistant", text: "Welcome in, how" }]);
    expect(state.live).toBeNull();
  });

  it("passes state through unchanged for audio events", () => {
    const state = applyToTranscript(initialTranscript, {
      kind: "audio",
      audio: "AAAA",
      format: "pcm",
      sampleRate: 16000,
    });
    expect(state).toBe(initialTranscript);
  });
});
