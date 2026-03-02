"""Parse ChatGPT conversations.json export into events."""
import hashlib
import json
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from memory_hub.config import DB_PATH, RAW_DIR
from memory_hub.db import get_connection, insert_event


def _event_id(conversation_id: str, message_id: str) -> str:
    raw = f"chatgpt:{conversation_id}:{message_id}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _extract_text(content: dict) -> str:
    """Extract plain text from a ChatGPT message content block."""
    if not content:
        return ""
    ct = content.get("content_type", "")
    if ct == "text":
        parts = content.get("parts", [])
        return " ".join(str(p) for p in parts if isinstance(p, str) and p.strip())
    if ct == "code":
        return content.get("text", "")
    if ct == "tether_quote":
        return content.get("text", "")
    # Fallback: grab any text/parts fields present
    parts = content.get("parts", [])
    if parts:
        return " ".join(str(p) for p in parts if isinstance(p, str))
    return content.get("text", "")


def ingest_chatgpt_zip(zip_path: Path, db_path: Path = DB_PATH) -> dict:
    """
    Parse a ChatGPT export ZIP file and insert events into the DB.

    Returns stats dict: {conversations, messages_added, messages_skipped}
    """
    zip_path = Path(zip_path)
    if not zip_path.exists():
        raise FileNotFoundError(f"Export ZIP not found: {zip_path}")

    # Extract conversations.json
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        conv_file = next((n for n in names if n.endswith("conversations.json")), None)
        if not conv_file:
            raise ValueError("No conversations.json found in ZIP")
        with zf.open(conv_file) as f:
            conversations = json.load(f)

    stats = {"conversations": 0, "messages_added": 0, "messages_skipped": 0}
    log_id = str(uuid.uuid4())

    with get_connection(db_path) as conn:
        conn.execute(
            "INSERT INTO ingest_log (log_id, source, file_path) VALUES (?,?,?)",
            (log_id, "chatgpt", str(zip_path)),
        )

        for conv in conversations:
            conv_id = conv.get("id", "")
            title = conv.get("title", "Untitled")
            mapping = conv.get("mapping", {})
            stats["conversations"] += 1

            for node_id, node in mapping.items():
                msg = node.get("message")
                if not msg:
                    continue

                role = msg.get("author", {}).get("role", "unknown")
                content_block = msg.get("content", {})
                text = _extract_text(content_block)

                if not text.strip():
                    continue

                create_time = msg.get("create_time")
                if create_time:
                    ts = datetime.fromtimestamp(create_time, tz=timezone.utc).isoformat()
                else:
                    ts = None

                event = {
                    "event_id": _event_id(conv_id, msg.get("id", node_id)),
                    "source": "chatgpt",
                    "timestamp_utc": ts,
                    "role": role,
                    "content": text,
                    "conversation_id": conv_id,
                    "conversation_title": title,
                    "topic_tags": "[]",
                }

                if insert_event(conn, event):
                    stats["messages_added"] += 1
                else:
                    stats["messages_skipped"] += 1

        conn.execute(
            """UPDATE ingest_log SET events_added=?, events_skipped=?,
               completed_at=datetime('now') WHERE log_id=?""",
            (stats["messages_added"], stats["messages_skipped"], log_id),
        )

    return stats
