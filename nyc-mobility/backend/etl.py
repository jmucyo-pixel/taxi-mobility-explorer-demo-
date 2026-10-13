"""
ETL pipeline: raw TLC files -> cleaned, enriched rows in SQLite.

    python backend/etl.py                  # uses ./data
    python backend/etl.py --limit 500000   # quick dry run on the first N raw rows

Inputs (inside DATA_DIR):
    yellow_tripdata_*.parquet     fact table
    taxi_zone_lookup.csv          dimension table
    taxi_zones*.geojson / .json   zone polygons (WGS84 preferred; EPSG:2263 is auto-reprojected)
"""
import argparse
import glob
import json
import sqlite3
import sys
import time

import numpy as np
import pandas as pd

import config as C

VENDORS = {0: "Unknown", 1: "Creative Mobile Technologies", 2: "VeriFone Inc.", 6: "Myle Technologies", 7: "Helix"}
RATE_CODES = {1: "Standard rate", 2: "JFK", 3: "Newark", 4: "Nassau/Westchester",
              5: "Negotiated fare", 6: "Group ride", 99: "Unknown"}
PAYMENTS = {1: "Credit card", 2: "Cash", 3: "No charge", 4: "Dispute", 5: "Unknown", 6: "Voided trip"}

REASONS = {
    "missing_critical": "Null timestamp, zone id, distance or fare",
    "duplicate": "Exact duplicate of an earlier row (vendor, timestamps, zones, distance, fare)",
    "unknown_zone": "Pickup/dropoff zone missing from lookup or mapped to Unknown/Outside NYC (264, 265)",
    "bad_timestamp": "Dropoff is not after pickup",
    "out_of_period": "Pickup falls outside the dominant month(s) of the file",
    "duration_too_long": f"Duration above {C.MAX_DURATION_MIN} minutes",
    "duration_too_short": f"Duration under {C.MIN_DURATION_SEC} seconds",
    "bad_distance": f"Distance <= 0 or > {C.MAX_DISTANCE_MI} miles",
    "bad_fare": f"fare_amount <= 0 or > ${C.MAX_FARE}, or total_amount <= 0",
    "negative_charge": "Negative tip, tolls, extra or mta_tax",
    "bad_passengers": f"passenger_count of 0 or above {C.MAX_PASSENGERS}",
    "speed_outlier": f"Average speed above {C.MAX_SPEED_MPH} mph (physically implausible in NYC)",
}


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------- zones
def load_zones():
    path = C.DATA_DIR / "taxi_zone_lookup.csv"
    if not path.exists():
        sys.exit(f"Missing {path}")
    z = pd.read_csv(path)
    z.columns = [c.strip() for c in z.columns]
    z = z.rename(columns={"LocationID": "location_id", "Borough": "borough",
                          "Zone": "zone_name", "service_zone": "service_zone"})
    z["borough"] = z["borough"].fillna("Unknown").replace({"N/A": "Unknown"})
    z["zone_name"] = z["zone_name"].fillna("Unknown")
    z["service_zone"] = z["service_zone"].fillna("Unknown").replace({"N/A": "Unknown"})
    return z[["location_id", "borough", "zone_name", "service_zone"]]


def _walk(coords, fn):
    if coords and isinstance(coords[0], (int, float)):
        return fn(coords)
    return [_walk(c, fn) for c in coords]


def load_geometries():
    """Returns {location_id: geojson geometry dict} in WGS84, coords rounded to 5 dp."""
    files = glob.glob(str(C.DATA_DIR / "taxi_zones*.geojson")) + glob.glob(str(C.DATA_DIR / "taxi_zones*.json"))
    if not files:
        log("WARNING: no taxi_zones*.geojson found - map will have no polygons")
        return {}
    with open(files[0]) as f:
        gj = json.load(f)
    feats = gj["features"]

    def first_xy(g):
        c = g["coordinates"]
        while isinstance(c[0], list):
            c = c[0]
        return c
    projected = max(abs(v) for v in first_xy(feats[0]["geometry"])) > 180
    fn = lambda p: [round(p[0], 5), round(p[1], 5)]
    if projected:
        from pyproj import Transformer
        tr = Transformer.from_crs("EPSG:2263", "EPSG:4326", always_xy=True)
        fn = lambda p: [round(v, 5) for v in tr.transform(p[0], p[1])]
        log("GeoJSON looks projected (EPSG:2263) - reprojecting to WGS84")

    out = {}
    for ft in feats:
        props = {k.lower(): v for k, v in ft["properties"].items()}
        lid = props.get("locationid", props.get("location_id", props.get("objectid")))
        if lid is None:
            continue
        lid = int(lid)
        g = ft["geometry"]
        polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
        polys = [_walk(p, fn) for p in polys]
        if lid in out:                       # a few zones are split over several features
            out[lid].extend(polys)
        else:
            out[lid] = polys
    return {k: {"type": "MultiPolygon", "coordinates": v} for k, v in out.items()}


# ---------------------------------------------------------------- trips
NEEDED = ["VendorID", "tpep_pickup_datetime", "tpep_dropoff_datetime", "passenger_count", "trip_distance",
          "RatecodeID", "PULocationID", "DOLocationID", "payment_type", "fare_amount", "extra", "mta_tax",
          "tip_amount", "tolls_amount", "total_amount"]


def load_trips(limit=None):
    files = sorted(glob.glob(str(C.DATA_DIR / "yellow_tripdata*.parquet")))
    if not files:
        sys.exit(f"No yellow_tripdata*.parquet in {C.DATA_DIR}")
    frames = []
    for f in files:
        log(f"Reading {f}")
        frames.append(pd.read_parquet(f, columns=NEEDED))
    df = pd.concat(frames, ignore_index=True)
    if limit:
        df = df.head(limit)
    df = df.rename(columns={"VendorID": "vendor_id", "tpep_pickup_datetime": "pickup", "tpep_dropoff_datetime": "dropoff",
                            "RatecodeID": "rate_code_id", "PULocationID": "pu", "DOLocationID": "do",
                            "payment_type": "payment_type_id"})
    df["pickup"] = pd.to_datetime(df["pickup"], errors="coerce")
    df["dropoff"] = pd.to_datetime(df["dropoff"], errors="coerce")
    log(f"Loaded {len(df):,} raw rows")
    return df


def clean(df, zones):
    """Flags each row with the FIRST rule it breaks, so every exclusion has exactly one reason."""
    df = df.reset_index(drop=True)
    df["src_row"] = df.index
    df["reason"] = ""

    def flag(mask, reason):
        m = mask & (df["reason"] == "")
        df.loc[m, "reason"] = reason

    valid_zones = set(zones.loc[zones["borough"] != "Unknown", "location_id"])
    duration = (df["dropoff"] - df["pickup"]).dt.total_seconds() / 60.0
    dist = df["trip_distance"].astype(float)
    speed = dist / (duration / 60.0)
    months = df["pickup"].dt.to_period("M")
    share = months.value_counts(normalize=True)
    good_months = set(share[share >= C.MIN_MONTH_SHARE].index)

    flag(df[["pickup", "dropoff", "pu", "do", "trip_distance", "fare_amount", "total_amount"]].isna().any(axis=1),
         "missing_critical")
    dup_cols = ["vendor_id", "pickup", "dropoff", "pu", "do", "trip_distance", "fare_amount"]
    flag(df.duplicated(subset=dup_cols, keep="first"), "duplicate")
    flag(~df["pu"].isin(valid_zones) | ~df["do"].isin(valid_zones), "unknown_zone")
    flag(duration <= 0, "bad_timestamp")
    flag(~months.isin(good_months), "out_of_period")
    flag(duration > C.MAX_DURATION_MIN, "duration_too_long")
    flag(duration * 60 < C.MIN_DURATION_SEC, "duration_too_short")
    flag((dist <= 0) | (dist > C.MAX_DISTANCE_MI), "bad_distance")
    flag((df["fare_amount"] <= 0) | (df["fare_amount"] > C.MAX_FARE) | (df["total_amount"] <= 0), "bad_fare")
    flag((df[["tip_amount", "tolls_amount", "extra", "mta_tax"]].fillna(0) < 0).any(axis=1), "negative_charge")
    pc = df["passenger_count"]
    flag((pc == 0) | (pc > C.MAX_PASSENGERS), "bad_passengers")
    flag(speed > C.MAX_SPEED_MPH, "speed_outlier")

    bad = df[df["reason"] != ""].copy()
    good = df[df["reason"] == ""].copy()
    log(f"Kept {len(good):,} rows, excluded {len(bad):,} ({len(bad) / max(len(df), 1):.2%})")
    return good, bad


def normalise_and_engineer(g):
    g = g.copy()
    # categorical normalisation: unknown codes -> explicit 'Unknown' members of the lookup tables
    g["vendor_id"] = g["vendor_id"].fillna(0).astype(int)
    g.loc[~g["vendor_id"].isin(VENDORS), "vendor_id"] = 0
    g["rate_code_id"] = g["rate_code_id"].fillna(99).astype(int)
    g.loc[~g["rate_code_id"].isin(RATE_CODES), "rate_code_id"] = 99
    g["payment_type_id"] = g["payment_type_id"].fillna(5).astype(int)
    g.loc[~g["payment_type_id"].isin(PAYMENTS), "payment_type_id"] = 5
    g["passenger_count"] = g["passenger_count"].astype("Int64")  # keep NULLs (not imputed)
    for c in ["extra", "mta_tax", "tip_amount", "tolls_amount"]:
        g[c] = g[c].fillna(0.0).astype(float).round(2)
    for c in ["fare_amount", "total_amount", "trip_distance"]:
        g[c] = g[c].astype(float).round(2)
    g["pu"] = g["pu"].astype(int)
    g["do"] = g["do"].astype(int)

    # ---- feature engineering
    dur = (g["dropoff"] - g["pickup"]).dt.total_seconds() / 60.0
    g["duration_min"] = dur.round(2)
    g["speed_mph"] = (g["trip_distance"] / (dur / 60.0)).round(2)                 # 1) congestion proxy
    g["fare_per_mile"] = (g["fare_amount"] / g["trip_distance"]).round(2)          # 2) pricing efficiency
    credit = (g["payment_type_id"] == 1) & (g["fare_amount"] > 0)
    g["tip_pct"] = np.where(credit, (g["tip_amount"] / g["fare_amount"] * 100).round(2), np.nan)  # 3) generosity
    h = g["pickup"].dt.hour
    g["pickup_hour"] = h
    g["pickup_dow"] = g["pickup"].dt.dayofweek
    g["is_weekend"] = (g["pickup_dow"] >= 5).astype(int)                           # 4) temporal context
    g["time_bucket"] = np.select(
        [h.between(6, 9), h.between(10, 15), h.between(16, 19), h.between(20, 23)],
        ["morning_rush", "midday", "evening_rush", "evening"], default="late_night")
    g["pickup_date"] = g["pickup"].dt.strftime("%Y-%m-%d")
    g["pickup_ts"] = g["pickup"].dt.strftime("%Y-%m-%d %H:%M:%S")
    g["dropoff_ts"] = g["dropoff"].dt.strftime("%Y-%m-%d %H:%M:%S")
    return g


# ---------------------------------------------------------------- load
TRIP_COLS = ["vendor_id", "pickup_ts", "dropoff_ts", "pu", "do", "passenger_count", "trip_distance", "rate_code_id",
             "payment_type_id", "fare_amount", "extra", "mta_tax", "tip_amount", "tolls_amount", "total_amount",
             "pickup_date", "pickup_hour", "pickup_dow", "is_weekend", "time_bucket", "duration_min", "speed_mph",
             "fare_per_mile", "tip_pct"]


def build_db(zones, geoms, good, bad):
    if C.DB_PATH.exists():
        C.DB_PATH.unlink()
    con = sqlite3.connect(C.DB_PATH)
    con.executescript((C.ROOT / "backend" / "schema.sql").read_text())

    boroughs = sorted(zones["borough"].unique())
    bmap = {b: i + 1 for i, b in enumerate(boroughs)}
    services = sorted(zones["service_zone"].unique())
    smap = {s: i + 1 for i, s in enumerate(services)}
    con.executemany("INSERT INTO borough VALUES (?,?)", [(i, b) for b, i in bmap.items()])
    con.executemany("INSERT INTO service_zone VALUES (?,?)", [(i, s) for s, i in smap.items()])
    con.executemany("INSERT INTO vendor VALUES (?,?)", VENDORS.items())
    con.executemany("INSERT INTO rate_code VALUES (?,?)", RATE_CODES.items())
    con.executemany("INSERT INTO payment_type VALUES (?,?)", PAYMENTS.items())
    con.executemany("INSERT INTO zone VALUES (?,?,?,?,?)", [
        (int(r.location_id), r.zone_name, bmap[r.borough], smap[r.service_zone],
         json.dumps(geoms[int(r.location_id)], separators=(",", ":")) if int(r.location_id) in geoms else None)
        for r in zones.itertuples()])

    out = good[TRIP_COLS].copy()
    out = out.rename(columns={"pu": "pu_zone_id", "do": "do_zone_id"})
    out["passenger_count"] = out["passenger_count"].astype(object).where(out["passenger_count"].notna(), None)
    log(f"Inserting {len(out):,} trips ...")
    out.to_sql("trip", con, if_exists="append", index=False, chunksize=100_000)

    counts = bad["reason"].value_counts()
    con.executemany("INSERT INTO cleaning_summary VALUES (?,?,?)",
                    [(r, int(counts.get(r, 0)), d) for r, d in REASONS.items()])
    ex = bad[["src_row", "reason", "pickup", "dropoff", "pu", "do", "trip_distance", "fare_amount", "total_amount"]].copy()
    ex.columns = ["src_row", "reason", "pickup_ts", "dropoff_ts", "pu_zone", "do_zone",
                  "trip_distance", "fare_amount", "total_amount"]
    C.LOG_DIR.mkdir(exist_ok=True)
    ex.to_csv(C.LOG_DIR / "excluded_records.csv", index=False)           # full transparency log
    per = max(1, C.DB_EXCLUDED_SAMPLE // len(REASONS))
    ex.groupby("reason", group_keys=False).head(per) \
      .astype({"pickup_ts": str, "dropoff_ts": str}).to_sql("excluded_records", con, if_exists="append", index=False)
    con.commit()
    log("Creating indexes ...")
    con.executescript((C.ROOT / "backend" / "indexes.sql").read_text())
    con.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="only process the first N raw rows")
    args = ap.parse_args()
    t0 = time.time()
    zones = load_zones()
    geoms = load_geometries()
    raw = load_trips(args.limit)
    good, bad = clean(raw, zones)
    del raw
    good = normalise_and_engineer(good)
    build_db(zones, geoms, good, bad)
    log("Exclusion summary:")
    for r, n in bad["reason"].value_counts().items():
        print(f"    {r:<20}{n:>10,}")
    log(f"Done in {time.time() - t0:.0f}s -> {C.DB_PATH}")


if __name__ == "__main__":
    main()
