-- Player form features. Every rolling window ends at 1 PRECEDING and partitions by season, element.
-- As in v_team_form, outcome-based features are frozen at the player's first fixture of each GW
-- (first_value over the GW), so both fixtures of a double gameweek only see earlier gameweeks.
-- selected / transfers_balance are lagged (their same-GW values are post-deadline counts).
create or replace view v_player_form as
with by_fixture as (
    select
        season, element, name, fixture, gw, kickoff_time, position, team_id, team,
        opponent_team, opponent_team_name, was_home, team_h_difficulty, team_a_difficulty,
        price, value,
        total_points as y,                                         -- target (this fixture)
        lag(total_points) over p                                   as pts_last1,
        avg(total_points) over (p rows between 3 preceding and 1 preceding) as pts_r3,
        avg(total_points) over p5                                  as pts_r5,
        avg(total_points) over (p rows between unbounded preceding and 1 preceding)
                                                                   as pts_season_avg,
        sum(total_points) over (p rows between unbounded preceding and 1 preceding) * 90.0
            / nullif(sum(minutes) over (p rows between unbounded preceding and 1 preceding), 0)
                                                                   as pts_per90_season,
        avg(bps)          over p5                                  as bps_r5,
        avg(bonus)        over p5                                  as bonus_r5,
        avg(ict_index)    over p5                                  as ict_r5,
        avg(minutes)      over (p rows between 3 preceding and 1 preceding) as minutes_r3,
        avg(minutes)      over p5                                  as minutes_r5,
        avg((minutes >= 60)::int) over p5                          as played60_r5,
        avg(expected_goals)             over p5                    as xg_r5,
        avg(expected_assists)           over p5                    as xa_r5,
        avg(expected_goal_involvements) over p5                    as xgi_r5,
        avg(goals_scored)  over p5                                 as goals_r5,
        avg(assists)       over p5                                 as assists_r5,
        avg(threat)        over p5                                 as threat_r5,
        avg(creativity)    over p5                                 as creativity_r5,
        avg(influence)     over p5                                 as influence_r5,
        avg(expected_goals_conceded) over p5                       as xgc_r5,
        avg(clean_sheets)  over p5                                 as cs_r5,
        avg(saves)         over p5                                 as saves_r5,
        avg(defensive_contribution) over p5                        as defcon_r5,
        ln(1 + lag(selected) over p)                               as log_selected_lag1,
        lag(transfers_balance) over p                              as transfers_balance_lag1,
        -- schedule and price are known before the deadline, so these stay per fixture
        price - lag(price, 3) over p                               as price_change_3,
        date_diff('day', lag(kickoff_time) over p, kickoff_time)   as days_rest
    from v_player_match
    window p  as (partition by season, element order by gw, kickoff_time, fixture),
           p5 as (p rows between 5 preceding and 1 preceding)
)
select
    season, element, name, fixture, gw, kickoff_time, position, team_id, team,
    opponent_team, opponent_team_name, was_home, team_h_difficulty, team_a_difficulty,
    price, value, y,
    first_value(pts_last1)        over g as pts_last1,
    first_value(pts_r3)           over g as pts_r3,
    first_value(pts_r5)           over g as pts_r5,
    first_value(pts_season_avg)   over g as pts_season_avg,
    first_value(pts_per90_season) over g as pts_per90_season,
    first_value(bps_r5)           over g as bps_r5,
    first_value(bonus_r5)         over g as bonus_r5,
    first_value(ict_r5)           over g as ict_r5,
    first_value(minutes_r3)       over g as minutes_r3,
    first_value(minutes_r5)       over g as minutes_r5,
    first_value(played60_r5)      over g as played60_r5,
    days_rest,
    first_value(xg_r5)            over g as xg_r5,
    first_value(xa_r5)            over g as xa_r5,
    first_value(xgi_r5)           over g as xgi_r5,
    first_value(goals_r5)         over g as goals_r5,
    first_value(assists_r5)       over g as assists_r5,
    first_value(threat_r5)        over g as threat_r5,
    first_value(creativity_r5)    over g as creativity_r5,
    first_value(influence_r5)     over g as influence_r5,
    first_value(xgc_r5)           over g as xgc_r5,
    first_value(cs_r5)            over g as cs_r5,
    first_value(saves_r5)         over g as saves_r5,
    first_value(defcon_r5)        over g as defcon_r5,
    price_change_3,
    first_value(log_selected_lag1)      over g as log_selected_lag1,
    first_value(transfers_balance_lag1) over g as transfers_balance_lag1
from by_fixture
window g as (partition by season, element, gw order by kickoff_time, fixture);
