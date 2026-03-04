"""Click CLI entry point for memory-hub."""
import io
import shutil
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
    CANONICAL_DIR,
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
    SEED_EXPORT_PATH,
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

    # Copy seed export if it exists and hasn't been copied yet
    dest = CANONICAL_DIR / "user_memory_export.md"
    if SEED_EXPORT_PATH.exists() and not dest.exists():
        shutil.copy2(SEED_EXPORT_PATH, dest)
        console.print(f"  [green]OK[/green] Copied seed export to {dest}")
    elif dest.exists():
        console.print(f"  [dim]- Seed export already in canonical dir[/dim]")

    # Create empty changelog if missing
    if not CHANGELOG_PATH.exists():
        CHANGELOG_PATH.write_text("# Changelog\n", encoding="utf-8")
        console.print(f"  [green]OK[/green] Created changelog")

    # Create empty manual profile placeholder if missing
    if not PROFILE_MANUAL_PATH.exists():
        PROFILE_MANUAL_PATH.write_text(
            "# the user - Manual Profile\n"
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


# ── hub reconcile ─────────────────────────────────────────────────────────────

@cli.command()
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=None)
def reconcile(db_path: Path):
    """Extract facts from events and detect conflicts."""
    from memory_hub.reconcile import reconcile as do_reconcile
    _db = db_path or DB_PATH
    console.print("[bold]Running reconciliation...[/bold]")
    with console.status("Scanning events and extracting facts..."):
        stats = do_reconcile(_db)
    console.print(
        f"  [green]OK[/green] {stats['facts_added']} new facts, "
        f"{stats['facts_confirmed']} confirmed, "
        f"{stats['conflicts_added']} conflicts"
    )
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


# ── hub search ────────────────────────────────────────────────────────────────

@cli.command()
@click.argument("query")
@click.option("--limit", default=20, show_default=True, help="Max results to return")
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=None)
def search(query: str, limit: int, db_path: Path):
    """Full-text search across all ingested conversations."""
    _db = db_path or DB_PATH
    if not _db.exists():
        console.print("[red]Database not found. Run `hub init` first.[/red]")
        sys.exit(1)

    with get_connection(_db) as conn:
        results = search_events(conn, query, limit)

    if not results:
        console.print(f"[yellow]No results for:[/yellow] {query}")
        return

    table = Table(title=f'Search: "{query}"', box=box.ROUNDED)
    table.add_column("Source", style="cyan", width=8)
    table.add_column("Date", width=12)
    table.add_column("Conversation", width=30)
    table.add_column("Snippet")

    for row in results:
        table.add_row(
            row["source"] or "",
            (row["timestamp_utc"] or "")[:10],
            (row["conversation_title"] or "")[:30],
            row["snippet"] or "",
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
