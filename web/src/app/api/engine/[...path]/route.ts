// Proxy vers le moteur FastAPI local : le navigateur ne parle qu'à Next.js,
// l'adresse du moteur reste côté serveur. Moteur injoignable → 503 « moteur hors ligne ».
import type { NextRequest } from "next/server";

export const dynamic = "force-dynamic";

const ENGINE_URL = `http://${process.env.ENGINE_HOST || "127.0.0.1"}:${process.env.ENGINE_PORT || "8765"}`;
const FORWARDED_REQUEST_HEADERS = ["content-type", "accept", "content-length"];
const FORWARDED_RESPONSE_HEADERS = ["content-type", "cache-control", "content-disposition", "content-length"];

async function proxy(req: NextRequest, ctx: RouteContext<"/api/engine/[...path]">): Promise<Response> {
  const { path } = await ctx.params;
  const target = `${ENGINE_URL}/${path.map(encodeURIComponent).join("/")}${req.nextUrl.search}`;

  const headers = new Headers();
  for (const name of FORWARDED_REQUEST_HEADERS) {
    const value = req.headers.get(name);
    if (value) headers.set(name, value);
  }
  const hasBody = req.method !== "GET" && req.method !== "HEAD";
  // « Reconstruire le prompt » attend le LLM (2 essais au plus) : délai plus long que les autres routes.
  const slow = path.at(-2) === "prompt" && path.at(-1) === "rebuild";

  let res: Response;
  try {
    res = await fetch(target, {
      method: req.method,
      headers,
      body: hasBody ? req.body : undefined,
      cache: "no-store",
      redirect: "manual",
      signal: AbortSignal.timeout(slow ? 180_000 : 60_000),
      // Requis par undici pour transmettre un corps en flux (upload d'images).
      ...(hasBody ? { duplex: "half" } : {}),
    } as RequestInit);
  } catch {
    return Response.json({ detail: "Moteur hors ligne", offline: true }, { status: 503 });
  }

  const outHeaders = new Headers();
  for (const name of FORWARDED_RESPONSE_HEADERS) {
    const value = res.headers.get(name);
    if (value) outHeaders.set(name, value);
  }
  return new Response(res.body, { status: res.status, headers: outHeaders });
}

export { proxy as DELETE, proxy as GET, proxy as PATCH, proxy as POST, proxy as PUT };
