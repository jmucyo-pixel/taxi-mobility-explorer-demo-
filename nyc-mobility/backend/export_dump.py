"""
Export the database for submission (works on Windows too, no sqlite3 CLI needed).

    python backend/export_dump.py              # schema + lookup tables + 1,000 sample trips -> docs/mobility_dump.sql
    python backend/export_dump.py --full       # every row (can be several GB for a full month)
"""
import argparse
import sqlite3

import config as C

ap = argparse.ArgumentParser()
ap.add_argument("--full", action="store_true")
ap.add_argument("--sample", type=int, default=1000)
a = ap.parse_args()

con = sqlite3.connect(C.DB_PATH)
out = C.ROOT / "docs" / "mobility_dump.sql"
with open(out, "w", encoding="utf-8") as f:
    for line in con.iterdump():
        if line.startswith('INSERT INTO "trip"') and not a.full:
            continue            # trips are added below as a sample
        f.write(line + "\n")
    if not a.full:
        cols = [r[1] for r in con.execute("PRAGMA table_info(trip)")]
        f.write(f"-- sample of {a.sample} trips (use --full for everything)\n")
        for row in con.execute(f"SELECT * FROM trip ORDER BY trip_id LIMIT {int(a.sample)}"):
            vals = ",".join("NULL" if v is None else repr(v) for v in row)
            f.write(f'INSERT INTO "trip" ({",".join(cols)}) VALUES ({vals});\n')
print(f"Wrote {out}")
