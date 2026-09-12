/**
 * Presigned WebSocket connection to the deployed AgentCore Runtime.
 *
 * Adapted from the vendored sample's `websocket-presigned.ts` with
 * three deliberate changes, each called out inline: guest credentials
 * via the Cognito basic flow instead of staff-JWT enhanced-flow ones;
 * the clinic named in the **first WebSocket message** rather than the
 * URL (a live probe proved AgentCore's gateway strips custom query
 * params, so `clinic_id` in the signed query never reaches the app --
 * `agentcore_app.py` reads it from the handshake); and `ws://` (not
 * `wss://`) in local dev, because Vite's dev server is plain http on
 * localhost.
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

async function fetchPresignedUrl(sessionId: string): Promise<string> {
  const isLocalDev = import.meta.env.VITE_LOCAL_DEV === "true";
  const localUrl = import.meta.env.VITE_AGENT_RUNTIME_URL;
  if (isLocalDev && localUrl) {
    // CHANGE vs vendored sample: it hardcodes wss://, which fails
    // against Vite's plain-http dev server on localhost.
    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    return `${scheme}://${window.location.host}${localUrl}`;
  }

  const agentRuntimeArn = import.meta.env.VITE_AGENT_RUNTIME_ARN;
  const region = import.meta.env.VITE_REGION;
  if (!agentRuntimeArn || !region) {
    throw new Error(
      "Voice is not configured: VITE_AGENT_RUNTIME_ARN and VITE_REGION must be set.",
    );
  }

  // CHANGE vs vendored sample: guest credentials via the Cognito basic
  // flow, no staff JWT involved.
  const credentials = await getGuestCredentials();

  const url = new URL(
    `https://bedrock-agentcore.${region}.amazonaws.com/runtimes/${encodeURIComponent(agentRuntimeArn)}/ws`,
  );
  url.searchParams.set("qualifier", "DEFAULT");
  url.searchParams.set("X-Amzn-Bedrock-AgentCore-Runtime-Session-Id", sessionId);

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
  const presignedUrl = await fetchPresignedUrl(sessionId);
  const ws = new WebSocket(presignedUrl);

  return new Promise((resolve, reject) => {
    ws.onopen = () => {
      // CHANGE vs vendored sample: the clinic is named in the first
      // WebSocket message, not the URL -- AgentCore's gateway strips
      // custom query params, so this frame is the only channel that
      // reaches `agentcore_app.py`'s handshake read.
      ws.send(JSON.stringify({ clinic_id: options.clinicId }));
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
