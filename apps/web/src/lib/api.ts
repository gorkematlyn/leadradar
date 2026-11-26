// Relative-URL API client. All requests go to the same origin (/api), so no domain is needed.
export class ApiError extends Error {
  status: number;
  detail: string;
  errors?: unknown;
  constructor(status: number, detail: string, errors?: unknown) {
    super(detail);
    this.status = status;
    this.detail = detail;
    this.errors = errors;
  }
}

function csrfToken(): string | undefined {
  if (typeof document === "undefined") return undefined;
  const m = document.cookie.match(/(?:^|; )lr_csrf=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : undefined;
}

type Query = Record<string, string | number | boolean | string[] | null | undefined>;

export interface ApiOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  query?: Query;
  form?: FormData;
  signal?: AbortSignal;
  raw?: boolean;
}

export function buildUrl(path: string, query?: Query): string {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query ?? {})) {
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v)) v.forEach((x) => params.append(k, x));
    else params.set(k, String(v));
  }
  const qs = params.toString();
  return `/api${path}${qs ? `?${qs}` : ""}`;
}

export async function api<T = unknown>(path: string, opts: ApiOptions = {}): Promise<T> {
  const method = opts.method ?? (opts.body !== undefined || opts.form ? "POST" : "GET");
  const headers: Record<string, string> = { Accept: "application/json" };
  if (method !== "GET") {
    const token = csrfToken();
    if (token) headers["X-CSRF-Token"] = token;
  }
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  const res = await fetch(buildUrl(path, opts.query), {
    method,
    headers,
    body,
    credentials: "same-origin",
    signal: opts.signal,
    cache: "no-store",
  });
  if (opts.raw) {
    if (!res.ok) throw new ApiError(res.status, "request_failed");
    return res as unknown as T;
  }
  if (res.status === 401 && typeof window !== "undefined" && !path.startsWith("/auth/")) {
    const next = encodeURIComponent(window.location.pathname + window.location.search);
    window.location.href = `/login?next=${next}`;
  }
  const text = await res.text();
  const data = text ? safeJson(text) : null;
  if (!res.ok) {
    const detail = (data && typeof data === "object" && "detail" in data ? String((data as { detail: unknown }).detail) : null) ?? `http_${res.status}`;
    throw new ApiError(res.status, detail, (data as { errors?: unknown } | null)?.errors);
  }
  return data as T;
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return { detail: "invalid_response" };
  }
}

export async function download(path: string, body: unknown, filename: string, query?: Query) {
  const token = csrfToken();
  const res = await fetch(buildUrl(path, query), {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(token ? { "X-CSRF-Token": token } : {}) },
    body: JSON.stringify(body),
    credentials: "same-origin",
  });
  if (!res.ok) throw new ApiError(res.status, "download_failed");
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
