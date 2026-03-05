"""Generate OpenClaw memory projection files."""
import json
from datetime import datetime
from pathlib import Path

from memory_hub.config import DB_PATH, PROFILE_MANUAL_PATH, PROJ_OPENCLAW
from memory_hub.db import get_connection, get_active_facts_as_dicts, record_projections, sanitize_statement

# Max facts per category in the session brief (keeps it scannable)
BRIEF_MAX_PER_CATEGORY = 8
# How many recent conversation summaries to include
BRIEF_RECENT_SUMMARIES = 6


def project_openclaw(deploy: bool = False, openclaw_memory_dir: Path = None, db_path: Path = DB_PATH) -> dict[str, Path]:
    """
    Generate OpenClaw memory documents:
      - MEMORY.md: full fact dump (for the projections archive)
      - memory/YYYY-MM-DD.md: dated snapshot
      - session_brief.md: compact, prioritized brief for session startup

    If deploy=True, writes session_brief.md to openclaw_memory_dir.
    Returns dict of {name: path}.
    """
    PROJ_OPENCLAW.mkdir(parents=True, exist_ok=True)

    with get_connection(db_path) as conn:
        facts = get_active_facts_as_dicts(conn)
        # Fetch recent conversation summaries for the brief
        recent_summaries = conn.execute(
            """SELECT title, source, summary, key_topics, date_range
               FROM conversation_summaries
               ORDER BY generated_at DESC
               LIMIT ?""",
            (BRIEF_RECENT_SUMMARIES * 3,),  # fetch more, filter to useful ones
        ).fetchall()

    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")

    categories = [
        ("identity", "Identity"),
        ("preference", "Communication Style"),
        ("work", "Professional"),
        ("interest", "Interests"),
        ("relationship", "Relationships"),
        ("lifestyle", "Lifestyle"),
        ("financial", "Financial"),
    ]

    # ── Full MEMORY.md ────────────────────────────────────────────────────────
    memory_lines = [
        "# the user — Persistent Memory",
        f"# Last updated: {date_str} by memory-hub",
        "",
    ]
    for cat_key, cat_label in categories:
        stmts = [sanitize_statement(f["statement"]) for f in facts if f["category"] == cat_key]
        if stmts:
            memory_lines.append(f"## {cat_label}")
            for s in stmts:
                memory_lines.append(f"- {s}")
            memory_lines.append("")

    if PROFILE_MANUAL_PATH.exists():
        memory_lines += ["## Additional Context", ""]
        for line in PROFILE_MANUAL_PATH.read_text(encoding="utf-8").splitlines():
            if line.startswith("- ") and line not in memory_lines:
                memory_lines.append(line)
        memory_lines.append("")

    memory_content = "\n".join(memory_lines)
    daily_content = f"# Memory Snapshot — {date_str}\n\n" + memory_content

    memory_path = PROJ_OPENCLAW / "MEMORY.md"
    daily_dir = PROJ_OPENCLAW / "memory"
    daily_dir.mkdir(exist_ok=True)
    daily_path = daily_dir / f"{date_str}.md"

    memory_path.write_text(memory_content, encoding="utf-8")
    daily_path.write_text(daily_content, encoding="utf-8")

    # ── Session Brief ─────────────────────────────────────────────────────────
    brief_lines = [
        "# Session Brief — the user",
        f"# Generated: {date_str} | Source: memory-hub ({len(facts)} facts)",
        "# Read this on every new session for cross-conversation context.",
        "",
    ]

    # High-confidence facts only, capped per category for scannability
    HIGH_CONF_THRESHOLD = 0.7
    for cat_key, cat_label in categories:
        cat_facts = sorted(
            [f for f in facts if f["category"] == cat_key],
            key=lambda f: f.get("confidence", 0.5),
            reverse=True,
        )
        # High confidence first, then fill with lower if needed
        top = [f for f in cat_facts if f.get("confidence", 0.5) >= HIGH_CONF_THRESHOLD]
        top = top[:BRIEF_MAX_PER_CATEGORY]
        if not top:
            top = cat_facts[:BRIEF_MAX_PER_CATEGORY // 2]

        stmts = [s for s in [sanitize_statement(f["statement"]) for f in top] if s]
        # Filter out obvious noise (very short or regex-garbage-looking statements)
        stmts = [s for s in stmts if len(s) > 10 and not s.endswith(":") and "Preference: " not in s or len(s) > 30]

        if stmts:
            brief_lines.append(f"## {cat_label}")
            for s in stmts:
                brief_lines.append(f"- {s}")
            brief_lines.append("")

    # Recent conversation summaries (skip very short/generic ones)
    useful_summaries = [
        s for s in recent_summaries
        if s["summary"] and len(s["summary"]) > 40
        and (s["title"] or "").lower() not in ("untitled", "greeting", "hi", "")
    ][:BRIEF_RECENT_SUMMARIES]

    if useful_summaries:
        brief_lines.append("## Recent Conversations")
        for s in useful_summaries:
            title = (s["title"] or "Untitled")[:60]
            date = (s["date_range"] or "")[:10]
            summary = s["summary"]
            topics = ", ".join(json.loads(s["key_topics"] or "[]")[:3])
            brief_lines.append(f"**{title}** ({s['source']}, {date})")
            brief_lines.append(f"  {summary}")
            if topics:
                brief_lines.append(f"  Topics: {topics}")
        brief_lines.append("")

    brief_lines += [
        "---",
        "Use `hub search <query>` for deeper history. Use `hub ingest openclaw` to sync latest memories.",
    ]

    brief_content = "\n".join(brief_lines)
    brief_path = PROJ_OPENCLAW / "session_brief.md"
    brief_path.write_text(brief_content, encoding="utf-8")

    out_files = {
        "MEMORY": memory_path,
        "daily": daily_path,
        "session_brief": brief_path,
    }

    if deploy and openclaw_memory_dir:
        openclaw_memory_dir = Path(openclaw_memory_dir)
        openclaw_memory_dir.mkdir(parents=True, exist_ok=True)
        (openclaw_memory_dir / "MEMORY.md").write_text(memory_content, encoding="utf-8")
        dated_dir = openclaw_memory_dir / "memory"
        dated_dir.mkdir(exist_ok=True)
        (dated_dir / f"{date_str}.md").write_text(daily_content, encoding="utf-8")
        # Deploy session brief to workspace root so I can find it easily
        (openclaw_memory_dir / "session_brief.md").write_text(brief_content, encoding="utf-8")

    with get_connection(db_path) as conn:
        record_projections(conn, "openclaw", out_files)

    return out_files
