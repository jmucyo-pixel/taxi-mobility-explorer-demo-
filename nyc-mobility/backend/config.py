"""Central configuration. Every value can be overridden with an environment variable."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", ROOT / "data"))
LOG_DIR = Path(os.getenv("LOG_DIR", ROOT / "logs"))
DB_PATH = Path(os.getenv("DB_PATH", ROOT / "data" / "mobility.db"))
FRONTEND_DIR = ROOT / "frontend"

# Cleaning thresholds (documented in README / report)
MAX_DURATION_MIN = 360      # trips longer than 6 h
MIN_DURATION_SEC = 30       # trips shorter than 30 s
MAX_DISTANCE_MI = 100
MAX_FARE = 500
MAX_SPEED_MPH = 80
MAX_PASSENGERS = 6
MIN_MONTH_SHARE = 0.05      # a month is "in period" if it holds >= 5% of rows
DB_EXCLUDED_SAMPLE = 20000  # rows of the exclusion log mirrored into the DB (full log goes to CSV)
