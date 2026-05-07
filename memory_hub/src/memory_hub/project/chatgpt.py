"""Generate ChatGPT profile pack for manual import."""
from datetime import datetime
from pathlib import Path

from memory_hub.config import DB_PATH, PROFILE_MANUAL_PATH, PROJ_CHATGPT
from memory_hub.db import get_connection, get_active_facts_as_dicts, get_statements, record_projections


def project_chatgpt(db_path: Path = DB_PATH) -> dict[str, Path]:
    """
    Generate portable profile pack for ChatGPT.
    Returns dict of {name: path}.
    """
    PROJ_CHATGPT.mkdir(parents=True, exist_ok=True)

    with get_connection(db_path) as conn:
        facts = get_active_facts_as_dicts(conn)

    now = datetime.now().strftime("%Y-%m-%d")

    def _section(label: str, *categories: str) -> list[str]:
        stmts = get_statements(facts, *categories)
        return ["", f"## {label}"] + [f"- {s}" for s in stmts]

    # ── Profile Pack ──────────────────────────────────────────────────────────
    profile_lines = [
        "# Portable Profile Pack",
        f"# Generated: {now} | Use with any AI assistant",
        "",
        "## Who I Am",
    ]
    profile_lines += [f"- {s}" for s in get_statements(facts, "identity")]
    profile_lines += _section("How to Talk to Me", "preference")
    profile_lines += _section("My Work", "work")
    profile_lines += _section("My Interests", "interest")
    profile_lines += _section("My Relationships", "relationship")
    profile_lines += _section("My Lifestyle", "lifestyle")
    profile_lines += _section("Financial Context", "financial")

    # Supplement from manual profile if available
    if PROFILE_MANUAL_PATH.exists():
        profile_lines += ["", "---", "# Extended Context (from personal profile)", ""]
        profile_lines.append(PROFILE_MANUAL_PATH.read_text(encoding="utf-8"))

    profile_content = "\n".join(profile_lines)

    # ── Custom Instructions ───────────────────────────────────────────────────
    prefs = get_statements(facts, "preference")
    work = get_statements(facts, "work")

    custom_instr_lines = [
        "# Custom Instructions for ChatGPT",
        f"# Generated: {now}",
        "",
        "## What would you like ChatGPT to know about you?",
        "",
        "# Profile content below; edit profile.manual.md to customize.",
        "",
    ]
    # Identity facts from the canonical store (e.g. "Lives in ...", "Born in ...")
    identity = get_statements(facts, "identity")
    for s in identity[:4]:
        custom_instr_lines.append(f"- {s}")
    # Work context
    for s in work[:2]:
        custom_instr_lines.append(f"- {s}")
    custom_instr_lines.append("")
    for s in prefs[:6]:
        custom_instr_lines.append(f"- {s}")
    custom_instr_content = "\n".join(custom_instr_lines)

    # ── Memory Refresh Prompt ─────────────────────────────────────────────────
    refresh_prompt = f"""# Memory Refresh Prompt for ChatGPT
# Generated: {now}
# Paste this into ChatGPT to update its memory

---

Please update your memory about me with the following information.
Add new facts and update any outdated ones:

{profile_content}

---
After reading this, confirm what you've remembered about me by listing 5-10 key facts.
"""

    out_files = {}
    profile_path = PROJ_CHATGPT / "profile_pack.md"
    custom_path = PROJ_CHATGPT / "custom_instructions.md"
    refresh_path = PROJ_CHATGPT / "memory_refresh_prompt.md"

    profile_path.write_text(profile_content, encoding="utf-8")
    custom_path.write_text(custom_instr_content, encoding="utf-8")
    refresh_path.write_text(refresh_prompt, encoding="utf-8")

    out_files = {
        "profile_pack": profile_path,
        "custom_instructions": custom_path,
        "memory_refresh_prompt": refresh_path,
    }

    with get_connection(db_path) as conn:
        record_projections(conn, "chatgpt", out_files)

    return out_files
