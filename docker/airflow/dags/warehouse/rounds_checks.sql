-- The report's quality checks on game rounds. Referential: the round points to a current asteroid scenario
-- and a historical disaster with known deaths. Consistency: its correct_* flags match fact_event_toll, and it
-- asked about damage exactly when EM-DAT has a damage figure. check_name stays NULL for a valid round.
CREATE TEMPORARY TABLE checked_round ON COMMIT DROP AS
SELECT staged.*,
       asteroid.event_key AS asteroid_event_key,
       disaster.event_key AS disaster_event_key,
       location.location_key,
       CASE
           WHEN asteroid_toll.deaths IS NULL OR disaster_toll.deaths IS NULL THEN 'referential'
           WHEN staged.correct_deaths <> (staged.chose_asteroid_deaths = (asteroid_toll.deaths > disaster_toll.deaths))
             OR (staged.correct_damage IS NULL) <> (disaster_toll.damage_usd IS NULL)
             OR staged.correct_damage
                <> (staged.chose_asteroid_damage = (asteroid_toll.damage_usd > disaster_toll.damage_usd))
               THEN 'consistency'
       END AS check_name
FROM staging.stg_round AS staged
LEFT JOIN dim_event AS asteroid
       ON asteroid.event_id = staged.asteroid_des AND asteroid.is_current AND asteroid.origin = 'Simulated'
LEFT JOIN dim_event AS disaster
       ON disaster.event_id = staged.dis_no AND disaster.is_current AND disaster.origin = 'Historical'
LEFT JOIN dim_location AS location ON location.location_id = staged.geonameid::TEXT
LEFT JOIN fact_event_toll AS asteroid_toll
       ON asteroid_toll.event_key = asteroid.event_key AND asteroid_toll.location_key = location.location_key
LEFT JOIN fact_event_toll AS disaster_toll ON disaster_toll.event_key = disaster.event_key;
