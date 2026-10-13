# NYC Taxi Mobility Explorer

Full-stack analytics app for the NYC TLC Yellow Taxi dataset: a Python ETL pipeline cleans the raw data, loads it into a normalized SQLite database, a Flask API serves it, and a browser dashboard (HTML/CSS/JS, Leaflet, Chart.js) lets you explore urban mobility patterns.

**Video walkthrough:** <PASTE YOUR VIDEO LINK HERE>
**Team participation sheet:** <PASTE LINK HERE>

## Quick start

Requirements: Python 3.10+ and an internet connection in the browser (the dashboard loads Leaflet, Chart.js, map tiles and fonts from CDNs). No database server needed; SQLite ships with Python.

```bash
# 1. Install
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 2. Put the three TLC files in ./data  (exact names shown; month in the parquet name can differ)
#    data/yellow_tripdata_2019-01.parquet
#    data/taxi_zone_lookup.csv
#    data/taxi_zones.geojson          <- GeoJSON version of taxi_zones (see note below)

# 3. Clean + enrich + load the database  (a few minutes for ~7M rows; needs ~4 GB RAM)
python backend/etl.py
#    optional quick run on a subset:  python backend/etl.py --limit 500000

# 4. Start backend + frontend (one process)
python backend/app.py
#    open http://localhost:5000
```

Backend and frontend are served together by Flask, so there is nothing separate to launch. To run the frontend elsewhere, serve `frontend/` with any static server and open it with `?api=http://localhost:5000` (CORS is enabled).

**About `taxi_zones`:** the dashboard needs polygons as GeoJSON named `taxi_zones*.geojson` (or `.json`) in `data/`, with a `LocationID` property. If you only have the TLC shapefile, convert it once (QGIS "Export > Save Features As > GeoJSON", or `ogr2ogr -f GeoJSON data/taxi_zones.geojson taxi_zones.shp`). GeoJSON in the original EPSG:2263 projection is detected and reprojected to WGS84 automatically.

Multiple months work too: drop several `yellow_tripdata_*.parquet` files in `data/`.

## Project structure

```
docs/                  build_report.py, VIDEO_SCRIPT.md, TEAM_SHEET_CONTENT.md
backend/
  export_dump.py       database dump for submission
  config.py            paths and cleaning thresholds (env-overridable)
  etl.py               ingest -> clean -> normalise -> feature engineering -> load
  schema.sql           normalized schema (also the "database schema file" deliverable)
  indexes.sql          indexes, created after bulk load
  algorithms.py        hand-written HashCounter + MinHeap + top_k (no built-ins)
  test_algorithms.py   verifies the algorithms against Python built-ins
  app.py               Flask REST API + static file server
frontend/              index.html, style.css, app.js
data/                  raw inputs + mobility.db (generated, git-ignored)
logs/                  excluded_records.csv (generated)
```

## Data pipeline

1. **Integration:** trips are joined to `taxi_zone_lookup.csv` (borough, zone, service zone) and `taxi_zones` polygons by `LocationID`. Lookup tables are created for vendor, rate code and payment type.
2. **Cleaning:** each row is tagged with the *first* rule it violates, so every exclusion has exactly one reason:

| Reason | Rule |
|---|---|
| missing_critical | null timestamp, zone, distance, fare or total |
| duplicate | same vendor, timestamps, zones, distance and fare as an earlier row |
| unknown_zone | zone not in lookup, or Unknown/Outside NYC (264, 265) |
| bad_timestamp | dropoff not after pickup |
| out_of_period | pickup outside the month(s) holding >= 5% of rows |
| duration_too_long / too_short | > 6 h / < 30 s |
| bad_distance | <= 0 or > 100 miles |
| bad_fare | fare <= 0 or > $500, or total <= 0 |
| negative_charge | negative tip, tolls, extra or MTA tax |
| bad_passengers | 0 or > 6 passengers (nulls are kept as NULL, not imputed) |
| speed_outlier | > 80 mph |

3. **Normalisation:** timestamps become `YYYY-MM-DD HH:MM:SS`; money rounded to cents; unknown vendor/rate/payment codes map to explicit "Unknown" members of their lookup tables.
4. **Transparency log:** every excluded row goes to `logs/excluded_records.csv`; per-reason counts go to table `cleaning_summary`, and a sample of rows to `excluded_records`. Counts are also shown in the dashboard sidebar.

### Engineered features

| Feature | Formula | Why it matters |
|---|---|---|
| `speed_mph` | distance / duration | congestion proxy by hour and zone; also the best outlier detector |
| `fare_per_mile` | fare_amount / distance | pricing efficiency; exposes short-trip minimums and airport flat fares |
| `tip_pct` | tip / fare x 100, card payments only | generosity by place and time (cash tips are never recorded, so cash is NULL, not 0) |
| `time_bucket`, `is_weekend`, `pickup_hour`, `pickup_dow` | from pickup timestamp | temporal context for rush-hour and weekend analysis |

## Database design

Normalized to 3NF: `borough`, `service_zone`, `zone` (with GeoJSON geometry), `vendor`, `rate_code`, `payment_type` are dimensions; `trip` is the fact table with foreign keys to all of them. Indexes: `pickup_ts`, `(pickup_date, pickup_hour)`, `(pu_zone_id, pickup_date)`, `do_zone_id`, `trip_distance`, `fare_amount`, `(pickup_dow, pickup_hour)`. Indexes are built after the bulk insert, which is much faster. To export the dump deliverable: `python backend/export_dump.py` (schema, lookup tables and 1,000 sample trips; add `--full` for every row).

## Custom algorithm (Top-K busiest zones / routes)

`backend/algorithms.py` implements, without `heapq`, `Counter`, `sorted` or pandas:

* **HashCounter:** separate-chaining hash table with multiplicative hashing and automatic resizing at load factor 0.75.
* **MinHeap:** array-based binary heap with manual `sift_up` / `sift_down`.
* **top_k:** keeps a size-K min-heap; a key replaces the root only if it beats the current K-th best. The K survivors are popped and manually reversed into descending order.

```
counts = HashCounter()
for each (pickup, dropoff) row streamed from the DB:
    counts.increment(key)                    # key = zone, or pickup*1000+dropoff
heap = MinHeap()
for (key, c) in counts:
    if heap.size < K:            heap.push((c, key))
    elif (c, key) beats heap.root: heap.replace_root((c, key))
pop heap into array (ascending) -> read it backwards -> top K
```

Time O(n + m log K), space O(m + K), with n rows scanned, m distinct keys, K results. Trade-off: SQL `GROUP BY ... ORDER BY` would be faster, but the assignment requires a manual algorithm; the endpoint reports rows scanned and elapsed ms so you can discuss this in the report. Run `python backend/test_algorithms.py` to verify correctness.

## API

All endpoints accept the same filters: `date_from`, `date_to`, `hour_from`, `hour_to`, `day_type` (weekday/weekend), `borough`, `pu_zone`, `payment_type`, `min_distance`, `max_distance`, `min_fare`, `max_fare`.

| Endpoint | Returns |
|---|---|
| `GET /api/meta` | date range, trip count, boroughs |
| `GET /api/summary` | trips, avg fare/distance/duration/speed/tip %, revenue |
| `GET /api/hourly` | trips, speed, fare per hour of day |
| `GET /api/heatmap` | trips by day-of-week x hour |
| `GET /api/zones` | per-zone pickups, dropoffs, avg fare, avg speed |
| `GET /api/geojson` | zone polygons |
| `GET /api/tips` | avg tip % by borough x time bucket |
| `GET /api/top?kind=zone\|route&k=10` | Top-K via the custom algorithm |
| `GET /api/trips?sort=&order=&page=&page_size=` | paginated, sortable trip rows |
| `GET /api/cleaning` | exclusion counts per rule |

All SQL is parameterised; sort columns are whitelisted.

## Dashboard

Filters (date, hour, weekday/weekend, borough, distance, fare) drive every panel: KPI strip, a zone choropleth switchable between pickups, dropoffs, average fare and average speed, hourly demand against speed, tipping by time of day and borough, a weekly demand heatmap, Top-K zones/routes, and a sortable, paginated trip explorer. Clicking a zone on the map filters everything to pickups from that zone.

## Submission extras (in `docs/`)

* `python docs/build_report.py --team "Name" --members "A, B, C"` builds `docs/technical_report.pdf` (2-3 pages) from your database: figures, numbers and insight text are computed from your data. Run it after the ETL, edit `TEAM_REFLECTION` in the script first, then read the insight text and adjust anything that does not match what you see in the dashboard.
* `docs/VIDEO_SCRIPT.md`: timed script and shot list for the 5-minute walkthrough.
* `docs/TEAM_SHEET_CONTENT.md`: content for the team participation sheet.

## Configuration (optional environment variables)

`DATA_DIR`, `LOG_DIR`, `DB_PATH`, `PORT`. Thresholds are in `backend/config.py`.

## Troubleshooting

* *"Database not found"*: run `python backend/etl.py` first.
* *Empty map*: `data/taxi_zones*.geojson` was missing when the ETL ran; add it and re-run the ETL.
* *Out of memory in the ETL*: use `--limit 1000000`, or run on a machine with more RAM.
* *Blank charts/map offline*: the dashboard fetches libraries and tiles from CDNs.
