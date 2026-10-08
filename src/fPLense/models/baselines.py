"""Baselines the LightGBM model has to beat (PLAN.md §8 P3).

- B0, rolling form: ``pts_r5``, falling back to ``pts_season_avg``, then 0.
- B1, Ridge: median impute (+ missing-value indicators) -> standardise -> ``RidgeCV``, with the
  position one-hot encoded.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import RidgeCV
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from fPLense import config

RIDGE_ALPHAS = np.logspace(-2, 4, 13)


def rolling_baseline(df: pd.DataFrame) -> np.ndarray:
    """B0: last-5 average points, else season-to-date average, else 0."""
    pred = df["pts_r5"].astype(float).fillna(df["pts_season_avg"].astype(float)).fillna(0.0)
    return pred.to_numpy()


def make_ridge(features: list[str] = config.FEATURES) -> Pipeline:
    """B1 pipeline. Numeric columns: impute + indicator + scale; ``position``: one-hot."""
    categorical = [f for f in features if f in config.CATEGORICAL_FEATURES]
    numeric = [f for f in features if f not in categorical]
    numeric_pipe = Pipeline(
        [
            ("impute", SimpleImputer(strategy="median", add_indicator=True)),
            ("scale", StandardScaler()),
        ]
    )
    pre = ColumnTransformer(
        [
            ("num", numeric_pipe, numeric),
            ("cat", OneHotEncoder(handle_unknown="ignore"), categorical),
        ]
    )
    return Pipeline([("pre", pre), ("ridge", RidgeCV(alphas=RIDGE_ALPHAS))])


def ridge_frame(df: pd.DataFrame, features: list[str] = config.FEATURES) -> pd.DataFrame:
    """Feature columns as float (``position`` as str), so nullable Int64 / NA become NaN."""
    out = pd.DataFrame(index=df.index)
    for f in features:
        if f in config.CATEGORICAL_FEATURES:
            out[f] = df[f].astype(str)
        else:
            out[f] = pd.to_numeric(df[f], errors="coerce").astype(float)
    return out


def fit_ridge(train: pd.DataFrame, features: list[str] = config.FEATURES) -> Pipeline:
    model = make_ridge(features)
    model.fit(ridge_frame(train, features), train[config.TARGET].astype(float))
    return model


def predict_ridge(
    model: Pipeline, df: pd.DataFrame, features: list[str] = config.FEATURES
) -> np.ndarray:
    return model.predict(ridge_frame(df, features))
