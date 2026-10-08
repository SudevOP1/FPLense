"""Cached loaders and small UI pieces shared by the Streamlit pages.

The app reads only ``data/published/``; nothing here calls the FPL API.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from fPLense import app_data, config

TTL_S = 600  # re-read published files at most every 10 minutes (a scheduled refresh may land)


@st.cache_data(ttl=TTL_S)
def latest() -> dict | None:
    return app_data.load_latest()


@st.cache_data(ttl=TTL_S)
def predictions(file: str) -> pd.DataFrame:
    return pd.read_parquet(config.PUBLISHED_DIR / file)


@st.cache_data(ttl=TTL_S)
def shap_values(file: str) -> pd.DataFrame:
    return pd.read_parquet(config.PUBLISHED_DIR / file)


@st.cache_data(ttl=TTL_S)
def published_json(name: str) -> dict | None:
    return app_data.read_json(name)


def require_latest() -> dict:
    """The newest predictions' metadata; stops the page with a hint if none are published."""
    meta = latest()
    if meta is None:
        st.error(
            "No predictions published yet. Run "
            "`python -m fPLense.pipeline --refresh --predict --horizon 5 --force` first."
        )
        st.stop()
    return meta


def gw_label(gw: int) -> str:
    return f"GW{gw}"


def sidebar_status(meta: dict) -> None:
    with st.sidebar:
        st.caption(
            f"**{meta['season']} GW{meta['gw']}** · deadline in "
            f"{app_data.time_until(meta.get('deadline'))}  \n"
            f"Data through GW{meta.get('data_through_gw')} · "
            f"refreshed {app_data.age(meta.get('generated_at'))}"
        )
        st.caption(f"[Source on GitHub]({config.REPO_URL})")
