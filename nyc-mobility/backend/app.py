"""
Flask API + static file server for the dashboard.

    python backend/app.py        ->  http://localhost:5000
"""
import json
import os
import sqlite3
import time

from flask import Flask, jsonify, request, send_from_directory

import config as C
from algorithms import HashCounter, top_k

app = Flask(__name__, static_folder=None)

FROM = ("trip t JOIN zone z ON z.location_id = t.pu_zone_id "
        "JOIN borough b ON b.borough_id = z.borough_id")


def db():
    if not C.DB_PATH.exists():
        raise RuntimeError(f"Database not found at {C.DB_PATH}. Run: python backend/etl.py")
    con = sqlite3.connect(f"file:{C.DB_PATH}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def rows(sql, params=()):
    con = db()
    try:
        return [dict(r) for r in con.execute(sql, params).fetchall()]
    finally:
        con.close()


def num(name, cast=float):
    v = request.args.get(name)
    if v in (None, ""):
        return None
    try:
        return cast(v)
    except ValueError:
        return None


def where():
    """Builds a parameterised WHERE clause from the query string (never string-concatenates user input)."""
    c, p = [], []

    def add(cond, val):
        if val is not None:
            c.append(cond)
            p.append(val)
    a = request.args
    add("t.pickup_date >= ?", a.get("date_from") or None)
    add("t.pickup_date <= ?", a.get("date_to") or None)
    add("t.pickup_hour >= ?", num("hour_from", int))
    add("t.pickup_hour <= ?", num("hour_to", int))
    add("t.trip_distance >= ?", num("min_distance"))
    add("t.trip_distance <= ?", num("max_distance"))
    add("t.fare_amount >= ?", num("min_fare"))
    add("t.fare_amount <= ?", num("max_fare"))
    add("b.name = ?", a.get("borough") or None)
    add("t.pu_zone_id = ?", num("pu_zone", int))
    add("t.payment_type_id = ?", num("payment_type", int))
    if a.get("day_type") == "weekday":
        c.append("t.is_weekend = 0")
    elif a.get("day_type") == "weekend":
        c.append("t.is_weekend = 1")
    return ("WHERE " + " AND ".join(c)) if c else "", p


@app.after_request
def cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


@app.errorhandler(Exception)
def fail(e):
    return jsonify(error=str(e)), 500


@app.get("/api/meta")
def meta():
    r = rows("SELECT MIN(pickup_date) AS date_min, MAX(pickup_date) AS date_max, COUNT(*) AS trips FROM trip")[0]
    r["boroughs"] = [x["name"] for x in rows(
        "SELECT name FROM borough WHERE name != 'Unknown' ORDER BY name")]
    return jsonify(r)


@app.get("/api/summary")
def summary():
    w, p = where()
    r = rows(f"""SELECT COUNT(*) AS trips, AVG(fare_amount) AS avg_fare, AVG(trip_distance) AS avg_distance,
                        AVG(duration_min) AS avg_duration, AVG(speed_mph) AS avg_speed, AVG(tip_pct) AS avg_tip_pct,
                        SUM(total_amount) AS revenue
                 FROM {FROM} {w}""", p)[0]
    return jsonify(r)


@app.get("/api/hourly")
def hourly():
    w, p = where()
    return jsonify(rows(f"""SELECT t.pickup_hour AS hour, COUNT(*) AS trips, AVG(t.speed_mph) AS avg_speed,
                                   AVG(t.fare_amount) AS avg_fare, AVG(t.fare_per_mile) AS avg_fare_per_mile
                            FROM {FROM} {w} GROUP BY t.pickup_hour ORDER BY t.pickup_hour""", p))


@app.get("/api/heatmap")
def heatmap():
    w, p = where()
    return jsonify(rows(f"""SELECT t.pickup_dow AS dow, t.pickup_hour AS hour, COUNT(*) AS trips
                            FROM {FROM} {w} GROUP BY t.pickup_dow, t.pickup_hour""", p))


@app.get("/api/zones")
def zones():
    w, p = where()
    pick = rows(f"""SELECT t.pu_zone_id AS zone_id, z.zone_name AS name, b.name AS borough, COUNT(*) AS pickups,
                           AVG(t.fare_amount) AS avg_fare, AVG(t.speed_mph) AS avg_speed,
                           AVG(t.trip_distance) AS avg_distance
                    FROM {FROM} {w} GROUP BY t.pu_zone_id""", p)
    drop = {r["zone_id"]: r["dropoffs"] for r in rows(
        f"SELECT t.do_zone_id AS zone_id, COUNT(*) AS dropoffs FROM {FROM} {w} GROUP BY t.do_zone_id", p)}
    for r in pick:
        r["dropoffs"] = drop.pop(r["zone_id"], 0)
    for zid, n in drop.items():          # zones that only receive dropoffs under the current filter
        pick.append(dict(zone_id=zid, name=None, borough=None, pickups=0, dropoffs=n,
                         avg_fare=None, avg_speed=None, avg_distance=None))
    return jsonify(pick)


_geo_cache = {}


@app.get("/api/geojson")
def geojson():
    if "fc" not in _geo_cache:
        feats = []
        for r in rows("""SELECT z.location_id, z.zone_name, b.name AS borough, z.geometry
                         FROM zone z JOIN borough b ON b.borough_id = z.borough_id WHERE z.geometry IS NOT NULL"""):
            feats.append({"type": "Feature", "geometry": json.loads(r["geometry"]),
                          "properties": {"id": r["location_id"], "name": r["zone_name"], "borough": r["borough"]}})
        _geo_cache["fc"] = {"type": "FeatureCollection", "features": feats}
    return jsonify(_geo_cache["fc"])


@app.get("/api/tips")
def tips():
    w, p = where()
    w = (w + " AND " if w else "WHERE ") + "t.tip_pct IS NOT NULL"
    return jsonify(rows(f"""SELECT b.name AS borough, t.time_bucket AS bucket, AVG(t.tip_pct) AS avg_tip_pct,
                                   COUNT(*) AS trips
                            FROM {FROM} {w} GROUP BY b.name, t.time_bucket""", p))


@app.get("/api/top")
def top():
    """Top-K busiest pickup zones or routes, computed with the hand-written HashCounter + MinHeap."""
    kind = request.args.get("kind", "zone")
    k = max(1, min(num("k", int) or 10, 100))
    w, p = where()
    names = {r["location_id"]: r["zone_name"] for r in rows("SELECT location_id, zone_name FROM zone")}
    t0 = time.perf_counter()
    con = db()
    counter = HashCounter()
    n = 0
    try:
        cur = con.execute(f"SELECT t.pu_zone_id, t.do_zone_id FROM {FROM} {w}", p)
        while True:
            batch = cur.fetchmany(50_000)
            if not batch:
                break
            for pu, do in batch:
                counter.increment(pu if kind == "zone" else pu * 1000 + do)
                n += 1
    finally:
        con.close()
    result = top_k(counter.items(), k)
    out = []
    for key, count in result:
        if kind == "zone":
            out.append({"label": names.get(key, str(key)), "trips": count})
        else:
            out.append({"label": f"{names.get(key // 1000, '?')} → {names.get(key % 1000, '?')}", "trips": count})
    return jsonify({"kind": kind, "k": k, "rows_scanned": n, "distinct_keys": len(counter),
                    "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1), "results": out})


SORTS = {"pickup_ts": "t.pickup_ts", "trip_distance": "t.trip_distance", "duration_min": "t.duration_min",
         "speed_mph": "t.speed_mph", "fare_amount": "t.fare_amount", "tip_amount": "t.tip_amount",
         "total_amount": "t.total_amount", "tip_pct": "t.tip_pct", "fare_per_mile": "t.fare_per_mile"}


@app.get("/api/trips")
def trips():
    w, p = where()
    page = max(1, num("page", int) or 1)
    size = max(1, min(num("page_size", int) or 25, 100))
    col = SORTS.get(request.args.get("sort", "pickup_ts"), "t.pickup_ts")
    order = "ASC" if request.args.get("order") == "asc" else "DESC"
    total = rows(f"SELECT COUNT(*) AS n FROM {FROM} {w}", p)[0]["n"]
    data = rows(f"""SELECT t.trip_id, t.pickup_ts, z.zone_name AS pickup_zone, zd.zone_name AS dropoff_zone,
                           t.trip_distance, t.duration_min, t.speed_mph, t.fare_amount, t.tip_amount,
                           t.total_amount, t.tip_pct, t.fare_per_mile
                    FROM {FROM} JOIN zone zd ON zd.location_id = t.do_zone_id
                    {w} ORDER BY {col} {order}, t.trip_id LIMIT ? OFFSET ?""", p + [size, (page - 1) * size])
    return jsonify({"total": total, "page": page, "page_size": size, "rows": data})


@app.get("/api/cleaning")
def cleaning():
    return jsonify(rows("SELECT reason, count, description FROM cleaning_summary ORDER BY count DESC"))


@app.get("/")
def index():
    return send_from_directory(C.FRONTEND_DIR, "index.html")


@app.get("/<path:name>")
def static_files(name):
    return send_from_directory(C.FRONTEND_DIR, name)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=False)
