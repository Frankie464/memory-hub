"""Parse ChatGPT memory dump markdown into events."""
import hashlib
import re
from pathlib import Path

from memory_hub.config import DB_PATH
from memory_hub.db import get_connection, insert_event, log_ingest_start, log_ingest_complete

# Matches lines like: [2024-08-23] - Some memory entry
_DATED_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2})\]\s*-\s*(.+)$")
# Matches lines like: [undated] - Some memory entry
_UNDATED_RE = re.compile(r"^\[undated[^\]]*\]\s*-\s*(.+)$", re.IGNORECASE)
# Code block fence marker
_CODE_FENCE = re.compile(r"^```")


def _content_hash(text: str) -> str:
    """Content-addressed hash for dedup. Purely content-based, no source prefix."""
    return hashlib.sha256(text.strip().encode()).hexdigest()


def ingest_chatgpt_memory(file_path: Path, db_path: Path = DB_PATH) -> dict:
    """
    Parse a ChatGPT memory dump markdown file and insert events.

    The export format (from prompting ChatGPT to list all stored memories):
      ```text
      [YYYY-MM-DD] - Category (provided by user): Content
      [undated] - Category: Content
      ```
    Returns stats dict: {entries_found, added, skipped}
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"ChatGPT memory dump not found: {file_path}")

    text = file_path.read_text(encoding="utf-8")
    stats = {"entries_found": 0, "added": 0, "skipped": 0}

    # Strip markdown code fences if present
    lines = text.splitlines()
    clean_lines = []
    in_fence = False
    for line in lines:
        if _CODE_FENCE.match(line.strip()):
            in_fence = not in_fence
            continue
        clean_lines.append(line)

    # Collect multi-line entries: a dated/undated header followed by continuation lines
    entries = []
    current_ts = None
    current_parts = []

    def flush():
        if current_parts:
            content = " ".join(current_parts).strip()
            if content:
                entries.append((current_ts, content))

    for line in clean_lines:
        dated = _DATED_RE.match(line.strip())
        undated = _UNDATED_RE.match(line.strip())

        if dated:
            flush()
            current_parts = []
            current_ts = dated.group(1) + "T00:00:00+00:00"
            current_parts.append(dated.group(2).strip())
        elif undated:
            flush()
            current_parts = []
            current_ts = None
            current_parts.append(undated.group(1).strip())
        elif line.strip() and current_parts is not None:
            # Continuation of previous entry
            current_parts.append(line.strip())

    flush()

    with get_connection(db_path) as conn:
        log_id = log_ingest_start(conn, "chatgpt", str(file_path))

        for ts, content in entries:
            stats["entries_found"] += 1
            event = {
                "event_id": _content_hash(content),
                "source": "chatgpt",
                "timestamp_utc": ts,
                "role": "system",
                "content": content,
                "conversation_id": None,
                "conversation_title": "ChatGPT Memory Dump",
                "topic_tags": "[]",
            }
            if insert_event(conn, event):
                stats["added"] += 1
            else:
                stats["skipped"] += 1

        log_ingest_complete(conn, log_id, stats["added"], stats["skipped"])

    return stats
