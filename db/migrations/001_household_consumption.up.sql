-- 001 up: hourly household electricity use per price area, from Elhub open data
-- (dataset CONSUMPTION_PER_GROUP_MBA_HOUR, consumptionGroup = 'household').
-- Used to spread a household's monthly kWh over the hours of that month.

CREATE TABLE IF NOT EXISTS household_consumption (
    price_area      TEXT             NOT NULL,
    time_start      TIMESTAMPTZ      NOT NULL,
    quantity_kwh    DOUBLE PRECISION NOT NULL CHECK (quantity_kwh >= 0),  -- all households in the area
    metering_points INTEGER          NOT NULL CHECK (metering_points > 0),
    elhub_updated   TIMESTAMPTZ      NOT NULL,  -- Elhub's lastUpdatedTime; values get corrected for ~2 weeks
    PRIMARY KEY (price_area, time_start)
);
