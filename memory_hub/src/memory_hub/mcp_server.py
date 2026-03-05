"""
MCP server for memory-hub — stdio transport, read-only.

Exposes the user's canonical memory DB to AI assistants (e.g. OpenClaw)
via the Model Context Protocol. Three tools: search, facts, status.

Launch: python -m memory_hub.mcp_server
Config: { "command": "hub-mcp" }
"""
import io
import re
import sys

# Force UTF-8 on Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

from memory_hub.config import DB_PATH
from memory_hub.db import (
    get_ro_connection, get_connection, _sanitize_fts_query,
    get_active_facts, get_stats, search_hybrid, search_summaries,
)

MAX_RESULTS = 10
MAX_SNIPPET_LEN = 300
MAX_FACT_LEN = 200

VALID_CATEGORIES = frozenset({
    "identity", "preference", "work", "interest",
    "relationship", "lifestyle", "financial",
})


def _truncate(text: str, max_len: int) -> str:
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text


app = Server("memory-hub")


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="search_memories",
            description=(
                "Search the user's memory database for relevant context using hybrid "
                "keyword + semantic search. Use this to find past conversations about any topic."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search terms (natural language ok)"},
                    "limit": {"type": "integer", "default": 5, "maximum": MAX_RESULTS},
                    "mode": {
                        "type": "string",
                        "enum": ["hybrid", "keyword", "semantic"],
                        "default": "hybrid",
                        "description": "Search mode: hybrid (default), keyword, or semantic",
                    },
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="search_conversations",
            description=(
                "Search conversation summaries to quickly find what topics were discussed. "
                "Returns summaries with key topics and decisions."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Topic or keyword to search for"},
                    "limit": {"type": "integer", "default": 5, "maximum": MAX_RESULTS},
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="get_facts",
            description="Retrieve stored facts about the user, optionally filtered by category.",
            inputSchema={
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": sorted(VALID_CATEGORIES),
                        "description": "Optional category filter",
                    }
                },
            },
        ),
        types.Tool(
            name="get_status",
            description="Check memory database stats and whether any sources need refreshing.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if not DB_PATH.exists():
        return [types.TextContent(type="text", text="Memory database not initialized.")]

    try:
        if name == "search_memories":
            return _handle_search(arguments)
        elif name == "search_conversations":
            return _handle_search_conversations(arguments)
        elif name == "get_facts":
            return _handle_facts(arguments)
        elif name == "get_status":
            return _handle_status()
        return [types.TextContent(type="text", text="Unknown tool.")]
    except Exception as e:
        return [types.TextContent(type="text", text=f"Memory service temporarily unavailable: {e}")]


def _handle_search(arguments: dict) -> list[types.TextContent]:
    query = str(arguments.get("query", "")).strip()
    if not query:
        return [types.TextContent(type="text", text="No query provided.")]

    limit = min(int(arguments.get("limit", 5)), MAX_RESULTS)
    mode = arguments.get("mode", "hybrid")

    with get_connection() as conn:
        if mode == "keyword":
            fts_query = _sanitize_fts_query(query)
            try:
                rows = conn.execute(
                    """SELECT e.source, e.timestamp_utc, e.conversation_title,
                              snippet(events_fts, 0, '', '', '...', 30) AS snippet
                       FROM events_fts
                       JOIN events e ON e.rowid = events_fts.rowid
                       WHERE events_fts MATCH ?
                       ORDER BY rank LIMIT ?""",
                    (fts_query, limit),
                ).fetchall()
            except Exception:
                rows = []
            if not rows:
                return [types.TextContent(type="text", text="No matching memories found.")]
            lines = []
            for r in rows:
                snippet = _truncate(r["snippet"] or "", MAX_SNIPPET_LEN)
                title = (r["conversation_title"] or "")[:50]
                date = (r["timestamp_utc"] or "")[:10]
                lines.append(f"[{r['source']}|{date}] {title}: {snippet}")
            return [types.TextContent(type="text", text="\n\n".join(lines))]
        else:
            # hybrid (default) or semantic
            try:
                results = search_hybrid(conn, query, limit=limit)
            except Exception:
                results = []
            if not results:
                return [types.TextContent(type="text", text="No matching memories found.")]
            lines = []
            for r in results:
                snippet = _truncate(r.get("snippet") or "", MAX_SNIPPET_LEN)
                title = (r.get("conversation_title") or "")[:50]
                date = (r.get("timestamp_utc") or "")[:10]
                source = r.get("source") or ""
                lines.append(f"[{source}|{date}] {title}: {snippet}")
            return [types.TextContent(type="text", text="\n\n".join(lines))]


def _handle_search_conversations(arguments: dict) -> list[types.TextContent]:
    query = str(arguments.get("query", "")).strip()
    if not query:
        return [types.TextContent(type="text", text="No query provided.")]

    limit = min(int(arguments.get("limit", 5)), MAX_RESULTS)

    with get_connection() as conn:
        rows = search_summaries(conn, query, limit=limit)

    if not rows:
        return [types.TextContent(type="text", text="No conversation summaries found.")]

    import json as _json
    lines = []
    for r in rows:
        topics = ", ".join(_json.loads(r["key_topics"] or "[]"))
        decisions = "; ".join(_json.loads(r["key_decisions"] or "[]"))
        line = f"[{r['source']}|{(r['date_range'] or '')[:10]}] {r['title'] or 'Untitled'}\n  {r['summary']}"
        if topics:
            line += f"\n  Topics: {topics}"
        if decisions:
            line += f"\n  Decisions: {decisions}"
        lines.append(line)
    return [types.TextContent(type="text", text="\n\n".join(lines))]


def _handle_facts(arguments: dict) -> list[types.TextContent]:
    category = arguments.get("category")
    if category and category not in VALID_CATEGORIES:
        return [types.TextContent(type="text", text=f"Invalid category. Valid: {', '.join(sorted(VALID_CATEGORIES))}")]

    with get_ro_connection() as conn:
        facts = get_active_facts(conn, category)

    if not facts:
        return [types.TextContent(type="text", text="No facts found.")]

    lines = []
    for f in facts:
        stmt = _truncate(f["statement"] or "", MAX_FACT_LEN)
        lines.append(f"[{f['category']}] {stmt}")
    return [types.TextContent(type="text", text="\n".join(lines))]


def _handle_status() -> list[types.TextContent]:
    with get_ro_connection() as conn:
        stats = get_stats(conn)

    lines = [
        f"Events: {stats['events']:,}",
        f"Active facts: {stats['facts']}",
        f"Pending conflicts: {stats['pending_conflicts']}",
        f"Last ingest: {stats['last_ingest'] or 'never'}",
        f"Last reconcile: {stats['last_reconcile'] or 'never'}",
    ]
    if stats["projections"]:
        lines.append("Projections:")
        for target, ts in stats["projections"].items():
            lines.append(f"  {target}: {ts or 'never'}")

    # Check for stale sources
    from memory_hub.watcher import _load_state, _check_stale_sources
    state = _load_state()
    reminders = _check_stale_sources(state)
    if reminders:
        lines.append("")
        lines.append("Reminders:")
        for r in reminders:
            lines.append(f"  ! {r}")

    return [types.TextContent(type="text", text="\n".join(lines))]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


def main_sync():
    """Synchronous entry point for console_scripts."""
    import asyncio
    asyncio.run(main())


if __name__ == "__main__":
    main_sync()
