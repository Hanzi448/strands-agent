/**
 * Pure state machine for the live transcript: committed replies and
 * utterances become turns, the in-flight line is live, an interruption
 * drops the in-flight partial.
 *
 * Adapted from the vendored sample's hook (`useVoiceAgent.ts`) and
 * deliberately simplified: `ui-context.md` asks for a live transcript
 * below the orb, not a chat UI, so there is no bubble-merging and no
 * force-new-bubble flag -- every final is its own turn.
 *
 * The rules below encode the wire behaviour a live probe of the
 * deployed Nova Sonic runtime established (2026-09-14, see
 * `progress-tracker.md`), which the sample's shape does not survive:
 * patient speech arrives as one `is_final` event whose text is the
 * COMPLETE utterance, so a final must replace its partials, not append
 * to them; assistant speech arrives only as `is_final: false` sentence
 * deltas -- never a final pass, never a completion event -- so the
 * reply is committed as a turn when the conversation moves on (the
 * patient answers, or the other role starts), not when a final that
 * never comes arrives. Deltas also carry significant leading
 * whitespace (" \n\nTo get started"), so all text is normalised.
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

/** Collapse whitespace runs to one space and trim: the model pads its
 * deltas with newlines and double spaces that a transcript line must
 * never show. */
function normalise(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}

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
      const text = normalise(event.text);
      if (text === "") return state;

      // The other role's live line is over, however it ended: the
      // patient answered, or the agent started replying. Commit it --
      // wiping it (the alternative) is how the agent's replies used to
      // vanish the moment the patient spoke again.
      const priorTurns =
        state.live !== null && state.live.role !== event.role
          ? [...state.turns, state.live]
          : state.turns;

      if (event.isFinal) {
        // A final's text is the complete utterance on this wire --
        // the user's interim accumulation is superseded, not added to.
        return {
          turns: [...priorTurns, { role: event.role, text }],
          live: null,
        };
      }
      const carried =
        state.live !== null && state.live.role === event.role
          ? state.live.text
          : "";
      return {
        turns: priorTurns,
        live: {
          role: event.role,
          text: carried === "" ? text : `${carried} ${text}`,
        },
      };
    }
  }
}
