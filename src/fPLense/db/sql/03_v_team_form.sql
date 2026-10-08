-- Team form over the team's previous 5 fixtures. Windows end at 1 PRECEDING and reset each season.
-- Leakage guard for double gameweeks: every fixture in a GW takes the form as it stood before the
-- team's first fixture of that GW (first_value over the GW), so a DGW's second match never sees
-- the first match's result (it is played after the FPL deadline).
create or replace view v_team_form as
with by_fixture as (
    select *,
        avg(goals_for)     over w5 as gf_r5_fx,
        avg(goals_against) over w5 as ga_r5_fx,
        avg(xg_for)        over w5 as xgf_r5_fx,
        avg(xg_against)    over w5 as xga_r5_fx
    from v_team_match
    window w5 as (partition by season, team_id order by gw, kickoff_time, fixture
                  rows between 5 preceding and 1 preceding)
)
select
    season, fixture, team_id, team, opponent_id, opponent, is_home, kickoff_time, gw,
    goals_for, goals_against, xg_for, xg_against,
    first_value(gf_r5_fx)  over g as team_gf_r5,
    first_value(ga_r5_fx)  over g as team_ga_r5,
    first_value(xgf_r5_fx) over g as team_xgf_r5,
    first_value(xga_r5_fx) over g as team_xga_r5,
    count(*) over (partition by season, team_id, gw) as team_fixtures_in_gw   -- DGW flag
from by_fixture
window g as (partition by season, team_id, gw order by kickoff_time, fixture);
