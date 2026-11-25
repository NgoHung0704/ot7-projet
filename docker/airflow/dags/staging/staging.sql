-- Staging schema of the warehouse: clean, typed copies of the latest raw batches.
-- Rebuilt by the staging DAG; safe to run again (IF NOT EXISTS).

CREATE SCHEMA IF NOT EXISTS staging;

CREATE TABLE IF NOT EXISTS staging.stg_asteroid (
    des                 TEXT PRIMARY KEY,
    fullname            TEXT,
    diameter_m          DOUBLE PRECISION NOT NULL,
    mass_kg             DOUBLE PRECISION NOT NULL,
    entry_speed_kms     DOUBLE PRECISION NOT NULL,  -- Sentry v_imp, never v_inf
    energy_mt           DOUBLE PRECISION,
    impact_probability  DOUBLE PRECISION,
    impact_date         DATE NOT NULL,              -- virtual impact with the highest probability
    n_impacts           INTEGER,
    last_obs            DATE
);

CREATE TABLE IF NOT EXISTS staging.stg_asteroid_removed (
    des         TEXT PRIMARY KEY,
    removed_at  TIMESTAMP
);

CREATE TABLE IF NOT EXISTS staging.stg_disaster (
    dis_no               TEXT PRIMARY KEY,
    event_name           TEXT,
    disaster_group       TEXT,
    disaster_subgroup    TEXT,
    disaster_type        TEXT,
    disaster_subtype     TEXT,
    iso3                 TEXT,  -- kept even for countries that no longer exist (SUN, YUG, ...)
    country              TEXT,
    subregion            TEXT,
    region               TEXT,
    start_date           DATE NOT NULL,
    date_precision       TEXT NOT NULL CHECK (date_precision IN ('day', 'month', 'year')),
    deaths               BIGINT,  -- NULL when EM-DAT has no figure, never 0
    damage_usd           BIGINT,  -- EM-DAT thousands of US$ x 1000
    damage_adjusted_usd  BIGINT,
    magnitude            DOUBLE PRECISION,
    magnitude_scale      TEXT,
    latitude             DOUBLE PRECISION,
    longitude            DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS staging.stg_city (
    geonameid                   BIGINT PRIMARY KEY,
    name                        TEXT NOT NULL,
    ascii_name                  TEXT,
    country_iso2                TEXT,
    country_iso3                TEXT,
    country_name                TEXT,
    continent                   TEXT,
    latitude                    DOUBLE PRECISION NOT NULL,
    longitude                   DOUBLE PRECISION NOT NULL,
    population                  BIGINT,
    is_capital                  BOOLEAN NOT NULL,
    admin1_code                 TEXT,
    admin1_name                 TEXT,
    gem_level                   TEXT NOT NULL CHECK (gem_level IN ('region', 'country')),
    gem_id_1                    TEXT,
    occupants                   DOUBLE PRECISION,  -- GEM region totals, NULL when gem_level = 'country'
    buildings                   DOUBLE PRECISION,
    repl_cost_usd               DOUBLE PRECISION,
    repl_cost_per_occupant_usd  DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS staging.quarantine (
    id           BIGSERIAL PRIMARY KEY,
    source       TEXT NOT NULL,
    natural_key  TEXT,
    check_name   TEXT NOT NULL,
    reason       TEXT,
    raw_payload  JSONB,
    run_id       TEXT,
    rejected_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Raw load_id each task used for its last build: an unchanged input means nothing to rebuild.
CREATE TABLE IF NOT EXISTS staging.build_log (
    task        TEXT NOT NULL,
    collection  TEXT NOT NULL,
    load_id     TEXT NOT NULL,
    built_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (task, collection)
);
