"""Optimal Squad: the PuLP integer program's best 15, re-solved live for the chosen settings."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import shared  # noqa: E402

from fPLense import app_data, config  # noqa: E402
from fPLense.optimize.squad_ilp import InfeasibleSquadError, pick_squad  # noqa: E402

st.set_page_config(page_title="Optimal Squad · FPLense", page_icon="🧮", layout="wide")
meta = shared.require_latest()
shared.sidebar_status(meta)
gws = meta["gws"]

st.title("Optimal Squad")
st.caption(
    "Integer linear program (PuLP + CBC): maximise the starters' expected points over the horizon "
    "+ the captain's next-GW points (the armband doubles one GW) + bench weight × the bench's "
    "points, subject to the budget, 2 GK / 5 DEF / 5 MID / 3 FWD, at most 3 players per club and "
    "a legal XI (1 GK, ≥3 DEF, ≥2 MID, ≥1 FWD). Injured (0%) and departed players are excluded."
)

with st.sidebar:
    st.header("Settings")
    budget = st.slider("Budget (£m)", 80.0, 110.0, config.BUDGET / 10, step=0.5)
    horizon = st.slider("Horizon (GWs)", 1, len(gws), len(gws))
    bench_w = st.slider("Bench weight", 0.0, 1.0, float(config.BENCH_WEIGHT), step=0.05)


@st.cache_data(ttl=shared.TTL_S, show_spinner="Solving the integer program…")
def solve(file: str, budget_tenths: int, horizon: int, bench_w: float):
    df = app_data.with_horizon(shared.predictions(file), meta, horizon, meta["discount"])
    pool = app_data.squad_pool(df)
    res = pick_squad(pool, budget=budget_tenths, bench_w=bench_w)
    stats = {"cost": res.cost, "expected": res.expected_points, "objective": res.objective}
    return app_data.squad_table(pool, res), stats


budget_tenths = round(budget * 10)
try:
    table, stats = solve(meta["files"]["predictions"], budget_tenths, horizon, bench_w)
except InfeasibleSquadError as exc:
    st.error(f"No legal squad for these settings: {exc}")
    st.stop()

c1, c2, c3, c4 = st.columns(4)
c1.metric(f"Expected points, GW{gws[0]}–{gws[horizon - 1]}", f"{stats['expected']:.1f}")
c2.metric("Squad cost", f"£{stats['cost'] / 10:.1f}m")
c3.metric("Money left", f"£{(budget_tenths - stats['cost']) / 10:.1f}m")
captain = table.loc[table["captain"], "name"].iloc[0]
vice = table.loc[table["vice"], "name"].iloc[0]
c4.metric("Captain", captain, f"vice: {vice}", delta_color="off")
st.caption(
    "Expected points = the starters' discounted points over the horizon + the captain's next-GW "
    "points (bench excluded)."
)


def card(p: dict) -> None:
    badge = " (C)" if p["captain"] else (" (V)" if p["vice"] else "")
    with st.container(border=True):
        st.markdown(f"**{p['name']}**{badge}")
        st.caption(f"{p['club']} · {p['pos']} · £{p['price']:.1f}m")
        st.write(f"GW{gws[0]}: {p['p1']:.2f} · {horizon} GW: {p['P_h']:.1f}")


lines = app_data.pitch_lines(table)
st.subheader("Starting XI")
for pos in app_data.POSITIONS:
    players = lines[pos]
    pad = max((5 - len(players)) / 2, 0.01)
    cols = st.columns([pad, *[1] * len(players), pad])
    for col, p in zip(cols[1:-1], players, strict=True):
        with col:
            card(p)

st.subheader("Bench")
for col, p in zip(st.columns(4), lines["bench"], strict=False):
    with col:
        st.caption(f"Sub {p['bench']}")
        card(p)

with st.expander("Squad table"):
    show = table.copy()
    show["role"] = [
        "captain"
        if r.captain
        else "vice"
        if r.vice
        else "starter"
        if r.starter
        else f"bench {r.bench}"
        for r in show.itertuples()
    ]
    st.dataframe(
        show[["name", "club", "pos", "price", "p1", "P_h", "role"]].rename(
            columns={"p1": f"GW{gws[0]}", "P_h": f"{horizon} GW"}
        ),
        hide_index=True,
        width="stretch",
    )

defaults = (
    budget_tenths == config.BUDGET
    and horizon == len(gws)
    and abs(bench_w - config.BENCH_WEIGHT) < 1e-9
)
published = shared.published_json(meta["files"]["squad"])
if published and defaults:
    same = set(table["element"]) == {p["element"] for p in published["players"]}
    st.caption(
        "Default settings: same squad as the one the pipeline published."
        if same
        else "Default settings: the solver found a different squad with the same objective."
    )
