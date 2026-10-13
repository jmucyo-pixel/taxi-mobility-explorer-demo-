-- Created AFTER the bulk load (much faster than indexing while inserting).
CREATE INDEX idx_trip_pickup_ts   ON trip(pickup_ts);
CREATE INDEX idx_trip_date_hour   ON trip(pickup_date, pickup_hour);
CREATE INDEX idx_trip_pu_date     ON trip(pu_zone_id, pickup_date);
CREATE INDEX idx_trip_do          ON trip(do_zone_id);
CREATE INDEX idx_trip_distance    ON trip(trip_distance);
CREATE INDEX idx_trip_fare        ON trip(fare_amount);
CREATE INDEX idx_trip_dow_hour    ON trip(pickup_dow, pickup_hour);
CREATE INDEX idx_zone_borough     ON zone(borough_id);
ANALYZE;
