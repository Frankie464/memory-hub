# memory-hub

Local cross-AI memory management system. Ingests conversation history from ChatGPT, Claude, and OpenClaw, normalizes it into a SQLite database, extracts memory facts via pattern matching, and generates platform-specific "projections" that keep all your AIs in sync.

**Primary interface:** Streamlit web dashboard (`hub gui`)
**Automation:** CLI commands + Windows Task Scheduler scripts

## Quick Start

```bash
git clone https://github.com/Frankie464/memory-hub.git
cd memory-hub/memory_hub
pip install -e .
hub init
hub gui          # Opens dashboard at http://localhost:8501
```

Or just double-click `launch.bat` (Windows) / run `./launch.sh` (Mac/Linux) after install.

## Requirements

- Python 3.10+
- pip

## What It Does

1. **Ingest** raw exports from ChatGPT (ZIP), Claude (memory export .md), and OpenClaw
2. **Reconcile** — extract facts (identity, preferences, work, interests, relationships, financial, lifestyle) using pattern matching
3. **Project** — generate platform-specific memory files for each AI
4. **Deploy** — optionally write projections to each platform's actual config location
5. **Sync** — automated weekly/monthly workflows that chain ingest + reconcile + project

## Setup on a New Machine

1. Clone the repo
2. `cd memory_hub && pip install -e .`
3. `hub init` — creates `data/` directories and SQLite database
4. Double-click `launch.bat` or run `hub gui` — opens the dashboard with a guided Setup Wizard

The Setup Wizard walks you through everything step by step (import data, build profile, deploy to platforms).

## Launching the Dashboard

**Easiest:** Double-click `launch.bat` (Windows) or run `./launch.sh` (Mac/Linux). Opens at http://localhost:8501.

**From terminal:** `hub gui`

**Create a desktop shortcut (Windows):** Right-click `launch.bat` -> Send to -> Desktop (create shortcut). Rename it to "memory-hub". You can also pin it to your taskbar.

---

## When Your ChatGPT Export Arrives

1. Download the ZIP from the email link
2. Either:
   - **GUI:** Open the dashboard -> Setup Wizard -> Step 4, upload the ZIP
   - **CLI:** Copy the ZIP to `data/raw/chatgpt_exports/` then run:
     ```bash
     hub ingest chatgpt --zip data/raw/chatgpt_exports/your_export.zip
     hub reconcile
     ```
3. Generate updated projections: `hub project chatgpt` (and any other platforms you want)

---

## Per-Platform Instructions

### ChatGPT Memory Dump (Optional)

If you asked ChatGPT to list all its stored memories about you (the `[date] - content` format),
you can import that dump as a quick bootstrap:

```bash
# Copy the .md file to data/raw/chatgpt_exports/
hub ingest chatgpt-memory --file data/raw/chatgpt_exports/your_memory_dump.md
hub reconcile
```

This is optional if you already have the full ChatGPT conversation ZIP (Step 1 above).

### Claude.ai (Web Chat)

**Push memories to Claude.ai:**
```bash
hub project claude-chat
```
This generates chunked `.md` files in `data/projections/claude_ai/`. Open each file and paste the content into a new Claude.ai chat with: *"Please save these as your memories about me."*

### Claude Code (VS Code Extension / CLI)

**Generate projection files:**
```bash
hub project claude-code           # Preview only (writes to data/projections/claude_code/)
hub project claude-code --deploy  # Writes to ~/.claude/CLAUDE.md + ~/.claude/rules/
```

**What gets deployed:**
- `~/.claude/CLAUDE.md` — personal context block (safely inserted between `<!-- BEGIN MEMORY_HUB -->` / `<!-- END MEMORY_HUB -->` markers; your existing content is preserved)
- `~/.claude/rules/personal-context.md` — relationships, lifestyle, financial context
- `~/.claude/rules/work-domain.md` — work domain context

### OpenClaw

**Generate memory files:**
```bash
hub project openclaw                                    # Preview only
hub project openclaw --deploy --openclaw-dir /path/to/openclaw/memory  # Deploy
```

**What gets deployed:**
- `MEMORY.md` — main persistent memory file
- `memory/YYYY-MM-DD.md` — dated snapshot

Find your OpenClaw memory directory in OpenClaw -> Settings -> Memory.

### ChatGPT

**Export your full history:**
1. Go to [chatgpt.com](https://chatgpt.com) -> Settings -> Data Controls -> Export Data
2. Confirm via email, wait for the download (can take hours)
3. Download the ZIP

**Import into memory-hub:**
```bash
# Copy ZIP to data/raw/chatgpt_exports/
hub ingest chatgpt --zip data/raw/chatgpt_exports/export.zip
hub reconcile
```

**Push profile back to ChatGPT:**
```bash
hub project chatgpt
```
This generates three files in `data/projections/chatgpt/`:
- `profile_pack.md` — portable profile summary
- `custom_instructions.md` — paste into ChatGPT -> Settings -> Personalization -> Custom Instructions
- `memory_refresh_prompt.md` — paste into a new ChatGPT chat to have it memorize your context

---

## CLI Reference

| Command | Description |
|---------|-------------|
| `hub init` | Create data directories and initialize database |
| `hub gui` | Launch Streamlit web dashboard |
| `hub ingest chatgpt --zip <path>` | Ingest ChatGPT export ZIP |
| `hub ingest chatgpt-memory --file <path>` | Ingest ChatGPT memory dump |
| `hub reconcile` | Extract facts from events, detect conflicts |
| `hub project claude-chat` | Generate Claude.ai memory import chunks |
| `hub project claude-code [--deploy]` | Generate/deploy Claude Code files |
| `hub project openclaw [--deploy]` | Generate/deploy OpenClaw memory files |
| `hub project chatgpt` | Generate ChatGPT profile pack |
| `hub search <query>` | Full-text search across all ingested history |
| `hub sync --profile weekly` | Run weekly sync workflow |
| `hub sync --profile monthly` | Run monthly sync workflow |
| `hub status` | Show database stats and projection status |

## How Sync Works

The sync system keeps all your AIs up to date with a single command. Here's the data flow:

```
Export from AI  ->  Ingest  ->  Reconcile  ->  Project  ->  Deploy
(ZIP or .md)     (parse +     (extract      (generate     (write to
                  store)       facts)        per-platform)  platform)
```

**Weekly sync** (`hub sync --profile weekly`):
1. Auto-finds the latest ChatGPT memory dump (`.md`) in `data/raw/chatgpt_exports/`
2. Ingests it (skips duplicates)
3. Runs reconcile to extract/update facts
4. Generates projections for Claude.ai, Claude Code, and OpenClaw
5. Writes a timestamped report to `reports/`

**Monthly sync** (`hub sync --profile monthly`):
1. Auto-finds the latest ChatGPT conversation ZIP in `data/raw/chatgpt_exports/`
2. Also ingests latest ChatGPT memory dump (if available)
3. Reconciles everything
4. Generates projections for ALL platforms (including ChatGPT)
5. Writes a report

**To run manually:**
```bash
hub sync --profile weekly           # Quick sync (memory dump + reconcile + 3 projections)
hub sync --profile monthly          # Full sync (conversations + memories + all projections)
hub sync --profile weekly --deploy  # Sync AND deploy to platform locations
```

**To automate:** See the Task Scheduler section below.

## Automation (Windows Task Scheduler)

PowerShell scripts are in `scripts/`:
- `run_weekly.ps1` — ingest ChatGPT memories + reconcile + project Claude/OpenClaw
- `run_monthly.ps1` — ingest ChatGPT conversations + memories + reconcile + all projections

Register with Task Scheduler (run in PowerShell as Admin):
```powershell
schtasks /create /tn "MemoryHub-Weekly" /tr "powershell -ExecutionPolicy Bypass -File C:\path\to\scripts\run_weekly.ps1" /sc weekly /d SUN /st 20:00
schtasks /create /tn "MemoryHub-Monthly" /tr "powershell -ExecutionPolicy Bypass -File C:\path\to\scripts\run_monthly.ps1" /sc monthly /d 1 /st 20:00
```

For Linux/Mac, use cron:
```bash
# Weekly (Sunday 8pm)
0 20 * * 0 cd /path/to/ChatGPT_Claude && hub sync --profile weekly >> reports/cron.log 2>&1
# Monthly (1st of month 8pm)
0 20 1 * * cd /path/to/ChatGPT_Claude && hub sync --profile monthly >> reports/cron.log 2>&1
```

## Transferring Between Machines

The `data/` directory is machine-specific (created fresh by `hub init`). To set up on a new machine:

1. Clone the git repo
2. `pip install -e .`
3. `hub init`
4. Copy your export files (ChatGPT ZIP, Claude .md) to `data/raw/`
5. Run `hub ingest` + `hub reconcile` to rebuild the database

The source code, scripts, and seed data are all in the repo. The database and projections are regenerated per-machine.

## Architecture

- **SQLite + FTS5** — canonical store with full-text search
- **Pattern-based reconciliation** — no LLM API calls, no cost, fast
- **Two-file profile** — `user_profile.manual.md` (human-edited, never overwritten) + `user_profile.generated.md` (auto-rebuilt)
- **Deploy is always opt-in** — `hub project` generates to `data/projections/`; `--deploy` flag writes to actual platform locations
