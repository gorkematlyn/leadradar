// Same-origin reverse proxy from the web container to the internal API service.
// API_INTERNAL_URL is an internal service address (e.g. http://leadradar-api:8000), never a public domain.
const HOP_BY_HOP = new Set([
  "connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer",
  "transfer-encoding", "upgrade", "host", "content-length",
]);

export function apiBase(): string {
  return (process.env.API_INTERNAL_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
}

export async function forward(request: Request, upstreamPath: string): Promise<Response> {
  const incoming = new URL(request.url);
  const target = `${apiBase()}${upstreamPath}${incoming.search}`;
  const headers = new Headers();
  request.headers.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key.toLowerCase()) && !key.toLowerCase().startsWith("x-forwarded-")) headers.set(key, value);
  });
  // Preserve the original public host/scheme for origin validation (Traefik sets these; the API
  // honours them only because this container is inside a trusted proxy network).
  const fwdHost = request.headers.get("x-forwarded-host") || request.headers.get("host") || incoming.host;
  const fwdProto = request.headers.get("x-forwarded-proto") || incoming.protocol.replace(":", "");
  headers.set("x-forwarded-host", fwdHost);
  headers.set("x-forwarded-proto", fwdProto);
  const xff = request.headers.get("x-forwarded-for");
  if (xff) headers.set("x-forwarded-for", xff);
  const init: RequestInit & { duplex?: "half" } = {
    method: request.method,
    headers,
    redirect: "manual",
    cache: "no-store",
  };
  if (!["GET", "HEAD"].includes(request.method)) {
    init.body = request.body;
    init.duplex = "half";
  }
  let upstream: Response;
  try {
    upstream = await fetch(target, init);
  } catch {
    return new Response(JSON.stringify({ detail: "api_unavailable" }), {
      status: 502,
      headers: { "content-type": "application/json" },
    });
  }
  const out = new Headers();
  upstream.headers.forEach((value, key) => {
    const k = key.toLowerCase();
    if (k === "set-cookie" || HOP_BY_HOP.has(k) || k === "content-encoding") return;
    out.set(key, value);
  });
  for (const cookie of upstream.headers.getSetCookie()) out.append("set-cookie", cookie);
  return new Response(upstream.body, { status: upstream.status, statusText: upstream.statusText, headers: out });
}
