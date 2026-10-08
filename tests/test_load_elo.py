"""Elo loader: Kaggle token discovery and cleaning (no network, no Kaggle calls)."""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from fPLense.etl import load_elo


def test_missing_token_gives_clear_message(tmp_path):
    with pytest.raises(
        load_elo.KaggleTokenError, match=r"Kaggle token not found: see PLAN.md §0.2"
    ):
        load_elo.kaggle_env(environ={}, config_dir=tmp_path)


def test_env_credentials_accepted(tmp_path):
    env = load_elo.kaggle_env(
        environ={"KAGGLE_USERNAME": "u", "KAGGLE_KEY": "k"}, config_dir=tmp_path
    )
    assert env["KAGGLE_KEY"] == "k"
    env = load_elo.kaggle_env(environ={"KAGGLE_API_TOKEN": "t"}, config_dir=tmp_path)
    assert env["KAGGLE_API_TOKEN"] == "t"


def test_kaggle_json_accepted(tmp_path):
    (tmp_path / "kaggle.json").write_text('{"username": "u", "key": "k"}', encoding="utf-8")
    assert "KAGGLE_API_TOKEN" not in load_elo.kaggle_env(environ={}, config_dir=tmp_path)


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16", "utf-8-sig"])
def test_access_token_any_encoding(tmp_path, encoding):
    # PowerShell's `>` redirect writes UTF-16 with a BOM; the kaggle CLI crashes on that
    (tmp_path / "access_token").write_text("KGAT_dummy\n", encoding=encoding)
    env = load_elo.kaggle_env(environ={}, config_dir=tmp_path)
    assert env["KAGGLE_API_TOKEN"] == "KGAT_dummy"


def test_clean_elo_filters_and_merges_aliases():
    raw = pd.DataFrame(
        {
            "date": [
                "2016-06-15",
                "2016-07-01",
                "2016-07-01",
                "2025-01-01",
                "2025-06-15",
                "2025-06-15",
            ],
            "club": [
                "Arsenal",
                "Arsenal",
                "Bayern",
                "Nott'm Forest",
                "Nottm Forest",
                "Nott'm Forest",
            ],
            "country": ["ENG", "ENG", "GER", "ENG", "ENG", "ENG"],
            "elo": ["1800", "1810.5", "1900", "1766.4", "1731.5", "1802.9"],
        }
    )
    out = load_elo.clean_elo(raw)
    assert list(out.columns) == ["date", "club", "elo"]
    assert set(out.club) == {"Arsenal", "Nott'm Forest"}  # no GER, no old alias left
    assert out.date.min() == dt.date(2016, 7, 1)  # nothing before ELO_START_DATE
    forest = out[out.club == "Nott'm Forest"].set_index("date").elo
    assert forest[dt.date(2025, 6, 15)] == pytest.approx(1802.9)  # canonical row wins the tie
    assert not out.duplicated(["date", "club"]).any()


def test_clean_elo_old_alias_renamed_when_alone():
    raw = pd.DataFrame(
        {"Date": ["2020-01-01"], "Club": ["Nottm Forest"], "Country": ["ENG"], "Elo": [1600.0]}
    )
    out = load_elo.clean_elo(raw)
    assert out.club.tolist() == ["Nott'm Forest"]
