"""Model Card: walk-forward metrics with CIs, MAE by gameweek, SHAP, backtest, limitations."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import shared  # noqa: E402

from fPLense import app_data, config  # noqa: E402

st.set_page_config(page_title="Model Card · FPLense", page_icon="🧾", layout="wide")
meta = shared.latest()
if meta:
    shared.sidebar_status(meta)

metrics = shared.published_json(config.METRICS_PATH.name)
shap_summary = shared.published_json(config.SHAP_IMPORTANCE_PATH.name)
backtest = shared.published_json(config.BACKTEST_PATH.name)
mae_gw = shared.published_json(config.MAE_BY_GW_PATH.name)

st.title("Model Card")
st.markdown(
    "**Model:** LightGBM regressor (L2 loss, 43 features) predicting FPL points **per fixture**; "
    "a gameweek forecast is the sum over the player's fixtures. Trained on 10 seasons "
    "(2016-17 to 2025-26). **Validation:** expanding-window walk-forward over 2025-26 GW5–38 "
    "(34 refits, each trained only on earlier gameweeks), scored per player-gameweek. "
    "Headline subset: **regulars** (lagged average minutes over the last 3 fixtures ≥ 45)."
)

if not metrics:
    st.error("metrics.json not found in data/published/.")
    st.stop()

head = app_data.headline(metrics)
c1, c2, c3, c4 = st.columns(4)
c1.metric("MAE cut vs rolling form", f"{head['gain_pct']:.1f}%")
c2.metric("95% CI (gameweek bootstrap)", f"{head['ci'][0]:.1f}–{head['ci'][1]:.1f}%")
c3.metric("Regulars MAE", f"{head['mae']:.3f}", f"baseline {head['b0_mae']:.3f}", delta_color="off")
c4.metric(
    "Spearman per GW",
    f"{head['spearman']:.2f}",
    f"baseline {head['b0_spearman']:.2f}",
    delta_color="off",
)

st.subheader("Walk-forward metrics")
subset = st.radio("Subset", ["regulars", "all"], horizontal=True)
view = st.radio(
    "View",
    ["walk_forward", "holdout"],
    format_func={"walk_forward": "Walk-forward 2025-26", "holdout": "Holdout 2024-25"}.get,
    horizontal=True,
)
st.dataframe(app_data.metrics_rows(metrics, view, subset), hide_index=True, width="stretch")
st.caption(
    "Gain vs B0 = MAE improvement over the rolling-form baseline (last-5 average); the 95% CI "
    "resamples whole gameweeks 1,000×. Top-20 precision = share of the predicted top 20 that "
    "finished in the actual top 20 that gameweek."
)

st.subheader("MAE by gameweek (regulars, 2025-26)")
if mae_gw:
    rows = [
        {"model": name, "gw": g, "MAE": m}
        for name, d in mae_gw["models"].items()
        for g, m in zip(d["gw"], d["mae"], strict=True)
    ]
    labels = {"b0": "B0 rolling form", "ridge": "B1 Ridge", "lgbm": "M1 LightGBM"}
    df = pd.DataFrame(rows).assign(model=lambda d: d["model"].map(labels).fillna(d["model"]))
    fig = px.line(df, x="gw", y="MAE", color="model", markers=True, labels={"gw": "Gameweek"})
    fig.update_layout(height=380, legend_title_text="")
    st.plotly_chart(fig, width="stretch")
elif img := app_data.image_path("mae_by_gw.png"):
    st.image(str(img))

abl = metrics.get("ablation", {})
if abl:
    with st.expander("Ablation: what each feature block adds (LightGBM, every 2nd GW, regulars)"):
        names = {
            "i_form": "(i) form, minutes, market",
            "ii_fixture": "(ii) + fixture / opponent form",
            "iii_xg": "(iii) + xG features",
            "iv_odds_elo": "(iv) + odds / Elo (all 43)",
            "iv_odds_elo_2022on": "(iv) trained on 2022-23+ only",
        }
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "features": names.get(k, k),
                        "n": abl["feature_counts"].get(k.removesuffix("_2022on"), None),
                        "MAE": round(m["regulars_mae"], 3),
                        "gain vs B0": f"{m['regulars_mae_gain_pct']:+.1f}%",
                    }
                    for k, m in abl.items()
                    if isinstance(m, dict) and "regulars_mae" in m
                ]
            ),
            hide_index=True,
        )
        st.caption("Odds/Elo add ≈0 once fixture form and xG are in; no gain is claimed for them.")

st.subheader("Explainability (SHAP)")
left, right = st.columns([1, 1])
if shap_summary:
    imp = pd.Series(shap_summary["mean_abs_shap"]).head(15)
    fig = px.bar(
        imp.iloc[::-1],
        orientation="h",
        labels={"value": "mean |SHAP| (points per fixture)", "index": ""},
        title=(
            f"Top 15 features, {shap_summary['sample_rows']:,} rows of "
            f"{shap_summary['sample_season']}"
        ),
    )
    fig.update_layout(showlegend=False, height=460)
    left.plotly_chart(fig, width="stretch")
if img := app_data.image_path("shap_beeswarm.png"):
    right.image(str(img), caption="Beeswarm: each dot is one player-fixture")
st.caption(
    "Minutes/role dominate (rotation risk is most of the signal), then recent form and price. "
    "The Projections page shows a per-player waterfall for the next gameweek."
)

st.subheader("Optimizer backtest (2025-26 GW5–38)")
if backtest:
    totals = pd.DataFrame(
        {
            "strategy": [backtest["strategies"][k] for k in backtest["total_points"]],
            "total points": list(backtest["total_points"].values()),
        }
    )
    b1, b2 = st.columns([1, 2])
    b1.dataframe(totals, hide_index=True)
    lo, hi = backtest["a_minus_b_ci95"]
    b1.caption(
        f"A − B = {backtest['a_minus_b']:+d} pts (95% CI {lo:+.0f} to {hi:+.0f}): **not "
        "significant**. The 11% MAE gain doesn't show up as season points in a single-path "
        "backtest; gameweek noise swamps it, so no backtest claim is made."
    )
    if img := app_data.image_path("backtest_cumulative.png"):
        b2.image(str(img))

st.subheader("Known limitations")
st.markdown(
    """
- **Rotation and injuries.** The model sees only lagged minutes; live predictions are scaled by
  FPL's coarse `chance_of_playing_next_round`.
- **Cold start.** New signings and promoted players have no rolling form for their first fixtures;
  last season's points per 90 is shown for context but isn't a model feature.
- **2026/27 BPS rule change** shifts bonus points; the model was trained on the old rules.
- **DEFCON** points only exist since 2025-26 (`defcon_r5` is NaN for 9 of 10 seasons).
- **Noise ceiling.** Points per appearance have an SD of about 3; Spearman per GW among regulars is
  only ~0.32.
- **Point predictions only**: no haul probability; the optimizer is risk-neutral. **No chips.**
- **Selling prices** aren't public, so the transfer planner values squads at current prices.
- **Odds for upcoming fixtures** only exist for the next round (not during international breaks);
  otherwise an Elo-only estimate is used, recorded per fixture as `odds_source`.
"""
)
st.caption(f"Full model card: [docs/model_card.md]({config.REPO_URL}/blob/main/docs/model_card.md)")
