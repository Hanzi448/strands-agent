/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_DASHBOARD_API_URL: string;
  readonly VITE_STAFF_USER_POOL_ID: string;
  readonly VITE_STAFF_USER_POOL_CLIENT_ID: string;
  // Patient voice UI (`src/voice/`).
  readonly VITE_AGENT_RUNTIME_ARN: string;
  readonly VITE_PATIENT_GUEST_IDENTITY_POOL_ID: string;
  readonly VITE_PATIENT_GUEST_ROLE_ARN: string;
  readonly VITE_REGION: string;
  // Optional local-dev bypass: connect straight to a locally running
  // agentcore_app without presigning (see voice/lib/agentSocket.ts).
  readonly VITE_LOCAL_DEV?: string;
  readonly VITE_AGENT_RUNTIME_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
