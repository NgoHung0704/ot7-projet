-- Natural-keyed simulation outputs let #10 load dimensions and facts without coupling physics to surrogate keys.
CREATE SCHEMA IF NOT EXISTS simulation;

CREATE TABLE IF NOT EXISTS simulation.event_toll (
    des TEXT NOT NULL,
    geonameid BIGINT NOT NULL,
    impact_date DATE NOT NULL,
    origin TEXT NOT NULL CHECK (origin = 'Simulated'),
    deaths BIGINT NOT NULL CHECK (deaths >= 0),
    damage_usd BIGINT NOT NULL CHECK (damage_usd >= 0),
    magnitude DOUBLE PRECISION,
    peak_wind_kmh DOUBLE PRECISION NOT NULL CHECK (peak_wind_kmh >= 0),
    shaking_class TEXT NOT NULL,
    wind_class TEXT NOT NULL,
    energy_mt DOUBLE PRECISION NOT NULL,
    burst_altitude_m DOUBLE PRECISION NOT NULL,
    exposed_population DOUBLE PRECISION NOT NULL CHECK (exposed_population >= 0),
    disc_radius_km DOUBLE PRECISION NOT NULL,
    model_version TEXT NOT NULL,
    built_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (des, geonameid),
    CHECK (deaths <= exposed_population)
);

CREATE TABLE IF NOT EXISTS simulation.historical_intensity (
    dis_no TEXT PRIMARY KEY,
    magnitude DOUBLE PRECISION,
    max_wind_kmh DOUBLE PRECISION,
    shaking_class TEXT NOT NULL,
    wind_class TEXT NOT NULL,
    built_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
