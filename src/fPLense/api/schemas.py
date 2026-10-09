"""Request and response models (pydantic v2). Prices are integer tenths of £1m (55 = £5.5m)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from fPLense import config

Position = Literal["GK", "DEF", "MID", "FWD"]
SlotKind = Literal["entry", "model_pick", "hindsight", "code", "squad"]


class ApiError(BaseModel):
    detail: str
    kind: str | None = None


# --- meta -------------------------------------------------------------------------------------


class Health(BaseModel):
    status: Literal["ok", "no_data"]
    season: str
    next_gw: int | None
    published_at: str | None


class Headline(BaseModel):
    gain_pct: float
    ci: list[float]
    mae: float
    b0_mae: float
    n: int
    season: str
    spearman: float
    b0_spearman: float


class Meta(BaseModel):
    season: str
    current_gw: int | None = Field(description="last finished gameweek")
    next_gw: int
    deadline: str | None = Field(description="next deadline, UTC ISO 8601")
    gws: list[int] = Field(description="gameweeks covered by the live predictions")
    finished_gws: list[int]
    archived_gws: list[int]
    backfilled_gws: list[int]
    live_gws: list[int]
    generated_at: str | None
    data_through_gw: int | None
    horizon_max: int
    budget: int
    headline: Headline | None
    rating_source: str


# --- players ----------------------------------------------------------------------------------


class GwPoints(BaseModel):
    gw: int
    points: float


class FixtureTick(BaseModel):
    gw: int
    opponent: str = Field(description="opponent short name, e.g. ARS")
    home: bool
    fdr: int | None
    kickoff: str


class Player(BaseModel):
    id: int
    code: int
    web_name: str
    name: str
    pos: Position
    club: str
    club_short: str
    price: int
    status: str
    chance_of_playing_next_round: float | None
    news: str
    availability: float
    selected_by_percent: float | None
    photo_url: str | None
    rating: int
    rating_source: str
    expected: list[GwPoints] = Field(description="expected points per GW (live horizon)")
    p: float = Field(description="expected points in the requested GW")
    P_h: float = Field(description="discounted expected points over the horizon")
    actual: int | None = Field(None, description="actual points if the GW is finished")
    minutes: int | None = None
    fixtures: list[FixtureTick]


class PlayersOut(BaseModel):
    gw: int
    gws: list[int]
    source: Literal["live", "backfill", "latest"]
    finished: bool
    players: list[Player]


class ShapItem(BaseModel):
    feature: str
    shap: float
    value: float | str | None


class PlayerGw(BaseModel):
    gw: int
    expected: float | None
    actual: int | None
    minutes: int | None
    source: str | None


class PlayerDetail(Player):
    season_points: int | None
    season_minutes: int | None
    prev_season_pts_per90: float | None
    top_shap: str | None
    shap_base_value: float | None
    shap_prediction: float | None = Field(description="raw next-GW prediction before availability")
    shap: list[ShapItem]
    season: list[PlayerGw]


# --- squads -----------------------------------------------------------------------------------


class SquadPlayer(BaseModel):
    id: int
    code: int | None
    web_name: str
    pos: Position
    club: str
    club_short: str
    price: int
    expected: float | None
    P_h: float | None
    actual: int | None
    minutes: int | None
    starter: bool
    bench_order: int | None
    captain: bool
    vice: bool
    photo_url: str | None
    rating: int | None
    rating_source: str | None
    status: str | None
    news: str | None


class Problem(BaseModel):
    rule: str
    message: str


class Squad(BaseModel):
    kind: str
    gw: int
    label: str
    players: list[SquadPlayer]
    starters: list[int]
    bench: list[int]
    captain: int
    vice: int
    cost: int
    bank: int
    budget: int
    expected_points: float | None = Field(description="XI + captain for the GW")
    horizon_expected: list[GwPoints]
    actual_points: int | None = Field(description="XI after auto-subs + captain, if finished")
    code: str | None = Field(description="shareable team code")
    source: str | None = None
    problems: list[Problem] = []


class OptimizeIn(BaseModel):
    budget: int = Field(config.BUDGET, ge=500, le=1500, description="tenths of £1m")
    horizon: int = Field(config.HISTORY_HORIZON, ge=1, le=config.PREDICT_HORIZON_MAX)
    bench_weight: float = Field(config.BENCH_WEIGHT, ge=0.0, le=1.0)
    locked: list[int] = Field(default_factory=list, max_length=15)
    banned: list[int] = Field(default_factory=list, max_length=200)


class EvaluateIn(BaseModel):
    players: list[int] = Field(max_length=15)
    starters: list[int] | None = Field(None, max_length=11)
    captain: int | None = None
    vice: int | None = None
    gw: int | None = None


class EvaluateOut(BaseModel):
    gw: int
    finished: bool
    legal: bool
    problems: list[Problem]
    cost: int
    bank: int
    starters: list[int]
    bench: list[int]
    captain: int | None
    vice: int | None
    expected_points: float | None
    horizon_expected: list[GwPoints]
    actual_points: int | None
    players: list[SquadPlayer]


# --- history ----------------------------------------------------------------------------------


class SummaryRow(BaseModel):
    gw: int
    source: str
    made_at: str | None
    model_expected: float
    model_actual: int
    model_cost: int
    hindsight_points: int
    hindsight_cost: int
    shared_players: int
    average_entry_score: int | None
    highest_score: int | None
    capture_ratio: float | None


class SeasonEvent(BaseModel):
    gw: int
    deadline_time: str
    finished: bool
    average_entry_score: int | None
    highest_score: int | None


class HistorySummary(BaseModel):
    season: str
    note: str
    gws: list[SummaryRow]
    events: list[SeasonEvent]


class HistoryGw(BaseModel):
    gw: int
    source: str
    made_at: str | None
    caveat: str | None
    model_pick: Squad
    hindsight: Squad | None
    summary: SummaryRow | None


# --- FPL entries ------------------------------------------------------------------------------


class Chip(BaseModel):
    name: str
    gw: int


class EntryGw(BaseModel):
    gw: int
    points: int
    total_points: int
    rank: int | None
    overall_rank: int | None
    bank: int
    value: int
    transfers: int
    transfers_cost: int
    points_on_bench: int
    chip: str | None
    model_pick_points: int | None
    hindsight_points: int | None
    average_entry_score: int | None


class Entry(BaseModel):
    id: int
    team_name: str
    manager_name: str
    overall_points: int | None
    overall_rank: int | None
    current_event: int | None
    value: int | None
    bank: int | None
    history: list[EntryGw]
    chips: list[Chip]


class AutoSub(BaseModel):
    out: int
    into: int


class EntryGwOut(BaseModel):
    team_id: int
    gw: int
    predict_gw: int
    active_chip: str | None
    points: int | None
    bank: int
    value: int
    squad: Squad
    automatic_subs: list[AutoSub]
    lineup: Squad | None = Field(description="lineup helper: best XI + captain from these 15")
    lineup_changes: list[int] = Field(description="players the helper moves into the XI")


# --- transfers --------------------------------------------------------------------------------


class TransferIn(BaseModel):
    team_id: int | None = Field(None, gt=0)
    squad: list[int] | None = Field(None, min_length=15, max_length=15)
    bank: int | None = Field(None, ge=0, le=1000, description="tenths; prefilled from FPL")
    free_transfers: int = Field(1, ge=0, le=config.MAX_FREE_TRANSFERS)
    max_transfers: int = Field(config.MAX_TRANSFERS_PLAN, ge=0, le=config.MAX_TRANSFERS_PLAN)
    horizon: int = Field(config.HISTORY_HORIZON, ge=1, le=config.PREDICT_HORIZON_MAX)
    target: list[int] | None = Field(
        None, min_length=15, max_length=15, description="target squad (default: best team)"
    )
    path: bool = Field(True, description="also plan the path to the target squad")


class Move(BaseModel):
    out: SquadPlayer
    into: SquadPlayer
    gain: float = Field(description="P_h of the player in minus the player out")


class TransferOptionOut(BaseModel):
    n_transfers: int
    moves: list[Move]
    hits: int
    expected_points: float
    net_gain: float
    bank_after: int
    recommended: bool


class PathStepOut(BaseModel):
    n_moves: int
    new_moves: list[Move]
    gain_before_hits: float
    hits: int
    net_gain: float
    bank_after: int


class PathOut(BaseModel):
    target: Squad
    steps: list[PathStepOut]
    make_now: int
    advice: str


class TransferOut(BaseModel):
    gw: int
    current: Squad
    bank: int
    free_transfers: int
    options: list[TransferOptionOut]
    recommended: int
    path: PathOut | None
    caveat: str


# --- compare ----------------------------------------------------------------------------------


class Slot(BaseModel):
    kind: SlotKind
    gw: int | None = None
    value: int | str | list[int] | None = Field(
        None, description="entry: team id · code: team code · squad: 15 player ids"
    )
    starters: list[int] | None = Field(None, max_length=11)
    captain: int | None = None
    vice: int | None = None
    label: str | None = Field(None, max_length=60)


class CompareIn(BaseModel):
    slots: list[Slot] = Field(min_length=2, max_length=3)


class PositionPoints(BaseModel):
    pos: Position
    expected: float
    actual: int | None


class SlotOut(BaseModel):
    letter: Literal["A", "B", "C"]
    kind: SlotKind
    squad: Squad
    captain_expected: float | None
    captain_actual: int | None
    bench_expected: float | None
    bench_actual: int | None
    by_position: list[PositionPoints]
    differentials: list[int]


class SharedPlayer(BaseModel):
    id: int
    slots: list[str]


class HorizonRow(BaseModel):
    gw: int
    points: list[float | None]


class CompareOut(BaseModel):
    slots: list[SlotOut]
    shared: list[SharedPlayer]
    horizon: list[HorizonRow]


# --- team codes -------------------------------------------------------------------------------


class DecodeIn(BaseModel):
    code: str = Field(max_length=500)


class DecodeOut(BaseModel):
    code: str
    season: str
    squad: Squad
    over_budget: bool


class EncodeIn(BaseModel):
    starters: list[int] = Field(min_length=11, max_length=11)
    bench: list[int] = Field(min_length=4, max_length=4)
    captain: int
    vice: int

    @field_validator("bench")
    @classmethod
    def _distinct(cls, bench, info):
        starters = info.data.get("starters") or []
        if len(set(starters) | set(bench)) != len(starters) + len(bench):
            raise ValueError("a player appears twice")
        return bench


class EncodeOut(BaseModel):
    code: str
    share_param: str
