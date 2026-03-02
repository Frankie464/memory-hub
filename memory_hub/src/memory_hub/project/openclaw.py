"""Generate OpenClaw memory projection files."""
from datetime import datetime
from pathlib import Path

from memory_hub.config import DB_PATH, PROFILE_MANUAL_PATH, PROJ_OPENCLAW
from memory_hub.db import get_connection, get_active_facts_as_dicts, record_projections


def project_openclaw(deploy: bool = False, openclaw_memory_dir: Path = None, db_path: Path = DB_PATH) -> dict[str, Path]:
    """
    Generate OpenClaw memory documents.
    OpenClaw uses file-based memory: MEMORY.md + dated daily files.

    If deploy=True, writes to openclaw_memory_dir (must be provided).
    Returns dict of {name: path}.
    """
    PROJ_OPENCLAW.mkdir(parents=True, exist_ok=True)

    with get_connection(db_path) as conn:
        facts = get_active_facts_as_dicts(conn)

    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")

    # Build MEMORY.md (main persistent memory file)
    memory_lines = [
        "# the user — Persistent Memory",
        f"# Last updated: {date_str} by memory-hub",
        "",
    ]

    categories = [
        ("identity", "Identity"),
        ("preference", "Communication Style"),
        ("work", "Professional"),
        ("interest", "Interests"),
        ("relationship", "Relationships"),
        ("lifestyle", "Lifestyle"),
        ("financial", "Financial"),
    ]

    for cat_key, cat_label in categories:
        stmts = [f["statement"] for f in facts if f["category"] == cat_key]
        if stmts:
            memory_lines.append(f"## {cat_label}")
            for s in stmts:
                memory_lines.append(f"- {s}")
            memory_lines.append("")

    # If manual profile exists, merge it
    if PROFILE_MANUAL_PATH.exists():
        memory_lines += [
            "## Additional Context",
            "# (from manually curated profile)",
            "",
        ]
        manual_text = PROFILE_MANUAL_PATH.read_text(encoding="utf-8")
        # Add any lines not already in memory_lines
        for line in manual_text.splitlines():
            if line.startswith("- ") and line not in memory_lines:
                memory_lines.append(line)
        memory_lines.append("")

    memory_content = "\n".join(memory_lines)

    # Build dated daily file (snapshot)
    daily_content = f"# Memory Snapshot — {date_str}\n\n" + memory_content

    out_files = {}

    memory_path = PROJ_OPENCLAW / "MEMORY.md"
    daily_dir = PROJ_OPENCLAW / "memory"
    daily_dir.mkdir(exist_ok=True)
    daily_path = daily_dir / f"{date_str}.md"

    memory_path.write_text(memory_content, encoding="utf-8")
    daily_path.write_text(daily_content, encoding="utf-8")

    out_files = {"MEMORY": memory_path, "daily": daily_path}

    if deploy and openclaw_memory_dir:
        openclaw_memory_dir = Path(openclaw_memory_dir)
        openclaw_memory_dir.mkdir(parents=True, exist_ok=True)
        (openclaw_memory_dir / "MEMORY.md").write_text(memory_content, encoding="utf-8")
        dated_dir = openclaw_memory_dir / "memory"
        dated_dir.mkdir(exist_ok=True)
        (dated_dir / f"{date_str}.md").write_text(daily_content, encoding="utf-8")

    with get_connection(db_path) as conn:
        record_projections(conn, "openclaw", out_files)

    return out_files
