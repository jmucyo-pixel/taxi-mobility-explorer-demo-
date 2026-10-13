"""
Builds docs/technical_report.pdf (2-3 pages) from YOUR database: every number, chart and insight sentence
is computed from data/mobility.db, so the report always matches the data you actually loaded.

    python docs/build_report.py --team "Team Name" --members "Alice, Bob, Carol"

Edit the TEAM_REFLECTION text below (team challenges) before the final run.
"""
import argparse
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
import config as C
from algorithms import HashCounter, top_k

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import Image, KeepTogether, Paragraph, Preformatted, SimpleDocTemplate, Spacer

# ---- EDIT ME: the part only your team can write -----------------------------------------------------------
TEAM_REFLECTION = (
    "[TEAM: replace this sentence with 2-3 honest sentences on team challenges - e.g. how you split work, "
    "a disagreement about cleaning thresholds, time-zone/availability problems, how you resolved merge conflicts.]"
)
# -----------------------------------------------------------------------------------------------------------

FIG = Path(__file__).resolve().parent / "figures"
YELLOW, DEEP, GREY = "#f6b800", "#17445a", "#9aa7b0"
BUCKETS = ["late_night", "morning_rush", "midday", "evening_rush", "evening"]
BUCKET_LABEL = {"late_night": "Late night\n0-5", "morning_rush": "Morning rush\n6-9", "midday": "Midday\n10-15",
                "evening_rush": "Evening rush\n16-19", "evening": "Evening\n20-23"}
plt.rcParams.update({"font.size": 7.5, "axes.spines.top": False, "axes.spines.right": False, "font.family": "DejaVu Sans"})


def q(con, sql, p=()):
    return con.execute(sql, p).fetchall()


def f(v, d=1):
    return "n/a" if v is None else f"{v:,.{d}f}"


# =========================================================================== data
def gather(con):
    d = {}
    d["kept"] = q(con, "SELECT COUNT(*) FROM trip")[0][0]
    d["cleaning"] = q(con, "SELECT reason, count FROM cleaning_summary ORDER BY count DESC")
    d["excluded"] = sum(c for _, c in d["cleaning"])
    d["raw"] = d["kept"] + d["excluded"]
    d["dmin"], d["dmax"] = q(con, "SELECT MIN(pickup_date), MAX(pickup_date) FROM trip")[0]
    d["zones"] = q(con, "SELECT COUNT(*) FROM zone")[0][0]

    # unexpected observation: cash tips are never recorded
    d["pay"] = {r[0]: r[1:] for r in q(con, """SELECT p.name, COUNT(*), AVG(t.tip_amount), AVG(t.tip_amount > 0)
                                                FROM trip t JOIN payment_type p USING(payment_type_id) GROUP BY p.name""")}

    # insight 1: hourly demand and speed
    d["hourly"] = q(con, "SELECT pickup_hour, COUNT(*), AVG(speed_mph) FROM trip GROUP BY pickup_hour ORDER BY pickup_hour")

    # insight 2: airport trips
    ids = [r[0] for r in q(con, "SELECT location_id FROM zone WHERE zone_name LIKE '%Airport%'")]
    d["airport_ids"] = ids
    if ids:
        marks = ",".join("?" * len(ids))
        d["airport"] = q(con, f"""SELECT CASE WHEN t.pu_zone_id IN ({marks}) THEN t.pu_zone_id
                                              WHEN t.do_zone_id IN ({marks}) THEN t.do_zone_id ELSE 0 END AS g,
                                         COUNT(*), AVG(t.fare_amount), AVG(t.trip_distance), AVG(t.fare_per_mile), AVG(t.tip_pct)
                                  FROM trip t GROUP BY g""", ids + ids)
        d["airport_names"] = {r[0]: r[1] for r in q(con, "SELECT location_id, zone_name FROM zone")}
    else:
        d["airport"] = []

    # insight 3: weekday vs weekend by time bucket
    d["wk"] = q(con, """SELECT is_weekend, time_bucket, COUNT(*), AVG(tip_pct), AVG(trip_distance)
                        FROM trip GROUP BY is_weekend, time_bucket""")

    # algorithm benchmark on the real data
    t0 = time.perf_counter()
    hc, n = HashCounter(), 0
    for (pu,) in con.execute("SELECT pu_zone_id FROM trip"):
        hc.increment(pu)
        n += 1
    top = top_k(hc.items(), 5)
    d["algo_ms"] = (time.perf_counter() - t0) * 1000
    t0 = time.perf_counter()
    sql_top = q(con, "SELECT pu_zone_id, COUNT(*) c FROM trip GROUP BY pu_zone_id ORDER BY c DESC, pu_zone_id LIMIT 5")
    d["sql_ms"] = (time.perf_counter() - t0) * 1000
    d["algo_n"], d["algo_m"] = n, len(hc)
    d["algo_matches_sql"] = [k for k, _ in top] == [r[0] for r in sql_top]
    names = {r[0]: r[1] for r in q(con, "SELECT location_id, zone_name FROM zone")}
    d["top_names"] = [(names[k], c) for k, c in top]
    return d


# =========================================================================== figures
def fig_architecture():
    fig, ax = plt.subplots(figsize=(7.2, 1.55))
    ax.axis("off"); ax.set_xlim(0, 100); ax.set_ylim(0, 22)
    boxes = [(1, "Raw TLC files\nparquet / CSV / GeoJSON", GREY), (21, "ETL (pandas)\nclean, normalise,\nengineer features", YELLOW),
             (41, "SQLite\n7 normalized tables\n+ indexes", DEEP), (61, "Flask REST API\nfilters, aggregates,\ncustom Top-K", YELLOW),
             (81, "Dashboard\nLeaflet map, Chart.js,\ntables", GREY)]
    for x, label, c in boxes:
        ax.add_patch(plt.Rectangle((x, 5), 18, 14, fc=c, ec="none", alpha=.9))
        ax.text(x + 9, 12, label, ha="center", va="center", color="white" if c == DEEP else "#1d2a35", fontsize=6.6)
    for x in (19, 39, 59, 79):
        ax.annotate("", xy=(x + 2, 12), xytext=(x, 12), arrowprops=dict(arrowstyle="-|>", color="#1d2a35", lw=1))
    ax.annotate("", xy=(30, 2.2), xytext=(30, 5), arrowprops=dict(arrowstyle="-|>", color="#1d2a35", lw=1))
    ax.text(30, 0.2, "logs/excluded_records.csv", ha="center", va="center", fontsize=6.3)
    ax.text(89, 2.6, "HTTP / JSON", ha="center", fontsize=6.3, color="#555")
    fig.savefig(FIG / "architecture.png", dpi=220, bbox_inches="tight"); plt.close(fig)
    return 7.2, 1.55


def fig_hourly(d):
    hrs = [r[0] for r in d["hourly"]]
    fig, ax = plt.subplots(figsize=(7.2, 2.05))
    ax.bar(hrs, [r[1] for r in d["hourly"]], color=YELLOW)
    ax.set_xlabel("Pickup hour"); ax.set_ylabel("Trips"); ax.set_xticks(range(0, 24, 2))
    ax2 = ax.twinx(); ax2.spines["right"].set_visible(True)
    ax2.plot(hrs, [r[2] for r in d["hourly"]], color=DEEP, marker="o", ms=2.5, lw=1.4)
    ax2.set_ylabel("Average speed (mph)", color=DEEP); ax2.set_ylim(bottom=0)
    fig.savefig(FIG / "insight1_hourly.png", dpi=220, bbox_inches="tight"); plt.close(fig)
    return 7.2, 2.05


def fig_airport(d):
    rows = sorted(d["airport"], key=lambda r: (r[0] == 0, r[0]))
    labels = [("All other trips" if r[0] == 0 else d["airport_names"][r[0]].replace(" Airport", "")) for r in rows]
    cols = [GREY if r[0] == 0 else DEEP for r in rows]
    fig, axs = plt.subplots(1, 3, figsize=(7.2, 1.7))
    for ax, idx, title in zip(axs, (2, 4, 5), ("Average fare ($)", "Fare per mile ($)", "Average card tip (%)")):
        vals = [r[idx] or 0 for r in rows]
        ax.barh(labels, vals, color=cols); ax.set_title(title, fontsize=7.5); ax.invert_yaxis()
        for y, v in enumerate(vals):
            ax.text(v, y, f" {v:.1f}", va="center", fontsize=6.5)
        if ax is not axs[0]:
            ax.set_yticklabels([])
    fig.tight_layout(); fig.savefig(FIG / "insight2_airport.png", dpi=220, bbox_inches="tight"); plt.close(fig)
    return 7.2, 1.7


def fig_weekend(d):
    idx = {(r[0], r[1]): r for r in d["wk"]}
    fig, axs = plt.subplots(1, 2, figsize=(7.2, 1.9))
    for ax, col, title in zip(axs, (3, 4), ("Average card tip (%)", "Average trip distance (mi)")):
        x = range(len(BUCKETS)); w = .38
        ax.bar([i - w / 2 for i in x], [(idx.get((0, b)) or [0] * 5)[col] or 0 for b in BUCKETS], w, color=DEEP, label="Weekday")
        ax.bar([i + w / 2 for i in x], [(idx.get((1, b)) or [0] * 5)[col] or 0 for b in BUCKETS], w, color=YELLOW, label="Weekend")
        ax.set_xticks(list(x)); ax.set_xticklabels([BUCKET_LABEL[b] for b in BUCKETS], fontsize=6); ax.set_title(title, fontsize=7.5)
    axs[0].legend(fontsize=6.5, frameon=False)
    fig.tight_layout(); fig.savefig(FIG / "insight3_weekend.png", dpi=220, bbox_inches="tight"); plt.close(fig)
    return 7.2, 1.9


# =========================================================================== insight text (all computed)
def insight1(d):
    h = d["hourly"]; total = sum(r[1] for r in h)
    peak = max(h, key=lambda r: r[1])
    ok = [r for r in h if r[1] >= 0.01 * total and r[2] is not None]
    slow, fast = min(ok, key=lambda r: r[2]), max(ok, key=lambda r: r[2])
    drop = (1 - slow[2] / fast[2]) * 100
    rush = [r for r in h if 16 <= r[0] <= 19]; night = [r for r in h if 1 <= r[0] <= 5]
    sp = lambda rs: sum(r[1] * r[2] for r in rs) / max(1, sum(r[1] for r in rs))
    sentence = (f"Demand peaks at {peak[0]}:00 ({peak[1]:,} trips, {peak[1] / total:.1%} of all trips). Average speed is lowest at "
                f"{slow[0]}:00 ({slow[2]:.1f} mph) and highest at {fast[0]}:00 ({fast[2]:.1f} mph), a {drop:.0f}% gap. "
                f"Trip-weighted speed is {sp(rush):.1f} mph in the 16-19h window versus {sp(night):.1f} mph from 1-5h.")
    meaning = ("Because speed is distance divided by duration, a lower figure at busy hours means the same distance takes longer, "
               "which is consistent with congestion. "
               + ("The slowest hour coincides with or sits next to the demand peak, so demand and delay build together."
                  if abs(slow[0] - peak[0]) <= 2 else
                  "The slowest hour is not the demand peak, so traffic conditions are not just a function of taxi volume."))
    return sentence, meaning


def insight2(d):
    rows = {r[0]: r for r in d["airport"]}
    if not rows or 0 not in rows or len(rows) < 2:
        return "No airport zones were found in the lookup table, so this insight could not be computed.", ""
    air = [r for k, r in rows.items() if k != 0]
    n = sum(r[1] for r in air); other = rows[0]
    w = lambda i: sum(r[1] * (r[i] or 0) for r in air) / n
    fare, dist, fpm, tip = w(2), w(3), w(4), w(5)
    share = n / (n + other[1])
    sentence = (f"Airport trips are {share:.1%} of all trips but average ${fare:.2f} per fare versus ${other[2]:.2f} for other trips "
                f"({fare / other[2]:.1f}x), over {dist:.1f} mi versus {other[3]:.1f} mi. Fare per mile is ${fpm:.2f} versus ${other[4]:.2f}, "
                f"and the average card tip is {tip:.1f}% versus {other[5]:.1f}%.")
    meaning = (("Airport fares are high mainly because trips are long, not because each mile costs more" if fpm <= other[4] * 1.05 else
                "Airport fares are high because trips are long and each mile also costs more (flat fares, tolls and surcharges)") +
               "; " + ("tips are proportionally lower, which is consistent with a larger fixed fare component that riders tip less on."
                       if tip < other[5] - 0.5 else "tips are proportionally higher, so airport riders tip more generously on the larger fares."
                       if tip > other[5] + 0.5 else "tip percentages are similar, so riders tip about the same share on the larger airport fares."))
    return sentence, meaning


def insight3(d):
    idx = {(r[0], r[1]): r for r in d["wk"]}
    gaps = []
    for b in BUCKETS:
        wd, we = idx.get((0, b)), idx.get((1, b))
        if wd and we and wd[3] is not None and we[3] is not None:
            gaps.append((b, we[3] - wd[3], we[4] - wd[4], wd, we))
    if not gaps:
        return "Not enough weekday and weekend data to compare.", ""
    bt = max(gaps, key=lambda g: abs(g[1])); bd = max(gaps, key=lambda g: abs(g[2]))
    nm = lambda b: b.replace("_", " ")
    sentence = (f"The largest weekday/weekend tip gap is in the {nm(bt[0])} bucket ({bt[4][3]:.1f}% weekend vs {bt[3][3]:.1f}% weekday, "
                f"{bt[1]:+.1f} pts). The largest trip-length gap is in {nm(bd[0])} ({bd[4][4]:.1f} mi vs {bd[3][4]:.1f} mi, {bd[2]:+.1f} mi).")
    meaning = ("Weekday buckets are plausibly shaped by commuting and weekend buckets by leisure and nightlife. Differences in trip length and tipping "
               "between the same hours on different day types suggest different trip purposes, although this dataset has no rider "
               "information, so that explanation is a hypothesis rather than something the data proves.")
    return sentence, meaning


# =========================================================================== PDF
def build(team, members):
    con = sqlite3.connect(C.DB_PATH)
    d = gather(con)
    sizes = {"arch": fig_architecture(), "h": fig_hourly(d), "a": fig_airport(d) if d["airport"] else None, "w": fig_weekend(d)}

    st = lambda **k: ParagraphStyle("x", fontName=k.pop("fn", "Helvetica"), fontSize=k.pop("fs", 8.8), leading=k.pop("ld", 11), **k)
    body, h1 = st(spaceAfter=2.5), st(fn="Helvetica-Bold", fs=10.5, ld=12.5, spaceBefore=5, spaceAfter=2.5, textColor=colors.HexColor(DEEP))
    h2, small = st(fn="Helvetica-Bold", fs=8.6, ld=10.5, spaceBefore=2.5, spaceAfter=1), st(fs=7.6, ld=9, textColor=colors.HexColor("#555555"))
    title = st(fn="Helvetica-Bold", fs=15, ld=17, textColor=colors.HexColor("#1d2a35"))
    code = ParagraphStyle("c", fontName="Courier", fontSize=6.9, leading=8.1, backColor=colors.HexColor("#f1f2ee"), borderPadding=3, spaceAfter=3)

    def img(key, name):
        w, h = sizes[key]; W = 17.6 * cm
        return Image(str(FIG / name), width=W, height=W * h / w)

    cash, card = d["pay"].get("Cash"), d["pay"].get("Credit card")
    cash_share = cash[0] / d["kept"] if cash else 0
    top_reason, top_n = d["cleaning"][0]
    if top_n == 0:
        top_reason = "none"
    story = [Paragraph("NYC Taxi Mobility Explorer: Technical Report", title),
             Paragraph(f"{team}" + (f" &nbsp;|&nbsp; {members}" if members else ""), small), Spacer(1, 3)]

    # 1
    story += [Paragraph("1. Problem framing and dataset analysis", h1),
              Paragraph(f"<b>Dataset.</b> NYC TLC Yellow Taxi trip records ({d['dmin']} to {d['dmax']}): a fact table of {d['raw']:,} raw trips "
                        f"(timestamps, distance, rate code, itemised fares), a {d['zones']}-row zone lookup (borough, zone, service zone) and zone polygons "
                        f"(GeoJSON). The goal is to understand where, when and at what price people move through the city.", body),
              Paragraph(f"<b>Challenges and cleaning.</b> {d['excluded']:,} rows ({d['excluded'] / d['raw']:.1%}) were excluded and logged to "
                        f"<i>logs/excluded_records.csv</i>, each with the first rule it broke; the largest category was <i>{top_reason}</i> ({top_n:,}). "
                        f"Rules cover nulls, exact duplicates, unknown zones (264/265), dropoff not after pickup, pickups outside the dominant month, "
                        f"duration under 30 s or over 6 h, distance of 0 or over 100 mi, fares at or below $0 or over $500, negative charges, 0 or more than 6 "
                        f"passengers, and speeds above 80 mph.", body),
              Paragraph("<b>Assumptions.</b> (i) Thresholds are generous so that real but unusual trips (long airport runs, a $300 fare) stay in; they live in "
                        "<i>config.py</i>. (ii) Missing passenger count is kept as NULL rather than imputed. (iii) Unknown vendor, rate or payment codes map to "
                        "an explicit 'Unknown' row instead of being dropped. (iv) Zones 264/265 are excluded because they carry no location information.", body)]
    if cash and card:
        story.append(Paragraph(
            f"<b>Unexpected observation.</b> Cash trips ({cash_share:.1%} of trips) record an average tip of ${cash[1]:.2f} and only {cash[2]:.1%} have any tip, "
            f"versus ${card[1]:.2f} and {card[2]:.1%} for credit-card trips. Cash tips are simply not captured, so averaging tips over all trips would badly "
            f"understate generosity. This changed the design: <i>tip_pct</i> is NULL (not 0) for non-card trips and every tip chart is labelled card-only.", body))

    # 2
    story += [Paragraph("2. System architecture and design decisions", h1), img("arch", "architecture.png"),
              Paragraph("<b>Stack.</b> Python/pandas for the ETL (vectorised rules on millions of rows), SQLite for storage, Flask for the API, and plain "
                        "HTML/CSS/JS with Leaflet (choropleth) and Chart.js. SQLite needs no server, so the README is runnable with two commands, and the "
                        "workload is read-heavy with a single writer (the ETL). Flask also serves the frontend, so one process runs the whole app.", body),
              Paragraph("<b>Schema.</b> Third normal form: <i>borough, service_zone, zone, vendor, rate_code, payment_type</i> are dimensions; <i>trip</i> "
                        "is the fact table with foreign keys to all of them. Indexes: pickup time, (date, hour), (pickup zone, date), dropoff zone, distance, "
                        "fare and (weekday, hour), built after the bulk load. Exclusions are kept in <i>cleaning_summary</i> and <i>excluded_records</i>.", body),
              Paragraph("<b>Trade-offs.</b> Derived features (speed, fare per mile, tip %, time bucket) are stored in <i>trip</i> rather than computed per query: "
                        "this duplicates information and breaks strict normalisation, but makes every dashboard filter an indexed read. SQLite gives up concurrent "
                        "writers and spatial functions (PostGIS); polygons are stored as GeoJSON text and rendered client-side. Filters are applied in SQL with "
                        "parameterised queries, and sortable columns are whitelisted.", body)]

    # 3
    story += [Paragraph("3. Algorithmic logic and data structures", h1),
              Paragraph("<b>Problem.</b> Rank the K busiest pickup zones or routes for any filter combination. <b>Approach.</b> Stream rows from the database "
                        "once, count keys in a hand-written separate-chaining <b>hash table</b> (multiplicative hash, resize at load factor 0.75), then push the "
                        "counts through a hand-written size-K <b>min-heap</b> (manual sift-up/sift-down). Only keys that beat the current K-th best enter the heap, "
                        "so the heap never grows beyond K. No heapq, Counter, sorted or sort_values is used.", body),
              Preformatted("counts = HashCounter()\n"
                           "for (pu, do) in rows:                       # n rows\n"
                           "    counts.increment(pu  or  pu*1000 + do)  # O(1) expected\n"
                           "heap = MinHeap()\n"
                           "for (key, c) in counts:                     # m distinct keys\n"
                           "    if heap.size < K:   heap.push((c, key))                # O(log K)\n"
                           "    elif (c, key) beats heap.root:  heap.replace_root((c, key))\n"
                           "out = []\n"
                           "while heap not empty:  out.append(heap.pop())   # K pops, ascending\n"
                           "return reverse(out)                           # manual reverse, O(K)", code),
              Paragraph(f"<b>Complexity.</b> With n rows, m distinct keys and K results: counting O(n) expected time and O(m) space; heap pass O(m log K) time and "
                        f"O(K) space; final ordering O(K log K). Total <b>O(n + m log K) time, O(m + K) space</b>. Measured on this database: {d['algo_n']:,} rows, "
                        f"{d['algo_m']} distinct zones, {d['algo_ms']:,.0f} ms for the custom code versus {d['sql_ms']:,.0f} ms for SQL GROUP BY + ORDER BY; "
                        f"the top-5 zone ids {'match' if d['algo_matches_sql'] else 'DO NOT match'} the SQL result"
                        f"{'' if d['algo_matches_sql'] else ' (investigate before submitting)'}. SQL is faster because it runs inside the engine; the custom "
                        f"version exists to show the algorithm and is verified against built-ins in <i>test_algorithms.py</i>.", body)]

    # 4
    s1, m1 = insight1(d)
    story += [Paragraph("4. Insights and interpretation", h1),
              KeepTogether([Paragraph("Insight 1: demand rises while the city slows down", h2),
              Paragraph(f"<i>Derived from:</i> GROUP BY pickup_hour on trip counts and the engineered <i>speed_mph</i> feature (dashboard: 'Demand and speed through the day').", small),
              img("h", "insight1_hourly.png")]), Paragraph(s1, body), Paragraph(f"<b>Meaning.</b> {m1}", body)]
    s2, m2 = insight2(d)
    blk = [Paragraph("Insight 2: airport trips are expensive mainly because they are long", h2),
           Paragraph("<i>Derived from:</i> trips grouped by whether pickup or dropoff is a zone named 'Airport', using <i>fare_per_mile</i> and <i>tip_pct</i>.", small)]
    if d["airport"]:
        blk.append(img("a", "insight2_airport.png"))
    story.append(KeepTogether(blk))
    story += [Paragraph(s2, body)] + ([Paragraph(f"<b>Meaning.</b> {m2}", body)] if m2 else [])
    s3, m3 = insight3(d)
    story += [KeepTogether([Paragraph("Insight 3: weekends change how and how far people ride", h2),
              Paragraph("<i>Derived from:</i> GROUP BY is_weekend and time_bucket (dashboard: day-type filter plus the tip chart).", small),
              img("w", "insight3_weekend.png")]), Paragraph(s3, body), Paragraph(f"<b>Meaning.</b> {m3}", body)]

    # 5
    story += [Paragraph("5. Reflection and future work", h1),
              Paragraph("<b>Technical challenges.</b> Loading millions of rows with pandas needs several GB of RAM, so the pipeline works on a single "
                        "in-memory frame and offers a <i>--limit</i> flag; the zone polygons arrive in a projected coordinate system and had to be detected and "
                        "reprojected to WGS84 for Leaflet; the first cleaning pass flagged rows under several rules at once, which made the exclusion log "
                        "ambiguous until each row was assigned the first rule it broke; and Top-K tie-breaking had to be made deterministic so the custom code "
                        "matches SQL.", body),
              Paragraph(f"<b>Team challenges.</b> {TEAM_REFLECTION}", body),
              Paragraph("<b>Next steps for a real product.</b> Move to PostgreSQL with PostGIS and materialised views for pre-aggregated hourly and zone "
                        "metrics; stream the ETL in chunks and run it incrementally each month; add weather, events and traffic feeds to explain demand and speed; "
                        "cache hot API responses; add automated tests and CI; and deploy behind Gunicorn with a managed database so the dashboard is publicly "
                        "available.", body)]

    out = Path(__file__).resolve().parent / "technical_report.pdf"
    SimpleDocTemplate(str(out), pagesize=A4, leftMargin=1.7 * cm, rightMargin=1.7 * cm, topMargin=1.4 * cm, bottomMargin=1.3 * cm,
                      title="NYC Taxi Mobility Explorer - Technical Report", author=team).build(story)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--team", default="Team name")
    ap.add_argument("--members", default="")
    a = ap.parse_args()
    out = build(a.team, a.members)
    from pypdf import PdfReader
    pages = len(PdfReader(str(out)).pages)
    print(f"Wrote {out} ({pages} pages)" + ("  <- over the 3-page limit, shorten text or figures" if pages > 3 else ""))
