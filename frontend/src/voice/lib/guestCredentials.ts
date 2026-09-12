/**
 * Guest AWS credentials for the patient voice UI, via the Cognito
 * **basic (classic) auth flow**.
 *
 * The enhanced flow (`GetCredentialsForIdentity`) cannot be used here:
 * Cognito applies an unauthenticated scope-down *session policy* to
 * enhanced-flow guests whose service allow-list does not include
 * bedrock-agentcore (Amazon Cognito Developer Guide -> IAM roles ->
 * "Services that unauthenticated users can access"), so the role
 * policy can never grant it -- verified against this deploy as a 403
 * "no session policy allows InvokeAgentRuntimeWithWebSocketStream".
 * The basic flow calls STS `AssumeRoleWithWebIdentity` directly with a
 * Cognito-issued OIDC token, so only the role's own policy applies
 * (which `api_stack.py` scopes to the single AgentCore Runtime).
 *
 * Adapted from the vendored sample's `aws-credentials.ts` with the
 * flow inverted: the sample exchanges a staff JWT for enhanced-flow
 * identity-pool credentials; patients never log in, and the anonymous
 * basic flow above is what a login-free visitor can use.
 */

import {
  CognitoIdentityClient,
  GetIdCommand,
  GetOpenIdTokenCommand,
} from "@aws-sdk/client-cognito-identity";
import { STSClient, AssumeRoleWithWebIdentityCommand } from "@aws-sdk/client-sts";

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
  const guestRoleArn = import.meta.env.VITE_PATIENT_GUEST_ROLE_ARN;
  const region = import.meta.env.VITE_REGION;
  if (!identityPoolId || !guestRoleArn || !region) {
    throw new Error(
      "Voice is not configured: VITE_PATIENT_GUEST_IDENTITY_POOL_ID, " +
        "VITE_PATIENT_GUEST_ROLE_ARN, and VITE_REGION must be set.",
    );
  }

  const cognito = new CognitoIdentityClient({ region });

  // No `Logins` anywhere: this is an anonymous identity, not an
  // authenticated one.
  const identityId = (
    await cognito.send(new GetIdCommand({ IdentityPoolId: identityPoolId }))
  ).IdentityId;
  if (!identityId) {
    throw new Error("The clinic's voice sign-in did not return an identity.");
  }

  const { Token: openIdToken } = await cognito.send(
    new GetOpenIdTokenCommand({ IdentityId: identityId }),
  );
  if (!openIdToken) {
    throw new Error("The clinic's voice sign-in did not return a token.");
  }

  const sts = new STSClient({ region });
  const assumed = await sts.send(
    new AssumeRoleWithWebIdentityCommand({
      RoleArn: guestRoleArn,
      RoleSessionName: "clinicpilot-voice-guest",
      WebIdentityToken: openIdToken,
    }),
  );
  const credentials = assumed.Credentials;
  if (
    !credentials?.AccessKeyId ||
    !credentials?.SecretAccessKey ||
    !credentials?.SessionToken
  ) {
    throw new Error("The clinic's voice sign-in did not return credentials.");
  }

  const result: GuestCredentials = {
    accessKeyId: credentials.AccessKeyId,
    secretAccessKey: credentials.SecretAccessKey,
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
