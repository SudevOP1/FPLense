"""Write ``web/src/test/fixtures/*.json``: real API responses for the frontend's MSW mocks.

The P7 Vitest suite never hits the network. Its mocked API answers with these files, which are
produced by the **real FastAPI app** on the synthetic ``tests/published_mini`` folder (60 made-up
players, GW1 backfilled, GW2 live, GW3 next) and the fake FPL API from ``tests/conftest.py``, so
the frontend is tested against responses of the exact shape the backend sends. ``model.json``
comes from the committed ``data/published/`` (our own model's metrics, no source data).

Re-run when the API schema changes (after ``python -m fPLense.api.export_openapi``):

    python scripts/make_web_fixtures.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from fPLense import config
from fPLense.api.fpl_proxy import FplProxy
from fPLense.api.main import create_app

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "web" / "src" / "test" / "fixtures"
sys.path.insert(0, str(ROOT / "tests"))

from conftest import ENTRY_ID, FakeFpl  # noqa: E402
from published_mini import build  # noqa: E402


async def _no_sleep(_):
    return None


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        published = build(Path(tmp))
        best = json.loads((published / "squad_gw03.json").read_text(encoding="utf-8"))
        starters = [p["element"] for p in best["players"] if p["starter"]]
        bench = sorted(
            (p for p in best["players"] if not p["starter"]), key=lambda p: p["bench_order"]
        )
        squad = starters + [p["element"] for p in bench]
        proxy = FplProxy(transport=httpx.MockTransport(FakeFpl(squad)), sleep=_no_sleep, backoff=0)
        app = create_app(published_dir=published, proxy=proxy, rate_capacity=1000)
        with TestClient(app) as c:
            players = c.get("/api/players").json()
            first = players["players"][0]["id"]
            squad_best = c.get("/api/squads/best").json()
            code = squad_best["code"]
            # the mini entry already owns the best squad, so plan a path to GW2's hindsight team
            hindsight = c.get("/api/history/2").json()["hindsight"]
            target = hindsight["starters"] + hindsight["bench"]
            out = {
                "health": c.get("/api/health").json(),
                "meta": c.get("/api/meta").json(),
                "players": players,
                "players_gw2": c.get("/api/players", params={"gw": 2}).json(),
                "player": c.get(f"/api/players/{first}").json(),
                "squad_best": squad_best,
                "optimize": c.post("/api/squads/optimize", json={}).json(),
                "evaluate": c.post(
                    "/api/squads/evaluate",
                    json={"players": squad_best["starters"] + squad_best["bench"]},
                ).json(),
                "history_summary": c.get("/api/history/summary").json(),
                "history_gw1": c.get("/api/history/1").json(),
                "history_gw2": c.get("/api/history/2").json(),
                "entry": c.get(f"/api/entry/{ENTRY_ID}").json(),
                "entry_gw2": c.get(f"/api/entry/{ENTRY_ID}/gw/2").json(),
                "transfers": c.post(
                    "/api/transfers/plan",
                    json={"team_id": ENTRY_ID, "free_transfers": 1, "target": target},
                ).json(),
                "compare": c.post(
                    "/api/compare",
                    json={
                        "slots": [{"kind": "model_pick", "gw": 2}, {"kind": "hindsight", "gw": 2}]
                    },
                ).json(),
                "compare3": c.post(
                    "/api/compare",
                    json={
                        "slots": [
                            {"kind": "model_pick", "gw": 2},
                            {"kind": "hindsight", "gw": 2},
                            {"kind": "code", "value": code},
                        ]
                    },
                ).json(),
                "decode": c.post("/api/codes/decode", json={"code": code}).json(),
            }
    with TestClient(create_app()) as real:
        out["model"] = real.get("/api/model").json()
    for name, doc in out.items():
        (OUT / f"{name}.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {len(out)} fixtures to {OUT.relative_to(ROOT)} (season {config.CURRENT_SEASON})")


if __name__ == "__main__":
    main()
