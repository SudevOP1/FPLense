"""API plumbing: CORS, OpenAPI drift vs web/openapi.json, import weight, token bucket."""

from __future__ import annotations

import json
import subprocess
import sys

from fPLense import config
from fPLense.api.deps import TokenBucket
from fPLense.api.main import create_app


def test_cors_only_for_allowed_origins(make_client):
    c = make_client(origins=["https://fplense.example"])
    ok = c.get("/api/health", headers={"Origin": "https://fplense.example"})
    assert ok.headers.get("access-control-allow-origin") == "https://fplense.example"
    bad = c.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in bad.headers
    pre = c.options(
        "/api/squads/optimize",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert pre.status_code == 400


def test_cors_origins_from_env(monkeypatch):
    from fPLense.api import main

    monkeypatch.setenv(config.API_CORS_ENV, "https://a.example/, https://b.example")
    assert main.cors_origins() == ["https://a.example", "https://b.example"]


def test_openapi_has_no_drift():
    """`web/openapi.json` (TypeScript types are generated from it in P7) equals the live schema.
    Regenerate with `python -m fPLense.api.export_openapi`."""
    saved = json.loads(config.WEB_OPENAPI_PATH.read_text(encoding="utf-8"))
    live = json.loads(json.dumps(create_app().openapi()))
    assert saved == live


def test_every_endpoint_is_in_the_schema():
    paths = create_app().openapi()["paths"]
    for p in [
        "/api/health",
        "/api/meta",
        "/api/players",
        "/api/players/{player_id}",
        "/api/squads/best",
        "/api/squads/optimize",
        "/api/squads/evaluate",
        "/api/history/summary",
        "/api/history/{gw}",
        "/api/entry/{team_id}",
        "/api/entry/{team_id}/gw/{gw}",
        "/api/transfers/plan",
        "/api/compare",
        "/api/codes/decode",
        "/api/codes/encode",
    ]:
        assert p in paths, p


def test_api_import_is_light():
    """No lightgbm / shap / duckdb / sklearn on the request path (free hosts: ~512 MB RAM)."""
    code = (
        "import sys, fPLense.api.main; "
        "print(sorted({m.split('.')[0] for m in sys.modules} & "
        "{'lightgbm', 'shap', 'duckdb', 'sklearn', 'matplotlib', 'streamlit'}))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"


def test_no_streamlit_left():
    src = config.PACKAGE_DIR
    hits = [p for p in src.rglob("*.py") if "streamlit" in p.read_text(encoding="utf-8")]
    assert hits == []
    assert not (config.ROOT / "app").exists()


def test_token_bucket_refills():
    t = {"now": 0.0}
    bucket = TokenBucket(capacity=2, rate=0.5, clock=lambda: t["now"])
    assert bucket.take("a") == 0 and bucket.take("a") == 0
    wait = bucket.take("a")
    assert wait == 2.0  # one token every 2 s
    assert bucket.take("b") == 0  # per client
    t["now"] = 2.0
    assert bucket.take("a") == 0
