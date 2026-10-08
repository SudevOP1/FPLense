"""Transfer Planner: the best 0-3 transfers for a real FPL team, net of hits."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import shared  # noqa: E402

from fPLense import app_data, config  # noqa: E402
from fPLense.etl import fetch_api  # noqa: E402
from fPLense.etl.net import FetchError  # noqa: E402
from fPLense.optimize.squad_ilp import InfeasibleSquadError  # noqa: E402
from fPLense.optimize.transfers import options_table, plan_transfers, recommended  # noqa: E402

st.set_page_config(page_title="Transfer Planner · FPLense", page_icon="🔁", layout="wide")
meta = shared.require_latest()
shared.sidebar_status(meta)
gws = meta["gws"]
picks_gw = int(meta.get("data_through_gw") or gws[0] - 1)

st.title("Transfer Planner")
st.caption(
    "Loads your public FPL team and solves the same integer program as the Optimal Squad page, "
    "limited to squads you can reach with exactly T = 0, 1, 2 or 3 transfers. Each transfer "
    f"beyond your free ones costs {config.HIT_COST} points."
)
st.info(
    "**Selling prices aren't public.** When you sell, FPL refunds only half of any price rise, "
    "but the API doesn't expose your selling prices, so your squad is valued at current prices. "
    "Adjust the bank below if you know the difference. The squad shown is the one you fielded in "
    f"GW{picks_gw}; transfers made since that deadline stay hidden until GW{gws[0]} starts."
)


@st.cache_data(ttl=300, show_spinner="Fetching your team from the FPL API…")
def get_picks(team_id: int, gw: int) -> dict:
    return fetch_api.parse_picks(fetch_api.fetch_picks(team_id, gw))


with st.form("team"):
    team_id = st.number_input(
        "FPL team ID", min_value=1, step=1, value=None, placeholder="e.g. 1234567"
    )
    st.caption("It's in your Points page URL: fantasy.premierleague.com/entry/**ID**/event/N")
    submitted = st.form_submit_button("Load team")
if submitted and team_id:
    try:
        st.session_state["picks"] = get_picks(int(team_id), picks_gw)
        st.session_state["team_id"] = int(team_id)
    except FetchError as exc:
        st.error(f"Couldn't load team {int(team_id)} for GW{picks_gw}: {exc}")
    except fetch_api.SchemaError as exc:
        st.error(f"Unexpected FPL API response: {exc}")

picks = st.session_state.get("picks")
if not picks:
    st.stop()

c1, c2, c3, c4 = st.columns(4)
bank = c1.number_input(
    "Bank (£m)", min_value=0.0, max_value=100.0, value=picks["bank"] / 10, step=0.1
)
free = c2.number_input("Free transfers", min_value=0, max_value=config.MAX_FREE_TRANSFERS, value=1)
horizon = c3.slider("Horizon (GWs)", 1, len(gws), len(gws))
bench_w = c4.slider("Bench weight", 0.0, 1.0, float(config.BENCH_WEIGHT), step=0.05)

file = meta["files"]["predictions"]
view = app_data.with_horizon(shared.predictions(file), meta, horizon, meta["discount"])
current = app_data.picks_summary(picks, view)
with st.expander(f"Team {st.session_state['team_id']}: GW{picks['gw']} squad"):
    st.dataframe(
        current.drop(columns="element").rename(
            columns={"p1": f"GW{gws[0]}", "P_h": f"{horizon} GW"}
        ),
        hide_index=True,
        width="stretch",
    )

missing = [e for e in picks["squad"] if e not in set(view["element"])]
if missing:
    st.error(f"Players {missing} aren't in the published predictions, so no plan is possible.")
    st.stop()


@st.cache_data(ttl=shared.TTL_S, show_spinner="Solving T = 0..3…")
def plan(file: str, squad: tuple, bank_tenths: int, free: int, horizon: int, bench_w: float):
    d = app_data.with_horizon(shared.predictions(file), meta, horizon, meta["discount"])
    pool = app_data.squad_pool(d)
    options = plan_transfers(pool, list(squad), bank_tenths, free, bench_w=bench_w)
    return options_table(options, pool["web_name"]), recommended(options).n_transfers


try:
    table, best_t = plan(file, tuple(picks["squad"]), round(bank * 10), int(free), horizon, bench_w)
except InfeasibleSquadError as exc:
    st.error(f"No legal squad reachable: {exc}")
    st.stop()

best = table[table["transfers"] == best_t].iloc[0]
if best_t == 0:
    st.success("**Recommendation: hold.** No transfer adds expected points after hits.")
else:
    hit = f" after a {best['hit']} pt hit" if best["hit"] else ""
    st.success(
        f"**Recommendation: {best_t} transfer(s).** Out: {best['out']} · in: {best['in']} · "
        f"net gain {best['net_gain']:+.2f} pts over GW{gws[0]}–{gws[horizon - 1]}{hit}"
    )

shown = table.rename(
    columns={
        "transfers": "T",
        "hit": "hit (pts)",
        "expected_points": "expected points",
        "net_gain": "net gain vs hold",
        "bank_after": "bank after (£m)",
    }
)


def highlight(row):
    colour = "background-color: rgba(46, 160, 67, 0.18)" if row["T"] == best_t else ""
    return [colour] * len(row)


st.dataframe(
    shown.style.apply(highlight, axis=1).format(
        {"expected points": "{:.2f}", "net gain vs hold": "{:+.2f}", "bank after (£m)": "£{:.1f}m"}
    ),
    hide_index=True,
    width="stretch",
)
st.caption(
    "Expected points = the new XI's discounted points over the horizon + the captain's next-GW "
    "points. Net gain = the ILP objective (including the bench term) minus hits, relative to "
    "T = 0. Options the budget can't reach are left out."
)
