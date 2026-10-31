export const API_BASE = "/api/v1";

export type ErrorParams = Record<string, unknown>;

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly params: ErrorParams;

  constructor(status: number, code: string, params: ErrorParams = {}) {
    super(code);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.params = params;
  }
}

/** The server could not be reached (offline, DNS, proxy down). */
export class NetworkError extends Error {
  constructor() {
    super("network");
    this.name = "NetworkError";
  }
}

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

let unauthorizedHandler: (() => void) | null = null;

/** Called on 401 answers (except bad credentials) so the app can go back to /login. */
export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler;
}

export interface RequestOptions {
  body?: unknown;
  /** Do not trigger the global 401 handler (used for the initial session probe). */
  skipUnauthorizedHandler?: boolean;
}

async function parseError(res: Response): Promise<ApiError> {
  try {
    const data = (await res.json()) as { error?: { code?: unknown; params?: unknown } };
    const code = typeof data.error?.code === "string" ? data.error.code : "unknown";
    const params =
      data.error?.params && typeof data.error.params === "object"
        ? (data.error.params as ErrorParams)
        : {};
    return new ApiError(res.status, code, params);
  } catch {
    return new ApiError(res.status, "unknown");
  }
}

export async function request<T>(
  method: string,
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const upper = method.toUpperCase();
  const headers: Record<string, string> = { Accept: "application/json" };
  if (!SAFE_METHODS.has(upper)) headers["X-Requested-With"] = "cobble";
  let body: string | undefined;
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.body);
  }

  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method: upper,
      headers,
      body,
      credentials: "same-origin",
    });
  } catch {
    throw new NetworkError();
  }

  if (!res.ok) {
    const error = await parseError(res);
    if (res.status === 401 && error.code !== "invalid_credentials") {
      if (!options.skipUnauthorizedHandler) {
        if (unauthorizedHandler) unauthorizedHandler();
        else window.location.assign("/login");
      }
    }
    throw error;
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  get: <T>(path: string, options?: RequestOptions) => request<T>("GET", path, options),
  post: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>("POST", path, { ...options, body }),
  patch: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>("PATCH", path, { ...options, body }),
  delete: <T = void>(path: string, options?: RequestOptions) => request<T>("DELETE", path, options),
};
