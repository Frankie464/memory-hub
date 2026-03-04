"""Parse Claude Code CLI session JSONL files into events."""
import hashlib
import json
from pathlib import Path

from memory_hub.config import DB_PATH
from memory_hub.db import get_connection, insert_event, log_ingest_start, log_ingest_complete

CLAUDE_CODE_PROJECTS_DIR = Path.home() / ".claude" / "projects"


def _event_id(session_id: str, line_index: int) -> str:
    """Deterministic event ID: SHA256(claude_code:{session}:{line})."""
    raw = f"claude_code:{session_id}:{line_index}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _decode_project_title(folder_name: str) -> str:
    """Decode a Claude Code project folder name to human-readable form.

    E.g. 'c--Users-ogam6-Documents-Code-ChatGPT-Claude' → 'ChatGPT_Claude'
    (returns just the last path segment for readability)
    """
    parts = folder_name.split("-")
    # Filter out empty parts from leading/double hyphens, return last meaningful segment
    parts = [p for p in parts if p]
    return parts[-1] if parts else folder_name


def _extract_text_blocks(content) -> str:
    """Extract only type='text' blocks from message content.

    Skips thinking, tool_use, tool_result blocks.
    Content may be a string or list of blocks.
    """
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts).strip()
    return ""


def ingest_claude_code(
    projects_dir: Path | None = None,
    db_path: Path = DB_PATH,
) -> dict:
    """
    Walk ~/.claude/projects/**/*.jsonl and ingest user/assistant messages.

    Only type="user" and type="assistant" records are ingested.
    Thinking blocks, tool calls, and session metadata are skipped.

    Returns stats dict.
    """
    projects_dir = Path(projects_dir) if projects_dir else CLAUDE_CODE_PROJECTS_DIR
    stats = {
        "files_found": 0,
        "sessions_found": 0,
        "messages_added": 0,
        "messages_skipped": 0,
    }

    if not projects_dir.exists():
        return stats

    jsonl_files = sorted(projects_dir.rglob("*.jsonl"))
    stats["files_found"] = len(jsonl_files)

    with get_connection(db_path) as conn:
        log_id = log_ingest_start(conn, "claude_code", str(projects_dir))

        for jsonl_path in jsonl_files:
            # Project title from parent folder name
            project_folder = jsonl_path.parent.name
            # Skip if parent is a UUID subdir (memory/, file-history/, etc.)
            if project_folder in ("memory", "file-history", "todos", "plans"):
                continue

            project_title = _decode_project_title(project_folder)
            session_counted = False

            # Read line-by-line for large files
            with open(jsonl_path, encoding="utf-8", errors="replace") as f:
                for line_index, line in enumerate(f):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    rec_type = record.get("type", "")
                    if rec_type not in ("user", "assistant"):
                        continue

                    if not session_counted:
                        stats["sessions_found"] += 1
                        session_counted = True

                    session_id = record.get("sessionId") or jsonl_path.stem
                    timestamp = record.get("timestamp")

                    if rec_type == "user":
                        text = _extract_text_blocks(record.get("content", []))
                        role = "user"
                    else:  # assistant
                        message = record.get("message", {})
                        text = _extract_text_blocks(message.get("content", []))
                        role = "assistant"

                    if not text:
                        continue

                    event = {
                        "event_id": _event_id(session_id, line_index),
                        "source": "claude_code",
                        "timestamp_utc": timestamp,
                        "role": role,
                        "content": text,
                        "conversation_id": session_id,
                        "conversation_title": f"Claude Code: {project_title}",
                        "topic_tags": "[]",
                    }

                    if insert_event(conn, event):
                        stats["messages_added"] += 1
                    else:
                        stats["messages_skipped"] += 1

        log_ingest_complete(conn, log_id, stats["messages_added"], stats["messages_skipped"])

    return stats
