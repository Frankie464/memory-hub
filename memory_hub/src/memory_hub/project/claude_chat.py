"""Generate Claude.ai memory import chunks from active facts."""
import uuid
from datetime import datetime
from pathlib import Path

from memory_hub.config import DB_PATH, PROFILE_MANUAL_PATH, PROJ_CLAUDE_AI, CLAUDE_AI_CHUNK_MAX
from memory_hub.db import get_connection, get_active_facts, get_stats

CHUNK_CATEGORIES = [
    ("01_identity", ["identity"], "Identity"),
    ("02_communication", ["preference"], "Communication Style"),
    ("03_professional", ["work"], "Professional Context"),
    ("04_interests", ["interest"], "Interests & Domains"),
    ("05_relationships", ["relationship"], "Relationships"),
    ("06_lifestyle", ["lifestyle"], "Lifestyle"),
    ("07_financial", ["financial"], "Financial Framework"),
]


def _read_manual_profile() -> dict[str, list[str]]:
    """Parse user_profile.manual.md into category → statements."""
    if not PROFILE_MANUAL_PATH.exists():
        return {}
    text = PROFILE_MANUAL_PATH.read_text(encoding="utf-8")
    result: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            result[current] = []
        elif line.startswith("- ") and current:
            result[current].append(line[2:].strip())
    return result


def project_claude_chat(db_path: Path = DB_PATH) -> list[Path]:
    """
    Generate chunked memory import files in projections/claude_ai/.
    Returns list of generated file paths.
    """
    PROJ_CLAUDE_AI.mkdir(parents=True, exist_ok=True)
    manual = _read_manual_profile()

    with get_connection(db_path) as conn:
        all_facts = get_active_facts(conn)

    # Group DB facts by category
    db_by_cat: dict[str, list[str]] = {}
    for f in all_facts:
        db_by_cat.setdefault(f["category"], []).append(f["statement"])

    generated_files = []
    now = datetime.now().strftime("%Y-%m-%d")

    for filename, categories, label in CHUNK_CATEGORIES:
        statements = []

        # Manual profile takes priority
        for cat in categories:
            # Try to match by label name in manual profile
            for manual_key, manual_stmts in manual.items():
                if cat in manual_key.lower() or manual_key.lower() in cat:
                    statements.extend(manual_stmts)

        # Supplement with DB facts not already covered
        for cat in categories:
            for stmt in db_by_cat.get(cat, []):
                if stmt not in statements:
                    statements.append(stmt)

        if not statements:
            continue

        content = f"# {label}\n# Import into Claude.ai memory — {now}\n\n"
        for stmt in statements:
            content += f"- {stmt}\n"

        # Split if over limit
        if len(content) <= CLAUDE_AI_CHUNK_MAX:
            out_path = PROJ_CLAUDE_AI / f"{filename}.md"
            out_path.write_text(content, encoding="utf-8")
            generated_files.append(out_path)
        else:
            # Split into parts
            chunks = []
            current_chunk = f"# {label}\n# Import into Claude.ai memory — {now}\n\n"
            for stmt in statements:
                line = f"- {stmt}\n"
                if len(current_chunk) + len(line) > CLAUDE_AI_CHUNK_MAX:
                    chunks.append(current_chunk)
                    current_chunk = f"# {label} (continued)\n\n"
                current_chunk += line
            if current_chunk.strip():
                chunks.append(current_chunk)
            for i, chunk in enumerate(chunks, 1):
                out_path = PROJ_CLAUDE_AI / f"{filename}_part{i}.md"
                out_path.write_text(chunk, encoding="utf-8")
                generated_files.append(out_path)

    # Record in projections table
    with get_connection(db_path) as conn:
        for path in generated_files:
            conn.execute(
                """INSERT OR REPLACE INTO projections
                   (artifact_id, target, file_path, generated_at)
                   VALUES (?,?,?,datetime('now'))""",
                (str(uuid.uuid4()), "claude_chat", str(path)),
            )

    return generated_files
