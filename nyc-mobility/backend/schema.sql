-- Normalized schema (3NF). Lookup tables remove repeated text from the fact table.
PRAGMA foreign_keys = ON;

CREATE TABLE borough (
    borough_id INTEGER PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE
);
CREATE TABLE service_zone (
    service_zone_id INTEGER PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE
);
CREATE TABLE zone (
    location_id     INTEGER PRIMARY KEY,
    zone_name       TEXT NOT NULL,
    borough_id      INTEGER NOT NULL REFERENCES borough(borough_id),
    service_zone_id INTEGER NOT NULL REFERENCES service_zone(service_zone_id),
    geometry        TEXT            -- GeoJSON geometry (WGS84), NULL if no polygon
);
CREATE TABLE vendor (
    vendor_id INTEGER PRIMARY KEY,
    name      TEXT NOT NULL
);
CREATE TABLE rate_code (
    rate_code_id INTEGER PRIMARY KEY,
    name         TEXT NOT NULL
);
CREATE TABLE payment_type (
    payment_type_id INTEGER PRIMARY KEY,
    name            TEXT NOT NULL
);

CREATE TABLE trip (
    trip_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    vendor_id       INTEGER NOT NULL REFERENCES vendor(vendor_id),
    pickup_ts       TEXT    NOT NULL,   -- 'YYYY-MM-DD HH:MM:SS'
    dropoff_ts      TEXT    NOT NULL,
    pu_zone_id      INTEGER NOT NULL REFERENCES zone(location_id),
    do_zone_id      INTEGER NOT NULL REFERENCES zone(location_id),
    passenger_count INTEGER,
    trip_distance   REAL    NOT NULL,
    rate_code_id    INTEGER NOT NULL REFERENCES rate_code(rate_code_id),
    payment_type_id INTEGER NOT NULL REFERENCES payment_type(payment_type_id),
    fare_amount     REAL    NOT NULL,
    extra           REAL,
    mta_tax         REAL,
    tip_amount      REAL,
    tolls_amount    REAL,
    total_amount    REAL    NOT NULL,
    -- derived / engineered features
    pickup_date     TEXT    NOT NULL,
    pickup_hour     INTEGER NOT NULL,
    pickup_dow      INTEGER NOT NULL,   -- 0 = Monday
    is_weekend      INTEGER NOT NULL,
    time_bucket     TEXT    NOT NULL,
    duration_min    REAL    NOT NULL,
    speed_mph       REAL    NOT NULL,
    fare_per_mile   REAL    NOT NULL,
    tip_pct         REAL                -- NULL unless paid by credit card
);

CREATE TABLE cleaning_summary (
    reason TEXT PRIMARY KEY,
    count  INTEGER NOT NULL,
    description TEXT
);
CREATE TABLE excluded_records (
    src_row INTEGER, reason TEXT, pickup_ts TEXT, dropoff_ts TEXT,
    pu_zone INTEGER, do_zone INTEGER, trip_distance REAL, fare_amount REAL, total_amount REAL
);
