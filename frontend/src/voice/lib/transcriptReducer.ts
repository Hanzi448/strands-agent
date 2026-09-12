/**
 * Pure state machine for the live transcript: final utterances become
 * turns, partials accumulate into a single live line, an interruption
 * drops the in-flight partial.
 *
 * Adapted from the vendored sample's hook (`useVoiceAgent.ts`) and
 * deliberately simplified: `ui-context.md` asks for a live transcript
 * below the orb, not a chat UI, so there is no bubble-merging and no
 * force-new-bubble flag -- every final is its own turn.
 */

import type { AgentMessage } from "./agentEvents";

export interface TranscriptTurn {
  readonly role: "user" | "assistant";
  readonly text: string;
}

export interface LiveTranscript {
  readonly role: "user" | "assistant";
  readonly text: string;
}

export interface TranscriptState {
  readonly turns: readonly TranscriptTurn[];
  readonly live: LiveTranscript | null;
}

export const initialTranscript: TranscriptState = { turns: [], live: null };

export function applyToTranscript(
  state: TranscriptState,
  event: AgentMessage,
): TranscriptState {
  switch (event.kind) {
    case "audio":
      return state;

    case "interruption":
      return { turns: state.turns, live: null };

    case "transcript": {
      if (event.isFinal) {
        if (event.text === "") return state;
        const carried =
          state.live !== null && state.live.role === event.role ? state.live.text : "";
        return {
          turns: [...state.turns, { role: event.role, text: carried + event.text }],
          live: null,
        };
      }
      if (event.text === "") return state;
      const carried =
        state.live !== null && state.live.role === event.role ? state.live.text : "";
      return { turns: state.turns, live: { role: event.role, text: carried + event.text } };
    }
  }
}
