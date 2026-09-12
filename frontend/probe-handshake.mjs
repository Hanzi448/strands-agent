/**
 * Probe v3 — end-to-end over the deployed runtime with the
 * first-message handshake protocol: basic-flow guest credentials,
 * presigned /ws URL (no clinic_id in the URL), first frame
 * {"clinic_id": "clinic-dental"}, then listen for the greeting.
 *
 * Scratch tool for Task 11 of the patient-voice-ui plan; not app code.
 */
import {
  CognitoIdentityClient,
  GetIdCommand,
  GetOpenIdTokenCommand,
} from "@aws-sdk/client-cognito-identity";
import { STSClient, AssumeRoleWithWebIdentityCommand } from "@aws-sdk/client-sts";
import { Sha256 } from "@aws-crypto/sha256-js";
import { SignatureV4 } from "@aws-sdk/signature-v4";
import { HttpRequest } from "@smithy/protocol-http";

const IDENTITY_POOL_ID = "us-east-1:450ae2bf-e107-44f6-a424-dd3cdb3724e5";
const GUEST_ROLE_ARN = "arn:aws:iam::233245302646:role/clinicpilot-dev-patient-guest";
const AGENT_RUNTIME_ARN =
  "arn:aws:bedrock-agentcore:us-east-1:233245302646:runtime/clinicpilot_dev_agent_runtime-dguqGaF2Zr";
const REGION = "us-east-1";
const CLINIC_ID = "clinic-dental";

const cognito = new CognitoIdentityClient({ region: REGION });
const identityId = (
  await cognito.send(new GetIdCommand({ IdentityPoolId: IDENTITY_POOL_ID }))
).IdentityId;
if (!identityId) throw new Error("no identity id");
const { Token: openIdToken } = await cognito.send(
  new GetOpenIdTokenCommand({ IdentityId: identityId }),
);
if (!openIdToken) throw new Error("no openid token");

const sts = new STSClient({ region: REGION });
const assumed = await sts.send(
  new AssumeRoleWithWebIdentityCommand({
    RoleArn: GUEST_ROLE_ARN,
    RoleSessionName: "clinicpilot-voice-guest",
    WebIdentityToken: openIdToken,
  }),
);
const creds = assumed.Credentials;
if (!creds?.AccessKeyId) throw new Error("no sts credentials");
console.log("basic-flow credentials: ok");

const sessionId = crypto.randomUUID();
const url = new URL(
  `https://bedrock-agentcore.${REGION}.amazonaws.com/runtimes/${encodeURIComponent(AGENT_RUNTIME_ARN)}/ws`,
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
  region: REGION,
  credentials: {
    accessKeyId: creds.AccessKeyId,
    secretAccessKey: creds.SecretAccessKey,
    sessionToken: creds.SessionToken,
  },
  sha256: Sha256,
});
const signed = await signer.presign(request, { expiresIn: 3600 });
const query = signed.query ?? {};
const queryString = Object.entries(query)
  .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
  .join("&");
const wsUrl = `wss://${signed.hostname}${signed.path ?? "/"}${queryString ? `?${queryString}` : ""}`;

let messageCount = 0;
const ws = new WebSocket(wsUrl);
const timeout = setTimeout(() => {
  console.log("TIMEOUT: 45s elapsed; closing.");
  ws.close();
  process.exit(2);
}, 45000);

ws.onopen = () => {
  console.log("OPEN: socket accepted");
  console.log("sending handshake: " + JSON.stringify({ clinic_id: CLINIC_ID }));
  ws.send(JSON.stringify({ clinic_id: CLINIC_ID }));
};
ws.onclose = (event) => {
  console.log(`CLOSE: code=${event.code} reason=${event.reason || "(empty)"}`);
  clearTimeout(timeout);
  process.exit(messageCount > 0 ? 0 : 1);
};
ws.onerror = () => console.log("ERROR event on socket");
ws.onmessage = (event) => {
  messageCount++;
  console.log(`MESSAGE ${messageCount}: ${String(event.data).slice(0, 220)}`);
  // Transcript + a couple of audio chunks prove the greeting loop is
  // really running; then stop before running up a Bedrock bill.
  if (messageCount >= 6 && (String(event.data).includes("bidi_transcript_stream") || String(event.data).includes("bidi_audio_stream"))) {
    console.log("probe satisfied: greeting received, closing.");
    ws.close();
  }
};
