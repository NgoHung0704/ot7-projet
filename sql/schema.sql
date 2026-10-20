-- Star schema (pseudocode SQL)

CREATE TABLE dim_event (
    event_key          INTEGER PRIMARY KEY,
    event_id           VARCHAR,   -- EM-DAT DisNo. or Sentry designation
    event_name         VARCHAR,
    origin             VARCHAR,   -- 'Historical' or 'Simulated'
    disaster_type      VARCHAR,   -- e.g. Earthquake, Storm, Explosion, Impact
    magnitude          FLOAT,     -- ground shaking (EM-DAT, or computed for an asteroid)
    max_wind_kmh       FLOAT,     -- wind speed (EM-DAT, or computed for an asteroid)
    shaking_class      VARCHAR,   -- e.g. '6-7', or 'Not applicable'
    wind_class         VARCHAR,   -- e.g. '178-251 km/h', or 'Not applicable'
    diameter_m         FLOAT,     -- asteroids only
    mass_kg            FLOAT,     -- asteroids only
    entry_speed_kms    FLOAT,     -- asteroids only
    impact_probability FLOAT,     -- asteroids only
    is_active          BOOLEAN,   -- asteroids only
    valid_from         DATE,      -- SCD Type 2
    valid_to           DATE,
    is_current         BOOLEAN
);

CREATE TABLE dim_location (
    location_key INTEGER PRIMARY KEY,
    location_id  VARCHAR,         -- city id, or country code for a historical disaster
    city         VARCHAR,         -- 'Whole country' for a historical disaster
    country      VARCHAR,
    latitude     FLOAT,
    longitude    FLOAT
);

CREATE TABLE dim_date (
    date_key  INTEGER PRIMARY KEY, -- YYYYMMDD
    full_date DATE,
    day       INTEGER,
    month     INTEGER,
    year      INTEGER,
    decade    INTEGER
);

-- Grain: one event at one place
-- (one historical disaster in one country, or one asteroid striking one city)
CREATE TABLE fact_event_toll (
    event_key    INTEGER REFERENCES dim_event,
    location_key INTEGER REFERENCES dim_location,
    date_key     INTEGER REFERENCES dim_date,
    deaths       INTEGER,
    damage_usd   BIGINT,
    PRIMARY KEY (event_key, location_key)
);
