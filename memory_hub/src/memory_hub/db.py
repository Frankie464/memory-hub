"""SQLite database management — schema, helpers, and connection context."""
import hashlib
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path

from memory_hub.config import DB_PATH

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    source TEXT NOT NULL CHECK(source IN ('chatgpt','claude','openclaw','claude_code','github','gemini')),
    timestamp_utc TEXT,
    role TEXT,
    content TEXT NOT NULL,
    conversation_id TEXT,
    conversation_title TEXT,
    topic_tags TEXT DEFAULT '[]',
    ingested_at TEXT DEFAULT (datetime('now'))
);

CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
    content,
    conversation_title,
    topic_tags,
    content=events,
    content_rowid=rowid
);

CREATE TRIGGER IF NOT EXISTS events_ai AFTER INSERT ON events BEGIN
    INSERT INTO events_fts(rowid, content, conversation_title, topic_tags)
    VALUES (new.rowid, new.content, new.conversation_title, new.topic_tags);
END;

CREATE TRIGGER IF NOT EXISTS events_au AFTER UPDATE ON events BEGIN
    INSERT INTO events_fts(events_fts, rowid, content, conversation_title, topic_tags)
    VALUES ('delete', old.rowid, old.content, old.conversation_title, old.topic_tags);
    INSERT INTO events_fts(rowid, content, conversation_title, topic_tags)
    VALUES (new.rowid, new.content, new.conversation_title, new.topic_tags);
END;

CREATE TRIGGER IF NOT EXISTS events_ad AFTER DELETE ON events BEGIN
    INSERT INTO events_fts(events_fts, rowid, content, conversation_title, topic_tags)
    VALUES ('delete', old.rowid, old.content, old.conversation_title, old.topic_tags);
END;

CREATE TABLE IF NOT EXISTS facts (
    fact_id TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    statement TEXT NOT NULL,
    evidence_event_ids TEXT DEFAULT '[]',
    confidence REAL DEFAULT 1.0,
    first_seen TEXT,
    last_seen TEXT,
    ttl_class TEXT DEFAULT 'permanent',
    active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS conflicts (
    conflict_id TEXT PRIMARY KEY,
    fact_id TEXT,
    field TEXT,
    old_value TEXT,
    new_value TEXT,
    old_source TEXT,
    new_source TEXT,
    resolution TEXT DEFAULT 'pending' CHECK(resolution IN ('pending','accept_new','keep_old','dismissed')),
    created_at TEXT DEFAULT (datetime('now')),
    resolved_at TEXT,
    FOREIGN KEY (fact_id) REFERENCES facts(fact_id)
);

CREATE TABLE IF NOT EXISTS projections (
    artifact_id TEXT PRIMARY KEY,
    target TEXT NOT NULL CHECK(target IN ('claude_chat','claude_code','openclaw','chatgpt')),
    file_path TEXT,
    source_fact_ids TEXT DEFAULT '[]',
    content_hash TEXT,
    generated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS ingest_log (
    log_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    file_path TEXT,
    events_added INTEGER DEFAULT 0,
    events_skipped INTEGER DEFAULT 0,
    started_at TEXT DEFAULT (datetime('now')),
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS reconcile_log (
    log_id TEXT PRIMARY KEY,
    facts_added INTEGER DEFAULT 0,
    facts_confirmed INTEGER DEFAULT 0,
    conflicts_added INTEGER DEFAULT 0,
    ran_at TEXT DEFAULT (datetime('now'))
);
"""


def init_db(db_path: Path = DB_PATH) -> None:
    """Create all tables and triggers if they don't exist."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA)
        _run_migrations(conn)
        conn.commit()
    finally:
        conn.close()


def _run_migrations(conn: sqlite3.Connection) -> None:
    """Run versioned migrations. Each migration runs exactly once."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]

    if version < 1:
        # v1: Fix misattributed ChatGPT memory dump events (were labeled 'claude').
        # Also recompute event_ids to content-only hashes (no source prefix).
        rows = conn.execute(
            "SELECT event_id, content FROM events "
            "WHERE conversation_title IN ('Claude Memory Export', 'ChatGPT Memory Dump')"
        ).fetchall()
        for old_id, content in rows:
            new_id = hashlib.sha256(content.strip().encode()).hexdigest()
            if old_id != new_id:
                conn.execute(
                    "UPDATE events SET event_id=?, source='chatgpt', "
                    "conversation_title='ChatGPT Memory Dump' WHERE event_id=?",
                    (new_id, old_id),
                )
                # Update evidence references in facts table
                conn.execute(
                    "UPDATE facts SET evidence_event_ids = REPLACE(evidence_event_ids, ?, ?) "
                    "WHERE evidence_event_ids LIKE ?",
                    (old_id, new_id, f"%{old_id}%"),
                )
        conn.execute(
            "UPDATE ingest_log SET source='chatgpt' "
            "WHERE source='claude' AND file_path LIKE '%.md'"
        )
        conn.execute("PRAGMA user_version = 1")

    if version < 2:
        # v2: Expand source CHECK constraint to include claude_code, github, gemini.
        # SQLite cannot ALTER CHECK constraints; must recreate the table.
        conn.executescript("""
            CREATE TABLE events_new (
                event_id TEXT PRIMARY KEY,
                source TEXT NOT NULL CHECK(source IN (
                    'chatgpt','claude','openclaw','claude_code','github','gemini'
                )),
                timestamp_utc TEXT,
                role TEXT,
                content TEXT NOT NULL,
                conversation_id TEXT,
                conversation_title TEXT,
                topic_tags TEXT DEFAULT '[]',
                ingested_at TEXT DEFAULT (datetime('now'))
            );
            INSERT INTO events_new SELECT * FROM events;
            DROP TABLE events;
            ALTER TABLE events_new RENAME TO events;

            DROP TRIGGER IF EXISTS events_ai;
            DROP TRIGGER IF EXISTS events_au;
            DROP TRIGGER IF EXISTS events_ad;

            CREATE TRIGGER events_ai AFTER INSERT ON events BEGIN
                INSERT INTO events_fts(rowid, content, conversation_title, topic_tags)
                VALUES (new.rowid, new.content, new.conversation_title, new.topic_tags);
            END;
            CREATE TRIGGER events_au AFTER UPDATE ON events BEGIN
                INSERT INTO events_fts(events_fts, rowid, content, conversation_title, topic_tags)
                VALUES ('delete', old.rowid, old.content, old.conversation_title, old.topic_tags);
                INSERT INTO events_fts(rowid, content, conversation_title, topic_tags)
                VALUES (new.rowid, new.content, new.conversation_title, new.topic_tags);
            END;
            CREATE TRIGGER events_ad AFTER DELETE ON events BEGIN
                INSERT INTO events_fts(events_fts, rowid, content, conversation_title, topic_tags)
                VALUES ('delete', old.rowid, old.content, old.conversation_title, old.topic_tags);
            END;

            PRAGMA user_version = 2;
        """)


@contextmanager
def get_connection(db_path: Path = DB_PATH):
    """Context manager returning a sqlite3 connection with WAL mode."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def insert_event(conn: sqlite3.Connection, event: dict) -> bool:
    """Insert an event, skipping duplicates. Returns True if inserted."""
    try:
        conn.execute(
            """INSERT INTO events
               (event_id, source, timestamp_utc, role, content,
                conversation_id, conversation_title, topic_tags)
               VALUES (:event_id,:source,:timestamp_utc,:role,:content,
                       :conversation_id,:conversation_title,:topic_tags)""",
            event,
        )
        return True
    except sqlite3.IntegrityError:
        return False


def upsert_fact(conn: sqlite3.Connection, fact: dict) -> str:
    """Insert or update a fact. Returns 'inserted' or 'updated'."""
    existing = conn.execute(
        "SELECT fact_id FROM facts WHERE fact_id = ?", (fact["fact_id"],)
    ).fetchone()
    if existing:
        conn.execute(
            """UPDATE facts SET last_seen=:last_seen, confidence=:confidence,
               updated_at=datetime('now') WHERE fact_id=:fact_id""",
            fact,
        )
        return "updated"
    else:
        conn.execute(
            """INSERT INTO facts
               (fact_id, category, statement, evidence_event_ids,
                confidence, first_seen, last_seen, ttl_class)
               VALUES (:fact_id,:category,:statement,:evidence_event_ids,
                       :confidence,:first_seen,:last_seen,:ttl_class)""",
            fact,
        )
        return "inserted"


def search_events(conn: sqlite3.Connection, query: str, limit: int = 20) -> list:
    """Full-text search over events. Returns list of Row objects."""
    # Wrap in double quotes for phrase matching — prevents FTS5 treating
    # hyphens, colons, etc. as operators. Escape existing double quotes.
    fts_query = '"' + query.replace('"', '""') + '"'
    rows = conn.execute(
        """SELECT e.event_id, e.source, e.timestamp_utc, e.conversation_title,
                  snippet(events_fts, 0, '<b>', '</b>', '...', 30) AS snippet
           FROM events_fts
           JOIN events e ON e.rowid = events_fts.rowid
           WHERE events_fts MATCH ?
           ORDER BY rank
           LIMIT ?""",
        (fts_query, limit),
    ).fetchall()
    return rows


def get_active_facts(conn: sqlite3.Connection, category: str = None) -> list:
    """Return active facts, optionally filtered by category."""
    if category:
        return conn.execute(
            "SELECT * FROM facts WHERE active=1 AND category=? ORDER BY confidence DESC",
            (category,),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM facts WHERE active=1 ORDER BY category, confidence DESC"
    ).fetchall()


def get_statements(facts: list, *categories: str) -> list[str]:
    """Return statement strings from facts matching any of the given categories."""
    return [f["statement"] for f in facts if f["category"] in categories]


def get_active_facts_as_dicts(conn: sqlite3.Connection, category: str = None) -> list[dict]:
    """Return active facts as plain dicts, optionally filtered by category."""
    return [dict(f) for f in get_active_facts(conn, category)]


def log_ingest_start(conn: sqlite3.Connection, source: str, file_path: str) -> str:
    """Insert an ingest_log row and return its log_id."""
    log_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO ingest_log (log_id, source, file_path) VALUES (?,?,?)",
        (log_id, source, file_path),
    )
    return log_id


def log_ingest_complete(conn: sqlite3.Connection, log_id: str, added: int, skipped: int) -> None:
    """Mark an ingest_log row complete with counts."""
    conn.execute(
        """UPDATE ingest_log SET events_added=?, events_skipped=?,
           completed_at=datetime('now') WHERE log_id=?""",
        (added, skipped, log_id),
    )


def record_projections(conn: sqlite3.Connection, target: str, paths) -> None:
    """Record generated projection files. paths may be a list or dict of Path values."""
    file_paths = paths.values() if isinstance(paths, dict) else paths
    for path in file_paths:
        conn.execute(
            """INSERT OR REPLACE INTO projections
               (artifact_id, target, file_path, generated_at)
               VALUES (?,?,?,datetime('now'))""",
            (str(uuid.uuid4()), target, str(path)),
        )


def get_pending_conflicts(conn: sqlite3.Connection) -> list:
    """Return unresolved conflicts."""
    return conn.execute(
        "SELECT * FROM conflicts WHERE resolution='pending' ORDER BY created_at DESC"
    ).fetchall()


def get_stats(conn: sqlite3.Connection) -> dict:
    """Return dashboard stats."""
    events = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    facts = conn.execute("SELECT COUNT(*) FROM facts WHERE active=1").fetchone()[0]
    conflicts = conn.execute(
        "SELECT COUNT(*) FROM conflicts WHERE resolution='pending'"
    ).fetchone()[0]
    last_ingest = conn.execute(
        "SELECT completed_at FROM ingest_log ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    last_reconcile = conn.execute(
        "SELECT ran_at FROM reconcile_log ORDER BY ran_at DESC LIMIT 1"
    ).fetchone()
    projections = conn.execute(
        "SELECT target, MAX(generated_at) FROM projections GROUP BY target"
    ).fetchall()
    return {
        "events": events,
        "facts": facts,
        "pending_conflicts": conflicts,
        "last_ingest": last_ingest[0] if last_ingest else None,
        "last_reconcile": last_reconcile[0] if last_reconcile else None,
        "projections": {row[0]: row[1] for row in projections},
    }
