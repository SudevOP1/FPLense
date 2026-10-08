"""FPLense: Streamlit home page. Run with ``streamlit run app/Home.py``."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

import shared  # noqa: E402

from fPLense import app_data, config  # noqa: E402

st.set_page_config(page_title="FPLense", page_icon="⚽", layout="wide")

st.title("FPLense")
st.markdown(
    "**Fantasy Premier League points forecaster and squad optimizer.** A LightGBM model trained "
    "on 10 seasons of player-gameweek history (250K+ rows, 43 leakage-safe features built as "
    "DuckDB window-function views) predicts every player's points for the next gameweeks; a "
    "PuLP integer program picks the best legal squad and plans transfers."
)

meta = shared.latest()
if meta:
    shared.sidebar_status(meta)
metrics = shared.published_json(config.METRICS_PATH.name)
head = app_data.headline(metrics)

c1, c2, c3, c4 = st.columns(4)
if meta:
    c1.metric(f"Next deadline: GW{meta['gw']}", app_data.time_until(meta.get("deadline")))
    c2.metric(
        "Data through", f"GW{meta.get('data_through_gw')}", app_data.age(meta.get("generated_at"))
    )
    c3.metric("Players projected", f"{meta['players']:,}")
else:
    c1.warning("No predictions published yet.")
if head:
    lo, hi = head["ci"]
    c4.metric(
        "MAE cut vs rolling form",
        f"{head['gain_pct']:.1f}%",
        f"95% CI {lo:.1f}–{hi:.1f}%",
        delta_color="off",
        help=(
            f"Regulars (lagged minutes_r3 >= 45), walk-forward {head['season']} GW5-38: "
            f"LightGBM MAE {head['mae']:.3f} vs rolling-form baseline {head['b0_mae']:.3f} "
            f"per player-gameweek (n = {head['n']:,})."
        ),
    )

if meta:
    squad = shared.published_json(meta["files"]["squad"])
    if squad:
        names = {p["element"]: p["name"] for p in squad["players"]}
        st.info(
            f"**GW{meta['gw']} optimal squad:** {squad['expected_points']:.1f} expected "
            f"points over GW{meta['gws'][0]}–{meta['gws'][-1]} (discounted), "
            f"£{squad['cost'] / 10:.1f}m, "
            f"captain **{names[squad['captain']]}**, vice {names[squad['vice']]}."
        )
    sources = meta.get("odds_sources", {})
    if sources:
        parts = [
            f"GW{gw}: " + ", ".join(f"{n} {src}" for src, n in counts.items())
            for gw, counts in sources.items()
        ]
        st.caption(
            "Opponent strength per fixture comes from bookmaker odds when football-data.co.uk "
            "lists the match, otherwise from an Elo-only estimate: " + " · ".join(parts)
        )

st.subheader("Pages")
p1, p2, p3, p4 = st.columns(4)
with p1:
    st.page_link("pages/1_Projections.py", label="Projections", icon="📈")
    st.caption("Every player's expected points per gameweek, filters and SHAP explanations.")
with p2:
    st.page_link("pages/2_Optimal_Squad.py", label="Optimal Squad", icon="🧮")
    st.caption("The ILP's best 15 under budget, quotas and the 3-per-club rule.")
with p3:
    st.page_link("pages/3_Transfer_Planner.py", label="Transfer Planner", icon="🔁")
    st.caption("Best 0–3 transfers for your own team, net of hits.")
with p4:
    st.page_link("pages/4_Model_Card.py", label="Model Card", icon="🧾")
    st.caption("Walk-forward metrics with CIs, SHAP, backtest and limitations.")

st.divider()
st.markdown(
    f"[Source code on GitHub]({config.REPO_URL}) · Predictions are refreshed before each "
    "gameweek deadline by GitHub Actions."
)
st.caption(
    "Data: [vaastav/Fantasy-Premier-League](https://github.com/vaastav/Fantasy-Premier-League), "
    "the official FPL API (unofficial use), [football-data.co.uk](https://www.football-data.co.uk) "
    "odds, ClubElo ratings via Kaggle `adamgbor/club-football-match-data-2000-2025` (MIT). "
    "Not affiliated with the Premier League. Not betting advice."
)
