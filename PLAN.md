# Memory-Hub v0.2 — Implementation Plan

## Current State
- 2,504 events across 192 conversations (claude: 1,382, claude_code: 1,110, github: 12)
- 45 regex-extracted facts (many are noise)
- FTS5 keyword search only
- No OpenClaw data, no conversation summaries, fragile watcher

## Changes Overview

Five improvements, ordered by implementation dependency:

| # | Feature | New Files | Modified Files |
|---|---------|-----------|----------------|
| 1 | Smart watcher source detection | — | `watcher.py` |
| 2 | LLM-assisted fact extraction | `llm.py` | `reconcile.py`, `db.py`, `config.py`, `cli.py` |
| 3 | Semantic search (embeddings) | — | `db.py`, `config.py`, `cli.py`, `mcp_server.py` |
| 4 | OpenClaw ingest | `ingest/openclaw.py` | `cli.py`, `watcher.py`, `config.py` |
| 5 | Conversation summaries | — | `db.py`, `reconcile.py`, `cli.py`, `mcp_server.py` |

New dependency: `anthropic` (for LLM calls) and `sentence-transformers` (for embeddings).

---

## 1. Smart Watcher Source Detection

**Problem:** Watcher uses filename globs (`data-*.zip`) which match both ChatGPT and Claude exports. The README claims auto-detection but the code doesn't do it.

**Fix:** After finding a ZIP in Downloads, peek inside before routing:

```python
def _detect_zip_source(zip_path: Path) -> str | None:
    """Peek inside a ZIP to determine if it's ChatGPT or Claude."""
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        # ChatGPT: contains conversations.json at root or in a folder
        for name in names:
            if name.endswith("conversations.json"):
                # Peek at structure: ChatGPT has "mapping" key, Claude has "chat_messages"
                with zf.open(name) as f:
                    data = json.load(f)
                    if isinstance(data, list) and len(data) > 0:
                        sample = data[0]
                        if "mapping" in sample:
                            return "chatgpt"
                        if "chat_messages" in sample:
                            return "claude"
                return "chatgpt"  # conversations.json without clear markers -> assume ChatGPT
        # Claude: look for chat_messages pattern or memories.json
        if any(n.endswith("memories.json") for n in names):
            return "claude"
    return None
```

**Changes to `watcher.py`:**
- Replace `DOWNLOADS_PATTERNS` with a single `*.zip` glob + `_detect_zip_source()`
- Keep folder detection for unzipped ChatGPT exports (those are unambiguous)
- Route detected source to correct ingest function

**Scope:** ~40 lines changed in `watcher.py`, add `import zipfile, json` at top.

---

## 2. LLM-Assisted Fact Extraction

**Problem:** Regex patterns produce noisy facts ("Preference: her", "Preference: the app"). Pattern-based extraction can't understand context.

**Design:**

### New file: `src/memory_hub/llm.py`
Thin wrapper around the Anthropic API (Haiku for cost efficiency):

```python
"""LLM helpers for memory-hub — fact extraction and summarization."""
import json
import os
from anthropic import Anthropic

DEFAULT_MODEL = "claude-haiku-4-5"

def get_client() -> Anthropic:
    """Get Anthropic client. Uses ANTHROPIC_API_KEY env var."""
    return Anthropic()  # auto-reads ANTHROPIC_API_KEY

def extract_facts(messages: list[dict], model: str = DEFAULT_MODEL) -> list[dict]:
    """
    Send a batch of messages to the LLM and extract structured facts.
    
    Input: list of {"role": str, "content": str, "conversation_title": str}
    Output: list of {"category": str, "statement": str, "confidence": float}
    """
    # Format messages into a readable block
    text_block = "\n\n".join(
        f"[{m['role']}] ({m.get('conversation_title', 'Unknown')}): {m['content'][:500]}"
        for m in messages
    )
    
    client = get_client()
    response = client.messages.create(
        model=model,
        max_tokens=2000,
        messages=[{
            "role": "user",
            "content": FACT_EXTRACTION_PROMPT.format(messages=text_block)
        }]
    )
    
    # Parse structured JSON response
    return _parse_facts_response(response.content[0].text)

FACT_EXTRACTION_PROMPT = """Analyze these conversation messages. Extract factual statements about the user (the "user" role messages represent the user speaking).

ONLY extract facts that are clearly stated or strongly implied. Skip opinions about external topics, transient requests, and conversational filler.

Categories: identity, work, preference, relationship, financial, lifestyle, interest

For each fact, provide:
- category: one of the categories above
- statement: concise factual statement (e.g., "Lives in Springfield", "Works at Acme as Software Engineer")  
- confidence: 0.0-1.0 (1.0 = explicitly stated, 0.5 = implied)

Return JSON array only. No commentary.

Example output:
[
  {{"category": "identity", "statement": "Lives in Springfield", "confidence": 1.0}},
  {{"category": "work", "statement": "Software Engineer at Acme", "confidence": 1.0}}
]

Messages:
{messages}"""
```

### Changes to `reconcile.py`:
- Add `--llm` flag (default: True if ANTHROPIC_API_KEY is set)
- Keep regex extraction as fallback when no API key
- Process in batches of ~20 messages (balances context vs cost)
- Only process messages not yet reconciled (track via `reconcile_log` or a new `last_reconciled_rowid` field)
- Deduplicate LLM-extracted facts against existing facts (same category + similar statement = update confidence, don't duplicate)

### Batching strategy:
- Group messages by conversation_id
- For each conversation, send user messages only (assistant responses add noise)
- Skip conversations already fully reconciled (check against ingest timestamps)
- Batch size: ~20 user messages per LLM call
- With 685 user messages: ~35 API calls for initial backfill, ~$0.10 with Haiku

### Changes to `db.py`:
- Add `reconciled_at` column to events table (migration v3)
- Helper: `get_unreconciled_events(conn, limit) -> list`

### Changes to `cli.py`:
- `hub reconcile` gets `--llm/--no-llm` flag
- `hub reconcile --backfill` processes all unreconciled events (one-time catch-up)

### Cost estimate:
- Initial backfill (685 user msgs): ~35 calls x ~1K input tokens x ~200 output tokens = ~$0.07
- Weekly sync (new messages only): 1-5 calls, < $0.01
- Negligible ongoing cost

---

## 3. Semantic Search (Embeddings)

**Problem:** FTS5 is keyword-only. "bike" misses "cycling" / "gravel". Need semantic similarity.

**Design:**

### Embedding model: `all-MiniLM-L6-v2` (sentence-transformers)
- 384-dimensional embeddings
- ~80MB model, runs locally, no API cost
- Fast: ~1000 sentences/second on CPU

### Schema changes (`db.py`, migration v3):
```sql
CREATE TABLE IF NOT EXISTS embeddings (
    event_id TEXT PRIMARY KEY,
    embedding BLOB NOT NULL,
    model TEXT DEFAULT 'all-MiniLM-L6-v2',
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (event_id) REFERENCES events(event_id)
);
```

Using BLOB for numpy arrays (384 floats x 4 bytes = 1.5KB per event). Total for 2,504 events: ~3.7MB. Very manageable.

### New functions in `db.py`:
```python
def embed_text(text: str) -> bytes:
    """Embed a single text string, return as bytes."""
    # Lazy-load model (singleton)
    ...

def embed_batch(texts: list[str]) -> list[bytes]:
    """Embed a batch of texts efficiently."""
    ...

def search_semantic(conn, query: str, limit: int = 10) -> list:
    """Embed query, compute cosine similarity against all embeddings, return top-K."""
    ...

def search_hybrid(conn, query: str, limit: int = 10) -> list:
    """Combine FTS5 rank + embedding similarity for best results."""
    ...
```

### Hybrid search strategy:
1. Run FTS5 query -> get top 50 candidates with rank scores
2. Run semantic query -> get top 50 candidates with cosine scores
3. Merge using reciprocal rank fusion (RRF): `score = 1/(k+rank_fts) + 1/(k+rank_embed)`
4. Return top `limit` results

This gives you keyword precision (exact matches rank high) plus semantic recall (conceptual matches appear).

### Embedding pipeline:
- On ingest: auto-embed new events (batch for efficiency)
- Migration backfill: `hub embed --backfill` to embed all existing events
- CLI: `hub search` gets `--semantic` flag (default: hybrid)
- MCP: `search_memories` uses hybrid by default

### Changes:
- `db.py`: New table, embed functions, hybrid search
- `config.py`: Add `EMBEDDING_MODEL` constant
- `cli.py`: Add `hub embed` command, update `hub search` with `--mode` flag
- `mcp_server.py`: Update `search_memories` to use hybrid search
- `pyproject.toml`: Add `sentence-transformers` dependency

### Performance:
- Initial backfill (2,504 events): ~3 seconds on CPU
- Per-query: ~10ms embed + ~50ms scan (fine for 10K+ events; consider FAISS if it grows past 100K)

---

## 4. OpenClaw Ingest

**Problem:** Conversations with the user (the richest source of current context) aren't in the database.

**Design:**

### New file: `src/memory_hub/ingest/openclaw.py`

Two data sources:
1. **Memory files**: `~/.openclaw/workspace/memory/*.md` (daily logs)
2. **MEMORY.md**: `~/.openclaw/workspace/MEMORY.md` (curated long-term memory)

```python
"""Ingest OpenClaw workspace memory files into events."""

def ingest_openclaw(workspace_dir: Path = None, db_path: Path = DB_PATH) -> dict:
    """
    Parse OpenClaw memory files and insert as events.
    
    - memory/YYYY-MM-DD.md files -> individual events per section/paragraph
    - MEMORY.md -> system-role summary events (like Claude stored memories)
    
    Returns stats dict.
    """
```

### Parsing strategy:
- Daily files (`memory/YYYY-MM-DD.md`): Split by `##` headers or `---` dividers. Each section becomes an event with timestamp derived from filename.
- `MEMORY.md`: Split by `##` headers. Each section becomes a system-role event (similar to how Claude stored memories are handled).
- Event ID: `sha256(openclaw:{filepath}:{section_hash})` for dedup across re-ingests.

### Changes:
- New file: `src/memory_hub/ingest/openclaw.py`
- `cli.py`: Add `hub ingest openclaw` command with `--workspace` option (defaults to `~/.openclaw/workspace`)
- `watcher.py`: Add OpenClaw to auto-ingest sources (check mtime of memory files)
- `config.py`: Add `OPENCLAW_WORKSPACE` path constant

### Auto-sync in watcher:
Since OpenClaw memory files change frequently (every session), the watcher should:
- Check mtime of `~/.openclaw/workspace/memory/` directory
- Only re-ingest files modified since last scan
- This runs automatically in `hub watch --once` alongside Claude Code and GitHub

---

## 5. Conversation Summaries

**Problem:** Raw messages are stored but there's no way to quickly understand what a conversation was about. Search results show snippets but lack context.

**Design:**

### Schema changes (`db.py`, migration v3):
```sql
CREATE TABLE IF NOT EXISTS conversation_summaries (
    conversation_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    title TEXT,
    summary TEXT NOT NULL,
    key_topics TEXT DEFAULT '[]',
    key_decisions TEXT DEFAULT '[]',
    message_count INTEGER,
    date_range TEXT,
    generated_at TEXT DEFAULT (datetime('now'))
);
```

### Summary generation (in `reconcile.py` or new `summarize.py`):
- Group events by conversation_id
- For each unsummarized conversation with 3+ messages:
  - Send first message + last 5 messages + title to Haiku
  - Get back: 2-3 sentence summary, list of topics, list of decisions/outcomes
  - Store in `conversation_summaries`

### LLM prompt:
```
Summarize this conversation between the user and an AI assistant.

Title: {title}
Messages: {messages}

Return JSON:
{
  "summary": "2-3 sentence summary of what was discussed and any outcomes",
  "key_topics": ["topic1", "topic2"],
  "key_decisions": ["decision1", "decision2"]  // empty if none
}
```

### Batching:
- Can batch multiple short conversations into one LLM call
- For 192 conversations: ~40-50 API calls, ~$0.15 one-time
- New conversations summarized during weekly sync

### Integration:
- `hub search` shows conversation summary alongside snippets
- `mcp_server.py`: Add `search_conversations` tool that searches summaries
- `hub summarize --backfill` for initial generation
- Auto-generate during reconcile for new conversations

### Changes:
- `db.py`: New table, helpers
- `reconcile.py` or new `summarize.py`: Summary generation logic
- `cli.py`: Add `hub summarize` command
- `mcp_server.py`: Update search results to include summaries, add `search_conversations` tool

---

## Migration v3 (all schema changes in one migration)

In `db.py._run_migrations()`, add version 3:

```python
if version < 3:
    conn.executescript("""
        -- Track which events have been LLM-reconciled
        ALTER TABLE events ADD COLUMN reconciled_at TEXT;
        
        -- Embeddings table
        CREATE TABLE IF NOT EXISTS embeddings (
            event_id TEXT PRIMARY KEY,
            embedding BLOB NOT NULL,
            model TEXT DEFAULT 'all-MiniLM-L6-v2',
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (event_id) REFERENCES events(event_id)
        );
        
        -- Conversation summaries
        CREATE TABLE IF NOT EXISTS conversation_summaries (
            conversation_id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            title TEXT,
            summary TEXT NOT NULL,
            key_topics TEXT DEFAULT '[]',
            key_decisions TEXT DEFAULT '[]',
            message_count INTEGER,
            date_range TEXT,
            generated_at TEXT DEFAULT (datetime('now'))
        );
        
        PRAGMA user_version = 3;
    """)
```

---

## New Dependencies

```toml
dependencies = [
    "click>=8.1",
    "rich>=13.0",
    "streamlit>=1.40",
    "pandas>=1.4",
    "mcp>=1.0",
    "anthropic>=0.40",
    "sentence-transformers>=3.0",
]
```

`sentence-transformers` pulls in `torch` (~2GB download). Acceptable tradeoff for local semantic search with zero ongoing cost. The model itself is ~80MB and loads in ~2 seconds.

Alternative: Use Anthropic's embedding API (`voyage-3-lite`) to avoid the torch dependency. Tradeoff: ~$0.003 per 1K events for embedding, but install stays lightweight. **Decision:** local torch vs API embeddings.

---

## Implementation Order

```
Phase 1: Foundation (no new deps)
  1a. Smart watcher source detection (watcher.py only)
  1b. DB migration v3 (schema changes)
  1c. OpenClaw ingest module

Phase 2: LLM features (needs anthropic)  
  2a. llm.py helper module
  2b. LLM fact extraction in reconcile.py
  2c. Conversation summaries

Phase 3: Semantic search (needs sentence-transformers or anthropic embeddings)
  3a. Embedding pipeline
  3b. Hybrid search
  3c. Update MCP server + CLI

Phase 4: Backfill + polish
  4a. hub reconcile --backfill (LLM-extract all existing events)
  4b. hub embed --backfill (embed all existing events)  
  4c. hub summarize --backfill (summarize all conversations)
  4d. Update weekly sync to include new steps
  4e. Tests
```

## File Change Summary

| File | Changes |
|------|---------|
| `pyproject.toml` | Add anthropic, sentence-transformers deps |
| `config.py` | Add EMBEDDING_MODEL, OPENCLAW_WORKSPACE constants |
| `db.py` | Migration v3, embeddings table/helpers, summary table/helpers, reconciled_at tracking |
| `llm.py` | **NEW** — Anthropic wrapper, fact extraction, summarization prompts |
| `reconcile.py` | LLM extraction mode, keep regex as fallback, conversation summaries |
| `ingest/openclaw.py` | **NEW** — OpenClaw workspace memory file parser |
| `watcher.py` | Smart ZIP detection, OpenClaw auto-ingest |
| `cli.py` | New commands: `hub ingest openclaw`, `hub embed`, `hub summarize`; flags: `--llm`, `--semantic` |
| `mcp_server.py` | Hybrid search, conversation search tool, summary in results |
| `sync.py` | Add embedding + summary steps to weekly/monthly workflows |

## Cost Summary

| Operation | Cost |
|-----------|------|
| Initial fact backfill (685 user msgs) | ~$0.07 |
| Initial conversation summaries (192 convos) | ~$0.15 |
| Weekly sync (new messages only) | < $0.02 |
| Embeddings (local sentence-transformers) | $0.00 |
| **Total initial setup** | **~$0.22** |
| **Monthly ongoing** | **< $0.08** |
