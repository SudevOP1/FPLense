"""LightGBM points model (PLAN.md §8 P3, M1/M2).

The target is points **per fixture**; a gameweek forecast is the sum over the player's fixtures.
Early stopping uses the last ``config.EARLY_STOPPING_GWS`` gameweeks of the training window as the
validation set; the model is then refit on the whole window with the best iteration count, so the
most recent gameweeks still inform the final fit.
"""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb
import lightgbm as lgb
import numpy as np
import pandas as pd

from fPLense import config

log = logging.getLogger(__name__)

POSITION_CATEGORIES = ["GK", "DEF", "MID", "FWD"]


def load_features(con: duckdb.DuckDBPyConnection | None = None) -> pd.DataFrame:
    """All historical ``v_features`` rows (the 10 completed seasons), sorted by time."""
    from fPLense.db.build import build, features

    own = con is None
    if own:
        con = build(":memory:")
    seasons = ", ".join(f"'{s}'" for s in config.SEASONS)
    df = features(con, where=f"season in ({seasons})")
    if own:
        con.close()
    return add_regular_flag(df)


def add_regular_flag(df: pd.DataFrame) -> pd.DataFrame:
    """``regular`` = lagged ``minutes_r3 >= 45`` (known before the deadline; NaN -> False)."""
    out = df.copy()
    out["regular"] = (
        pd.to_numeric(out["minutes_r3"], errors="coerce").astype(float)
        >= config.REGULAR_MIN_MINUTES_R3
    ).fillna(False)
    return out


def lgbm_frame(df: pd.DataFrame, features: list[str] = config.FEATURES) -> pd.DataFrame:
    """Features as float, ``position`` as a fixed-category dtype (stable codes across folds)."""
    out = pd.DataFrame(index=df.index)
    for f in features:
        if f == "position":
            out[f] = pd.Categorical(df[f].astype(str), categories=POSITION_CATEGORIES)
        else:
            out[f] = pd.to_numeric(df[f], errors="coerce").astype(float)
    return out


def make_lgbm(objective: str = "regression", **overrides) -> lgb.LGBMRegressor:
    params = {**config.LGBM_PARAMS, "objective": objective, **overrides}
    return lgb.LGBMRegressor(random_state=config.RANDOM_STATE, verbose=-1, **params)


def gw_order(df: pd.DataFrame) -> pd.Series:
    """Sortable integer key for (season, gw): season start year * 100 + gw."""
    return df["season"].str[:4].astype(int) * 100 + df["gw"].astype(int)


def split_early_stopping(
    train: pd.DataFrame, n_gws: int = config.EARLY_STOPPING_GWS
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split a training window into (fit, valid): valid = its last ``n_gws`` (season, gw)s."""
    key = gw_order(train)
    last = np.sort(key.unique())[-n_gws:]
    mask = key.isin(last)
    return train[~mask], train[mask]


def fit_lgbm(
    train: pd.DataFrame,
    features: list[str] = config.FEATURES,
    objective: str = "regression",
    refit: bool = True,
    **overrides,
) -> lgb.LGBMRegressor:
    """Early-stop on the window's last GWs, then (by default) refit on all of it."""
    cats = [f for f in features if f in config.CATEGORICAL_FEATURES]
    fit_df, valid_df = split_early_stopping(train)
    model = make_lgbm(objective, **overrides)
    model.fit(
        lgbm_frame(fit_df, features),
        fit_df[config.TARGET].astype(float),
        eval_X=(lgbm_frame(valid_df, features),),
        eval_y=(valid_df[config.TARGET].astype(float),),
        eval_metric="l2" if objective == "regression" else objective,
        categorical_feature=cats or "auto",
        callbacks=[lgb.early_stopping(config.EARLY_STOPPING_ROUNDS, verbose=False)],
    )
    best = model.best_iteration_ or model.n_estimators
    if not refit:
        return model
    final = make_lgbm(objective, **{**overrides, "n_estimators": max(int(best), 1)})
    final.fit(
        lgbm_frame(train, features),
        train[config.TARGET].astype(float),
        categorical_feature=cats or "auto",
    )
    final.early_stopping_best_iteration_ = int(best)
    return final


def predict_lgbm(
    model: lgb.LGBMRegressor, df: pd.DataFrame, features: list[str] = config.FEATURES
) -> np.ndarray:
    return model.predict(lgbm_frame(df, features))


def train_final(
    df: pd.DataFrame | None = None, out_path: Path = config.MODEL_PATH
) -> lgb.LGBMRegressor:
    """Fit M1 (L2) on every historical season and save it in LightGBM text format."""
    if df is None:
        df = load_features()
    model = fit_lgbm(df)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    model.booster_.save_model(str(out_path))
    log.info("saved %s (%d trees, %d rows)", out_path, model.booster_.num_trees(), len(df))
    if out_path == config.MODEL_PATH:
        from fPLense.models.history import write_model_meta

        # the archive records which seasons the model saw (backfill refuses if it saw this one)
        write_model_meta(str(df["season"].max()), out_path, trees=model.booster_.num_trees())
    return model
