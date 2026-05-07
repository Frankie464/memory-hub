"""Click CLI entry point for memory-hub."""
import io
import subprocess
import sys
from pathlib import Path

# Force UTF-8 stdout on Windows (avoids CP1252 UnicodeEncodeErrors)
if sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import click
from rich.console import Console
from rich.table import Table
from rich import box

console = Console()

from memory_hub.config import (
    ALL_DIRS,
    CHANGELOG_PATH,
    DB_PATH,
    PROFILE_GENERATED_PATH,
    PROFILE_MANUAL_PATH,
    PROJ_CLAUDE_AI,
    PROJ_CLAUDE_CODE,
    PROJ_CHATGPT,
    PROJ_OPENCLAW,
    RAW_DIR,
    REPORTS_DIR,
    SCRIPTS_DIR,
)
from memory_hub.db import get_connection, get_stats, init_db, search_events


# ── Root group ────────────────────────────────────────────────────────────────

@click.group()
def cli():
    """memory-hub - cross-AI memory canonical store."""


# ── hub init ──────────────────────────────────────────────────────────────────

@cli.command()
def init():
    """Initialize database and data directories."""
    console.print("[bold cyan]Initializing memory-hub...[/bold cyan]")

    # Create all directories
    for d in ALL_DIRS:
        d.mkdir(parents=True, exist_ok=True)
    console.print(f"  [green]OK[/green] Created {len(ALL_DIRS)} directories")

    # Initialize DB
    init_db(DB_PATH)
    console.print(f"  [green]OK[/green] Database ready: {DB_PATH}")

    # Create empty changelog if missing
    if not CHANGELOG_PATH.exists():
        CHANGELOG_PATH.write_text("# Changelog\n", encoding="utf-8")
        console.print(f"  [green]OK[/green] Created changelog")

    # Create empty manual profile placeholder if missing
    if not PROFILE_MANUAL_PATH.exists():
        PROFILE_MANUAL_PATH.write_text(
            "# Manual Profile\n"
            "# Edit this file to provide curated personal context.\n"
            "# This file is NEVER auto-overwritten by memory-hub.\n\n"
            "## Identity\n\n"
            "## Communication Style\n\n"
            "## Professional\n\n"
            "## Interests\n\n"
            "## Relationships\n\n"
            "## Lifestyle\n\n"
            "## Financial Framework\n",
            encoding="utf-8",
        )
        console.print(f"  [green]OK[/green] Created manual profile template: {PROFILE_MANUAL_PATH}")

    console.print("\n[bold green]Ready.[/bold green] Run [bold]hub gui[/bold] to open the dashboard.")


# ── hub gui ───────────────────────────────────────────────────────────────────

@cli.command()
def gui():
    """Launch the Streamlit web dashboard."""
    app_path = Path(__file__).parent / "app.py"
    if not app_path.exists():
        console.print(f"[red]app.py not found at {app_path}[/red]")
        sys.exit(1)
    console.print("[bold cyan]Starting memory-hub dashboard at http://localhost:8501[/bold cyan]")
    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", str(app_path), "--server.headless", "false"],
        check=False,
    )


# ── hub ingest ────────────────────────────────────────────────────────────────

@cli.group()
def ingest():
    """Ingest data from AI platforms."""


@ingest.command("chatgpt")
@click.option("--zip", "zip_path", required=True, type=click.Path(exists=True, path_type=Path),
              help="Path to ChatGPT export ZIP file")
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=None)
def ingest_chatgpt(zip_path: Path, db_path: Path):
    """Ingest ChatGPT conversations export ZIP."""
    from memory_hub.ingest.chatgpt import ingest_chatgpt_zip
    _db = db_path or DB_PATH
    console.print(f"[bold]Ingesting ChatGPT export:[/bold] {zip_path.name}")
    with console.status("Parsing conversations..."):
        stats = ingest_chatgpt_zip(zip_path, _db)
    console.print(
        f"  [green]OK[/green] {stats['conversations']:,} conversations, "
        f"{stats['messages_added']:,} messages added, "
        f"{stats['messages_skipped']:,} skipped"
    )


@ingest.command("chatgpt-memory")
@click.option("--file", "file_path", required=True, type=click.Path(exists=True, path_type=Path),
              help="Path to ChatGPT memory dump markdown file")
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=None)
def ingest_chatgpt_memory(file_path: Path, db_path: Path):
    """Ingest ChatGPT memory dump markdown file."""
    from memory_hub.ingest.chatgpt_memory import ingest_chatgpt_memory
    _db = db_path or DB_PATH
    console.print(f"[bold]Ingesting ChatGPT memory dump:[/bold] {file_path.name}")
    with console.status("Parsing entries..."):
        stats = ingest_chatgpt_memory(file_path, _db)
    console.print(
        f"  [green]OK[/green] {stats['added']} new entries added, "
        f"{stats['skipped']} skipped"
    )


@ingest.command("claude")
@click.option("--zip", "zip_path", required=True, type=click.Path(exists=True, path_type=Path),
              help="Path to Claude export ZIP file or unzipped folder")
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=None)
def ingest_claude(zip_path: Path, db_path: Path):
    """Ingest Claude conversations and memories export."""
    from memory_hub.ingest.claude import ingest_claude_zip
    _db = db_path or DB_PATH
    console.print(f"[bold]Ingesting Claude export:[/bold] {zip_path.name}")
    with console.status("Parsing conversations and memories..."):
        stats = ingest_claude_zip(zip_path, _db)
    console.print(
        f"  [green]OK[/green] {stats['conversations']:,} conversations, "
        f"{stats['messages_added']:,} messages added, "
        f"{stats['messages_skipped']:,} skipped"
    )
    if stats["memories_added"] or stats["memories_skipped"]:
        console.print(
            f"  [green]OK[/green] {stats['memories_added']} stored memories added, "
            f"{stats['memories_skipped']} skipped"
        )


@ingest.command("github")
@click.option("--username", default=None, help="GitHub username (auto-detected if omitted)")
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=None)
def ingest_github(username: str, db_path: Path):
    """Ingest GitHub repo metadata and READMEs via gh CLI."""
    from memory_hub.ingest.github import ingest_github as do_ingest
    _db = db_path or DB_PATH
    console.print("[bold]Ingesting GitHub repos...[/bold]")
    try:
        with console.status("Fetching repos and READMEs from GitHub API..."):
            stats = do_ingest(username, _db)
        console.print(
            f"  [green]OK[/green] {stats['repos_found']} repos found, "
            f"{stats['readmes_fetched']} READMEs fetched, "
            f"{stats['events_added']:,} events added, "
            f"{stats['events_skipped']:,} skipped"
        )
    except RuntimeError as e:
        console.print(f"  [red]Error:[/red] {e}")
        sys.exit(1)


@ingest.command("claude-code")
@click.option("--dir", "projects_dir", type=click.Path(path_type=Path), default=None,
              help="Path to Claude Code projects dir (default: ~/.claude/projects/)")
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=None)
def ingest_claude_code_cmd(projects_dir: Path, db_path: Path):
    """Ingest Claude Code CLI session logs from ~/.claude/projects/."""
    from memory_hub.ingest.claude_code import ingest_claude_code
    _db = db_path or DB_PATH
    console.print("[bold]Ingesting Claude Code sessions...[/bold]")
    with console.status("Scanning JSONL session files..."):
        stats = ingest_claude_code(projects_dir, _db)
    console.print(
        f"  [green]OK[/green] {stats['files_found']} files, "
        f"{stats['sessions_found']} sessions, "
        f"{stats['messages_added']:,} messages added, "
        f"{stats['messages_skipped']:,} skipped"
    )


@ingest.command("openclaw")
@click.option("--workspace", "workspace_dir", type=click.Path(path_type=Path), default=None,
              help="Path to OpenClaw workspace (default: ~/.openclaw/workspace)")
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=None)
def ingest_openclaw_cmd(workspace_dir: Path, db_path: Path):
    """Ingest OpenClaw workspace memory files (MEMORY.md + daily logs)."""
    from memory_hub.ingest.openclaw import ingest_openclaw
    _db = db_path or DB_PATH
    console.print("[bold]Ingesting OpenClaw workspace memory...[/bold]")
    with console.status("Parsing memory files..."):
        stats = ingest_openclaw(workspace_dir, _db)
    console.print(
        f"  [green]OK[/green] {stats['files_found']} files, "
        f"{stats['messages_added']:,} events added, "
        f"{stats['messages_skipped']:,} skipped"
    )


# ── hub reconcile ─────────────────────────────────────────────────────────────

@cli.command()
@click.option("--llm/--no-llm", default=None,
              help="Use LLM for fact extraction (default: on if ANTHROPIC_API_KEY is set)")
@click.option("--backfill", is_flag=True, default=False,
              help="Process all events, not just unreconciled ones")
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=None)
def reconcile(llm: bool, backfill: bool, db_path: Path):
    """Extract facts from events and detect conflicts."""
    import os
    from memory_hub.reconcile import reconcile as do_reconcile
    _db = db_path or DB_PATH

    # Default: use LLM if API key is available, unless explicitly disabled
    if llm is None:
        llm = bool(os.environ.get("ANTHROPIC_API_KEY"))

    if llm:
        console.print("[bold]Running reconciliation with LLM extraction...[/bold]")
    else:
        console.print("[bold]Running reconciliation (regex only)...[/bold]")

    if backfill:
        console.print("  [dim]Backfill mode: processing all events[/dim]")

    with console.status("Extracting facts..."):
        stats = do_reconcile(_db, use_llm=llm, backfill=backfill)

    console.print(
        f"  [green]OK[/green] {stats['facts_added']} new facts, "
        f"{stats['facts_confirmed']} confirmed, "
        f"{stats['conflicts_added']} conflicts"
    )
    if stats.get("llm_calls"):
        console.print(f"  [dim]LLM calls made: {stats['llm_calls']}[/dim]")
    if PROFILE_GENERATED_PATH.exists():
        console.print(f"  [green]OK[/green] Profile regenerated: {PROFILE_GENERATED_PATH}")


# ── hub project ───────────────────────────────────────────────────────────────

@cli.group()
def project():
    """Generate platform-specific memory projections."""


@project.command("claude-chat")
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=None)
def project_claude_chat(db_path: Path):
    """Generate Claude.ai memory import chunks."""
    from memory_hub.project.claude_chat import project_claude_chat as do_project
    _db = db_path or DB_PATH
    console.print("[bold]Generating Claude.ai memory chunks...[/bold]")
    files = do_project(_db)
    for f in files:
        console.print(f"  [green]OK[/green] {f.name}")
    console.print(f"\n[dim]Output: {PROJ_CLAUDE_AI}[/dim]")
    console.print("\n[bold yellow]Next step:[/bold yellow] Open each file and paste into "
                  "claude.ai -> Profile -> Memory -> Add memories")


@project.command("claude-code")
@click.option("--deploy", is_flag=True, default=False,
              help="Deploy to ~/.claude/ (CLAUDE.md + rules/). Default: preview only.")
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=None)
def project_claude_code_cmd(deploy: bool, db_path: Path):
    """Generate CLAUDE.md additions and rules files for Claude Code."""
    from memory_hub.project.claude_code import project_claude_code as do_project
    _db = db_path or DB_PATH
    action = "Deploying" if deploy else "Generating"
    console.print(f"[bold]{action} Claude Code projection...[/bold]")
    files = do_project(deploy=deploy, db_path=_db)
    for name, path in files.items():
        console.print(f"  [green]OK[/green] {name}: {path}")
    if deploy:
        console.print("\n[green]Deployed to ~/.claude/[/green]")
        console.print("[dim]CLAUDE.md updated (marker block replaced), rules/ updated[/dim]")
    else:
        console.print(f"\n[dim]Preview in: {PROJ_CLAUDE_CODE}[/dim]")
        console.print("[dim]Use --deploy to write to ~/.claude/[/dim]")


@project.command("openclaw")
@click.option("--deploy", is_flag=True, default=False,
              help="Deploy to OpenClaw memory directory.")
@click.option("--openclaw-dir", type=click.Path(path_type=Path), default=None,
              help="Path to OpenClaw workspace memory directory (required with --deploy).")
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=None)
def project_openclaw_cmd(deploy: bool, openclaw_dir: Path, db_path: Path):
    """Generate OpenClaw memory files (MEMORY.md + dated snapshots)."""
    from memory_hub.project.openclaw import project_openclaw as do_project
    _db = db_path or DB_PATH
    if deploy and not openclaw_dir:
        console.print("[red]--openclaw-dir required when using --deploy[/red]")
        sys.exit(1)
    console.print("[bold]Generating OpenClaw projection...[/bold]")
    files = do_project(deploy=deploy, openclaw_memory_dir=openclaw_dir, db_path=_db)
    for name, path in files.items():
        console.print(f"  [green]OK[/green] {name}: {path}")
    if deploy:
        console.print(f"\n[green]Deployed to:[/green] {openclaw_dir}")


@project.command("chatgpt")
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=None)
def project_chatgpt_cmd(db_path: Path):
    """Generate ChatGPT profile pack and custom instructions."""
    from memory_hub.project.chatgpt import project_chatgpt as do_project
    _db = db_path or DB_PATH
    console.print("[bold]Generating ChatGPT projection...[/bold]")
    files = do_project(_db)
    for name, path in files.items():
        console.print(f"  [green]OK[/green] {name}: {path}")
    console.print(f"\n[dim]Output: {PROJ_CHATGPT}[/dim]")


# ── hub embed ─────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--backfill", is_flag=True, default=False,
              help="Embed all events (default: only new events without embeddings)")
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=None)
def embed(backfill: bool, db_path: Path):
    """Generate semantic embeddings for events (enables hybrid search)."""
    from memory_hub.db import (
        get_events_without_embeddings, embed_batch, store_embedding,
        get_connection as _gc,
    )
    _db = db_path or DB_PATH
    if not _db.exists():
        console.print("[red]Database not found. Run `hub init` first.[/red]")
        sys.exit(1)

    with _gc(_db) as conn:
        if backfill:
            events = conn.execute(
                "SELECT event_id, content FROM events ORDER BY ingested_at ASC"
            ).fetchall()
        else:
            events = get_events_without_embeddings(conn)

    if not events:
        console.print("[dim]All events already embedded.[/dim]")
        return

    console.print(f"[bold]Embedding {len(events):,} events...[/bold]")
    CHUNK = 128
    embedded = 0
    with console.status(f"Loading model and embedding...") as status:
        texts = [row["content"] or "" for row in events]
        ids = [row["event_id"] for row in events]

        for i in range(0, len(texts), CHUNK):
            chunk_texts = texts[i: i + CHUNK]
            chunk_ids = ids[i: i + CHUNK]
            blobs = embed_batch(chunk_texts)
            with _gc(_db) as conn:
                for eid, blob in zip(chunk_ids, blobs):
                    store_embedding(conn, eid, blob)
            embedded += len(chunk_ids)
            status.update(f"Embedded {embedded:,}/{len(events):,}...")

    console.print(f"  [green]OK[/green] {embedded:,} events embedded")


# ── hub summarize ─────────────────────────────────────────────────────────────

@cli.command()
@click.option("--backfill", is_flag=True, default=False,
              help="Re-summarize all conversations (default: only unsummarized)")
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=None)
def summarize(backfill: bool, db_path: Path):
    """Generate LLM summaries for conversations (requires ANTHROPIC_API_KEY)."""
    import os
    from memory_hub.reconcile import summarize_conversations
    _db = db_path or DB_PATH
    if not _db.exists():
        console.print("[red]Database not found. Run `hub init` first.[/red]")
        sys.exit(1)

    if not os.environ.get("ANTHROPIC_API_KEY"):
        console.print("[red]ANTHROPIC_API_KEY not set. Cannot generate summaries.[/red]")
        sys.exit(1)

    console.print("[bold]Generating conversation summaries...[/bold]")
    if backfill:
        console.print("  [dim]Backfill mode: processing all conversations[/dim]")

    with console.status("Summarizing..."):
        stats = summarize_conversations(_db, backfill=backfill)

    console.print(
        f"  [green]OK[/green] {stats['summaries_added']} summaries generated, "
        f"{stats['summaries_skipped']} skipped, "
        f"{stats['llm_calls']} LLM calls"
    )


# ── hub search ────────────────────────────────────────────────────────────────

@cli.command()
@click.argument("query")
@click.option("--limit", default=20, show_default=True, help="Max results to return")
@click.option("--mode", type=click.Choice(["keyword", "semantic", "hybrid"]), default="hybrid",
              show_default=True, help="Search mode")
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=None)
def search(query: str, limit: int, mode: str, db_path: Path):
    """Search across all ingested conversations (hybrid by default)."""
    _db = db_path or DB_PATH
    if not _db.exists():
        console.print("[red]Database not found. Run `hub init` first.[/red]")
        sys.exit(1)

    from memory_hub.db import search_hybrid, search_semantic

    with get_connection(_db) as conn:
        if mode == "keyword":
            results = search_events(conn, query, limit)
            # Normalize to common format
            results = [
                {
                    "source": r["source"],
                    "timestamp_utc": r["timestamp_utc"],
                    "conversation_title": r["conversation_title"],
                    "snippet": r["snippet"],
                }
                for r in results
            ]
        elif mode == "semantic":
            sem = search_semantic(conn, query, limit=limit)
            results = []
            for row, score in sem:
                content = row["content"] or ""
                results.append({
                    "source": row["source"],
                    "timestamp_utc": row["timestamp_utc"],
                    "conversation_title": row["conversation_title"],
                    "snippet": (content[:200] + "...") if len(content) > 200 else content,
                })
        else:  # hybrid
            results = search_hybrid(conn, query, limit=limit)

    if not results:
        console.print(f"[yellow]No results for:[/yellow] {query} [dim]({mode})[/dim]")
        return

    table = Table(title=f'Search: "{query}" [{mode}]', box=box.ROUNDED)
    table.add_column("Source", style="cyan", width=8)
    table.add_column("Date", width=12)
    table.add_column("Conversation", width=30)
    table.add_column("Snippet")

    for row in results:
        table.add_row(
            (row.get("source") or "")[:8],
            (row.get("timestamp_utc") or "")[:10],
            (row.get("conversation_title") or "")[:30],
            (row.get("snippet") or "")[:120],
        )
    console.print(table)


# ── hub sync ──────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--profile", type=click.Choice(["weekly", "monthly"]), required=True,
              help="Sync profile to run")
@click.option("--deploy", is_flag=True, default=False,
              help="Deploy projections to platform locations (opt-in)")
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=None)
def sync(profile: str, deploy: bool, db_path: Path):
    """Run a scheduled sync workflow (weekly or monthly)."""
    from memory_hub.sync import sync_weekly, sync_monthly
    _db = db_path or DB_PATH
    console.print(f"[bold cyan]Running {profile} sync...[/bold cyan]")

    with console.status(f"Executing {profile} workflow..."):
        if profile == "weekly":
            results = sync_weekly(deploy=deploy, db_path=_db)
        else:
            results = sync_monthly(deploy=deploy, db_path=_db)

    console.print(f"\n[bold]Steps completed:[/bold]")
    for step in results["steps"]:
        console.print(f"  {step}")

    stats = results.get("stats", {})
    console.print(f"\n[bold]Database stats:[/bold]")
    console.print(f"  Events:            {stats.get('events', 0):,}")
    console.print(f"  Active facts:      {stats.get('facts', 0)}")
    console.print(f"  Pending conflicts: {stats.get('pending_conflicts', 0)}")
    console.print(f"\n[dim]Report: {results.get('report_path', '')}[/dim]")


# ── hub watch ─────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--interval", default=604800, show_default=True,
              help="Poll interval in seconds (default: 1 week)")
@click.option("--once", is_flag=True, default=False,
              help="Run a single scan pass and exit (for cron / OpenClaw heartbeat)")
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=None)
def watch(interval: int, once: bool, db_path: Path):
    """Watch for new exports and auto-ingest them."""
    from memory_hub.watcher import scan_once, watch_loop
    _db = db_path or DB_PATH
    if once:
        console.print("[bold]Running single scan pass...[/bold]")
        result = scan_once(_db)
        for e in result["events"]:
            console.print(f"  {e}")
        if not result["events"]:
            console.print("[dim]No new files found.[/dim]")
        if result["reminders"]:
            console.print("\n[bold yellow]Reminders:[/bold yellow]")
            for r in result["reminders"]:
                console.print(f"  [yellow]![/yellow] {r}")
    else:
        console.print(f"[bold cyan]Watching for new exports (interval: {interval}s)...[/bold cyan]")
        console.print("[dim]Monitors ~/Downloads + data/raw/ directories[/dim]")
        console.print("[dim]Press Ctrl+C to stop[/dim]")
        try:
            watch_loop(interval, _db)
        except KeyboardInterrupt:
            console.print("\n[yellow]Watcher stopped.[/yellow]")


# ── hub status ────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=None)
def status(db_path: Path):
    """Show database stats and projection status."""
    _db = db_path or DB_PATH
    if not _db.exists():
        console.print("[red]Database not found. Run `hub init` first.[/red]")
        sys.exit(1)

    with get_connection(_db) as conn:
        stats = get_stats(conn)

    console.print("[bold cyan]memory-hub status[/bold cyan]\n")
    console.print(f"  Events ingested:   [bold]{stats['events']:,}[/bold]")
    console.print(f"  Active facts:      [bold]{stats['facts']}[/bold]")
    console.print(f"  Pending conflicts: [bold]{stats['pending_conflicts']}[/bold]")
    console.print(f"  Last ingest:       {stats['last_ingest'] or 'never'}")
    console.print(f"  Last reconcile:    {stats['last_reconcile'] or 'never'}")

    if stats["projections"]:
        console.print("\n  [bold]Projections:[/bold]")
        for target, generated_at in stats["projections"].items():
            console.print(f"    {target:<15} {generated_at or 'never'}")
