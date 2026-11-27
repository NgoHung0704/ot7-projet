-- The game reads only these views: the staging and simulation tables can change without breaking it.
-- Views run with their owner's rights, so game_reader needs no access to the tables behind them.

CREATE SCHEMA IF NOT EXISTS game;

DROP VIEW IF EXISTS game.asteroid_scenario;
CREATE VIEW game.asteroid_scenario AS
SELECT toll.des,
       COALESCE(asteroid.fullname, toll.des) AS asteroid_name,
       asteroid.diameter_m,
       asteroid.entry_speed_kms,
       toll.impact_date,
       city.geonameid,
       city.name AS city,
       city.country_name AS country,
       city.population,
       city.latitude,
       city.longitude,
       toll.deaths,
       toll.damage_usd,
       toll.magnitude,
       toll.peak_wind_kmh AS max_wind_kmh,
       toll.shaking_class,
       toll.wind_class
FROM simulation.event_toll AS toll
JOIN staging.stg_asteroid AS asteroid ON asteroid.des = toll.des
JOIN staging.stg_city AS city ON city.geonameid = toll.geonameid
-- NOT IN rather than NOT EXISTS: the planner takes the anti-join to keep almost no row and picks nested loops,
-- 30 s per draw on 356,000 scenarios. des is a primary key, so NOT IN never meets a NULL.
WHERE toll.des NOT IN (SELECT des FROM staging.stg_asteroid_removed);

-- Only sudden, local disasters with a known death toll: a decade-long famine is no match for an impact.
DROP VIEW IF EXISTS game.historical_disaster;
CREATE VIEW game.historical_disaster AS
SELECT disaster.dis_no,
       disaster.event_name,
       disaster.disaster_type,
       disaster.country,
       EXTRACT(YEAR FROM disaster.start_date)::INTEGER AS year,
       disaster.deaths,
       disaster.damage_adjusted_usd AS damage_usd,
       intensity.magnitude,
       intensity.max_wind_kmh,
       COALESCE(intensity.shaking_class, 'Not applicable') AS shaking_class,
       COALESCE(intensity.wind_class, 'Not applicable') AS wind_class
FROM staging.stg_disaster AS disaster
LEFT JOIN simulation.historical_intensity AS intensity ON intensity.dis_no = disaster.dis_no
WHERE disaster.deaths IS NOT NULL
  AND (disaster.disaster_type IN ('Earthquake', 'Storm', 'Flood', 'Volcanic activity')
       OR disaster.disaster_type LIKE 'Mass movement%'
       OR disaster.disaster_type LIKE 'Explosion%'
       OR disaster.disaster_subgroup = 'Industrial accident');

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'game_reader') THEN
        CREATE ROLE game_reader LOGIN;
    END IF;
    EXECUTE format('ALTER ROLE game_reader PASSWORD %L', current_setting('game.reader_password'));
END
$$;

GRANT USAGE ON SCHEMA game TO game_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA game TO game_reader;
