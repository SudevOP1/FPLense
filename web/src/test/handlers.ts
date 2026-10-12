// MSW handlers: the FPLense API answered from fixtures that the real FastAPI app produced on the
// synthetic published_mini folder (scripts/make_web_fixtures.py). No network in any test.
import { http, HttpResponse } from "msw";
import compare from "./fixtures/compare.json";
import compare3 from "./fixtures/compare3.json";
import decodeOut from "./fixtures/decode.json";
import entry from "./fixtures/entry.json";
import entryGw2 from "./fixtures/entry_gw2.json";
import evaluate from "./fixtures/evaluate.json";
import health from "./fixtures/health.json";
import historyGw1 from "./fixtures/history_gw1.json";
import historyGw2 from "./fixtures/history_gw2.json";
import summary from "./fixtures/history_summary.json";
import meta from "./fixtures/meta.json";
import model from "./fixtures/model.json";
import optimize from "./fixtures/optimize.json";
import player from "./fixtures/player.json";
import players from "./fixtures/players.json";
import playersGw2 from "./fixtures/players_gw2.json";
import squadBest from "./fixtures/squad_best.json";
import transfers from "./fixtures/transfers.json";

export const API = "http://localhost:8000";
export const ENTRY_ID = entry.id;
export const fixtures = { compare, compare3, decodeOut, entry, entryGw2, evaluate, meta, players, squadBest, transfers, summary, optimize };

/** Every request the mocked API received (method, path, JSON body). */
export const calls: { method: string; path: string; body: unknown }[] = [];

async function record(request: Request) {
  const url = new URL(request.url);
  let body: unknown = null;
  if (request.method === "POST") body = await request.clone().json();
  calls.push({ method: request.method, path: url.pathname + url.search, body });
  return body;
}

const notFound = (detail: string) => HttpResponse.json({ detail, kind: "not_found" }, { status: 404 });

export const handlers = [
  http.get(`${API}/api/health`, async ({ request }) => (await record(request), HttpResponse.json(health))),
  http.get(`${API}/api/meta`, async ({ request }) => (await record(request), HttpResponse.json(meta))),
  http.get(`${API}/api/model`, async ({ request }) => (await record(request), HttpResponse.json(model))),
  http.get(`${API}/api/players`, async ({ request }) => {
    await record(request);
    const gw = new URL(request.url).searchParams.get("gw");
    return HttpResponse.json(gw === "2" ? playersGw2 : players);
  }),
  http.get(`${API}/api/players/:id`, async ({ request, params }) => {
    await record(request);
    return HttpResponse.json({ ...player, id: Number(params.id) });
  }),
  http.get(`${API}/api/squads/best`, async ({ request }) => {
    await record(request);
    const gw = new URL(request.url).searchParams.get("gw");
    if (gw === "2") return HttpResponse.json(historyGw2.model_pick);
    return HttpResponse.json(squadBest);
  }),
  http.post(`${API}/api/squads/optimize`, async ({ request }) => (await record(request), HttpResponse.json(optimize))),
  http.post(`${API}/api/squads/evaluate`, async ({ request }) => (await record(request), HttpResponse.json(evaluate))),
  http.get(`${API}/api/history/summary`, async ({ request }) => (await record(request), HttpResponse.json(summary))),
  http.get(`${API}/api/history/:gw`, async ({ request, params }) => {
    await record(request);
    if (params.gw === "1") return HttpResponse.json(historyGw1);
    if (params.gw === "2") return HttpResponse.json(historyGw2);
    return notFound(`GW${params.gw} isn't archived yet`);
  }),
  http.get(`${API}/api/entry/:id`, async ({ request, params }) => {
    await record(request);
    if (Number(params.id) === entry.id) return HttpResponse.json(entry);
    if (params.id === "429")
      return HttpResponse.json({ detail: "Too many requests", kind: "rate_limited" }, { status: 429, headers: { "Retry-After": "12" } });
    return notFound(`No FPL team with ID ${params.id}.`);
  }),
  http.get(`${API}/api/entry/:id/gw/:gw`, async ({ request, params }) => {
    await record(request);
    if (Number(params.id) !== entry.id) return notFound(`No FPL team with ID ${params.id}.`);
    return HttpResponse.json(entryGw2);
  }),
  http.post(`${API}/api/transfers/plan`, async ({ request }) => (await record(request), HttpResponse.json(transfers))),
  http.post(`${API}/api/compare`, async ({ request }) => {
    const body = (await record(request)) as { slots: unknown[] };
    if (body.slots.length < 2 || body.slots.length > 3)
      return HttpResponse.json({ detail: "List should have at least 2 items", kind: null }, { status: 422 });
    return HttpResponse.json(body.slots.length === 3 ? compare3 : compare);
  }),
  http.post(`${API}/api/codes/decode`, async ({ request }) => {
    const body = (await record(request)) as { code: string };
    if (!body.code.includes(decodeOut.code.slice(10, 20)))
      return HttpResponse.json({ detail: "This code looks like a typo: the checksum doesn't match.", kind: "typo" }, { status: 422 });
    return HttpResponse.json(decodeOut);
  }),
];
