-- Databases created before the star schema was executable hold the empty tables of its pseudocode version,
-- which the database service ran at its first start. schema.sql's CREATE TABLE IF NOT EXISTS would keep them,
-- so drop them first; refuse if they hold rows, since nothing ever loaded them.
DO $$
BEGIN
    IF EXISTS (SELECT FROM information_schema.columns
               WHERE table_schema = 'public' AND table_name = 'dim_event'
                 AND column_name = 'event_key' AND is_identity = 'NO') THEN
        IF EXISTS (SELECT FROM dim_event) OR EXISTS (SELECT FROM dim_location)
           OR EXISTS (SELECT FROM dim_date) OR EXISTS (SELECT FROM fact_event_toll) THEN
            RAISE EXCEPTION 'the pseudocode star schema tables hold rows: check them, then drop them by hand';
        END IF;
        DROP TABLE IF EXISTS fact_round, fact_event_toll, dim_player, dim_event, dim_location, dim_date;
    END IF;
END $$;
