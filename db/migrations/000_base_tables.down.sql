-- 000 down: deliberately refuses. These tables hold four years of production data that
-- can't all be fetched again quickly, so dropping them should never be one command away.
-- To reset a LOCAL database, use: docker compose down -v

DO $$
BEGIN
    RAISE EXCEPTION 'Refusing to drop the base tables (prices, weather, forecasts). For a local reset use: docker compose down -v';
END $$;
