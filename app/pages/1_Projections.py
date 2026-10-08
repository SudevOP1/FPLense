"""Projections: every player's expected points per gameweek, with filters and SHAP."""

from __future__ import annotations

import sys
from pathlib import Path

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import shared  # noqa: E402

from fPLense import app_data  # noqa: E402

st.set_page_config(page_title="Projections · FPLense", page_icon="📈", layout="wide")
meta = shared.require_latest()
shared.sidebar_status(meta)
gws = meta["gws"]
df = shared.predictions(meta["files"]["predictions"])

st.title("Projections")
st.caption(
    f"Expected FPL points per player for GW{gws[0]}–{gws[-1]}: per-fixture LightGBM predictions "
    "summed per gameweek (double GW = 2 fixtures, blank = 0) and scaled by FPL's chance of "
    f"playing. P_h = discounted sum (×{meta['discount']} per GW) over the chosen horizon."
)

with st.sidebar:
    st.header("Filters")
    horizon = st.slider("Horizon (GWs)", 1, len(gws), len(gws))
    positions = st.multiselect("Position", app_data.POSITIONS)
    clubs = st.multiselect("Club", sorted(df["club"].unique()))
    lo, hi = float(df["price"].min()) / 10, float(df["price"].max()) / 10
    price = st.slider("Price (£m)", lo, hi, (lo, hi), step=0.5)
    min_minutes = st.slider("Min. average minutes, last 3 fixtures", 0, 90, 0, step=15)
    search = st.text_input("Search name")

view = app_data.with_horizon(df, meta, horizon, meta["discount"])
view = app_data.filter_projections(view, positions, clubs, price, min_minutes, search)
view = view.sort_values("P_h", ascending=False)
st.write(f"**{len(view):,}** players")

p_cols = app_data.gw_columns(meta)[:horizon]
table = view[
    ["web_name", "club_short", "pos", "price", "availability", *p_cols, "P_h"]
    + [f"fx_gw{gws[0]:02d}", "odds_source", "minutes_r3", "prev_season_pts_per90", "top_shap"]
].copy()
table["price"] = table["price"] / 10
table["availability"] = table["availability"] * 100
cfg = {
    "web_name": "Player",
    "club_short": "Club",
    "pos": "Pos",
    "price": st.column_config.NumberColumn("Price", format="£%.1fm"),
    "availability": st.column_config.NumberColumn("Avail.", format="%d%%"),
    "P_h": st.column_config.NumberColumn(f"P_h ({horizon} GW)", format="%.2f"),
    f"fx_gw{gws[0]:02d}": f"GW{gws[0]} fixture",
    "odds_source": st.column_config.TextColumn(
        "Odds source", help="avg / b365 = bookmaker odds; elo = Elo-only estimate"
    ),
    "minutes_r3": st.column_config.NumberColumn("Min. r3", format="%.0f"),
    "prev_season_pts_per90": st.column_config.NumberColumn(
        "Last season pts/90", format="%.2f", help="Context only, not a model feature"
    ),
    "top_shap": st.column_config.TextColumn(f"Top SHAP drivers GW{gws[0]}", width="large"),
}
for c, gw in zip(p_cols, gws, strict=False):
    cfg[c] = st.column_config.NumberColumn(f"GW{gw}", format="%.2f")
st.dataframe(table, column_config=cfg, hide_index=True, width="stretch", height=420)

top = view.head(20).iloc[::-1]
fig = px.bar(
    top,
    x="P_h",
    y="web_name",
    color="pos",
    orientation="h",
    hover_data={"club_short": True, "price": ":.0f", "p1": ":.2f"},
    category_orders={"pos": app_data.POSITIONS},
    labels={"P_h": f"Expected points, next {horizon} GW (discounted)", "web_name": ""},
    title=f"Top 20 by P_h over GW{gws[0]}–{gws[horizon - 1]}",
)
fig.update_layout(height=560, legend_title_text="")
st.plotly_chart(fig, width="stretch")

with st.expander(f"Why this prediction? SHAP for GW{gws[0]}", expanded=False):
    if view.empty:
        st.write("No players match the filters.")
    else:
        label = view["web_name"] + " (" + view["club_short"] + ", " + view["pos"] + ")"
        choice = st.selectbox(
            "Player",
            view["element"],
            format_func=dict(zip(view["element"], label, strict=True)).get,
        )
        sv = shared.shap_values(meta["files"]["shap"]).set_index("element")
        row = view.set_index("element").loc[choice]
        if choice not in sv.index:
            st.write("No fixture this gameweek (blank), so there is nothing to explain.")
        else:
            s = sv.loc[choice]
            wf = app_data.waterfall_data(s, k=10)
            pred = float(s["base_value"] + wf["shap"].sum())
            labels_ = [
                f"{f} = {v:.2f}" if isinstance(v, float) and v == v else str(f)
                for f, v in zip(wf["feature"], wf["value"], strict=True)
            ]
            fig = go.Figure(
                go.Waterfall(
                    orientation="h",
                    measure=["absolute", *["relative"] * len(wf), "total"],
                    y=["base value", *labels_, "prediction"],
                    x=[float(s["base_value"]), *wf["shap"], pred],
                    text=[
                        f"{float(s['base_value']):.2f}",
                        *[f"{v:+.2f}" for v in wf["shap"]],
                        f"{pred:.2f}",
                    ],
                )
            )
            fig.update_layout(
                height=520,
                yaxis={"autorange": "reversed"},
                title=f"{row['web_name']}: {pred:.2f} pts before availability "
                f"(×{row['availability']:.0%} → {row['p1']:.2f})",
            )
            st.plotly_chart(fig, width="stretch")
            st.caption(
                f"{int(s['n_fixtures'])} fixture(s) in GW{gws[0]}; SHAP values are summed over "
                "them. base value = the model's average prediction."
            )
        fx = [
            {
                "GW": gw,
                "fixtures": row[f"fx_gw{gw:02d}"],
                "odds source": row[f"src_gw{gw:02d}"],
                "expected points": round(float(row[f"p_gw{gw:02d}"]), 2),
            }
            for gw in gws
        ]
        st.dataframe(fx, hide_index=True)
        if row.get("news"):
            st.caption(f"FPL news: {row['news']}")
