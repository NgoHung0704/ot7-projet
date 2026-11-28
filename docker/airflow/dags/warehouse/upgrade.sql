-- Databases created before the star schema was executable hold the empty tables of its pseudocode version,
-- which the database service ran at its first start. schema.sql's CREATE TABLE IF NOT EXISTS would keep them,
-- so drop them first; refuse if any holds rows, since nothing ever loaded them.
DO $$
DECLARE
    star_table TEXT;
    has_rows   BOOLEAN;
BEGIN
    IF EXISTS (SELECT FROM information_schema.columns
               WHERE table_schema = 'public' AND table_name = 'dim_event'
                 AND column_name = 'event_key' AND is_identity = 'NO') THEN
        FOREACH star_table IN ARRAY ARRAY['fact_round', 'fact_event_toll', 'dim_player', 'dim_event',
                                          'dim_location', 'dim_date'] LOOP
            CONTINUE WHEN to_regclass('public.' || star_table) IS NULL;
            EXECUTE format('SELECT EXISTS (SELECT FROM public.%I)', star_table) INTO has_rows;
            IF has_rows THEN
                RAISE EXCEPTION 'the pseudocode star schema table % holds rows: check it, then drop it by hand',
                    star_table;
            END IF;
        END LOOP;
        DROP TABLE IF EXISTS fact_round, fact_event_toll, dim_player, dim_event, dim_location, dim_date;
    END IF;
END $$;
