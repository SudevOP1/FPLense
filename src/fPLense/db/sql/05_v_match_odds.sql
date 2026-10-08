-- Opponent strength from pre-match bookmaker odds and ClubElo: one row per (season, fixture, team).
-- Odds join on (season, home, away) via the team-name map; closing odds never reach the lake.
-- Elo: each club's latest snapshot dated strictly before the gameweek's first kick-off (ASOF JOIN).
create or replace view v_team_names as
select * from read_csv('${team_names}', header = true, all_varchar = true);

create or replace view v_odds as
select * from read_parquet('${lake}/odds/*/*.parquet', hive_partitioning = true, union_by_name = true);

create or replace view v_elo as
select * from read_parquet('${lake}/elo/*.parquet');

create or replace view v_fixture_odds as
select
    h.season, h.fixture, h.team as home, a.team as away,
    o.p_home, o.p_draw, o.p_away, o.lam_home, o.lam_away, o.source_1x2, o.source_ou,
    o.fthg, o.ftag
from v_team_match h
join v_team_match a
    on a.season = h.season and a.fixture = h.fixture and a.team_id = h.opponent_id
left join v_team_names nh on nh.fpl_name = h.team
left join v_team_names na on na.fpl_name = a.team
left join v_odds o
    on o.season = h.season and o.home_team = nh.fd_name and o.away_team = na.fd_name
where h.is_home;

create or replace view v_match_odds as
with gw_start as (
    select season, gw, cast(timezone('UTC', min(kickoff_time)) as date) as gw_start_date
    from v_team_match
    group by season, gw
),
team_rows as (
    select
        t.season, t.fixture, t.team_id, t.team, t.opponent, t.is_home, t.gw, g.gw_start_date,
        nt.clubelo_name   as elo_club,
        nopp.clubelo_name as opp_elo_club,
        case when t.is_home then f.lam_home else f.lam_away end as team_xg_implied,
        case when t.is_home then f.lam_away else f.lam_home end as opp_xg_implied,
        case when t.is_home then f.p_home   else f.p_away   end as p_win,
        f.source_1x2 as odds_source
    from v_team_match t
    join gw_start g on g.season = t.season and g.gw = t.gw
    left join v_fixture_odds f on f.season = t.season and f.fixture = t.fixture
    left join v_team_names nt   on nt.fpl_name = t.team
    left join v_team_names nopp on nopp.fpl_name = t.opponent
)
select
    r.season, r.fixture, r.team_id, r.team, r.opponent, r.is_home, r.gw, r.odds_source,
    r.team_xg_implied,
    r.opp_xg_implied,
    exp(-r.opp_xg_implied) as p_clean_sheet,
    r.p_win,
    e.elo                  as elo,
    eo.elo                 as opp_elo,
    e.elo - eo.elo         as elo_diff,
    e.date                 as elo_date
from team_rows r
asof left join v_elo e  on e.club  = r.elo_club     and r.gw_start_date > e.date
asof left join v_elo eo on eo.club = r.opp_elo_club and r.gw_start_date > eo.date;
