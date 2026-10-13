# 5-minute video walkthrough: script and shot list

Record the screen with a voice-over (Zoom/Meet/OBS). Rehearse once with a timer; aim for 4:45.
Have the dashboard open on the full dataset, a terminal ready, and `backend/algorithms.py` and `backend/schema.sql` open in your editor.

| Time | Show | Say (adapt to your own words) |
|---|---|---|
| 0:00-0:25 | Title slide or the dashboard top | Who we are, the dataset (NYC TLC Yellow Taxi, month, row count), and the question: how does the city move through time and space? |
| 0:25-1:10 | `docs/technical_report.pdf` architecture figure, then the folder tree | Raw parquet/CSV/GeoJSON -> pandas ETL -> normalized SQLite -> Flask API -> Leaflet/Chart.js dashboard. Why SQLite and Flask (zero setup, read-heavy, one-command run). |
| 1:10-2:00 | Terminal: `python backend/etl.py` output (pre-recorded run is fine); `logs/excluded_records.csv` | Cleaning rules, the exclusion count and top reason, the log of removed rows, and the four engineered features with one line of justification each. Mention the cash-tip observation. |
| 2:00-2:30 | `schema.sql` | Dimension tables and the trip fact table, foreign keys, why the indexes exist, why derived columns are stored. |
| 2:30-3:15 | `algorithms.py` | HashCounter (chaining, resize) and MinHeap (sift up/down), how Top-K uses them, O(n + m log K) time and O(m + K) space. Run `python backend/test_algorithms.py`. |
| 3:15-4:30 | Live dashboard | Apply a date and hour filter and show every panel update; switch map metric (pickups -> avg speed); click a zone and show the filter chip; the hourly demand vs speed chart; tipping chart; heatmap; Top-K table with the timing note; sort the trip table by fare and page through. |
| 4:30-5:00 | Report insights slide or the dashboard | One sentence on each of the three insights, one next step (PostgreSQL/PostGIS, pre-aggregation, deployment), thanks. |

Tips: every team member should speak for at least part of the video; keep the mouse slow; zoom the browser to 110% so text is readable; upload as unlisted on YouTube/Drive and paste the link into the README.
