/**
 * The validation boundary for everything the voice agent's WebSocket
 * sends (`code-standards.md` -> TypeScript/React: validate unknown
 * responses). Raw frames in, a typed union out; anything malformed or
 * not meant for the browser is `null` and silently ignored.
 *
 * Event shapes follow the bidirectional Nova Sonic protocol used by
 * the vendored reference sample and our deployed
 * `backend/agents/agentcore_app.py`.
 */

export type AgentMessage =
  | { kind: "audio"; audio: string; format: string; sampleRate: number }
  | { kind: "transcript"; text: string; isFinal: boolean; role: "user" | "assistant" }
  | { kind: "interruption" };

export function parseAgentMessage(raw: unknown): AgentMessage | null {
  if (typeof raw !== "string") return null;

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof parsed !== "object" || parsed === null) return null;

  const event = parsed as Record<string, unknown>;

  switch (event.type) {
    case "bidi_audio_stream": {
      if (typeof event.audio !== "string") return null;
      return {
        kind: "audio",
        audio: event.audio,
        format: typeof event.format === "string" ? event.format : "pcm",
        sampleRate: typeof event.sample_rate === "number" ? event.sample_rate : 16000,
      };
    }
    case "bidi_transcript_stream": {
      const text = typeof event.text === "string" ? event.text : "";
      if (text === "" && event.is_final === true) return null;
      return {
        kind: "transcript",
        text,
        isFinal: event.is_final !== false,
        role: event.role === "user" ? "user" : "assistant",
      };
    }
    case "bidi_text_response": {
      if (typeof event.text !== "string" || event.text === "") return null;
      return { kind: "transcript", text: event.text, isFinal: true, role: "assistant" };
    }
    case "bidi_interruption":
      return { kind: "interruption" };
    default:
      return null;
  }
}

/**
 * Map a WebSocket close to patient-facing copy. The deployed `/ws`
 * (`backend/agents/agentcore_app.py`) closes with code 1008 (policy)
 * or 1011 (internal error) and carries only a stable error code in the
 * reason -- never a human-readable message -- so this mapping is where
 * every user-visible close message lives.
 */
export function describeClose(code: number, reason: string): string {
  if (code === 1008) {
    switch (reason) {
      case "missing_clinic_id":
        return "No clinic was selected for this call. Please go back and choose a clinic.";
      case "not_found":
        return "We couldn't find that clinic. Please go back and choose a clinic.";
      default:
        return "The clinic couldn't take this call. Please try again.";
    }
  }
  return "Something went wrong during the call. Please try again.";
}
