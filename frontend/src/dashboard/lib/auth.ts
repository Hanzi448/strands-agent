import {
  CognitoUser,
  CognitoUserPool,
  AuthenticationDetails,
  type CognitoUserSession,
} from "amazon-cognito-identity-js";

/**
 * Staff login only (`architecture.md` -> Auth and Access Model): one
 * Cognito user pool, self-sign-up disabled
 * (`backend/infra/api_stack.py`'s `UserPool`), one demo account per
 * clinic seeded by `progress-tracker.md` Next Up #3. So unlike the
 * vendored sample's `auth.ts` this exposes no `signUp`/`confirmSignUp` --
 * there is no registration flow to build against a pool that refuses it.
 *
 * `VITE_STAFF_USER_POOL_ID`/`VITE_STAFF_USER_POOL_CLIENT_ID` come from
 * `ApiStack`'s `StaffUserPoolId`/`StaffUserPoolClientId` outputs
 * (`.env.example`). This pool is unrelated to the patient-facing guest
 * *identity* pool the voice endpoint will use -- staff auth and anonymous
 * visitor credentials must not share a path (`architecture.md` ->
 * Invariants #5).
 */

// Built lazily, not at module load: `CognitoUserPool`'s constructor throws
// on a blank id, and until `progress-tracker.md` Next Up #3 (seeding) and
// the CDK deploy that precedes it, no `.env` has real values yet. A
// module-level throw would blank-screen the whole app before the login
// form could even explain why.
let pool: CognitoUserPool | null | undefined;

function userPool(): CognitoUserPool {
  if (pool === undefined) {
    const userPoolId = import.meta.env.VITE_STAFF_USER_POOL_ID?.trim();
    const clientId = import.meta.env.VITE_STAFF_USER_POOL_CLIENT_ID?.trim();
    pool =
      userPoolId && clientId
        ? new CognitoUserPool({ UserPoolId: userPoolId, ClientId: clientId })
        : null;
  }
  if (!pool) {
    throw new Error(
      "Dashboard is not configured: set VITE_STAFF_USER_POOL_ID and " +
        "VITE_STAFF_USER_POOL_CLIENT_ID (see .env.example).",
    );
  }
  return pool;
}

// Matches `backend/infra/api_stack.py`'s `CLINIC_ID_ATTRIBUTE`; Cognito
// adds the `custom:` prefix to every custom attribute's claim name
// (`dashboard_api.CLINIC_ID_CLAIM` documents the same fact server-side).
const CLINIC_ID_CLAIM = "custom:clinic_id";

export interface StaffUser {
  email: string;
  clinicId: string;
}

function sessionToStaffUser(session: CognitoUserSession): StaffUser {
  const claims = session.getIdToken().decodePayload() as Record<string, unknown>;
  const email = claims.email;
  const clinicId = claims[CLINIC_ID_CLAIM];
  if (typeof email !== "string" || typeof clinicId !== "string") {
    throw new Error(
      "Signed-in token is missing 'email' or the 'custom:clinic_id' claim -- " +
        "check the seeded staff account's attributes.",
    );
  }
  return { email, clinicId };
}

export function signIn(email: string, password: string): Promise<StaffUser> {
  return new Promise((resolve, reject) => {
    const cognitoUser = new CognitoUser({ Username: email, Pool: userPool() });
    cognitoUser.authenticateUser(
      new AuthenticationDetails({ Username: email, Password: password }),
      {
        onSuccess: (session) => resolve(sessionToStaffUser(session)),
        onFailure: (err) => reject(err),
      },
    );
  });
}

export function signOut(): void {
  if (!pool) return;
  pool.getCurrentUser()?.signOut();
}

/** The signed-in staff user, if the current browser session still has a
 * valid one -- so a page reload does not force a fresh login. `null` both
 * when nobody is signed in and when the dashboard has no Cognito config
 * yet: either way there is nobody to resolve, and the login form is where
 * a missing config surfaces (`signIn` throws there). */
export function getCurrentUser(): Promise<StaffUser | null> {
  let cognitoUser;
  try {
    cognitoUser = userPool().getCurrentUser();
  } catch {
    return Promise.resolve(null);
  }
  if (!cognitoUser) return Promise.resolve(null);

  return new Promise((resolve) => {
    cognitoUser.getSession((err: Error | null, session: CognitoUserSession | null) => {
      if (err || !session || !session.isValid()) {
        resolve(null);
        return;
      }
      resolve(sessionToStaffUser(session));
    });
  });
}

/** The current ID token, for the `Authorization` header
 * `dashboard/lib/dashboardApi.ts` sends -- API Gateway's Cognito
 * authorizer verifies it and is what puts `custom:clinic_id` on
 * `requestContext.authorizer.claims` (`dashboard_api.py`'s docstring). */
export function getIdToken(): Promise<string | null> {
  let cognitoUser;
  try {
    cognitoUser = userPool().getCurrentUser();
  } catch {
    return Promise.resolve(null);
  }
  if (!cognitoUser) return Promise.resolve(null);

  return new Promise((resolve) => {
    cognitoUser.getSession((err: Error | null, session: CognitoUserSession | null) => {
      if (err || !session || !session.isValid()) {
        resolve(null);
        return;
      }
      resolve(session.getIdToken().getJwtToken());
    });
  });
}
