import { describe, expect, it } from "vitest";
import { describeClose, parseAgentMessage } from "./agentEvents";

describe("parseAgentMessage", () => {
  it("parses an audio stream event with defaults for missing format fields", () => {
    const message = parseAgentMessage(
      JSON.stringify({ type: "bidi_audio_stream", audio: "AAAA" }),
    );
    expect(message).toEqual({
      kind: "audio",
      audio: "AAAA",
      format: "pcm",
      sampleRate: 16000,
    });
  });

  it("parses a user partial transcript", () => {
    const message = parseAgentMessage(
      JSON.stringify({
        type: "bidi_transcript_stream",
        role: "user",
        is_final: false,
        text: "hello",
      }),
    );
    expect(message).toEqual({
      kind: "transcript",
      text: "hello",
      isFinal: false,
      role: "user",
    });
  });

  it("treats assistant as the role for anything but an explicit user", () => {
    const message = parseAgentMessage(
      JSON.stringify({ type: "bidi_transcript_stream", text: "hi" }),
    );
    expect(message).toMatchObject({ kind: "transcript", role: "assistant", isFinal: true });
  });

  it("parses a final text response as a final assistant transcript", () => {
    const message = parseAgentMessage(
      JSON.stringify({ type: "bidi_text_response", text: "You're booked." }),
    );
    expect(message).toEqual({
      kind: "transcript",
      text: "You're booked.",
      isFinal: true,
      role: "assistant",
    });
  });

  it("parses an interruption event", () => {
    expect(parseAgentMessage(JSON.stringify({ type: "bidi_interruption" }))).toEqual({
      kind: "interruption",
    });
  });

  it("ignores audio events whose audio is not a string", () => {
    expect(parseAgentMessage(JSON.stringify({ type: "bidi_audio_stream", audio: 42 }))).toBeNull();
  });

  it("ignores text responses with no text", () => {
    expect(parseAgentMessage(JSON.stringify({ type: "bidi_text_response" }))).toBeNull();
  });

  it("ignores unknown event types", () => {
    expect(parseAgentMessage(JSON.stringify({ type: "something_new" }))).toBeNull();
  });

  it("ignores non-JSON and non-string frames", () => {
    expect(parseAgentMessage("not json {")).toBeNull();
    expect(parseAgentMessage(42)).toBeNull();
    expect(parseAgentMessage(null)).toBeNull();
  });
});

describe("describeClose", () => {
  it("explains a policy close for a missing clinic", () => {
    expect(describeClose(1008, "missing_clinic_id")).toContain("clinic");
  });

  it("explains a policy close for an unknown clinic", () => {
    expect(describeClose(1008, "not_found")).toContain("clinic");
  });

  it("explains an internal-error close", () => {
    expect(describeClose(1011, "internal_error")).toContain("try again");
  });

  it("falls back to generic copy for unexpected codes and blank reasons", () => {
    expect(describeClose(1006, "")).toContain("try again");
    expect(describeClose(1008, "tool_error")).toContain("try again");
  });
});
