"""Path constants and configuration for memory-hub."""
from pathlib import Path

# Base project directory (two levels up from this file's src/memory_hub/ location)
_THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = _THIS_FILE.parent.parent.parent.parent  # ChatGPT_Claude/

DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
CANONICAL_DIR = DATA_DIR / "canonical"
HISTORY_DIR = DATA_DIR / "history"
PROJECTIONS_DIR = DATA_DIR / "projections"
REPORTS_DIR = PROJECT_ROOT / "reports"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"

DB_PATH = CANONICAL_DIR / "hub.db"
PROFILE_MANUAL_PATH = CANONICAL_DIR / "profile.manual.md"
PROFILE_GENERATED_PATH = CANONICAL_DIR / "profile.generated.md"
CHANGELOG_PATH = CANONICAL_DIR / "changelog.md"

# Claude Code paths
CLAUDE_MD_PATH = Path.home() / ".claude" / "CLAUDE.md"
CLAUDE_RULES_DIR = Path.home() / ".claude" / "rules"

# Projection subdirectories
PROJ_CLAUDE_AI = PROJECTIONS_DIR / "claude_ai"
PROJ_CLAUDE_CODE = PROJECTIONS_DIR / "claude_code"
PROJ_OPENCLAW = PROJECTIONS_DIR / "openclaw"
PROJ_CHATGPT = PROJECTIONS_DIR / "chatgpt"

# CLAUDE.md marker for managed block
CLAUDE_MD_BEGIN = "<!-- BEGIN MEMORY_HUB -->"
CLAUDE_MD_END = "<!-- END MEMORY_HUB -->"

# Max chars per Claude.ai memory import chunk
CLAUDE_AI_CHUNK_MAX = 2000

ALL_DIRS = [
    RAW_DIR / "chatgpt_exports",
    RAW_DIR / "claude_exports",
    RAW_DIR / "openclaw_events",
    CANONICAL_DIR,
    HISTORY_DIR,
    PROJ_CLAUDE_AI,
    PROJ_CLAUDE_CODE,
    PROJ_OPENCLAW,
    PROJ_CHATGPT,
    REPORTS_DIR,
    SCRIPTS_DIR,
]
