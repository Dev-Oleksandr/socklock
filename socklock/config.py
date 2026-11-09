"""All settings in one place: folders, Claude model, business numbers, pilot thresholds."""
import os
from pathlib import Path

# Folder that holds library/, data/, out/ and samples/.
# Default: the project folder. Override with the SOCKLOCK_HOME env var.
PROJECT_DIR = Path(__file__).resolve().parent.parent
HOME = Path(os.environ.get("SOCKLOCK_HOME", PROJECT_DIR))

LIBRARY_DIR = HOME / "library"           # style_guide.md + winners/
DB_PATH = HOME / "data" / "socklock.db"  # SQLite file with every generation
OUT_DIR = HOME / "out"                   # Markdown/JSON files with variants
SAMPLES_DIR = HOME / "samples"           # demo input files

# Claude. Backend: "cli" (local Claude Code subscription, default), "api" (API key) or "mock".
DEFAULT_BACKEND = os.environ.get("SOCKLOCK_BACKEND", "cli")
# The model can be changed with SOCKLOCK_MODEL or --model (e.g. claude-opus-5-5 to compare with Opus).
# The full name works for both backends; the cli backend also accepts aliases like "sonnet"/"opus".
DEFAULT_MODEL = os.environ.get("SOCKLOCK_MODEL", "claude-sonnet-5-5")
DEFAULT_EFFORT = os.environ.get("SOCKLOCK_EFFORT", "medium")
DEFAULT_VARIANTS = 10
MAX_VARIANTS = 30

# Business numbers from the brief.
LTV_USD = 68.0                  # used for ROMI when the CSV has no conversion value column
BASELINE_MODS_PER_MONTH = 240   # today: 6 designers
BASELINE_MINUTES_PER_MOD = 180  # today: ~3 h per modification
TARGET_MODS_PER_MONTH = 360

# Pilot success thresholds.
MIN_ACCEPTANCE = 0.50       # accepted variants / generated variants
MAX_MINUTES_PER_MOD = 120   # average time per modification
MIN_ROMI = 1.30             # conversion value / spend (130%)


def resolve_backend(backend=None, mock=False):
    """Mock is used ONLY when asked for explicitly (--mock, --backend mock or SOCKLOCK_MOCK=1).
    It is never a silent fallback when the real model fails."""
    if mock or os.environ.get("SOCKLOCK_MOCK") == "1":
        return "mock"
    return backend or DEFAULT_BACKEND
