const BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ?? "";
const TIMEOUT_MS = 15_000;

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly retryAfter: number | null;

  constructor(status: number, code: string, message: string, retryAfter: number | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.retryAfter = retryAfter;
  }
}

export type Params = Record<string, string | number | boolean | string[] | undefined | null>;

export function buildQuery(params: Params = {}): string {
  const search = new URLSearchParams();
  for (const key of Object.keys(params).sort()) {
    const value = params[key];
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) value.forEach((v) => search.append(key, v));
    else search.set(key, String(value));
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

export async function apiGet<T>(path: string, params?: Params, signal?: AbortSignal): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  signal?.addEventListener("abort", () => controller.abort(), { once: true });
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}${buildQuery(params)}`, {
      headers: { Accept: "application/json" },
      signal: controller.signal,
    });
  } catch {
    if (controller.signal.aborted && !signal?.aborted) {
      throw new ApiError(0, "timeout", "The server took too long to respond.");
    }
    throw new ApiError(0, "network", "Could not reach the GJURMË API. Check your connection.", null);
  } finally {
    clearTimeout(timer);
  }
  if (!response.ok) {
    let code = "http_error";
    let message = `Request failed (${response.status}).`;
    try {
      const body = (await response.json()) as { error?: { code?: string; message?: string } };
      code = body.error?.code ?? code;
      message = body.error?.message ?? message;
    } catch {
      /* non-JSON error body */
    }
    const retry = Number(response.headers.get("Retry-After"));
    throw new ApiError(response.status, code, message, Number.isFinite(retry) && retry > 0 ? retry : null);
  }
  return (await response.json()) as T;
}
