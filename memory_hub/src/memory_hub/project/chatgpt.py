"""Generate ChatGPT profile pack for manual import."""
import uuid
from datetime import datetime
from pathlib import Path

from memory_hub.config import DB_PATH, PROFILE_MANUAL_PATH, PROJ_CHATGPT
from memory_hub.db import get_connection, get_active_facts


def project_chatgpt(db_path: Path = DB_PATH) -> dict[str, Path]:
    """
    Generate portable profile pack for ChatGPT.
    Returns dict of {name: path}.
    """
    PROJ_CHATGPT.mkdir(parents=True, exist_ok=True)

    with get_connection(db_path) as conn:
        facts = get_active_facts(conn)
    facts = [dict(f) for f in facts]

    now = datetime.now().strftime("%Y-%m-%d")

    # ── Profile Pack ──────────────────────────────────────────────────────────
    profile_lines = [
        "# the user — Portable Profile Pack",
        f"# Generated: {now} | Use with any AI assistant",
        "",
        "## Who I Am",
    ]
    for f in facts:
        if f["category"] == "identity":
            profile_lines.append(f"- {f['statement']}")

    profile_lines += ["", "## How to Talk to Me"]
    for f in facts:
        if f["category"] == "preference":
            profile_lines.append(f"- {f['statement']}")

    profile_lines += ["", "## My Work"]
    for f in facts:
        if f["category"] == "work":
            profile_lines.append(f"- {f['statement']}")

    profile_lines += ["", "## My Interests"]
    for f in facts:
        if f["category"] == "interest":
            profile_lines.append(f"- {f['statement']}")

    profile_lines += ["", "## My Relationships"]
    for f in facts:
        if f["category"] == "relationship":
            profile_lines.append(f"- {f['statement']}")

    profile_lines += ["", "## My Lifestyle"]
    for f in facts:
        if f["category"] == "lifestyle":
            profile_lines.append(f"- {f['statement']}")

    profile_lines += ["", "## Financial Context"]
    for f in facts:
        if f["category"] == "financial":
            profile_lines.append(f"- {f['statement']}")

    # Supplement from manual profile if available
    if PROFILE_MANUAL_PATH.exists():
        profile_lines += ["", "---", "# Extended Context (from personal profile)", ""]
        profile_lines.append(PROFILE_MANUAL_PATH.read_text(encoding="utf-8"))

    profile_content = "\n".join(profile_lines)

    # ── Custom Instructions ───────────────────────────────────────────────────
    prefs = [f["statement"] for f in facts if f["category"] == "preference"]
    work = [f["statement"] for f in facts if f["category"] == "work"]

    custom_instr_lines = [
        "# Custom Instructions for ChatGPT",
        f"# Generated: {now}",
        "",
        "## What would you like ChatGPT to know about you?",
        "",
        "My name is the user. I'm 25, born in 2000, based in Springfield.",
        f"I work as an [ROLE] Design Validation Engineer.",
        "",
    ]
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
        for name, path in out_files.items():
            conn.execute(
                """INSERT OR REPLACE INTO projections
                   (artifact_id, target, file_path, generated_at)
                   VALUES (?,?,?,datetime('now'))""",
                (str(uuid.uuid4()), "chatgpt", str(path)),
            )

    return out_files
