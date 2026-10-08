-- One row per (season, fixture, team). xg_for = sum of the team's player xG (NULL before 2022-23);
-- xg_against = the opponent's xg_for.
create or replace view v_team_match as
with sides as (
    select
        season,
        fixture,
        team_id,
        any_value(team)               as team,
        any_value(opponent_team)      as opponent_id,
        any_value(opponent_team_name) as opponent,
        any_value(was_home)           as is_home,
        min(kickoff_time)             as kickoff_time,
        any_value(gw)                 as gw,
        max(team_score)               as goals_for,
        max(opp_score)                as goals_against,
        sum(expected_goals)           as xg_for
    from v_player_match
    group by season, fixture, team_id
)
select s.*, o.xg_for as xg_against
from sides s
left join sides o
    on o.season = s.season and o.fixture = s.fixture and o.team_id = s.opponent_id;
