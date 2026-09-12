# Patient Voice UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the patient-facing voice UI (`frontend/src/voice/`) that connects a browser to the deployed AgentCore Runtime `/ws` endpoint and carries a full voice conversation — mic capture, audio playback, live transcript, clinic picker.

**Architecture:** The browser presigns an AgentCore WebSocket URL with SigV4 using **guest** Cognito identity-pool credentials (no login), appends `clinic_id` to the signed query string (the tenant selector our `/ws` reads before `accept()`), then exchanges bidirectional JSON events: `bidi_audio_input` (base64 PCM 16 kHz mono) upstream, `bidi_audio_stream` / `bidi_transcript_stream` / `bidi_text_response` / `bidi_interruption` downstream. A React hook owns the WebSocket + audio lifecycle; a full-viewport voice screen (clinic picker → orb + transcript) renders it. All connection code is adapted **explicitly** from the vendored reference sample — never copied wholesale.

**Tech Stack:** React 18 + TypeScript (strict) + Vite, Tailwind with CSS-variable tokens, shadcn/ui primitives, Lucide icons, `@aws-sdk/client-cognito-identity` (guest creds), `@aws-crypto/sha256-js` + `@aws-sdk/signature-v4` + `@smithy/protocol-http` (presigning), Vitest for pure-logic unit tests.

**Spec:** `context/project-overview.md` (Goal #1, patient flow), `context/architecture.md` (Auth and Access Model, Invariants), `context/ui-context.md` (Colors, Radius, Layout Patterns, Icons), `context/code-standards.md` (TypeScript/React, Styling, File Organization), `context/ai-workflow-rules.md` (When to Split Work — this unit is frontend-only), `backend/agents/agentcore_app.py` (the deployed `/ws` contract this connects to).

## Global Constraints

- **Strict TypeScript everywhere; no `any`** (`code-standards.md` → TypeScript/React). The vendored sample uses `any` liberally — every adaptation must be strictly typed, and that is a deliberate change, not a transcription.
- **No hardcoded hex values in components** — only `var(--token)` references via Tailwind arbitrary-value syntax, e.g. `bg-[var(--bg-surface)]` (`code-standards.md` → Styling, `frontend/tailwind.config.ts` comment).
- **`voice/` owns the WebSocket/audio lifecycle; `dashboard/` owns REST calls — no cross-imports** (`code-standards.md` → TypeScript/React).
- **Validate unknown responses before trusting their shape** — every WebSocket message from the server is parsed through a validating function before use (`code-standards.md` → TypeScript/React).
- **Vendored sample is reference-only**: `vendor/sample-nova-sonic-websocket-agentcore/` must not be modified. Adaptations into `frontend/src/voice/` are called out in code comments at each divergence (`ai-workflow-rules.md` → Protected Files).
- **`npm run build` must pass** (`tsc -b && vite build`) after every task that touches `frontend/` (`ai-workflow-rules.md` → Before Moving to the Next Unit).
- **Never run `git commit` or `git push`** (`CLAUDE.md`). Each task below ends with a *suggested* commit message in a code block for the human to run.
- Icons: Lucide, `h-8 w-8` for the voice screen's mic/state icon, `h-5 w-5` elsewhere (`ui-context.md` → Icons).
- Colors: `--accent-primary` `#2F8F7E` (voice agent), `--state-error` `#D64545`, etc. — already defined in `frontend/src/index.css`; use them, don't redefine.

## Backend contract this UI talks to (read-only reference — do not modify)

`backend/agents/agentcore_app.py`:

- Endpoint: `wss://bedrock-agentcore.{region}.amazonaws.com/runtimes/{encodedArn}/ws?qualifier=DEFAULT&X-Amzn-Bedrock-AgentCore-Runtime-Session-Id={sessionId}&clinic_id={clinicId}` (the last two params ride the same signed-query mechanism the reference sample already uses for the session id).
- `clinic_id` is read from the query string **before** `websocket.accept()`; nothing sent after opening can change it.
- Close codes: `1008` (policy — reason `missing_clinic_id`, or a `ToolError.code` like `not_found`), `1011` (reason `internal_error`). The close reason carries only the stable error code, never a human message — the UI must map codes to user-facing copy.
- On accept, the agent sends a `Greeting()` immediately — the patient hears the clinic greet them first.

**Known risk (flagged, not fixed here):** whether AgentCore's proxy forwards the `clinic_id` query parameter through to `/ws` is unverified until a real browser session runs against the deployed runtime. It is tracked as an Open Question in `progress-tracker.md` (Task 1). If it turns out not to be forwarded, stop and escalate — do not invent a different tenant-selection channel.

## File Structure

```
frontend/src/voice/
  lib/
    clinics.ts               static demo-clinic registry (id, name, tagline)
    guestCredentials.ts      guest Cognito identity-pool -> SigV4 credentials
    agentSocket.ts           presign URL + WebSocket connect (adapted from vendor)
    agentEvents.ts           parse/validate server messages; close-code -> copy
    transcriptReducer.ts     pure transcript state machine (turns + live partial)
    pcm.ts                   Float32/Int16/base64 audio conversions
    *.test.ts                Vitest unit tests (colocated)
  audio-capture-processor.worklet.js   AudioWorklet Float32 -> Int16 (adapted)
  useVoiceCall.ts            React hook: socket + capture + playback + state
  VoiceApp.tsx               clinic-not-chosen -> picker, chosen -> voice screen
  components/
    ClinicPicker.tsx         "Who are you calling?" card list
    VoiceScreen.tsx          top bar + orb + transcript; owns nothing itself
    VoiceOrb.tsx             the single large stateful orb button
    TranscriptPanel.tsx      turn list + live partial, auto-scroll
frontend/src/App.tsx         (modified) hash router: #/voice vs dashboard
frontend/src/vite-env.d.ts   (modified) new VITE_* env var types
frontend/.env.example        (modified) document the new vars
frontend/package.json        (modified) new deps + "test" script
context/progress-tracker.md  (modified) Task 1 reconciliation
```

`voice/lib/` modules are pure or SDK-glue and single-purpose; the hook is the only place that touches both the socket and the Web Audio API; components stay dumb. Nothing in `voice/` imports from `dashboard/` and vice versa.

---

### Task 1: Reconcile `progress-tracker.md` → Next Up

The user's chosen workflow ("write a plan, then build unit by unit") requires the tracker to stop lying **before** any code lands: five spec'd items are missing from Next Up entirely.

**Files:**
- Modify: `context/progress-tracker.md` (Next Up section, ~line 2106; Open Questions section, ~line 2203; one note in In Progress, ~line 2059)

**Interfaces:**
- Consumes: nothing.
- Produces: a Next Up list whose **item 1 is this plan's unit**, so the rest of this plan is executing "the first item under Next Up" per `CLAUDE.md`.

- [ ] **Step 1: Add the missing items to Next Up, in dependency order**

In `context/progress-tracker.md`, replace the numbered list at the end of the Next Up preamble (currently the two items starting `1. Deploy \`agentcore_app.py\`...` and `2. **Demo video...`) with:

```markdown
1. **Patient voice UI** — `frontend/src/voice/`: clinic picker, presigned
   WebSocket to the deployed `/ws` (guest identity-pool credentials),
   mic capture + audio playback, live transcript, voice orb.
   Plan: `docs/superpowers/plans/2026-09-12-patient-voice-ui.md`.
   Frontend-only unit (`ai-workflow-rules.md` -> When to Split Work).
2. **Escalation email notifications** — when the agent creates an
   escalation, notify clinic staff by email (SES) so an escalation is
   actionable without watching the dashboard.
3. **Frontend hosting stack** — fill the empty `frontend_stack.py`: S3 +
   CloudFront for the built SPA, producing the public demo link item #6
   needs.
4. **AgentCore Memory** — session state per `architecture.md`, so the
   voice agent remembers context across a call (and optionally across
   calls) without process-level state.
5. **Settings tab** — editable hours and services (user decision,
   2026-09-12): staff edit hours/closures/services in the dashboard,
   writing to the Clinics table. Needs a new authenticated write route
   plus validation — backend unit first, then its frontend half.
6. Deploy `agentcore_app.py` to the AgentCore Runtime and verify one
   voice session end-to-end. **Status note (2026-09-12): the user
   reports the CDK deploy and seed have now been run and the frontend
   tested locally** — the "blocked in this environment" caveats below
   predate that. Whether the KB-swap resume steps in "In Progress" were
   part of it is unconfirmed; read that section before touching the
   Agent stack.
7. **Demo video, live demo link, AWS Builder ID / builder.aws.com
   post.** Blocked on #6's real deployment and #3's hosting stack for
   the live link.
```

- [ ] **Step 2: Add the new Open Questions**

Append to the Open Questions section:

```markdown
- **Public clinic-listing route?** The patient voice UI needs the list
  of clinics before a call, but the dashboard API is staff-auth-only.
  Interim answer (2026-09-12): a static registry in
  `frontend/src/voice/lib/clinics.ts` holding the two seeded demo
  clinics — fine for a two-clinic demo, wrong the moment clinics are
  added in DynamoDB. Should a public, read-only, unauthenticated
  `/clinics` route exist instead?

- **Does AgentCore's presigned-URL proxy forward extra query parameters
  (`clinic_id`) to `/ws`?** Unverified until a real browser session
  runs against the deployed runtime. The reference sample proves the
  proxy forwards its own session-id parameter; `clinic_id` rides the
  same mechanism, but nothing yet proves the runtime *sees* it. Verify
  during the voice UI's end-to-end test; if it is not forwarded, stop
  and decide the tenant-selection channel explicitly — do not invent
  one inline.

- **SES sandbox recipients** — seeded patient addresses are
  `@example.com`, so reminder emails will be `MessageRejected` until
  the recipients are verified or the account leaves the SES sandbox.
  Blocks end-to-end reminder testing, not reminder code.
```

- [ ] **Step 3: Note the deploy report on the In Progress KB item**

At the end of the `In Progress` KB-swap entry (after its "To resume, in order" list), append:

```markdown
  *Status note (2026-09-12): the user reports the full CDK deploy and
  seed have since been run and the frontend tested locally. Whether
  these resume steps were executed as part of that is unconfirmed —
  check the Agent stack's current status and the two
  `DentalKnowledgeBaseId` / `CosmeticKnowledgeBaseId` outputs before
  touching anything here.*
```

- [ ] **Step 4: Verify**

Re-read the Next Up section top to bottom. Item 1 must be the patient voice UI; the two former items must still be present (renumbered 6 and 7); the three new open questions must be present. No other section changed.

- [ ] **Step 5: Suggested commit message**

```text
docs: reconcile progress-tracker Next Up with the five missing spec'd items

Adds the patient voice UI, escalation email, frontend hosting stack,
AgentCore Memory, and Settings-tab items to Next Up in dependency
order, notes the user's 2026-09-12 deploy report, and records the
clinic-listing / clinic_id-forwarding / SES-sandbox open questions.
```

---

### Task 2: Dependencies, env vars, Vitest scaffold

**Files:**
- Modify: `frontend/package.json` (via npm, plus a `"test"` script)
- Modify: `frontend/src/vite-env.d.ts`
- Modify: `frontend/.env.example`

**Interfaces:**
- Consumes: nothing.
- Produces: typed `import.meta.env.VITE_AGENT_RUNTIME_ARN`, `VITE_PATIENT_GUEST_IDENTITY_POOL_ID`, `VITE_REGION`, `VITE_LOCAL_DEV`, `VITE_AGENT_RUNTIME_URL` for Tasks 6–7; a `npm test` script running Vitest for Tasks 3–5.

- [ ] **Step 1: Install the runtime and dev dependencies**

From `frontend/`:

```bash
npm install @aws-sdk/client-cognito-identity @aws-crypto/sha256-js @aws-sdk/signature-v4 @smithy/protocol-http
npm install -D vitest
```

(These are exactly the four packages the vendored sample uses for presigning; `amazon-cognito-identity-js` is already present for the dashboard's staff login and is **not** used by the guest flow.)

- [ ] **Step 2: Add the test script**

In `frontend/package.json` `"scripts"`, add:

```json
"test": "vitest run"
```

- [ ] **Step 3: Extend the env typings**

Replace `frontend/src/vite-env.d.ts` content with:

```ts
/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_DASHBOARD_API_URL: string;
  readonly VITE_STAFF_USER_POOL_ID: string;
  readonly VITE_STAFF_USER_POOL_CLIENT_ID: string;
  // Patient voice UI (`src/voice/`).
  readonly VITE_AGENT_RUNTIME_ARN: string;
  readonly VITE_PATIENT_GUEST_IDENTITY_POOL_ID: string;
  readonly VITE_REGION: string;
  // Optional local-dev bypass: connect straight to a locally running
  // agentcore_app without presigning (see voice/lib/agentSocket.ts).
  readonly VITE_LOCAL_DEV?: string;
  readonly VITE_AGENT_RUNTIME_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
```

- [ ] **Step 4: Document the new vars**

Append to `frontend/.env.example`:

```text
# Patient voice UI (`src/voice/`). Values come from the deployed
# stacks' CfnOutputs:
#   VITE_AGENT_RUNTIME_ARN              <- AgentStack AgentRuntimeArn
#   VITE_PATIENT_GUEST_IDENTITY_POOL_ID <- ApiStack PatientGuestIdentityPoolId
#   VITE_REGION                         <- deployment region (us-east-1)
VITE_AGENT_RUNTIME_ARN=
VITE_PATIENT_GUEST_IDENTITY_POOL_ID=
VITE_REGION=
# Optional local-dev bypass: skip presigning and connect directly to a
# locally running agentcore_app (e.g. VITE_AGENT_RUNTIME_URL=/ws,
# served behind a Vite dev-server proxy you configure yourself).
VITE_LOCAL_DEV=
VITE_AGENT_RUNTIME_URL=
```

- [ ] **Step 5: Verify**

From `frontend/`:

```bash
npm run build
npm test
```

Expected: build passes (no code changed, so this proves the new deps resolve under `tsc -b`); Vitest reports "no test files found" and exits — that is success at this point.

- [ ] **Step 6: Suggested commit message**

```text
chore(frontend): add voice-UI deps, env typings, and Vitest scaffold

Adds the four AWS presigning packages the vendored sample uses, types
the new VITE_* vars (runtime ARN, guest identity pool, region, local
dev bypass), and wires a vitest run script for the voice unit.
```

---

### Task 3: `voice/lib/pcm.ts` — audio conversions (TDD)

Pure functions converting between the three audio representations in the pipeline: `Float32Array` (Web Audio), `Int16Array` (16-bit PCM on the wire), and base64 (JSON transport). Adapted from the vendored sample's `audioToBase64` / hook-internal decode, with two deliberate changes: chunked base64 encoding (the sample's single `String.fromCharCode(...bytes)` spread overflows the stack on real audio buffers) and explicit odd-byte handling on decode.

**Files:**
- Create: `frontend/src/voice/lib/pcm.ts`
- Test: `frontend/src/voice/lib/pcm.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces (used by Tasks 7, 9):
  - `floatToInt16(samples: Float32Array): Int16Array`
  - `int16ToFloat32(pcm: Int16Array): Float32Array`
  - `int16ToBase64(pcm: Int16Array): string`
  - `base64ToInt16(base64: string): Int16Array`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/voice/lib/pcm.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { base64ToInt16, floatToInt16, int16ToBase64, int16ToFloat32 } from "./pcm";

describe("floatToInt16", () => {
  it("clamps samples outside [-1, 1] instead of wrapping", () => {
    const pcm = floatToInt16(new Float32Array([-2, 0, 2]));
    expect(pcm).toEqual(new Int16Array([-32768, 0, 32767]));
  });

  it("scales positive and negative halves to the full Int16 range", () => {
    const pcm = floatToInt16(new Float32Array([0.5, -0.5]));
    expect(pcm[0]).toBe(0.5 * 0x7fff);
    expect(pcm[1]).toBe(-0.5 * 0x8000);
  });
});

describe("int16ToFloat32", () => {
  it("round-trips through floatToInt16 for in-range floats", () => {
    const floats = new Float32Array([0, 0.25, -0.75]);
    const restored = int16ToFloat32(floatToInt16(floats));
    for (let i = 0; i < floats.length; i++) {
      expect(Math.abs(restored[i] - floats[i])).toBeLessThan(0.001);
    }
  });

  it("maps the Int16 extremes to exactly -1 and 1", () => {
    const restored = int16ToFloat32(new Int16Array([-32768, 32767]));
    expect(restored[0]).toBe(-1);
    expect(restored[1]).toBeGreaterThan(0.9999);
  });
});

describe("int16ToBase64 / base64ToInt16", () => {
  it("round-trips PCM samples through base64", () => {
    const pcm = new Int16Array([0, -1, 32767, -32768, 1234]);
    expect(base64ToInt16(int16ToBase64(pcm))).toEqual(pcm);
  });

  it("round-trips a buffer large enough to cross the 32 KiB chunk boundary", () => {
    // 40001 samples = 80002 bytes, straddling the 0x8000-byte chunking
    // inside int16ToBase64 -- this is the case the vendored sample's
    // single-spread version crashes on.
    const pcm = new Int16Array(40001);
    for (let i = 0; i < pcm.length; i++) pcm[i] = (i * 7) % 65536 - 32768;
    expect(base64ToInt16(int16ToBase64(pcm))).toEqual(pcm);
  });

  it("drops a trailing odd byte rather than misaligning the Int16 view", () => {
    // Three bytes: only the first two form a valid Int16 sample.
    const base64 = btoa(String.fromCharCode(0x01, 0x02, 0x03));
    expect(base64ToInt16(base64)).toEqual(new Int16Array([0x0201]));
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

From `frontend/`:

```bash
npm test
```

Expected: FAIL — `Cannot find module './pcm'` (or the resolver's equivalent).

- [ ] **Step 3: Write the implementation**

Create `frontend/src/voice/lib/pcm.ts`:

```ts
/**
 * Conversions between the three audio representations the voice path
 * uses: Float32Array (Web Audio), Int16Array (16-bit PCM on the wire),
 * and base64 (inside the JSON WebSocket events).
 *
 * Adapted from the vendored reference sample
 * (`vendor/sample-nova-sonic-websocket-agentcore/frontend/src/websocket-presigned.ts`
 * and its hook), with two deliberate changes: base64 encoding is
 * chunked (the sample's single `String.fromCharCode(...bytes)` spread
 * overflows the call stack on real audio buffers), and decoding drops
 * a trailing odd byte instead of building a misaligned Int16 view.
 */

/** Float32 samples in [-1, 1] -> signed 16-bit PCM. */
export function floatToInt16(samples: Float32Array): Int16Array {
  const pcm = new Int16Array(samples.length);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return pcm;
}

/** Signed 16-bit PCM -> Float32 samples in [-1, 1]. */
export function int16ToFloat32(pcm: Int16Array): Float32Array {
  const floats = new Float32Array(pcm.length);
  for (let i = 0; i < pcm.length; i++) {
    floats[i] = pcm[i] / (pcm[i] < 0 ? 0x8000 : 0x7fff);
  }
  return floats;
}

// 32 KiB per String.fromCharCode call -- small enough that the spread
// argument never approaches the call-stack limit.
const BASE64_CHUNK = 0x8000;

/** Signed 16-bit PCM -> base64 (for `bidi_audio_input.audio`). */
export function int16ToBase64(pcm: Int16Array): string {
  const bytes = new Uint8Array(pcm.buffer, pcm.byteOffset, pcm.byteLength);
  let binary = "";
  for (let i = 0; i < bytes.length; i += BASE64_CHUNK) {
    binary += String.fromCharCode(...bytes.subarray(i, i + BASE64_CHUNK));
  }
  return btoa(binary);
}

/** base64 -> signed 16-bit PCM (for `bidi_audio_stream.audio`). */
export function base64ToInt16(base64: string): Int16Array {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  const usableBytes = bytes.length - (bytes.length % 2);
  return new Int16Array(bytes.buffer, 0, usableBytes / 2);
}
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
npm test
```

Expected: PASS — all pcm tests green.

- [ ] **Step 5: Verify the build still passes**

```bash
npm run build
```

Expected: PASS.

- [ ] **Step 6: Suggested commit message**

```text
feat(voice): add PCM/base64 audio conversions with tests

Pure Float32/Int16/base64 helpers for the voice path, adapted from
the vendored sample with chunked base64 encoding (the sample's single
spread overflows the stack on real buffers) and odd-byte-safe decode.
```

---

### Task 4: `voice/lib/agentEvents.ts` — server-message parsing and close-code copy (TDD)

The single validation boundary for everything the server sends (`code-standards.md` → "Validate/parse unknown API responses before trusting their shape"): raw WebSocket frames in, a typed discriminated union out. Also owns the close-code → user-facing copy mapping, because the deployed `/ws` deliberately sends only stable error codes as close reasons (`agentcore_app.py`), never human-readable text.

**Files:**
- Create: `frontend/src/voice/lib/agentEvents.ts`
- Test: `frontend/src/voice/lib/agentEvents.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces (used by Tasks 7, 9):
  - `type AgentMessage = { kind: "audio"; audio: string; format: string; sampleRate: number } | { kind: "transcript"; text: string; isFinal: boolean; role: "user" | "assistant" } | { kind: "interruption" }`
  - `parseAgentMessage(raw: unknown): AgentMessage | null` — `null` means "not for us / malformed; ignore".
  - `describeClose(code: number, reason: string): string`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/voice/lib/agentEvents.test.ts`:

```ts
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
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
npm test
```

Expected: FAIL — `Cannot find module './agentEvents'`.

- [ ] **Step 3: Write the implementation**

Create `frontend/src/voice/lib/agentEvents.ts`:

```ts
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
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
npm test
```

Expected: PASS.

- [ ] **Step 5: Verify the build**

```bash
npm run build
```

Expected: PASS.

- [ ] **Step 6: Suggested commit message**

```text
feat(voice): validate server WebSocket events and map close codes to copy

parseAgentMessage is the single boundary every server frame crosses
(typed union out, null for malformed/unknown), and describeClose turns
the deployed endpoint's stable close codes into patient-facing text.
```

---

### Task 5: `voice/lib/transcriptReducer.ts` — transcript state machine (TDD)

Pure state machine for the live transcript: final utterances become turns, partials accumulate as a single live line, interruptions drop the in-flight partial. Adapted from the vendored hook's bubble logic — deliberately simplified: `ui-context.md` asks for a "live transcript" below the orb, not a chat UI, so there is no bubble-merging and no `forceNewBubble` flag; every final is its own turn.

**Files:**
- Create: `frontend/src/voice/lib/transcriptReducer.ts`
- Test: `frontend/src/voice/lib/transcriptReducer.test.ts`

**Interfaces:**
- Consumes: `AgentMessage` from Task 4.
- Produces (used by Task 9):
  - `interface TranscriptTurn { readonly role: "user" | "assistant"; readonly text: string }`
  - `interface LiveTranscript { readonly role: "user" | "assistant"; readonly text: string }`
  - `interface TranscriptState { readonly turns: readonly TranscriptTurn[]; readonly live: LiveTranscript | null }`
  - `const initialTranscript: TranscriptState`
  - `applyToTranscript(state: TranscriptState, event: AgentMessage): TranscriptState`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/voice/lib/transcriptReducer.test.ts`:

```ts
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
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
npm test
```

Expected: FAIL — `Cannot find module './transcriptReducer'`.

- [ ] **Step 3: Write the implementation**

Create `frontend/src/voice/lib/transcriptReducer.ts`:

```ts
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
```

Note: a final's text is *appended to* the carried partial (the final often repeats the accumulated partial with the tail added — same accumulation the vendored hook performs), so `"book a"` + final `" cleaning"` commits as one `"book a cleaning"` turn, exactly as the test specifies.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
npm test
```

Expected: PASS.

- [ ] **Step 5: Verify the build**

```bash
npm run build
```

Expected: PASS.

- [ ] **Step 6: Suggested commit message**

```text
feat(voice): add transcript state machine with tests

Finals commit as turns (appending any carried partial), partials
accumulate as one live line, interruptions drop the in-flight partial.
Simplified from the vendored hook's chat-bubble logic per ui-context.
```

---

### Task 6: `voice/lib/guestCredentials.ts` — guest Cognito credentials

SDK-glue: exchange nothing (no login) for temporary AWS credentials via the patient guest identity pool, cached until 5 minutes before expiry. This is the vendored sample's `aws-credentials.ts` with its core flow **inverted**: the sample exchanges a staff JWT for identity-pool credentials (`GetIdCommand` with `Logins`); patients have no login, and our `api_stack.py` identity pool has `allow_unauthenticated_identities=True` and no providers, so `GetId` is called **without** `Logins` at both steps.

**Files:**
- Create: `frontend/src/voice/lib/guestCredentials.ts`

**Interfaces:**
- Consumes: `import.meta.env.VITE_PATIENT_GUEST_IDENTITY_POOL_ID`, `VITE_REGION` (Task 2).
- Produces (used by Task 7):
  - `interface GuestCredentials { accessKeyId: string; secretAccessKey: string; sessionToken: string }`
  - `getGuestCredentials(): Promise<GuestCredentials>` (throws `Error` with a human-readable message if env is missing or AWS returns nothing)
  - `clearGuestCredentials(): void`

No unit test: the logic is two SDK calls plus a cache; the meaningful verification is the browser session in Task 11 (the vendored sample shipped the same code untested for the same reason). Type-correctness is enforced by `tsc -b`.

- [ ] **Step 1: Write the implementation**

Create `frontend/src/voice/lib/guestCredentials.ts`:

```ts
/**
 * Guest AWS credentials for the patient voice UI.
 *
 * Adapted from the vendored sample's `aws-credentials.ts` with the flow
 * inverted: the sample exchanges a staff JWT for identity-pool
 * credentials; patients never log in. Our identity pool
 * (`api_stack.py` -> `_build_patient_guest_identity`) allows
 * unauthenticated identities and has no providers, so both calls below
 * omit `Logins` entirely. The guest role's only grant is
 * `runtime.grant_invoke_runtime` -- nothing else.
 */

import {
  CognitoIdentityClient,
  GetCredentialsForIdentityCommand,
  GetIdCommand,
} from "@aws-sdk/client-cognito-identity";

export interface GuestCredentials {
  accessKeyId: string;
  secretAccessKey: string;
  sessionToken: string;
}

const FIVE_MINUTES_MS = 5 * 60 * 1000;

let cached: { credentials: GuestCredentials; expiresAt: number } | null = null;

export async function getGuestCredentials(): Promise<GuestCredentials> {
  if (cached !== null && cached.expiresAt - Date.now() > FIVE_MINUTES_MS) {
    return cached.credentials;
  }

  const identityPoolId = import.meta.env.VITE_PATIENT_GUEST_IDENTITY_POOL_ID;
  const region = import.meta.env.VITE_REGION;
  if (!identityPoolId || !region) {
    throw new Error(
      "Voice is not configured: VITE_PATIENT_GUEST_IDENTITY_POOL_ID and VITE_REGION must be set.",
    );
  }

  const client = new CognitoIdentityClient({ region });

  // No `Logins`: this is a guest identity, not an authenticated one.
  const identityId = (await client.send(new GetIdCommand({ IdentityPoolId: identityPoolId })))
    .IdentityId;
  if (!identityId) {
    throw new Error("The clinic's voice sign-in did not return an identity.");
  }

  const response = await client.send(
    new GetCredentialsForIdentityCommand({ IdentityId: identityId }),
  );
  const credentials = response.Credentials;
  if (
    !credentials?.AccessKeyId ||
    !credentials?.SecretKey ||
    !credentials?.SessionToken
  ) {
    throw new Error("The clinic's voice sign-in did not return credentials.");
  }

  const result: GuestCredentials = {
    accessKeyId: credentials.AccessKeyId,
    secretAccessKey: credentials.SecretKey,
    sessionToken: credentials.SessionToken,
  };
  cached = {
    credentials: result,
    expiresAt: credentials.Expiration?.getTime() ?? Date.now() + 50 * 60 * 1000,
  };
  return result;
}

/** Drop the cache (e.g. if a presign starts failing auth mid-session). */
export function clearGuestCredentials(): void {
  cached = null;
}
```

- [ ] **Step 2: Verify with the compiler and build**

```bash
npm test
npm run build
```

Expected: existing tests still PASS; build PASS (proves the new package resolves and the types line up).

- [ ] **Step 3: Suggested commit message**

```text
feat(voice): guest Cognito identity-pool credentials for patients

GetId/GetCredentialsForIdentity without Logins (guest flow), cached
with a 5-minute expiry buffer. Inverts the vendored sample's
JWT-authenticated flow to match the deployed guest identity pool.
```

---

### Task 7: `voice/lib/agentSocket.ts` — presign and connect

The connection module: presign the AgentCore WebSocket URL with SigV4 (guest credentials), **adding `clinic_id` to the signed query string** — the one wire-level change versus the vendored sample, and the mechanism the deployed `/ws` relies on for tenant selection. Also owns the local-dev bypass and typed message dispatch via `parseAgentMessage`.

**Files:**
- Create: `frontend/src/voice/lib/agentSocket.ts`

**Interfaces:**
- Consumes: `getGuestCredentials` (Task 6), `parseAgentMessage` (Task 4), `import.meta.env.VITE_AGENT_RUNTIME_ARN` / `VITE_REGION` / `VITE_LOCAL_DEV` / `VITE_AGENT_RUNTIME_URL` (Task 2).
- Produces (used by Task 9):
  - `interface BidiAudioInputEvent { type: "bidi_audio_input"; audio: string; format: "pcm"; sample_rate: 16000; channels: 1 }`
  - `interface VoiceAgentConnection { send(event: BidiAudioInputEvent): void; close(): void; isConnected(): boolean; readonly sessionId: string }`
  - `interface ConnectOptions { clinicId: string; onAudioChunk: (audio: string, format: string, sampleRate: number) => void; onTranscript: (text: string, isFinal: boolean, role: "user" | "assistant") => void; onInterruption?: () => void; onError?: (message: string) => void; onConnected?: () => void; onDisconnected?: (code: number, reason: string) => void; sessionId?: string }`
  - `connectToAgent(options: ConnectOptions): Promise<VoiceAgentConnection>` — resolves on open, rejects if the socket errors before opening.

No unit test: everything here is SDK/Socket glue; the pure logic it depends on (parsing, PCM, transcript) is tested in Tasks 3–5, and the connection itself is verified in Task 11's browser session.

- [ ] **Step 1: Write the implementation**

Create `frontend/src/voice/lib/agentSocket.ts`:

```ts
/**
 * Presigned WebSocket connection to the deployed AgentCore Runtime.
 *
 * Adapted from the vendored sample's `websocket-presigned.ts` with
 * three deliberate changes, each called out inline: guest credentials
 * instead of staff-JWT credentials; `clinic_id` added to the signed
 * query (the tenant selector `agentcore_app.py` reads before accept());
 * `ws://` (not `wss://`) in local dev, because Vite's dev server is
 * plain http on localhost.
 */

import { Sha256 } from "@aws-crypto/sha256-js";
import { SignatureV4 } from "@aws-sdk/signature-v4";
import { HttpRequest } from "@smithy/protocol-http";

import { parseAgentMessage } from "./agentEvents";
import { getGuestCredentials } from "./guestCredentials";

export interface BidiAudioInputEvent {
  type: "bidi_audio_input";
  audio: string;
  format: "pcm";
  sample_rate: 16000;
  channels: 1;
}

export interface VoiceAgentConnection {
  send(event: BidiAudioInputEvent): void;
  close(): void;
  isConnected(): boolean;
  readonly sessionId: string;
}

export interface ConnectOptions {
  clinicId: string;
  onAudioChunk: (audio: string, format: string, sampleRate: number) => void;
  onTranscript: (text: string, isFinal: boolean, role: "user" | "assistant") => void;
  onInterruption?: () => void;
  onError?: (message: string) => void;
  onConnected?: () => void;
  onDisconnected?: (code: number, reason: string) => void;
  /** Reuse a prior session id to resume a call's context. */
  sessionId?: string;
}

/** AgentCore requires session ids of at least 33 characters; a UUID is 36. */
function generateSessionId(): string {
  return crypto.randomUUID();
}

async function fetchPresignedUrl(clinicId: string, sessionId: string): Promise<string> {
  const isLocalDev = import.meta.env.VITE_LOCAL_DEV === "true";
  const localUrl = import.meta.env.VITE_AGENT_RUNTIME_URL;
  if (isLocalDev && localUrl) {
    // CHANGE vs vendored sample: it hardcodes wss://, which fails
    // against Vite's plain-http dev server on localhost.
    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    const url = new URL(`${scheme}://${window.location.host}${localUrl}`);
    url.searchParams.set("clinic_id", clinicId);
    return url.toString();
  }

  const agentRuntimeArn = import.meta.env.VITE_AGENT_RUNTIME_ARN;
  const region = import.meta.env.VITE_REGION;
  if (!agentRuntimeArn || !region) {
    throw new Error(
      "Voice is not configured: VITE_AGENT_RUNTIME_ARN and VITE_REGION must be set.",
    );
  }

  // CHANGE vs vendored sample: guest credentials, no staff JWT involved.
  const credentials = await getGuestCredentials();

  const url = new URL(
    `https://bedrock-agentcore.${region}.amazonaws.com/runtimes/${encodeURIComponent(agentRuntimeArn)}/ws`,
  );
  url.searchParams.set("qualifier", "DEFAULT");
  url.searchParams.set("X-Amzn-Bedrock-AgentCore-Runtime-Session-Id", sessionId);
  // CHANGE vs vendored sample: the tenant selector. It must be part of
  // the *signed* query, so it is set before presigning -- AgentCore's
  // proxy forwards its own session-id parameter through to /ws, and
  // clinic_id rides the same mechanism. Whether it actually arrives is
  // Open Question "clinic_id forwarding" in progress-tracker.md.
  url.searchParams.set("clinic_id", clinicId);

  const request = new HttpRequest({
    method: "GET",
    protocol: "https:",
    hostname: url.hostname,
    path: url.pathname,
    query: Object.fromEntries(url.searchParams),
    headers: { host: url.hostname },
  });

  const signer = new SignatureV4({
    service: "bedrock-agentcore",
    region,
    credentials: {
      accessKeyId: credentials.accessKeyId,
      secretAccessKey: credentials.secretAccessKey,
      sessionToken: credentials.sessionToken,
    },
    sha256: Sha256,
  });

  const signed = await signer.presign(request, { expiresIn: 3600 });

  const query = signed.query ?? {};
  const queryString = Object.entries(query)
    .map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`)
    .join("&");

  return `wss://${signed.hostname}${signed.path ?? "/"}${queryString ? `?${queryString}` : ""}`;
}

export async function connectToAgent(
  options: ConnectOptions,
): Promise<VoiceAgentConnection> {
  const sessionId = options.sessionId ?? generateSessionId();
  const presignedUrl = await fetchPresignedUrl(options.clinicId, sessionId);
  const ws = new WebSocket(presignedUrl);

  return new Promise((resolve, reject) => {
    ws.onopen = () => {
      options.onConnected?.();
      resolve({
        send: (event) => {
          if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(event));
        },
        close: () => ws.close(),
        isConnected: () => ws.readyState === WebSocket.OPEN,
        sessionId,
      });
    };

    // Fires both for pre-open failures (rejects below) and post-open
    // drops; rejecting an already-settled promise is a no-op, so both
    // paths are safe.
    ws.onerror = () => {
      const message = "Could not reach the clinic's voice service.";
      options.onError?.(message);
      reject(new Error(message));
    };

    ws.onclose = (event: CloseEvent) => {
      // The deployed /ws sends stable error codes as the reason
      // (agentcore_app.py); describeClose turns them into copy.
      options.onDisconnected?.(event.code, event.reason);
    };

    ws.onmessage = (event: MessageEvent) => {
      const message = parseAgentMessage(event.data);
      if (message === null) return;
      switch (message.kind) {
        case "audio":
          options.onAudioChunk(message.audio, message.format, message.sampleRate);
          break;
        case "transcript":
          options.onTranscript(message.text, message.isFinal, message.role);
          break;
        case "interruption":
          options.onInterruption?.();
          break;
      }
    };
  });
}
```

- [ ] **Step 2: Verify with the compiler and build**

```bash
npm test
npm run build
```

Expected: tests PASS; build PASS (proves the three presign packages resolve and the SigV4 types line up).

- [ ] **Step 3: Suggested commit message**

```text
feat(voice): presigned AgentCore WebSocket connection with clinic_id

SigV4-presigns the runtime /ws URL using guest credentials and adds
clinic_id to the signed query string -- the tenant selector the
deployed endpoint reads before accepting. Includes the local-dev
bypass (ws:// against Vite's dev server).
```

---

### Task 8: `voice/audio-capture-processor.worklet.js` — mic capture worklet

The AudioWorklet that converts mic Float32 frames to Int16 PCM on the audio thread. This one file is a faithful adaptation of the vendored sample's worklet — it is 27 lines, already correct, and has no types to add (AudioWorklet globals are plain JS).

**Files:**
- Create: `frontend/src/voice/audio-capture-processor.worklet.js`

**Interfaces:**
- Consumes: nothing (runs on the audio thread; loaded by Task 9 via `import workletUrl from "./audio-capture-processor.worklet.js?url"`).
- Produces: a registered `audio-capture-processor` worklet that posts `{ type: "audio", data: Int16Array }` messages.

No unit test: worklets cannot run outside a real AudioContext. Verified in Task 11's browser session.

- [ ] **Step 1: Create the worklet**

Create `frontend/src/voice/audio-capture-processor.worklet.js`:

```js
// AudioWorklet processor: converts mic Float32 frames to 16-bit PCM on
// the audio thread. Adapted from the vendored reference sample
// (vendor/sample-nova-sonic-websocket-agentcore/frontend/src/
// audio-processor.worklet.js); the body is unchanged -- only this
// comment and its new home differ. Plain JS by necessity: worklets run
// on the audio thread with no TypeScript support, and vite serves this
// file as-is via the `?url` import.

class AudioCaptureProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const input = inputs[0];

    if (!input || !input[0]) {
      return true;
    }

    const inputData = input[0];

    // Convert Float32Array to Int16Array (PCM 16-bit).
    const pcmData = new Int16Array(inputData.length);
    for (let i = 0; i < inputData.length; i++) {
      const s = Math.max(-1, Math.min(1, inputData[i]));
      pcmData[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }

    this.port.postMessage({ type: "audio", data: pcmData });

    return true;
  }
}

registerProcessor("audio-capture-processor", AudioCaptureProcessor);
```

- [ ] **Step 2: Verify the build**

```bash
npm run build
```

Expected: PASS (`tsc -b` skips plain `.js` here; vite proves the file exists and parses via the import added in Task 9 — if you run this step before Task 9, at minimum confirm the file exists and is syntactically valid JS).

- [ ] **Step 3: Suggested commit message**

```text
feat(voice): add mic-capture AudioWorklet (Float32 -> Int16 PCM)

Adapted from the vendored sample's worklet unchanged in body; plain JS
by necessity since worklets run on the audio thread without TS.
```

---

### Task 9: `voice/useVoiceCall.ts` — the hook

The only place that touches both the WebSocket and the Web Audio API. Adapted from the vendored sample's `useVoiceAgent.ts` with these deliberate changes: strictly typed throughout (no `any`, no `as any` MediaRecorder stand-in — a small `RecordingHandle` interface instead); guest connect takes `clinicId`; transcript state flows through the pure reducer from Task 5; playback supports PCM only (our runtime emits `pcm`; the sample's encoded-format branch is dead code here); interruption clears the playback queue *and* the live partial.

**Files:**
- Create: `frontend/src/voice/useVoiceCall.ts`

**Interfaces:**
- Consumes: `connectToAgent`, `BidiAudioInputEvent`, `VoiceAgentConnection` (Task 7); `describeClose` (Task 4); `applyToTranscript`, `initialTranscript`, `TranscriptState` (Task 5); `base64ToInt16`, `int16ToBase64` (Task 3); the worklet URL (Task 8).
- Produces (used by Task 10):
  - `interface UseVoiceCallReturn { isConnected: boolean; isRecording: boolean; isSpeaking: boolean; errorMessage: string | null; transcript: TranscriptState; connect(): Promise<void>; disconnect(): void; startRecording(): Promise<void>; stopRecording(): void; clearError(): void }`
  - `useVoiceCall(clinicId: string): UseVoiceCallReturn`

No unit test: every line is browser-API glue (AudioContext, getUserMedia, React state); the pure pieces it composes are tested in Tasks 3–5. Verified in Task 11's browser session.

- [ ] **Step 1: Write the implementation**

Create `frontend/src/voice/useVoiceCall.ts`:

```ts
/**
 * React hook owning one voice call: WebSocket connection, mic capture,
 * audio playback, and the state the voice screen renders.
 *
 * Adapted from the vendored sample's `useVoiceAgent.ts`, strictly
 * typed, with the changes listed in the plan: a RecordingHandle
 * replaces the sample's `as any` MediaRecorder stand-in, connect takes
 * a clinicId for the guest flow, transcript state flows through the
 * pure reducer, and playback is PCM-only (this runtime emits pcm).
 */

import { useCallback, useEffect, useRef, useState } from "react";

import workletUrl from "./audio-capture-processor.worklet.js?url";
import { describeClose } from "./lib/agentEvents";
import {
  connectToAgent,
  type BidiAudioInputEvent,
  type VoiceAgentConnection,
} from "./lib/agentSocket";
import { base64ToInt16, int16ToFloat32, int16ToBase64 } from "./lib/pcm";
import {
  applyToTranscript,
  initialTranscript,
  type TranscriptState,
} from "./lib/transcriptReducer";

const SAMPLE_RATE = 16000;

interface RecordingHandle {
  stop(): void;
}

export interface UseVoiceCallReturn {
  isConnected: boolean;
  isRecording: boolean;
  isSpeaking: boolean;
  errorMessage: string | null;
  transcript: TranscriptState;
  connect: () => Promise<void>;
  disconnect: () => void;
  startRecording: () => Promise<void>;
  stopRecording: () => void;
  clearError: () => void;
}

export function useVoiceCall(clinicId: string): UseVoiceCallReturn {
  const [isConnected, setIsConnected] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [transcript, setTranscript] = useState<TranscriptState>(initialTranscript);

  const connectionRef = useRef<VoiceAgentConnection | null>(null);
  const recordingRef = useRef<RecordingHandle | null>(null);
  const playbackContextRef = useRef<AudioContext | null>(null);
  const audioQueueRef = useRef<AudioBuffer[]>([]);
  const isPlayingRef = useRef(false);

  const playNextAudio = useCallback(() => {
    const context = playbackContextRef.current;
    if (!context || context.state === "closed" || audioQueueRef.current.length === 0) {
      isPlayingRef.current = false;
      setIsSpeaking(false);
      return;
    }
    isPlayingRef.current = true;
    setIsSpeaking(true);

    const buffer = audioQueueRef.current.shift()!;
    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(context.destination);
    source.onended = () => playNextAudio();
    source.start();
  }, []);

  const queueAudio = useCallback(
    (base64Audio: string, sampleRate: number) => {
      try {
        if (!playbackContextRef.current || playbackContextRef.current.state === "closed") {
          playbackContextRef.current = new AudioContext({ sampleRate });
        }
        const context = playbackContextRef.current;

        const floats = int16ToFloat32(base64ToInt16(base64Audio));
        const buffer = context.createBuffer(1, floats.length, sampleRate);
        buffer.getChannelData(0).set(floats);

        audioQueueRef.current.push(buffer);
        if (!isPlayingRef.current) playNextAudio();
      } catch (error) {
        console.error("Failed to queue audio for playback", error);
      }
    },
    [playNextAudio],
  );

  const connect = useCallback(async () => {
    try {
      setErrorMessage(null);
      const connection = await connectToAgent({
        clinicId,
        onConnected: () => setIsConnected(true),
        onDisconnected: (code, reason) => {
          setIsConnected(false);
          setIsRecording(false);
          setIsSpeaking(false);
          // 1000 is a normal close (we or the agent hung up); anything
          // else deserves an explanation.
          if (code !== 1000) setErrorMessage(describeClose(code, reason));
        },
        onAudioChunk: (audio, _format, sampleRate) => queueAudio(audio, sampleRate),
        onTranscript: (text, isFinal, role) => {
          setTranscript((prev) =>
            applyToTranscript(prev, { kind: "transcript", text, isFinal, role }),
          );
        },
        onInterruption: () => {
          // The patient talked over the agent: drop whatever was queued
          // or playing, and drop the in-flight partial.
          audioQueueRef.current = [];
          isPlayingRef.current = false;
          setIsSpeaking(false);
          setTranscript((prev) => applyToTranscript(prev, { kind: "interruption" }));
        },
        onError: (message) => setErrorMessage(message),
      });
      connectionRef.current = connection;
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      setErrorMessage(detail);
    }
  }, [clinicId, queueAudio]);

  const stopRecording = useCallback(() => {
    recordingRef.current?.stop();
    recordingRef.current = null;
    setIsRecording(false);
  }, []);

  const disconnect = useCallback(() => {
    stopRecording();
    connectionRef.current?.close();
    connectionRef.current = null;

    audioQueueRef.current = [];
    isPlayingRef.current = false;
    if (playbackContextRef.current && playbackContextRef.current.state !== "closed") {
      void playbackContextRef.current.close();
    }

    setIsConnected(false);
    setIsRecording(false);
    setIsSpeaking(false);
    setErrorMessage(null);
    setTranscript(initialTranscript);
  }, [stopRecording]);

  const startRecording = useCallback(async () => {
    if (recordingRef.current !== null || !connectionRef.current?.isConnected()) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          sampleRate: SAMPLE_RATE,
          echoCancellation: true,
          noiseSuppression: true,
        },
      });

      const context = new AudioContext({ sampleRate: SAMPLE_RATE });
      await context.audioWorklet.addModule(workletUrl);
      const source = context.createMediaStreamSource(stream);
      const node = new AudioWorkletNode(context, "audio-capture-processor");

      node.port.onmessage = (event: MessageEvent) => {
        const connection = connectionRef.current;
        if (!connection?.isConnected() || recordingRef.current === null) return;
        const payload = event.data as { type?: unknown; data?: unknown };
        if (payload.type !== "audio" || !(payload.data instanceof Int16Array)) return;

        const audioEvent: BidiAudioInputEvent = {
          type: "bidi_audio_input",
          audio: int16ToBase64(payload.data),
          format: "pcm",
          sample_rate: SAMPLE_RATE,
          channels: 1,
        };
        connection.send(audioEvent);
      };

      source.connect(node);
      // The worklet writes no output, but the graph must reach the
      // destination for the audio thread to be driven at all.
      node.connect(context.destination);

      recordingRef.current = {
        stop: () => {
          node.disconnect();
          source.disconnect();
          void context.close();
          stream.getTracks().forEach((track) => track.stop());
        },
      };
      setIsRecording(true);
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      setErrorMessage(`Microphone error: ${detail}`);
    }
  }, []);

  const clearError = useCallback(() => setErrorMessage(null), []);

  // Tear the whole call down on unmount.
  useEffect(() => disconnect, [disconnect]);

  return {
    isConnected,
    isRecording,
    isSpeaking,
    errorMessage,
    transcript,
    connect,
    disconnect,
    startRecording,
    stopRecording,
    clearError,
  };
}
```

- [ ] **Step 2: Verify with tests and build**

```bash
npm test
npm run build
```

Expected: tests PASS; build PASS — including the `?url` import resolving to the worklet file from Task 8.

- [ ] **Step 3: Suggested commit message**

```text
feat(voice): useVoiceCall hook wiring socket, capture, and playback

Strictly-typed adaptation of the vendored sample's hook: a proper
RecordingHandle replaces its `as any` stand-in, connect targets the
guest /ws with a clinicId, transcripts flow through the pure reducer,
and playback is PCM-only to match this runtime.
```

---

### Task 10: Voice UI components and routing

The screens: clinic picker → voice screen (top bar + orb + transcript), and the hash route that mounts them. Layout per `ui-context.md` → Layout Patterns ("Voice screen: full-viewport, centered layout — a single large voice orb/avatar as the focal point, minimal chrome, live transcript optionally shown below it, clinic name/logo in a slim top bar") and Colors/Radius/Icons tables.

**Files:**
- Create: `frontend/src/voice/lib/clinics.ts`
- Create: `frontend/src/voice/components/ClinicPicker.tsx`
- Create: `frontend/src/voice/components/VoiceOrb.tsx`
- Create: `frontend/src/voice/components/TranscriptPanel.tsx`
- Create: `frontend/src/voice/components/VoiceScreen.tsx`
- Create: `frontend/src/voice/VoiceApp.tsx`
- Modify: `frontend/src/App.tsx` (replace entirely — it is 11 lines whose only job was "mount the dashboard until voice/ exists")

**Interfaces:**
- Consumes: `useVoiceCall` (Task 9), `TranscriptState`/`TranscriptTurn`/`LiveTranscript` (Task 5), shadcn `Button` (`frontend/src/shared/components/ui/button.tsx`), Lucide icons.
- Produces: `VoiceApp` (mounted by App.tsx at `#/voice`); `Clinic { id, name, tagline }` in `voice/lib/clinics.ts`.

No unit test for the components themselves (no component-testing setup exists in this repo and adding one is out of scope); verification is `npm run build` plus the Task 11 browser check, per `ai-workflow-rules.md` ("a UI change renders and functions in the browser").

- [ ] **Step 1: The clinic registry**

Create `frontend/src/voice/lib/clinics.ts`:

```ts
/**
 * The clinics a patient can call, keyed by the `clinic_id` values the
 * backend scopes everything by. Names match `seed/clinic_data.py`.
 *
 * This is the interim answer to the "public clinic-listing route?"
 * Open Question in progress-tracker.md: a static registry is fine for
 * a two-clinic demo and wrong the moment clinics are added in
 * DynamoDB -- do not extend this pattern, resolve the question.
 */

export interface Clinic {
  readonly id: string;
  readonly name: string;
  /** One line of demo copy shown under the name in the picker. */
  readonly tagline: string;
}

export const DEMO_CLINICS: readonly Clinic[] = [
  {
    id: "clinic-dental",
    name: "Bright Smile Dental",
    tagline: "Dental appointments, reschedules, and questions",
  },
  {
    id: "clinic-cosmetic",
    name: "Lumiere Aesthetics",
    tagline: "Cosmetic consultations and bookings",
  },
];
```

- [ ] **Step 2: The clinic picker**

Create `frontend/src/voice/components/ClinicPicker.tsx`:

```tsx
import { Building2, Phone } from "lucide-react";

import type { Clinic } from "../lib/clinics";
import { DEMO_CLINICS } from "../lib/clinics";

interface ClinicPickerProps {
  onChoose: (clinic: Clinic) => void;
}

export function ClinicPicker({ onChoose }: ClinicPickerProps) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-8 bg-[var(--bg-base)] px-4">
      <div className="text-center">
        <h1 className="font-sans text-2xl font-semibold text-[var(--text-primary)]">
          Who are you calling?
        </h1>
        <p className="mt-1 text-sm text-[var(--text-muted)]">
          Pick a clinic to speak with its AI front desk.
        </p>
      </div>
      <div className="grid w-full max-w-md gap-3">
        {DEMO_CLINICS.map((clinic) => (
          <button
            key={clinic.id}
            type="button"
            onClick={() => onChoose(clinic)}
            className="flex items-center justify-between rounded-xl border border-[var(--border-default)] bg-[var(--bg-surface)] px-4 py-4 text-left transition-colors hover:border-[var(--accent-primary)]"
          >
            <span className="flex items-center gap-3">
              <Building2 className="h-5 w-5 text-[var(--accent-primary)]" />
              <span>
                <span className="block font-medium text-[var(--text-primary)]">
                  {clinic.name}
                </span>
                <span className="block text-sm text-[var(--text-muted)]">{clinic.tagline}</span>
              </span>
            </span>
            <Phone className="h-5 w-5 text-[var(--text-muted)]" />
          </button>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: The voice orb**

Create `frontend/src/voice/components/VoiceOrb.tsx`:

```tsx
import { Loader2, Mic, PhoneOff, Volume2 } from "lucide-react";

import type { LucideIcon } from "lucide-react";

export type OrbStatus = "connecting" | "ready" | "listening" | "speaking" | "error";

const ORB_STYLES: Record<OrbStatus, string> = {
  connecting:
    "border-[var(--border-default)] bg-[var(--bg-surface)] text-[var(--text-muted)]",
  ready: "border-transparent bg-[var(--accent-primary)] text-[var(--bg-surface)]",
  listening:
    "border-transparent bg-[var(--accent-primary)] text-[var(--bg-surface)] animate-pulse",
  speaking: "border-transparent bg-[var(--accent-secondary)] text-[var(--bg-surface)]",
  error: "border-transparent bg-[var(--state-error)] text-[var(--bg-surface)]",
};

const ORB_LABELS: Record<OrbStatus, string> = {
  connecting: "Connecting to the clinic…",
  ready: "Tap to speak",
  listening: "Listening — tap to pause",
  speaking: "The clinic is speaking",
  error: "The call failed",
};

const ORB_ICONS: Record<OrbStatus, LucideIcon> = {
  connecting: Loader2,
  ready: Mic,
  listening: Mic,
  speaking: Volume2,
  error: PhoneOff,
};

interface VoiceOrbProps {
  status: OrbStatus;
  onClick: () => void;
}

export function VoiceOrb({ status, onClick }: VoiceOrbProps) {
  const Icon = ORB_ICONS[status];
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={status === "connecting" || status === "error"}
      aria-label={ORB_LABELS[status]}
      className={`flex h-40 w-40 items-center justify-center rounded-full border-2 transition-colors ${ORB_STYLES[status]}`}
    >
      <Icon className={`h-8 w-8 ${status === "connecting" ? "animate-spin" : ""}`} />
    </button>
  );
}
```

(`text-[var(--bg-surface)]` — white — is the on-accent text color; `ui-context.md` defines no dedicated on-accent token, and reusing the surface token keeps every color a token reference.)

- [ ] **Step 4: The transcript panel**

Create `frontend/src/voice/components/TranscriptPanel.tsx`:

```tsx
import { useEffect, useRef } from "react";

import type { LiveTranscript, TranscriptTurn } from "../lib/transcriptReducer";

interface TranscriptPanelProps {
  turns: readonly TranscriptTurn[];
  live: LiveTranscript | null;
}

const speakerLabel = (role: "user" | "assistant"): string =>
  role === "user" ? "You: " : "Clinic: ";

export function TranscriptPanel({ turns, live }: TranscriptPanelProps) {
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "nearest" });
  }, [turns, live]);

  return (
    <div
      aria-live="polite"
      className="max-h-64 w-full max-w-xl overflow-y-auto rounded-xl border border-[var(--border-default)] bg-[var(--bg-surface)] px-4 py-3"
    >
      {turns.length === 0 && live === null && (
        <p className="text-sm text-[var(--text-muted)]">
          Your conversation will appear here.
        </p>
      )}
      {turns.map((turn, index) => (
        <p
          key={index}
          className={
            turn.role === "user"
              ? "text-sm text-[var(--text-muted)]"
              : "text-sm text-[var(--text-primary)]"
          }
        >
          <span className="font-medium">{speakerLabel(turn.role)}</span>
          {turn.text}
        </p>
      ))}
      {live !== null && (
        <p className="text-sm italic text-[var(--text-muted)]">
          <span className="font-medium not-italic">{speakerLabel(live.role)}</span>
          {live.text}
        </p>
      )}
      <div ref={endRef} />
    </div>
  );
}
```

- [ ] **Step 5: The voice screen**

Create `frontend/src/voice/components/VoiceScreen.tsx`:

```tsx
import { useEffect } from "react";
import { PhoneOff } from "lucide-react";

import { Button } from "@/shared/components/ui/button";
import type { Clinic } from "../lib/clinics";
import { useVoiceCall } from "../useVoiceCall";
import { TranscriptPanel } from "./TranscriptPanel";
import { VoiceOrb, type OrbStatus } from "./VoiceOrb";

interface VoiceScreenProps {
  clinic: Clinic;
  onExit: () => void;
}

export function VoiceScreen({ clinic, onExit }: VoiceScreenProps) {
  const call = useVoiceCall(clinic.id);

  // Connect when the screen opens, tear down when it closes. Both are
  // stable useCallbacks, so this runs once per mount.
  useEffect(() => {
    void call.connect();
    return () => call.disconnect();
  }, [call.connect, call.disconnect]);

  const orbStatus: OrbStatus = call.errorMessage !== null
    ? "error"
    : !call.isConnected
      ? "connecting"
      : call.isRecording
        ? "listening"
        : call.isSpeaking
          ? "speaking"
          : "ready";

  const handleOrbClick = () => {
    if (call.isRecording) call.stopRecording();
    else void call.startRecording();
  };

  return (
    <div className="flex min-h-screen flex-col bg-[var(--bg-base)]">
      <header className="flex items-center justify-between border-b border-[var(--border-default)] bg-[var(--bg-surface)] px-4 py-2">
        <span className="font-sans text-sm font-medium text-[var(--text-primary)]">
          {clinic.name}
        </span>
        <Button variant="ghost" size="sm" onClick={onExit}>
          <PhoneOff className="h-4 w-4" />
          End call
        </Button>
      </header>
      <main className="flex flex-1 flex-col items-center justify-center gap-8 px-4 py-8">
        <VoiceOrb status={orbStatus} onClick={handleOrbClick} />
        {call.errorMessage !== null && (
          <p className="max-w-md text-center text-sm text-[var(--state-error)]">
            {call.errorMessage}
          </p>
        )}
        <TranscriptPanel turns={call.transcript.turns} live={call.transcript.live} />
      </main>
    </div>
  );
}
```

(Check `frontend/src/shared/components/ui/button.tsx` before relying on `variant="ghost"` / `size="sm"` — it is stock shadcn and has both, but if either variant is absent, use the closest existing variant rather than editing the protected shadcn file.)

- [ ] **Step 6: The app shell**

Create `frontend/src/voice/VoiceApp.tsx`:

```tsx
import { useState } from "react";

import { ClinicPicker } from "./components/ClinicPicker";
import { VoiceScreen } from "./components/VoiceScreen";
import type { Clinic } from "./lib/clinics";

/**
 * The patient surface: pick a clinic, then carry the call. Mounting at
 * `#/voice` (see App.tsx); the dashboard stays at `#/` and below.
 */
export function VoiceApp() {
  const [clinic, setClinic] = useState<Clinic | null>(null);

  return clinic === null ? (
    <ClinicPicker onChoose={setClinic} />
  ) : (
    <VoiceScreen clinic={clinic} onExit={() => setClinic(null)} />
  );
}
```

- [ ] **Step 7: Route by hash in App.tsx**

Replace the whole of `frontend/src/App.tsx` with:

```tsx
import { useEffect, useState } from "react";

import { DashboardApp } from "@/dashboard/DashboardApp";
import { VoiceApp } from "@/voice/VoiceApp";

// `architecture.md` -> Stack: one SPA serves both the patient voice UI
// (`frontend/src/voice/`) and the staff dashboard
// (`frontend/src/dashboard/`). Hash routing keeps the split inside one
// static bundle with no router dependency and no server rewrites --
// `#/voice` is the patient surface, everything else is the dashboard.
type Surface = "dashboard" | "voice";

function surfaceFromHash(hash: string): Surface {
  return hash === "#/voice" ? "voice" : "dashboard";
}

export default function App() {
  const [surface, setSurface] = useState<Surface>(() =>
    surfaceFromHash(window.location.hash),
  );

  useEffect(() => {
    const onHashChange = () => setSurface(surfaceFromHash(window.location.hash));
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  return surface === "voice" ? <VoiceApp /> : <DashboardApp />;
}
```

- [ ] **Step 8: Verify with tests and build**

```bash
npm test
npm run build
```

Expected: tests PASS; build PASS with zero type errors.

- [ ] **Step 9: Browser smoke check (no AWS needed)**

```bash
npm run dev
```

Open `http://localhost:5173/#/voice`. Expected without any AWS config: the clinic picker renders with both clinics, clicking one opens the voice screen (top bar with the clinic name, orb in `connecting` state, empty transcript panel), and an error message appears once the presign fails on the missing env vars ("Voice is not configured…"). Then click "End call" → back to the picker; `#/` still shows the dashboard login. This proves routing, state flow, and error copy render before any cloud dependency.

- [ ] **Step 10: Suggested commit message**

```text
feat(voice): patient voice UI -- picker, orb, transcript, and routing

Full-viewport voice screen per ui-context.md: clinic picker (static
two-clinic registry), stateful orb with mic toggle, live transcript
with auto-scroll, slim clinic-name top bar. Mounted at #/voice via a
hash split that leaves the dashboard untouched at #/.
```

---

### Task 11: Configure env, end-to-end test, update tracker

**Files:**
- Modify: `frontend/.env` (real values — this file is git-ignored; ask the user, do not scrape AWS)
- Modify: `context/progress-tracker.md` (move the voice UI item Next Up → Completed)

**Interfaces:**
- Consumes: everything from Tasks 2–10.
- Produces: a tracker entry recording what shipped, what was verified live, and what remains open.

- [ ] **Step 1: Fill `frontend/.env` with the deployed values**

The three new values come from the deployed stacks' outputs. This environment has no AWS credentials (per the tracker's Session Notes), so **ask the user** for them, or have the user run from `backend/infra`:

```bash
npx cdk deploy --outputs-file cdk-outputs.json
```

…which writes every stack's `CfnOutput`s to one JSON file (`AgentRuntimeArn` from the Agent stack, `PatientGuestIdentityPoolId` from the Api stack). Append to `frontend/.env` (real values, this file is git-ignored):

```text
VITE_AGENT_RUNTIME_ARN=<AgentRuntimeArn output>
VITE_PATIENT_GUEST_IDENTITY_POOL_ID=<PatientGuestIdentityPoolId output>
VITE_REGION=us-east-1
```

- [ ] **Step 2: Run the real browser session**

```bash
npm run dev
```

Open `http://localhost:5173/#/voice`, pick **Bright Smile Dental**, allow the mic, tap the orb, and hold a short conversation ("When are you next open?"). What this must prove, in order:

1. The presign succeeds and the socket **opens** (orb leaves `connecting`) — proves the guest identity-pool flow end to end.
2. The greeting plays as audio — proves downstream `bidi_audio_stream` → PCM playback.
3. The transcript fills with both roles — proves `bidi_transcript_stream` parsing.
4. Ask something bookable ("Can I book a cleaning Tuesday morning?") — proves the full loop into the Orchestrator and back.
5. **The clinic_id question resolves**: if the call works, AgentCore forwards the param and the Open Question is answered *yes*; if the socket closes immediately with reason `missing_clinic_id`, it does not — stop, record the answer in the tracker's Open Questions, and escalate to the user rather than inventing a workaround.

- [ ] **Step 3: Record the clinic_id answer in the tracker**

Whichever way Step 2's check lands, update the "Does AgentCore's presigned-URL proxy forward extra query parameters" Open Question in `context/progress-tracker.md` with the observed answer and date. If it is *no*, also stop work here — the remainder of the session is deciding the tenant-selection channel, not coding.

- [ ] **Step 4: Move the item to Completed in the tracker**

In `context/progress-tracker.md`:

1. Remove the "Patient voice UI" item from Next Up and renumber the rest.
2. Add it under Completed, including: what was built (the file structure above), the deliberate divergences from the vendored sample (guest credentials, `clinic_id` in the signed query, chunked base64, PCM-only playback, `RecordingHandle` instead of `as any`, simplified transcript), the Vitest setup this adds to the repo, and what the live session verified.
3. Update the "Current Goal" section if it still claims voice UI work is not in the repo.

- [ ] **Step 5: Final checks**

```bash
cd frontend
npm test
npm run build
```

Expected: both PASS. Also confirm `git status` shows only intended files — nothing under `vendor/` or `backend/`.

- [ ] **Step 6: Suggested commit message for the whole unit**

```text
feat: patient voice UI connecting browsers to the deployed voice agent

frontend/src/voice/: clinic picker, presigned AgentCore WebSocket
(guest identity-pool credentials, clinic_id in the signed query),
AudioWorklet mic capture, PCM playback queue, live transcript, and
the voice orb screen at #/voice. Adds Vitest for the pure voice
logic (PCM, event parsing, transcript state). Completes the
"Patient voice UI" item in progress-tracker.md Next Up.

Co-Authored-By: Claude Code <noreply@anthropic.com>
```

---

## Self-Review notes (already applied)

- **Spec coverage:** `project-overview.md` Goal #1 (browser voice conversation) → Tasks 6–9 + 11; patient flow (select clinic → voice session) → Task 10; `ui-context.md` voice screen layout (orb, transcript, slim top bar, `h-8 w-8` icon, tokens, `rounded-full`) → Task 10; `code-standards.md` validation boundary → Task 4; no-cross-imports → nothing in `voice/` imports `dashboard/` and App.tsx is the only mount point.
- **Deliberately out of scope** (per `ai-workflow-rules.md` → When to Split Work): any backend change, any `frontend_stack.py` hosting work, AgentCore Memory, the Settings tab — all remain Next Up items.
- **Type consistency:** `AgentMessage` (Task 4) is consumed by Tasks 5, 7, 9 with one shape; `BidiAudioInputEvent` / `VoiceAgentConnection` / `ConnectOptions` (Task 7) match Task 9's usage; `TranscriptState` (Task 5) matches Task 10's `TranscriptPanel` props; `OrbStatus` is defined in `VoiceOrb.tsx` and imported as a type by `VoiceScreen.tsx`.
- **The `clinic_id`-forwarding risk** is contained: it surfaces as an explicit checkpoint in Task 11 with a stop-and-escalate instruction, not a silent assumption.
