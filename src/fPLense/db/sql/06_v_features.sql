-- Model-ready features: player form + own team form + opponent team form + odds/Elo, one row per
-- player-fixture. Feature names match config.FEATURES. Opponent form comes only from the
-- opponent's earlier matches (v_team_form windows end at 1 PRECEDING).
create or replace view v_features as
select
    pf.season, pf.element, pf.name, pf.fixture, pf.kickoff_time, pf.team_id, pf.team,
    pf.opponent_team, pf.opponent_team_name, pf.value, mo.odds_source, pf.y,
    -- form
    pf.pts_last1, pf.pts_r3, pf.pts_r5, pf.pts_season_avg, pf.pts_per90_season,
    pf.bps_r5, pf.bonus_r5, pf.ict_r5,
    -- minutes / role
    pf.minutes_r3, pf.minutes_r5, pf.played60_r5, pf.days_rest,
    -- attacking
    pf.xg_r5, pf.xa_r5, pf.xgi_r5, pf.goals_r5, pf.assists_r5,
    pf.threat_r5, pf.creativity_r5, pf.influence_r5,
    -- defensive
    pf.xgc_r5, pf.cs_r5, pf.saves_r5, pf.defcon_r5,
    -- market
    pf.price, pf.price_change_3, pf.log_selected_lag1, pf.transfers_balance_lag1,
    -- fixture / context (FDR is published before the season; NULL for 2016-17 and 2017-18)
    pf.was_home::integer as was_home,
    case when pf.was_home then pf.team_h_difficulty else pf.team_a_difficulty end as fdr,
    opp.team_gf_r5  as opp_gf_r5,
    opp.team_ga_r5  as opp_ga_r5,
    opp.team_xgf_r5 as opp_xgf_r5,
    opp.team_xga_r5 as opp_xga_r5,
    tf.team_gf_r5,
    tf.team_xgf_r5,
    (tf.team_fixtures_in_gw > 1)::integer as is_dgw,
    -- opponent strength from odds / Elo
    mo.team_xg_implied, mo.opp_xg_implied, mo.p_clean_sheet, mo.p_win, mo.elo_diff,
    -- categorical
    pf.position,
    pf.gw
from v_player_form pf
left join v_team_form tf
    on tf.season = pf.season and tf.fixture = pf.fixture and tf.team_id = pf.team_id
left join v_team_form opp
    on opp.season = pf.season and opp.fixture = pf.fixture and opp.team_id = pf.opponent_team
left join v_match_odds mo
    on mo.season = pf.season and mo.fixture = pf.fixture and mo.team_id = pf.team_id;
