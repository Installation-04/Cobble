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

async function send(
  method: string,
  path: string,
  options: RequestOptions,
  accept: string,
): Promise<Response> {
  const upper = method.toUpperCase();
  const headers: Record<string, string> = { Accept: accept };
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
  return res;
}

export async function request<T>(
  method: string,
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const res = await send(method, path, options, "application/json");
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export interface TextChunk {
  text: string;
  /** Value of the `X-Next-Offset` header (null when the server did not send a valid one). */
  nextOffset: number | null;
}

/** GET a text/plain resource (log chunks) together with its `X-Next-Offset` header. */
export async function requestText(path: string): Promise<TextChunk> {
  const res = await send("GET", path, {}, "text/plain");
  const header = res.headers.get("X-Next-Offset");
  const parsed = header === null ? Number.NaN : Number.parseInt(header, 10);
  return { text: await res.text(), nextOffset: Number.isFinite(parsed) ? parsed : null };
}

export const api = {
  get: <T>(path: string, options?: RequestOptions) => request<T>("GET", path, options),
  post: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>("POST", path, { ...options, body }),
  put: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>("PUT", path, { ...options, body }),
  patch: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>("PATCH", path, { ...options, body }),
  delete: <T = void>(path: string, options?: RequestOptions) => request<T>("DELETE", path, options),
};
