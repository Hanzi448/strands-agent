import { describe, expect, it } from "vitest";
import { applyToTranscript, initialTranscript } from "./transcriptReducer";
import type { AgentMessage } from "./agentEvents";

const userPartial = (text: string): AgentMessage => ({
  kind: "transcript",
  text,
  isFinal: false,
  role: "user",
});
const assistantFinal = (text: string): AgentMessage => ({
  kind: "transcript",
  text,
  isFinal: true,
  role: "assistant",
});

describe("applyToTranscript", () => {
  it("accumulates consecutive partials for the same role into one live line", () => {
    let state = applyToTranscript(initialTranscript, userPartial("I'd "));
    state = applyToTranscript(state, userPartial("like a "));
    state = applyToTranscript(state, userPartial("cleaning"));
    expect(state.turns).toEqual([]);
    expect(state.live).toEqual({ role: "user", text: "I'd like a cleaning" });
  });

  it("starts a fresh live line when the role changes", () => {
    let state = applyToTranscript(initialTranscript, userPartial("hello"));
    state = applyToTranscript(state, { kind: "transcript", text: "Hi!", isFinal: false, role: "assistant" });
    expect(state.live).toEqual({ role: "assistant", text: "Hi!" });
  });

  it("commits a final utterance as a turn and clears the live line", () => {
    let state = applyToTranscript(initialTranscript, userPartial("book a"));
    state = applyToTranscript(state, {
      kind: "transcript",
      text: " cleaning",
      isFinal: true,
      role: "user",
    });
    expect(state.turns).toEqual([{ role: "user", text: "book a cleaning" }]);
    expect(state.live).toBeNull();
  });

  it("appends each final as its own turn, in order", () => {
    let state = applyToTranscript(initialTranscript, {
      kind: "transcript",
      text: "Sure!",
      isFinal: true,
      role: "assistant",
    });
    state = applyToTranscript(state, {
      kind: "transcript",
      text: "Tuesday at 10?",
      isFinal: true,
      role: "assistant",
    });
    expect(state.turns).toEqual([
      { role: "assistant", text: "Sure!" },
      { role: "assistant", text: "Tuesday at 10?" },
    ]);
  });

  it("ignores empty finals so they never create blank turns", () => {
    const state = applyToTranscript(initialTranscript, {
      kind: "transcript",
      text: "",
      isFinal: true,
      role: "assistant",
    });
    expect(state.turns).toEqual([]);
  });

  it("drops the live partial on interruption without touching past turns", () => {
    let state = applyToTranscript(initialTranscript, assistantFinal("Welcome in, how"));
    state = applyToTranscript(state, { kind: "transcript", text: " can I", isFinal: false, role: "assistant" });
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
