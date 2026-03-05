"""Directory watcher for automatic ingest of new export files.

Polls raw export directories and ~/Downloads for new files,
ingests them, archives old ones, and triggers reconcile + projections.
"""
import hashlib
import json
import shutil
import time
import zipfile
from datetime import datetime
from pathlib import Path

from memory_hub.config import CANONICAL_DIR, DB_PATH, RAW_DIR, REPORTS_DIR

WATCHER_STATE_PATH = CANONICAL_DIR / "watcher_state.json"
ARCHIVE_DIR = RAW_DIR / "archive"
DOWNLOADS_DIR = Path.home() / "Downloads"
POLL_INTERVAL_SECONDS = 604800  # 1 week default

# Patterns for auto-detecting exports in ~/Downloads (ZIPs only — we detect source by peeking)
DOWNLOADS_ZIP_GLOB = "*.zip"
DOWNLOADS_FOLDER_PATTERN = "data-*"  # unzipped ChatGPT exports (folder with conversations.json)

# Patterns for watching raw directories
RAW_WATCH_SPECS = [
    # (subdirectory, glob_pattern, ingest_type)
    ("chatgpt_exports", "*.zip", "chatgpt_zip"),
    ("chatgpt_exports", "*.md", "chatgpt_memory"),
    ("claude_exports", "*.zip", "claude_zip"),
]


def _detect_zip_source(zip_path: Path) -> str | None:
    """
    Peek inside a ZIP to determine if it's a ChatGPT or Claude export.

    ChatGPT exports contain conversations.json with a 'mapping' key on items.
    Claude exports contain conversations.json with a 'chat_messages' key, or memories.json.
    Returns 'chatgpt', 'claude', or None if unrecognized.
    """
    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            # Check for memories.json — unique to Claude exports
            if any(n.endswith("memories.json") for n in names):
                return "claude"
            # Check conversations.json structure
            conv_name = next((n for n in names if n.endswith("conversations.json")), None)
            if conv_name:
                with zf.open(conv_name) as f:
                    try:
                        data = json.load(f)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        return None
                    if isinstance(data, list) and data:
                        sample = data[0]
                        if "mapping" in sample:
                            return "chatgpt"
                        if "chat_messages" in sample:
                            return "claude"
                        # Fallback: conversations.json present but ambiguous
                        return "chatgpt"
    except (zipfile.BadZipFile, KeyError, OSError):
        return None
    return None


def _file_hash(path: Path) -> str:
    """SHA256 hash of file contents for dedup."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_state() -> dict:
    if WATCHER_STATE_PATH.exists():
        return json.loads(WATCHER_STATE_PATH.read_text(encoding="utf-8"))
    return {"files": {}, "last_ingest": {}}


def _save_state(state: dict) -> None:
    WATCHER_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    WATCHER_STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _archive_file(path: Path) -> Path:
    """Move a processed file to the dated archive directory."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    dest_dir = ARCHIVE_DIR / date_str / path.parent.name
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / path.name
    if dest.exists():
        stem = path.stem
        suffix = path.suffix
        dest = dest_dir / f"{stem}_{datetime.now().strftime('%H%M%S')}{suffix}"
    shutil.move(str(path), str(dest))
    return dest


def _move_from_downloads(src: Path, dest_subdir: str) -> Path:
    """Move a detected export from Downloads to the correct raw directory."""
    dest_dir = RAW_DIR / dest_subdir
    dest_dir.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        # For folder-based exports (ChatGPT data-* folders), move the whole dir
        dest = dest_dir / src.name
        if dest.exists():
            dest = dest_dir / f"{src.name}_{datetime.now().strftime('%H%M%S')}"
        shutil.move(str(src), str(dest))
        return dest
    else:
        dest = dest_dir / src.name
        if dest.exists():
            dest = dest_dir / f"{src.stem}_{datetime.now().strftime('%H%M%S')}{src.suffix}"
        shutil.move(str(src), str(dest))
        return dest


def _ingest_file(path: Path, ingest_type: str, db_path: Path) -> dict:
    """Dispatch to the correct ingest function."""
    if ingest_type == "chatgpt_zip":
        from memory_hub.ingest.chatgpt import ingest_chatgpt_zip
        return ingest_chatgpt_zip(path, db_path)
    elif ingest_type == "chatgpt_memory":
        from memory_hub.ingest.chatgpt_memory import ingest_chatgpt_memory
        return ingest_chatgpt_memory(path, db_path)
    elif ingest_type == "claude_zip":
        from memory_hub.ingest.claude import ingest_claude_zip
        return ingest_claude_zip(path, db_path)
    elif ingest_type == "chatgpt_folder":
        # Folder containing conversations.json — find it and ingest
        from memory_hub.ingest.chatgpt import ingest_chatgpt_zip
        # The folder itself isn't a ZIP, but the parent data-* dir may be
        # Look for conversations.json inside
        conv_json = path if path.is_file() else path / "conversations.json"
        if conv_json.exists():
            # Create a temporary reference — the ingest function expects ZIP
            # but we have a folder. Use the folder-based ingest path.
            from memory_hub.ingest.chatgpt import ingest_chatgpt_zip
            # For folder exports, we need to handle differently
            return _ingest_chatgpt_folder(conv_json, db_path)
    raise ValueError(f"Unknown ingest type: {ingest_type}")


def _ingest_chatgpt_folder(conversations_json: Path, db_path: Path) -> dict:
    """Ingest a ChatGPT conversations.json file directly (non-ZIP)."""
    import json as json_mod
    from memory_hub.ingest.chatgpt import _event_id, _extract_text
    from memory_hub.db import get_connection, insert_event, log_ingest_start, log_ingest_complete
    from datetime import datetime as dt, timezone

    conversations = json_mod.loads(conversations_json.read_text(encoding="utf-8"))
    stats = {"conversations": 0, "messages_added": 0, "messages_skipped": 0}

    with get_connection(db_path) as conn:
        log_id = log_ingest_start(conn, "chatgpt", str(conversations_json))
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
                ts = dt.fromtimestamp(create_time, tz=timezone.utc).isoformat() if create_time else None
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
        log_ingest_complete(conn, log_id, stats["messages_added"], stats["messages_skipped"])
    return stats


def _post_ingest(db_path: Path) -> None:
    """Reconcile and regenerate projections after new ingest."""
    from memory_hub.reconcile import reconcile
    from memory_hub.project.claude_chat import project_claude_chat
    from memory_hub.project.claude_code import project_claude_code
    from memory_hub.project.openclaw import project_openclaw
    reconcile(db_path)
    project_claude_chat(db_path=db_path)
    project_claude_code(deploy=False, db_path=db_path)
    project_openclaw(deploy=False, db_path=db_path)


def _check_stale_sources(state: dict) -> list[str]:
    """Return reminder strings for sources not ingested in >7 days."""
    reminders = []
    now = datetime.now()
    for source, label in [("chatgpt", "ChatGPT"), ("claude", "Claude.ai")]:
        last = state.get("last_ingest", {}).get(source)
        if last:
            try:
                last_dt = datetime.fromisoformat(last)
                days = (now - last_dt).days
                if days > 7:
                    reminders.append(f"{label} export is {days} days old — consider requesting a new one")
            except (ValueError, TypeError):
                reminders.append(f"{label} last ingest date is invalid — consider re-exporting")
        else:
            reminders.append(f"No {label} export has been ingested yet")
    return reminders


def _write_watcher_report(events: list) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    path = REPORTS_DIR / f"watcher_{ts}.md"
    lines = [f"# Watcher Report — {ts}", ""]
    for e in events:
        lines.append(f"- {e}")
    path.write_text("\n".join(lines), encoding="utf-8")


def scan_once(db_path: Path = DB_PATH) -> dict:
    """
    Single scan pass. Returns dict with events list and reminders.
    Safe to call from Task Scheduler, OpenClaw heartbeat, or CLI.
    """
    state = _load_state()
    events = []
    new_files_found = False

    # ── Check ~/Downloads for new exports ──
    if DOWNLOADS_DIR.exists():
        # Detect ZIPs by peeking at contents (not filename patterns)
        for zip_path in sorted(DOWNLOADS_DIR.glob(DOWNLOADS_ZIP_GLOB)):
            if not zip_path.is_file():
                continue
            state_key = str(zip_path.resolve())
            if state.get("files", {}).get(state_key):
                continue  # already processed

            source = _detect_zip_source(zip_path)
            if source == "chatgpt":
                dest_subdir = "chatgpt_exports"
            elif source == "claude":
                dest_subdir = "claude_exports"
            else:
                events.append(f"Skipped unrecognized ZIP in Downloads: {zip_path.name}")
                continue

            events.append(f"New {source} export in Downloads: {zip_path.name}")
            try:
                moved = _move_from_downloads(zip_path, dest_subdir)
                events.append(f"  Moved to: {moved.relative_to(RAW_DIR)}")
            except Exception as exc:
                events.append(f"  Move failed: {exc}")
                continue

        # Detect unzipped ChatGPT folder exports (data-* folders with conversations.json)
        for folder in sorted(DOWNLOADS_DIR.glob(DOWNLOADS_FOLDER_PATTERN)):
            if not folder.is_dir():
                continue
            if not (folder / "conversations.json").exists():
                continue
            state_key = str(folder.resolve())
            if state.get("files", {}).get(state_key):
                continue

            events.append(f"New ChatGPT folder export in Downloads: {folder.name}")
            try:
                moved = _move_from_downloads(folder, "chatgpt_exports")
                events.append(f"  Moved to: {moved.relative_to(RAW_DIR)}")
            except Exception as exc:
                events.append(f"  Move failed: {exc}")
                continue

    # ── Check raw directories for new files ──
    for subdir, pattern, ingest_type in RAW_WATCH_SPECS:
        watch_dir = RAW_DIR / subdir
        if not watch_dir.exists():
            continue
        for path in sorted(watch_dir.glob(pattern)):
            if not path.is_file():
                continue
            file_hash = _file_hash(path)
            state_key = str(path.resolve())
            if state.get("files", {}).get(state_key) == file_hash:
                continue  # already processed

            events.append(f"New file: {path.name} ({ingest_type})")
            try:
                stats = _ingest_file(path, ingest_type, db_path)
                events.append(f"  Ingested: {stats}")
                if "files" not in state:
                    state["files"] = {}
                state["files"][state_key] = file_hash
                # Track last ingest time per source
                source = "chatgpt" if "chatgpt" in ingest_type else "claude"
                if "last_ingest" not in state:
                    state["last_ingest"] = {}
                state["last_ingest"][source] = datetime.now().isoformat()
                _save_state(state)
                archived = _archive_file(path)
                events.append(f"  Archived to: {archived.relative_to(RAW_DIR)}")
                new_files_found = True
            except Exception as exc:
                events.append(f"  ERROR: {exc}")

    # ── Auto-ingest API-based sources (always safe to re-run, dedup handles it) ──
    try:
        from memory_hub.ingest.claude_code import ingest_claude_code
        cc_stats = ingest_claude_code(db_path=db_path)
        if cc_stats["messages_added"] > 0:
            events.append(f"Claude Code: {cc_stats['messages_added']} new messages from {cc_stats['sessions_found']} sessions")
            new_files_found = True
    except Exception as exc:
        events.append(f"Claude Code ingest skipped: {exc}")

    try:
        from memory_hub.ingest.github import ingest_github
        gh_stats = ingest_github(db_path=db_path)
        if gh_stats["events_added"] > 0:
            events.append(f"GitHub: {gh_stats['events_added']} new events from {gh_stats['repos_found']} repos")
            new_files_found = True
    except Exception as exc:
        events.append(f"GitHub ingest skipped: {exc}")

    # ── Post-ingest if anything new was found ──
    if new_files_found:
        try:
            _post_ingest(db_path)
            events.append("Post-ingest: reconcile + projections complete")
        except Exception as exc:
            events.append(f"Post-ingest ERROR: {exc}")

    # ── Stale source reminders ──
    reminders = _check_stale_sources(state)

    if events:
        _write_watcher_report(events)

    return {"events": events, "reminders": reminders}


def watch_loop(interval: int = POLL_INTERVAL_SECONDS, db_path: Path = DB_PATH) -> None:
    """Blocking poll loop. Run as `hub watch`."""
    while True:
        try:
            scan_once(db_path)
        except Exception:
            pass  # Never crash the watcher loop
        time.sleep(interval)
