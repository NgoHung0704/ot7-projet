-- Upserts staging and simulation into the star schema on natural keys: a second load of the same data
-- changes nothing. Runs inside load.py's transaction, after schema.sql.

INSERT INTO dim_date (date_key, full_date, day, month, year)
SELECT to_char(event_date, 'YYYYMMDD')::INTEGER, event_date,
       EXTRACT(DAY FROM event_date), EXTRACT(MONTH FROM event_date), EXTRACT(YEAR FROM event_date)
FROM (SELECT start_date AS event_date FROM staging.stg_disaster
      UNION
      SELECT DISTINCT impact_date FROM simulation.event_toll) AS event_dates
ON CONFLICT (date_key) DO NOTHING;

INSERT INTO dim_location (location_id, city, country, latitude, longitude)
SELECT geonameid::TEXT, name, country_name, latitude, longitude
FROM staging.stg_city
UNION ALL
-- One row per code even if EM-DAT spelled the country two ways: an upsert cannot touch a row twice.
SELECT * FROM (SELECT DISTINCT ON (iso3) iso3, 'Whole country', country, NULL::FLOAT, NULL::FLOAT
               FROM staging.stg_disaster ORDER BY iso3, country) AS countries
ON CONFLICT (location_id) DO UPDATE
SET city = EXCLUDED.city, country = EXCLUDED.country,
    latitude = EXCLUDED.latitude, longitude = EXCLUDED.longitude;

-- Historical disasters: Type 1, EM-DAT corrections replace the old values.
INSERT INTO dim_event (event_id, event_name, origin, disaster_type, magnitude, max_wind_kmh,
                       shaking_class, wind_class, valid_from)
SELECT disaster.dis_no,
       COALESCE(disaster.event_name, disaster.disaster_type || ' in ' || disaster.country),
       'Historical', disaster.disaster_type, intensity.magnitude, intensity.max_wind_kmh,
       COALESCE(intensity.shaking_class, 'Not applicable'), COALESCE(intensity.wind_class, 'Not applicable'),
       current_date
FROM staging.stg_disaster AS disaster
LEFT JOIN simulation.historical_intensity AS intensity ON intensity.dis_no = disaster.dis_no
ON CONFLICT (event_id) WHERE is_current DO UPDATE
SET event_name = EXCLUDED.event_name, disaster_type = EXCLUDED.disaster_type,
    magnitude = EXCLUDED.magnitude, max_wind_kmh = EXCLUDED.max_wind_kmh,
    shaking_class = EXCLUDED.shaking_class, wind_class = EXCLUDED.wind_class;

-- Asteroids: the intensity does not depend on the city struck, so any scenario of the asteroid gives it.
CREATE TEMPORARY TABLE asteroid_source ON COMMIT DROP AS
SELECT asteroid.des AS event_id, COALESCE(asteroid.fullname, asteroid.des) AS event_name,
       asteroid.diameter_m, asteroid.mass_kg, asteroid.entry_speed_kms, asteroid.impact_probability,
       intensity.magnitude, intensity.peak_wind_kmh AS max_wind_kmh, intensity.shaking_class, intensity.wind_class
FROM staging.stg_asteroid AS asteroid
JOIN (SELECT DISTINCT ON (des) des, magnitude, peak_wind_kmh, shaking_class, wind_class
      FROM simulation.event_toll ORDER BY des) AS intensity ON intensity.des = asteroid.des
WHERE asteroid.des NOT IN (SELECT des FROM staging.stg_asteroid_removed);

-- Type 2: a new size or speed closes the current version; its scenarios keep pointing to it.
UPDATE dim_event AS event
SET valid_to = current_date, is_current = false
FROM asteroid_source AS source
WHERE event.event_id = source.event_id AND event.is_current
  AND (event.diameter_m, event.mass_kg, event.entry_speed_kms, event.magnitude, event.max_wind_kmh,
       event.shaking_class, event.wind_class)
      IS DISTINCT FROM
      (source.diameter_m, source.mass_kg, source.entry_speed_kms, source.magnitude, source.max_wind_kmh,
       source.shaking_class, source.wind_class);

UPDATE dim_event
SET valid_to = current_date, is_current = false
WHERE is_current AND origin = 'Simulated'
  AND event_id IN (SELECT des FROM staging.stg_asteroid_removed);

INSERT INTO dim_event (event_id, event_name, origin, disaster_type, magnitude, max_wind_kmh, shaking_class,
                       wind_class, diameter_m, mass_kg, entry_speed_kms, impact_probability, valid_from)
SELECT event_id, event_name, 'Simulated', 'Impact', magnitude, max_wind_kmh, shaking_class, wind_class,
       diameter_m, mass_kg, entry_speed_kms, impact_probability, current_date
FROM asteroid_source AS source
WHERE NOT EXISTS (SELECT 1 FROM dim_event AS event WHERE event.event_id = source.event_id AND event.is_current);

-- Type 1: the name and the impact probability overwrite every version.
UPDATE dim_event AS event
SET event_name = source.event_name, impact_probability = source.impact_probability
FROM asteroid_source AS source
WHERE event.event_id = source.event_id
  AND (event.event_name, event.impact_probability) IS DISTINCT FROM (source.event_name, source.impact_probability);

INSERT INTO fact_event_toll (event_key, location_key, date_key, deaths, damage_usd)
SELECT event.event_key, location.location_key, to_char(disaster.start_date, 'YYYYMMDD')::INTEGER,
       disaster.deaths, disaster.damage_adjusted_usd
FROM staging.stg_disaster AS disaster
JOIN dim_event AS event ON event.event_id = disaster.dis_no AND event.is_current
JOIN dim_location AS location ON location.location_id = disaster.iso3
ON CONFLICT (event_key, location_key) DO UPDATE
SET date_key = EXCLUDED.date_key, deaths = EXCLUDED.deaths, damage_usd = EXCLUDED.damage_usd;

INSERT INTO fact_event_toll (event_key, location_key, date_key, deaths, damage_usd)
SELECT event.event_key, location.location_key, to_char(toll.impact_date, 'YYYYMMDD')::INTEGER,
       toll.deaths, toll.damage_usd
FROM simulation.event_toll AS toll
JOIN dim_event AS event ON event.event_id = toll.des AND event.is_current AND event.origin = 'Simulated'
JOIN dim_location AS location ON location.location_id = toll.geonameid::TEXT
ON CONFLICT (event_key, location_key) DO UPDATE
SET date_key = EXCLUDED.date_key, deaths = EXCLUDED.deaths, damage_usd = EXCLUDED.damage_usd;
