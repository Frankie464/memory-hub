"""Scheduled sync orchestration for weekly and monthly workflows."""
from datetime import datetime
from pathlib import Path

from memory_hub.config import DB_PATH, RAW_DIR, REPORTS_DIR
from memory_hub.db import get_connection, get_stats
from memory_hub.ingest.chatgpt import ingest_chatgpt_zip
from memory_hub.ingest.claude import ingest_claude_memory
from memory_hub.project.claude_chat import project_claude_chat
from memory_hub.project.claude_code import project_claude_code
from memory_hub.project.openclaw import project_openclaw
from memory_hub.project.chatgpt import project_chatgpt
from memory_hub.reconcile import reconcile


def _write_report(profile: str, content: str) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    path = REPORTS_DIR / f"sync_{profile}_{date_str}.md"
    path.write_text(content, encoding="utf-8")
    return path


def _auto_find_latest(directory: Path, pattern: str) -> Path | None:
    """Find the most recently modified file matching pattern in directory."""
    files = sorted(directory.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def sync_weekly(deploy: bool = False, db_path: Path = DB_PATH) -> dict:
    """
    Weekly sync workflow:
    1. Ingest latest Claude memory export (if available in raw/claude_exports/)
    2. Reconcile facts
    3. Generate projections for Claude.ai, Claude Code, OpenClaw
    4. Write sync report
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    results = {"profile": "weekly", "ran_at": now, "steps": []}

    # Step 1: Ingest Claude memory export (auto-find latest)
    claude_export = _auto_find_latest(RAW_DIR / "claude_exports", "*.md")
    if claude_export:
        try:
            stats = ingest_claude_memory(claude_export, db_path)
            results["steps"].append(f"✓ Claude ingest: {stats['added']} new entries from {claude_export.name}")
        except Exception as e:
            results["steps"].append(f"✗ Claude ingest failed: {e}")
    else:
        results["steps"].append("⚠ No Claude memory export found in data/raw/claude_exports/")

    # Step 2: Reconcile
    try:
        rec = reconcile(db_path)
        results["steps"].append(
            f"✓ Reconcile: {rec['facts_added']} new facts, {rec['facts_confirmed']} confirmed, {rec['conflicts_added']} conflicts"
        )
    except Exception as e:
        results["steps"].append(f"✗ Reconcile failed: {e}")

    # Step 3: Generate projections
    for name, fn, kwargs in [
        ("Claude.ai", project_claude_chat, {"db_path": db_path}),
        ("Claude Code", project_claude_code, {"deploy": deploy, "db_path": db_path}),
        ("OpenClaw", project_openclaw, {"deploy": deploy, "db_path": db_path}),
    ]:
        try:
            out = fn(**kwargs)
            count = len(out) if isinstance(out, (list, dict)) else 1
            results["steps"].append(f"✓ {name} projection: {count} files generated")
        except Exception as e:
            results["steps"].append(f"✗ {name} projection failed: {e}")

    # Step 4: Stats snapshot
    with get_connection(db_path) as conn:
        stats = get_stats(conn)
    results["stats"] = stats

    # Write report
    report_lines = [
        f"# Weekly Sync Report — {now}",
        "",
        "## Steps",
    ]
    for step in results["steps"]:
        report_lines.append(f"- {step}")
    report_lines += [
        "",
        "## Database Stats",
        f"- Events: {stats['events']:,}",
        f"- Active facts: {stats['facts']}",
        f"- Pending conflicts: {stats['pending_conflicts']}",
    ]
    report_path = _write_report("weekly", "\n".join(report_lines))
    results["report_path"] = str(report_path)
    return results


def sync_monthly(deploy: bool = False, db_path: Path = DB_PATH) -> dict:
    """
    Monthly sync workflow:
    1. Ingest latest ChatGPT ZIP (auto-find in raw/chatgpt_exports/)
    2. Ingest latest Claude memory export
    3. Reconcile
    4. Generate ALL projections
    5. Write sync report
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    results = {"profile": "monthly", "ran_at": now, "steps": []}

    # Step 1: Ingest ChatGPT export (auto-find latest ZIP)
    chatgpt_zip = _auto_find_latest(RAW_DIR / "chatgpt_exports", "*.zip")
    if chatgpt_zip:
        try:
            stats = ingest_chatgpt_zip(chatgpt_zip, db_path)
            results["steps"].append(
                f"✓ ChatGPT ingest: {stats['messages_added']:,} messages added, "
                f"{stats['messages_skipped']:,} skipped from {stats['conversations']:,} conversations"
            )
        except Exception as e:
            results["steps"].append(f"✗ ChatGPT ingest failed: {e}")
    else:
        results["steps"].append("⚠ No ChatGPT export ZIP found in data/raw/chatgpt_exports/")

    # Step 2: Ingest Claude memory export
    claude_export = _auto_find_latest(RAW_DIR / "claude_exports", "*.md")
    if claude_export:
        try:
            stats = ingest_claude_memory(claude_export, db_path)
            results["steps"].append(f"✓ Claude ingest: {stats['added']} new entries")
        except Exception as e:
            results["steps"].append(f"✗ Claude ingest failed: {e}")
    else:
        results["steps"].append("⚠ No Claude memory export found")

    # Step 3: Reconcile
    try:
        rec = reconcile(db_path)
        results["steps"].append(
            f"✓ Reconcile: {rec['facts_added']} new facts, {rec['facts_confirmed']} confirmed"
        )
    except Exception as e:
        results["steps"].append(f"✗ Reconcile failed: {e}")

    # Step 4: All projections
    for name, fn, kwargs in [
        ("Claude.ai", project_claude_chat, {"db_path": db_path}),
        ("Claude Code", project_claude_code, {"deploy": deploy, "db_path": db_path}),
        ("OpenClaw", project_openclaw, {"deploy": deploy, "db_path": db_path}),
        ("ChatGPT", project_chatgpt, {"db_path": db_path}),
    ]:
        try:
            out = fn(**kwargs)
            count = len(out) if isinstance(out, (list, dict)) else 1
            results["steps"].append(f"✓ {name} projection: {count} files generated")
        except Exception as e:
            results["steps"].append(f"✗ {name} projection failed: {e}")

    # Step 5: Stats
    with get_connection(db_path) as conn:
        stats = get_stats(conn)
    results["stats"] = stats

    report_lines = [
        f"# Monthly Sync Report — {now}",
        "",
        "## Steps",
    ]
    for step in results["steps"]:
        report_lines.append(f"- {step}")
    report_lines += [
        "",
        "## Database Stats",
        f"- Events: {stats['events']:,}",
        f"- Active facts: {stats['facts']}",
        f"- Pending conflicts: {stats['pending_conflicts']}",
    ]
    report_path = _write_report("monthly", "\n".join(report_lines))
    results["report_path"] = str(report_path)
    return results
