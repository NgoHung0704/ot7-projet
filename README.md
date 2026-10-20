# Asteroid impacts vs. historical disasters

OT7 Data Engineering, INSA Lyon — Project 1: data architecture and dimensional model.

A web game where the player guesses which is deadlier: a real historical disaster (EM-DAT) or the simulated impact of an asteroid from NASA's Sentry risk list on a major city. The full design is in the report.

## Star schema

- `fact_event_toll`: one event at one place, either one historical disaster in one country or one asteroid striking one city. Measures: `deaths`, `damage_usd`.
- `dim_event`: name, origin (Historical or Simulated), disaster type, intensity (magnitude, wind speed and their classes), and the asteroid attributes.
- `dim_location`: city or country of the event.
- `dim_date`: calendar.

## Files

| File | Content |
|---|---|
| `sql/schema.sql` | Pseudocode SQL creating the star schema |

## Sources

- NASA/JPL Sentry API: https://ssd-api.jpl.nasa.gov/doc/sentry.html
- EM-DAT, CRED / UCLouvain: https://doc.emdat.be/
- ImpactEffect Python module: https://github.com/Daniel-Xing/impact-effects
