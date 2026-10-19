"""Configuration: weights, thresholds and risk tables from the review document, plus paths.

The numbers in this file are quoted in the project review document.
Do not change them without updating the document.
"""
import os
from datetime import timedelta, timezone
from pathlib import Path

# --------------------------------------------------------------------------- #
# Paths (everything is relative to the project folder unless overridden)
# --------------------------------------------------------------------------- #
PROJECT_ROOT = Path(__file__).resolve().parent.parent
HOME = Path(os.environ.get("SENTINEL_HOME", PROJECT_ROOT))

DATABASE_URL = os.environ.get("DATABASE_URL")          # postgresql://... -> PostgreSQL
SQLITE_PATH = Path(os.environ.get("SENTINEL_DB", HOME / "data_sentinel.db"))
MODEL_PATH = Path(os.environ.get("SENTINEL_MODEL", PROJECT_ROOT / "models" / "anomaly_iforest.joblib"))
QUARANTINE_DIR = Path(os.environ.get("SENTINEL_QUARANTINE", HOME / "quarantine"))
OUTBOX_DIR = Path(os.environ.get("SENTINEL_OUTBOX", HOME / "outbox"))
TOKEN_PATH = Path(os.environ.get("SENTINEL_TOKEN_FILE", HOME / ".sentinel_token"))

# --------------------------------------------------------------------------- #
# Organisation settings
# --------------------------------------------------------------------------- #
IST = timezone(timedelta(hours=5, minutes=30))          # organisation time zone
WORK_HOURS = (7, 20)                                    # 07:00-20:00 on weekdays is "normal"
LARGE_FILE_MB = 50


def company_domains():
    raw = os.environ.get("SENTINEL_COMPANY_DOMAINS", "company.com")
    return [d.strip().lower().lstrip("@.") for d in raw.split(",") if d.strip()]


# --------------------------------------------------------------------------- #
# Classification levels
# --------------------------------------------------------------------------- #
LEVELS = ["Public", "Internal", "Confidential", "Restricted"]

# --------------------------------------------------------------------------- #
# Context signals (each 0..1)
# --------------------------------------------------------------------------- #
ROLE_RISK = {"admin": 0.1, "employee": 0.4, "intern": 0.6, "contractor": 0.7}
UNKNOWN_ROLE_RISK = 0.5
TRUST_RISK = {"trusted": 0.0, "unknown": 0.7, "untrusted": 1.0}
DEST_RISK = {
    "internal": 0.0, "email_internal": 0.2, "network_share": 0.3, "email": 0.6,
    "usb": 0.7, "web": 0.7, "cloud": 0.8, "cloud_sync": 0.8, "messaging": 0.8,
    "genai": 0.8, "cloud_share": 0.9, "paste_site": 1.0, "other": 0.8,
}
DEST_LABELS = {
    "internal": "internal", "email_internal": "internal e-mail", "network_share": "network share",
    "email": "external e-mail", "usb": "USB drive", "web": "website", "cloud": "cloud storage",
    "cloud_sync": "cloud sync folder", "messaging": "messaging app", "genai": "AI chat",
    "cloud_share": "shared cloud file", "paste_site": "paste site", "other": "other",
}

# --------------------------------------------------------------------------- #
# Risk score
# --------------------------------------------------------------------------- #
WEIGHTS = {"sensitivity": 0.35, "user": 0.10, "device": 0.20,
           "destination": 0.15, "context": 0.10, "anomaly": 0.10}
THRESHOLDS = [(25, "LOW"), (50, "MEDIUM"), (70, "HIGH")]          # else CRITICAL
DEFAULT_POLICY = {"LOW": "ALLOW", "MEDIUM": "WARN", "HIGH": "BLOCK", "CRITICAL": "BLOCK"}
RANK = {"ALLOW": 0, "WARN": 1, "BLOCK": 2}

# --------------------------------------------------------------------------- #
# Anomaly detection
# --------------------------------------------------------------------------- #
FEATURES = ["hour", "sensitivity", "size_mb", "dest_risk", "count_1h"]
MIN_TRAIN_ROWS = 50
HEURISTIC_DIVISOR = 10            # heuristic = min(1, transfers in last hour / 10)

# --------------------------------------------------------------------------- #
# Channels
# --------------------------------------------------------------------------- #
POLL_SECONDS = 2.0
MAX_INSPECT_BYTES = 20 * 1024 * 1024      # browser uploads above this are judged by name + size
TEXT_READ_LIMIT = 2_000_000               # characters of text read per file for classification
API_HOST = "127.0.0.1"
API_PORT = int(os.environ.get("SENTINEL_API_PORT", 8765))
SMTP_HOST = "127.0.0.1"
SMTP_PORT = int(os.environ.get("SENTINEL_SMTP_PORT", 1025))
SMTP_UPSTREAM = os.environ.get("SENTINEL_SMTP_UPSTREAM")          # host:port, optional
