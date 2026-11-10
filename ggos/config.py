"""Central configuration. No secrets are stored here — only env var names.

Single absolute database path. Everything in the project resolves the DB
through ggos.config.DB_PATH, so there is exactly one database file.
"""
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = Path(os.environ.get("GGOS_DATA_DIR") or (PROJECT_ROOT / "data")).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = Path(os.environ.get("GGOS_DB_PATH") or (DATA_DIR / "gangster_god.db")).resolve()

# Empty string means "not configured": trigger endpoints answer 503 rather
# than falling back to a default secret.
API_TOKEN = os.environ.get("GGOS_API_TOKEN", "")

CORS_ORIGINS = [
    o.strip() for o in os.environ.get("GGOS_CORS_ORIGINS", "").split(",") if o.strip()
]

OUTBOUND_ENABLED = os.environ.get("GGOS_OUTBOUND_ENABLED", "0") == "1"
