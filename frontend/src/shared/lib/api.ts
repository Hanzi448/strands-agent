/**
 * Generic client for `{ data, error }`-shaped REST APIs
 * (`code-standards.md` -> API Routes). `dashboard/lib/dashboardApi.ts` is
 * the only current caller; kept here, not under `dashboard/`, because
 * `code-standards.md` -> File Organization names `frontend/src/shared/` as
 * the API client's home and a future `voice/` REST call (if any) should
 * reuse this rather than a second copy.
 */

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

interface ApiEnvelope {
  data: unknown;
  error: string | null;
}

/** `body` is `unknown` at this point -- a network response, not a value
 * this code produced -- so its shape is checked before anything trusts it
 * (`code-standards.md` -> TypeScript/React: validate unknown API responses). */
function isApiEnvelope(body: unknown): body is ApiEnvelope {
  return (
    typeof body === "object" &&
    body !== null &&
    "data" in body &&
    "error" in body
  );
}

export interface ApiRequest {
  baseUrl: string;
  path: string;
  method?: "GET" | "POST";
  token?: string | null;
  query?: Record<string, string | number | undefined>;
  body?: unknown;
}

/** Call one route of a `{ data, error }` API and return `data`, typed as
 * `T` by the caller. Never trusts `T` without the caller having validated
 * the shape it actually needs from `data`. */
export async function apiRequest<T>({
  baseUrl,
  path,
  method = "GET",
  token,
  query,
  body,
}: ApiRequest): Promise<T> {
  const url = new URL(path.replace(/^\//, ""), baseUrl.replace(/\/?$/, "/"));
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined) url.searchParams.set(key, String(value));
  }

  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers.Authorization = token;

  const response = await fetch(url.toString(), {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  let parsed: unknown;
  try {
    parsed = await response.json();
  } catch {
    throw new ApiError(
      `The server returned a response that was not JSON (status ${response.status}).`,
      response.status,
    );
  }

  if (!isApiEnvelope(parsed)) {
    throw new ApiError(
      "The server returned a response in an unexpected shape.",
      response.status,
    );
  }
  if (parsed.error !== null) {
    throw new ApiError(parsed.error, response.status);
  }
  return parsed.data as T;
}
