-- Star schema of the report: the consequences of every event (fact_event_toll) and every round played
-- in the game (fact_round), on shared dimensions. The load_warehouse and load_rounds DAGs run this file
-- before each load, so every statement must be safe to run again. Run alone: psql -v ON_ERROR_STOP=1 -f sql/schema.sql

-- SCD Type 2 on the attributes that drive a simulated toll (diameter, mass, entry speed and the
-- intensity computed from them): existing scenarios stay linked to the values used to compute them.
-- Type 1 on the other attributes.
CREATE TABLE IF NOT EXISTS dim_event (
    event_key          INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id           VARCHAR(20)  NOT NULL,  -- EM-DAT DisNo. or Sentry designation (des)
    event_name         VARCHAR(200) NOT NULL,
    origin             VARCHAR(10)  NOT NULL CHECK (origin IN ('Historical', 'Simulated')),
    disaster_type      VARCHAR(40)  NOT NULL,  -- EM-DAT's longest type has 32 characters
    magnitude          FLOAT,
    max_wind_kmh       FLOAT,
    shaking_class      VARCHAR(20)  NOT NULL,
    wind_class         VARCHAR(20)  NOT NULL,
    diameter_m         FLOAT,
    mass_kg            FLOAT,
    entry_speed_kms    FLOAT,
    impact_probability FLOAT,
    valid_from         DATE    NOT NULL,
    valid_to           DATE    NOT NULL DEFAULT '9999-12-31',
    is_current         BOOLEAN NOT NULL DEFAULT true
);
CREATE UNIQUE INDEX IF NOT EXISTS dim_event_current ON dim_event (event_id) WHERE is_current;

-- Type 1: names, coordinates and countries are only ever corrected.
CREATE TABLE IF NOT EXISTS dim_location (
    location_key INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    location_id  VARCHAR(12)  NOT NULL UNIQUE,  -- GeoNames id of a city, or ISO 3166 alpha-3 code of a country
    city         VARCHAR(100) NOT NULL,         -- 'Whole country' for a historical disaster
    country      VARCHAR(60),
    latitude     FLOAT,
    longitude    FLOAT
);

CREATE TABLE IF NOT EXISTS dim_date (
    date_key  INTEGER PRIMARY KEY,  -- YYYYMMDD
    full_date DATE     NOT NULL UNIQUE,
    day       SMALLINT NOT NULL,
    month     SMALLINT NOT NULL,
    year      SMALLINT NOT NULL,
    decade    SMALLINT GENERATED ALWAYS AS (year / 10 * 10) STORED
);

-- SCD Type 2 on level, Type 1 on country: accuracy is analysed with the level the player had when playing.
CREATE TABLE IF NOT EXISTS dim_player (
    player_key  INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    player_id   VARCHAR(36) NOT NULL,
    country     VARCHAR(60),
    level       VARCHAR(12) NOT NULL CHECK (level IN ('beginner', 'intermediate', 'expert')),
    signup_date DATE    NOT NULL,
    valid_from  DATE    NOT NULL,
    valid_to    DATE    NOT NULL DEFAULT '9999-12-31',
    is_current  BOOLEAN NOT NULL DEFAULT true,
    UNIQUE (player_id, valid_from)
);
CREATE UNIQUE INDEX IF NOT EXISTS dim_player_current ON dim_player (player_id) WHERE is_current;

-- Grain: one event at one place, either one historical disaster in one country (one EM-DAT record),
-- or one Sentry asteroid striking one city. Simulated tolls are alternative scenarios: aggregate them
-- with AVG or MAX, never SUM.
CREATE TABLE IF NOT EXISTS fact_event_toll (
    event_key    INTEGER NOT NULL REFERENCES dim_event,
    location_key INTEGER NOT NULL REFERENCES dim_location,
    date_key     INTEGER NOT NULL REFERENCES dim_date,
    deaths       INTEGER,  -- NULL when EM-DAT has no figure
    damage_usd   BIGINT,   -- NULL when EM-DAT has no figure
    PRIMARY KEY (event_key, location_key)
);

-- Grain: one round played. The answers' correctness is fixed when the round is played, so a later
-- correction in EM-DAT or Sentry does not change the rounds already played.
CREATE TABLE IF NOT EXISTS fact_round (
    round_id              BIGINT   PRIMARY KEY,  -- degenerate dimension
    player_key            INTEGER  NOT NULL REFERENCES dim_player,
    date_key              INTEGER  NOT NULL REFERENCES dim_date,
    asteroid_event_key    INTEGER  NOT NULL REFERENCES dim_event,
    disaster_event_key    INTEGER  NOT NULL REFERENCES dim_event,
    location_key          INTEGER  NOT NULL REFERENCES dim_location,
    chose_asteroid_deaths SMALLINT NOT NULL CHECK (chose_asteroid_deaths IN (0, 1)),
    correct_deaths        SMALLINT NOT NULL CHECK (correct_deaths IN (0, 1)),
    chose_asteroid_damage SMALLINT CHECK (chose_asteroid_damage IN (0, 1)),  -- NULL when damage was not asked
    correct_damage        SMALLINT CHECK (correct_damage IN (0, 1)),
    response_time_s       FLOAT    NOT NULL CHECK (response_time_s > 0)
);
