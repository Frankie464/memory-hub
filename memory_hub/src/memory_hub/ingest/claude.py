"""Parse Claude export (ZIP or folder) into events."""
import hashlib
import json
import zipfile
from pathlib import Path

from memory_hub.config import DB_PATH
from memory_hub.db import get_connection, insert_event, log_ingest_start, log_ingest_complete


def _event_id(conversation_id: str, message_id: str) -> str:
    """Deterministic event ID: SHA256(claude:{conv_id}:{msg_id})."""
    raw = f"claude:{conversation_id}:{message_id}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _memory_hash(text: str) -> str:
    """Content-addressed hash for Claude stored memories."""
    return hashlib.sha256(text.strip().encode()).hexdigest()


def _extract_text(message: dict) -> str:
    """Extract plain text from a Claude message.

    Prefers the top-level 'text' field. Falls back to scanning
    content blocks for type='text'. Skips thinking/tool_use blocks.
    """
    if message.get("text", "").strip():
        return message["text"].strip()
    parts = []
    for block in message.get("content", []):
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "\n".join(parts).strip()


def _map_role(sender: str) -> str:
    return {"human": "user", "assistant": "assistant"}.get(sender, sender or "unknown")


def _safe_zip_member(name: str) -> bool:
    """Return True if the ZIP member path is safe (no path traversal)."""
    norm = Path(name).as_posix()
    return ".." not in norm and not norm.startswith("/")


def _load_json(source_path: Path, filename: str):
    """Load a JSON file from a ZIP or directory."""
    if source_path.is_dir():
        target = source_path / filename
        if target.exists():
            return json.loads(target.read_text(encoding="utf-8"))
        return None
    # ZIP file (with zip-slip protection)
    with zipfile.ZipFile(source_path) as zf:
        safe_names = [n for n in zf.namelist() if _safe_zip_member(n)]
        match = next((n for n in safe_names if n.endswith(filename)), None)
        if match:
            with zf.open(match) as f:
                return json.load(f)
    return None


def ingest_claude_zip(zip_path: Path, db_path: Path = DB_PATH) -> dict:
    """
    Parse a Claude export (ZIP or unzipped folder) and insert events.

    Handles:
      - conversations.json -> conversation messages
      - memories.json -> stored memories as system-role events

    Returns stats dict.
    """
    zip_path = Path(zip_path)
    if not zip_path.exists():
        raise FileNotFoundError(f"Claude export not found: {zip_path}")

    conversations = _load_json(zip_path, "conversations.json") or []
    memories_data = _load_json(zip_path, "memories.json") or []

    stats = {
        "conversations": 0,
        "messages_added": 0,
        "messages_skipped": 0,
        "memories_added": 0,
        "memories_skipped": 0,
    }

    with get_connection(db_path) as conn:
        log_id = log_ingest_start(conn, "claude", str(zip_path))

        # ── Conversations ──
        for conv in conversations:
            conv_id = conv.get("uuid", "")
            title = conv.get("name") or "Untitled"
            stats["conversations"] += 1

            for msg in conv.get("chat_messages", []):
                msg_id = msg.get("uuid", "")
                text = _extract_text(msg)
                if not text:
                    continue

                event = {
                    "event_id": _event_id(conv_id, msg_id),
                    "source": "claude",
                    "timestamp_utc": msg.get("created_at"),
                    "role": _map_role(msg.get("sender")),
                    "content": text,
                    "conversation_id": conv_id,
                    "conversation_title": title,
                    "topic_tags": "[]",
                }
                if insert_event(conn, event):
                    stats["messages_added"] += 1
                else:
                    stats["messages_skipped"] += 1

        # ── Stored memories ──
        _ingest_memories(conn, memories_data, stats)

        total_added = stats["messages_added"] + stats["memories_added"]
        total_skipped = stats["messages_skipped"] + stats["memories_skipped"]
        log_ingest_complete(conn, log_id, total_added, total_skipped)

    return stats


def _ingest_memories(conn, memories_data, stats):
    """Ingest Claude stored memories as system-role events.

    Each paragraph becomes a separate event for granular fact extraction.
    """
    if isinstance(memories_data, dict):
        memories_data = [memories_data]

    for mem_obj in memories_data:
        text_parts = []

        # Main conversation memory
        if mem_obj.get("conversations_memory"):
            text_parts.append(str(mem_obj["conversations_memory"]))

        # Project-specific memories (dict of project_uuid -> memory text)
        project_mems = mem_obj.get("project_memories", {})
        if isinstance(project_mems, dict):
            for proj_text in project_mems.values():
                if proj_text:
                    text_parts.append(str(proj_text))

        full_text = "\n\n".join(text_parts).strip()
        if not full_text:
            continue

        # Split into paragraphs for granular fact extraction
        paragraphs = [p.strip() for p in full_text.split("\n\n") if p.strip()]

        for para in paragraphs:
            if len(para) < 10:
                continue
            event = {
                "event_id": _memory_hash(para),
                "source": "claude",
                "timestamp_utc": None,
                "role": "system",
                "content": para,
                "conversation_id": None,
                "conversation_title": "Claude Stored Memories",
                "topic_tags": "[]",
            }
            if insert_event(conn, event):
                stats["memories_added"] += 1
            else:
                stats["memories_skipped"] += 1
