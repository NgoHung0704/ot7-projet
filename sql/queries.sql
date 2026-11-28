-- Demo queries Q1–Q8 of the report, on the star schema of schema.sql.
-- Run with psql, giving the parameters of Q4 and Q5:
--   psql -v asteroid_des="'101955'" -f sql/queries.sql

-- Q1. Asteroids that players misjudge most often on the number of deaths.
SELECT e.event_name AS asteroid,
       COUNT(*)                  AS rounds,
       1 - AVG(r.correct_deaths) AS deaths_error_rate
FROM fact_round r
JOIN dim_event e ON e.event_key = r.asteroid_event_key
GROUP BY e.event_name
HAVING COUNT(*) >= 100
ORDER BY deaths_error_rate DESC
LIMIT 10;

-- Q2. Types of historical disasters that players misjudge most often.
SELECT e.disaster_type,
       COUNT(*)                  AS rounds,
       1 - AVG(r.correct_deaths) AS deaths_error_rate,
       1 - AVG(r.correct_damage) AS damage_error_rate
FROM fact_round r
JOIN dim_event e ON e.event_key = r.disaster_event_key
GROUP BY e.disaster_type
ORDER BY deaths_error_rate DESC;

-- Q3. Top 10 asteroids by risk-weighted expected deaths.
SELECT e.event_name, e.diameter_m, e.impact_probability,
       AVG(f.deaths)                        AS avg_deaths,
       e.impact_probability * AVG(f.deaths) AS risk_weighted_deaths
FROM fact_event_toll f
JOIN dim_event e ON e.event_key = f.event_key
                AND e.origin = 'Simulated' AND e.is_current
GROUP BY e.event_key, e.event_name, e.diameter_m, e.impact_probability
ORDER BY risk_weighted_deaths DESC NULLS LAST
LIMIT 10;

-- Q4. Cities with the highest risk-weighted expected deaths for a given asteroid.
SELECT l.city, l.country, f.deaths,
       e.impact_probability * f.deaths AS risk_weighted_deaths
FROM fact_event_toll f
JOIN dim_event e    ON e.event_key = f.event_key
                   AND e.event_id = :asteroid_des AND e.is_current
JOIN dim_location l ON l.location_key = f.location_key
ORDER BY risk_weighted_deaths DESC NULLS LAST
LIMIT 10;

-- Q5. Historical earthquakes and storms with the same intensity class as a given asteroid.
SELECT h.event_name, h.disaster_type, h.magnitude, h.max_wind_kmh,
       f.deaths, f.damage_usd
FROM dim_event a
JOIN dim_event h ON h.origin = 'Historical'
                AND (   (h.shaking_class = a.shaking_class AND a.shaking_class <> 'Not applicable')
                     OR (h.wind_class    = a.wind_class    AND a.wind_class    <> 'Not applicable'))
JOIN fact_event_toll f ON f.event_key = h.event_key
WHERE a.event_id = :asteroid_des AND a.is_current
ORDER BY f.deaths DESC NULLS LAST;

-- Q6. Number of events per decade (histogram).
SELECT d.decade,
       e.origin,
       COUNT(DISTINCT f.event_key) AS events
FROM fact_event_toll f
JOIN dim_event e ON e.event_key = f.event_key
                AND e.is_current
JOIN dim_date d  ON d.date_key = f.date_key
GROUP BY d.decade, e.origin
ORDER BY d.decade, e.origin;

-- Q7. Error rate on deaths vs. on material damage.
SELECT COUNT(*)                  AS rounds,
       1 - AVG(r.correct_deaths) AS deaths_error_rate,
       1 - AVG(r.correct_damage) AS damage_error_rate
FROM fact_round r;

-- Q8. Accuracy per player level (the level the player had when playing).
SELECT p.level,
       COUNT(*)              AS rounds,
       AVG(r.correct_deaths) AS deaths_accuracy,
       AVG(r.correct_damage) AS damage_accuracy
FROM fact_round r
JOIN dim_player p ON p.player_key = r.player_key
GROUP BY p.level
ORDER BY deaths_accuracy;
