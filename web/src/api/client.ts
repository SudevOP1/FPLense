// Thin fetch wrapper for the FPLense API. The browser only ever talks to our API (never to FPL).

export const API_URL = (import.meta.env.VITE_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

export class ApiError extends Error {
  status: number;
  kind: string | null;
  retryAfter: number | null;

  constructor(status: number, detail: string, kind: string | null = null, retryAfter: number | null = null) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.kind = kind;
    this.retryAfter = retryAfter;
  }

  /** Short, human message for the UI. */
  get friendly(): string {
    if (this.status === 0) return "Can't reach the FPLense server. Check your connection and try again.";
    if (this.status === 429)
      return `Too many requests: try again in ${this.retryAfter ?? 10} seconds.`;
    if (this.status === 403) return "FPL is blocking our server right now. You can still paste a team code.";
    return this.message;
  }
}

export interface RequestOptions {
  method?: "GET" | "POST";
  body?: unknown;
  signal?: AbortSignal;
  query?: Record<string, string | number | boolean | null | undefined>;
}

export async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const url = new URL(API_URL + path);
  for (const [k, v] of Object.entries(opts.query ?? {})) {
    if (v != null) url.searchParams.set(k, String(v));
  }
  let res: Response;
  try {
    res = await fetch(url, {
      method: opts.method ?? (opts.body === undefined ? "GET" : "POST"),
      headers: opts.body === undefined ? undefined : { "Content-Type": "application/json" },
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
      signal: opts.signal,
    });
  } catch (err) {
    if ((err as Error)?.name === "AbortError") throw err;
    throw new ApiError(0, "network error");
  }
  if (!res.ok) {
    let detail = res.statusText || `HTTP ${res.status}`;
    let kind: string | null = null;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
      else if (Array.isArray(body?.detail)) detail = body.detail.map((d: { msg?: string }) => d.msg).join("; ");
      kind = body?.kind ?? null;
    } catch {
      // non-JSON error body
    }
    const retry = Number(res.headers.get("Retry-After"));
    throw new ApiError(res.status, detail, kind, Number.isFinite(retry) && retry > 0 ? retry : null);
  }
  return (await res.json()) as T;
}
