-- Valid rounds into fact_round, each with the player version of the day it was played.
-- Runs after rounds_checks.sql and the dim_player merge of rounds.py.

-- Type 1: a player's country and signup date are corrections, taken from their latest round.
UPDATE dim_player AS player
SET country = latest.player_country, signup_date = latest.player_signup_date
FROM (SELECT DISTINCT ON (player_id) player_id, player_country, player_signup_date
      FROM checked_round WHERE check_name IS NULL
      ORDER BY player_id, played_at DESC, round_id DESC) AS latest
WHERE player.player_id = latest.player_id
  AND (player.country, player.signup_date) IS DISTINCT FROM (latest.player_country, latest.player_signup_date);

INSERT INTO dim_date (date_key, full_date, day, month, year)
SELECT DISTINCT to_char(played_at, 'YYYYMMDD')::INTEGER, played_at::DATE,
       EXTRACT(DAY FROM played_at), EXTRACT(MONTH FROM played_at), EXTRACT(YEAR FROM played_at)
FROM checked_round WHERE check_name IS NULL
ON CONFLICT (date_key) DO NOTHING;

INSERT INTO fact_round (round_id, player_key, date_key, asteroid_event_key, disaster_event_key, location_key,
                        chose_asteroid_deaths, correct_deaths, chose_asteroid_damage, correct_damage, response_time_s)
SELECT checked.round_id, player.player_key, to_char(checked.played_at, 'YYYYMMDD')::INTEGER,
       checked.asteroid_event_key, checked.disaster_event_key, checked.location_key,
       checked.chose_asteroid_deaths::INTEGER, checked.correct_deaths::INTEGER,
       checked.chose_asteroid_damage::INTEGER, checked.correct_damage::INTEGER, checked.response_time_s
FROM checked_round AS checked
JOIN dim_player AS player
  ON player.player_id = checked.player_id
 AND checked.played_at::DATE >= player.valid_from AND checked.played_at::DATE < player.valid_to
WHERE checked.check_name IS NULL
ON CONFLICT (round_id) DO UPDATE
SET player_key = EXCLUDED.player_key, date_key = EXCLUDED.date_key,
    asteroid_event_key = EXCLUDED.asteroid_event_key, disaster_event_key = EXCLUDED.disaster_event_key,
    location_key = EXCLUDED.location_key, chose_asteroid_deaths = EXCLUDED.chose_asteroid_deaths,
    correct_deaths = EXCLUDED.correct_deaths, chose_asteroid_damage = EXCLUDED.chose_asteroid_damage,
    correct_damage = EXCLUDED.correct_damage, response_time_s = EXCLUDED.response_time_s;
