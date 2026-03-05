"""Ingest OpenClaw workspace memory files into the events database."""
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

from memory_hub.config import DB_PATH
from memory_hub.db import get_connection, insert_event, log_ingest_start, log_ingest_complete

DEFAULT_WORKSPACE = Path.home() / ".openclaw" / "workspace"
DAILY_FILE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.md$")


def _event_id(rel_path: str, content: str) -> str:
    """Stable content-addressed ID for OpenClaw events."""
    raw = f"openclaw:{rel_path}:{hashlib.sha256(content.strip().encode()).hexdigest()[:16]}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _parse_sections(text: str, min_len: int = 20) -> list[str]:
    """
    Split markdown text into sections by ## headers or paragraph blocks.
    Returns list of non-trivial text chunks.
    """
    # Try splitting by ## headers first
    sections = re.split(r"\n(?=##\s)", text)
    # Fall back to paragraph splitting if only one section
    if len(sections) <= 1:
        sections = [p.strip() for p in re.split(r"\n{2,}", text)]
    return [s.strip() for s in sections if len(s.strip()) >= min_len]


def _ts_from_filename(filename: str) -> str | None:
    """Extract ISO timestamp from a YYYY-MM-DD.md filename."""
    m = DAILY_FILE_RE.match(filename)
    if m:
        try:
            dt = datetime.strptime(m.group(1), "%Y-%m-%d").replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except ValueError:
            pass
    return None


def ingest_openclaw(workspace_dir: Path = None, db_path: Path = DB_PATH) -> dict:
    """
    Parse OpenClaw workspace memory files and insert as events.

    Reads:
      - MEMORY.md (curated long-term memory) — each ## section becomes an event
      - memory/YYYY-MM-DD.md (daily logs) — each ## section or paragraph becomes an event

    Returns stats dict with files_found, messages_added, messages_skipped.
    """
    workspace = Path(workspace_dir) if workspace_dir else DEFAULT_WORKSPACE
    stats = {"files_found": 0, "messages_added": 0, "messages_skipped": 0}

    if not workspace.exists():
        return stats

    files_to_ingest: list[tuple[Path, str | None]] = []  # (path, timestamp_or_None)

    # MEMORY.md
    memory_md = workspace / "MEMORY.md"
    if memory_md.exists():
        files_to_ingest.append((memory_md, None))

    # Daily files: memory/YYYY-MM-DD.md
    memory_dir = workspace / "memory"
    if memory_dir.exists():
        for f in sorted(memory_dir.glob("*.md")):
            if DAILY_FILE_RE.match(f.name):
                ts = _ts_from_filename(f.name)
                files_to_ingest.append((f, ts))

    with get_connection(db_path) as conn:
        log_id = log_ingest_start(conn, "openclaw", str(workspace))

        for file_path, timestamp in files_to_ingest:
            stats["files_found"] += 1
            rel = file_path.relative_to(workspace).as_posix()

            try:
                text = file_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            # Strip MEMORY.md comment lines (lines starting with #)
            lines = [l for l in text.splitlines() if not l.strip().startswith("# ")]
            clean_text = "\n".join(lines)

            sections = _parse_sections(clean_text)
            for section in sections:
                # Determine title from section header if present
                title_match = re.match(r"^##\s+(.+)", section, re.MULTILINE)
                conv_title = f"OpenClaw {title_match.group(1).strip()}" if title_match else f"OpenClaw {rel}"

                event = {
                    "event_id": _event_id(rel, section),
                    "source": "openclaw",
                    "timestamp_utc": timestamp,
                    "role": "system",
                    "content": section,
                    "conversation_id": rel,  # use filepath as "conversation" grouping
                    "conversation_title": conv_title,
                    "topic_tags": "[]",
                }
                if insert_event(conn, event):
                    stats["messages_added"] += 1
                else:
                    stats["messages_skipped"] += 1

        log_ingest_complete(conn, log_id, stats["messages_added"], stats["messages_skipped"])

    return stats
