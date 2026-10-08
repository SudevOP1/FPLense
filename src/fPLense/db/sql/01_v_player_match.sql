-- One row per player-fixture, read straight from the Parquet lake (season from the hive path).
create or replace view v_player_match as
select *
from read_parquet('${lake}/player_match/*/*.parquet', hive_partitioning = true, union_by_name = true);
