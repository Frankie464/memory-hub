# Memory Hub — Project Context

## What This Project Is

This is **memory-hub**: a local Python application that serves as a cross-AI memory management system for the user. It ingests conversation history from ChatGPT, Claude, and OpenClaw, normalizes it into a SQLite database, extracts memory facts, and generates platform-specific "projections" (CLAUDE.md additions, Claude.ai memory import chunks, OpenClaw memory files, etc.).

The primary interface is a **Streamlit web dashboard** (`hub gui`). CLI commands exist for automation and scheduling.

## Key Concepts

- **Canonical store**: `data/canonical/hub.db` (SQLite with FTS5)
- **Events**: raw messages from all AI platforms, stored once, deduped by event_id
- **Facts**: distilled memory statements extracted from events via pattern matching
- **Projections**: platform-specific output files generated from facts (never edited manually)
- **Manual profile**: `data/canonical/user_profile.manual.md` — authoritative, NEVER auto-overwritten
- **Generated profile**: `data/canonical/user_profile.generated.md` — rebuilt by `hub reconcile`

## Project Structure

```
memory_hub/
  src/memory_hub/
    cli.py          ← Click CLI (hub command)
    app.py          ← Streamlit dashboard (hub gui)
    config.py       ← All path constants
    db.py           ← SQLite schema + helpers
    ingest/         ← Parsers for each platform
    project/        ← Projection generators for each platform
    reconcile.py    ← Fact extraction + conflict detection
    sync.py         ← Scheduled sync orchestration
data/
  raw/              ← Raw exports (never modified)
  canonical/        ← hub.db, profiles, changelog
  history/          ← chatgpt2md markdown output
  projections/      ← Generated platform files
reports/            ← Sync reports and logs
scripts/            ← PowerShell wrapper scripts for Task Scheduler
```

## Important Patterns

- `deploy` is always opt-in (`--deploy` flag or "Deploy" button in GUI). Generate first, review, then deploy.
- CLAUDE.md modifications use `<!-- BEGIN MEMORY_HUB -->` / `<!-- END MEMORY_HUB -->` marker blocks to prevent duplication.
- FTS index is maintained via INSERT/UPDATE/DELETE triggers on the events table.
- Role column in events is unconstrained TEXT (ChatGPT uses tool/developer/unknown roles beyond user/assistant/system).
- Dedup: event_id = SHA256(conversation_id + message_id) for ChatGPT conversations; content hash for ChatGPT memory dumps.

## Install & Run

```bash
cd memory_hub
pip install -e .
hub init          # Initialize data dirs + DB
hub gui           # Launch Streamlit dashboard at localhost:8501
hub ingest chatgpt --zip path/to/export.zip
hub ingest chatgpt-memory --file path/to/memory_dump.md
hub reconcile
hub project claude-code --deploy
hub sync --profile weekly
```

## Dependencies

- Python 3.10+
- `click` — CLI
- `rich` — terminal output
- `streamlit` — web dashboard
- SQLite + FTS5 (built into Python)

## External Tool: chatgpt2md

chatgpt2md (Rust binary) handles the markdown archive + MCP server separately from the hub.
Binary lives in PATH. Markdown output goes to `data/history/`.

## v1 vs v2 Scope

v1 (built): init, ingest chatgpt (ZIP + memory dump), reconcile, project all platforms, search, sync, Streamlit GUI
v2 (deferred): interactive facts browser, conflicts resolver, OpenClaw log ingestion, cross-AI verify suite
