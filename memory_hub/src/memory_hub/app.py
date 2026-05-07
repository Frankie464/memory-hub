"""Streamlit web dashboard for memory-hub."""
import subprocess
import sys
from pathlib import Path
from datetime import datetime

import streamlit as st

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
from memory_hub.db import (
    get_active_facts,
    get_connection,
    get_pending_conflicts,
    get_stats,
    init_db,
    search_events,
)

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="memory-hub",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────

st.markdown(
    """
<style>
    .status-card {
        background: #1e1e2e;
        border-radius: 10px;
        padding: 16px 20px;
        border-left: 4px solid #7c3aed;
        margin-bottom: 12px;
    }
    .platform-card {
        background: #1e2d3d;
        border-radius: 10px;
        padding: 16px 20px;
        margin-bottom: 16px;
    }
    .step-header {
        font-size: 1.2em;
        font-weight: 700;
        margin-bottom: 8px;
    }
    .tip-box {
        background: #0d2137;
        border-radius: 8px;
        padding: 12px 16px;
        border-left: 4px solid #0ea5e9;
        margin: 8px 0;
        font-size: 0.9em;
    }
</style>
""",
    unsafe_allow_html=True,
)

# ── Sidebar navigation ─────────────────────────────────────────────────────────

PAGES = [
    "🏠 Dashboard",
    "🧭 Setup Wizard",
    "📥 Ingest Data",
    "🔬 Reconcile & Facts",
    "⚙️ Generate Projections",
    "🚀 Deploy to Platforms",
    "🔍 Search History",
    "🔄 Sync & Reports",
]

with st.sidebar:
    st.markdown("## 🧠 memory-hub")
    st.markdown("---")
    page = st.radio("Navigate", PAGES, label_visibility="collapsed")
    st.markdown("---")

    # Mini status in sidebar
    if DB_PATH.exists():
        try:
            with get_connection(DB_PATH) as conn:
                s = get_stats(conn)
            st.metric("Events", f"{s['events']:,}")
            st.metric("Facts", s["facts"])
            if s["pending_conflicts"] > 0:
                st.warning(f"⚠️ {s['pending_conflicts']} conflicts pending")
        except Exception:
            st.caption("DB not initialized")
    else:
        st.caption("⚠️ Run Setup Wizard first")

    st.markdown("---")
    st.caption("memory-hub v0.1.0")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _db_ready() -> bool:
    return DB_PATH.exists()


def _require_db():
    if not _db_ready():
        st.error("Database not initialized. Go to **Setup Wizard** → Step 2 first.")
        st.stop()


def _run_cli(*args):
    """Run a hub CLI command via subprocess and return (stdout, stderr, returncode)."""
    result = subprocess.run(
        [sys.executable, "-m", "memory_hub.cli", *args],
        capture_output=True,
        text=True,
    )
    return result.stdout, result.stderr, result.returncode


def _format_dt(iso_str: str | None) -> str:
    if not iso_str:
        return "Never"
    try:
        return iso_str[:16].replace("T", " ")
    except Exception:
        return iso_str


def _platform_status_icon(last_gen: str | None) -> str:
    if not last_gen:
        return "🔴"
    try:
        dt = datetime.fromisoformat(last_gen)
        days = (datetime.utcnow() - dt).days
        if days < 7:
            return "🟢"
        elif days < 30:
            return "🟡"
        else:
            return "🔴"
    except Exception:
        return "🟡"


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: Dashboard
# ══════════════════════════════════════════════════════════════════════════════

if page == "🏠 Dashboard":
    st.title("🧠 memory-hub Dashboard")
    st.caption("Cross-AI canonical memory store")

    if not _db_ready():
        st.info("👋 Welcome to memory-hub! Start with the **Setup Wizard** in the sidebar to get started.")
        st.stop()

    with get_connection(DB_PATH) as conn:
        stats = get_stats(conn)

    # ── Status cards row ────────────────────────────────────────────────────
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("📨 Events", f"{stats['events']:,}")
    col2.metric("🧩 Active Facts", stats["facts"])
    col3.metric("⚠️ Conflicts", stats["pending_conflicts"])
    col4.metric("📅 Last Reconcile", _format_dt(stats["last_reconcile"]))

    st.markdown("---")

    # ── Platform projection status ──────────────────────────────────────────
    st.subheader("Platform Projections")
    platforms = {
        "claude_chat": ("Claude.ai", PROJ_CLAUDE_AI),
        "claude_code": ("Claude Code", PROJ_CLAUDE_CODE),
        "openclaw": ("OpenClaw", PROJ_OPENCLAW),
        "chatgpt": ("ChatGPT", PROJ_CHATGPT),
    }
    p_cols = st.columns(4)
    for i, (key, (label, proj_dir)) in enumerate(platforms.items()):
        last_gen = stats["projections"].get(key)
        icon = _platform_status_icon(last_gen)
        with p_cols[i]:
            st.markdown(f"**{icon} {label}**")
            st.caption(_format_dt(last_gen))

    st.markdown("---")

    # ── Quick actions ────────────────────────────────────────────────────────
    st.subheader("Quick Actions")
    qa_col1, qa_col2, qa_col3 = st.columns(3)

    with qa_col1:
        if st.button("🔬 Run Reconcile", use_container_width=True):
            with st.spinner("Reconciling..."):
                from memory_hub.reconcile import reconcile
                rec = reconcile(DB_PATH)
            st.success(
                f"Done: {rec['facts_added']} new facts, "
                f"{rec['facts_confirmed']} confirmed, "
                f"{rec['conflicts_added']} conflicts"
            )
            st.rerun()

    with qa_col2:
        if st.button("⚙️ Generate All Projections", use_container_width=True):
            from memory_hub.project.claude_chat import project_claude_chat
            from memory_hub.project.claude_code import project_claude_code
            from memory_hub.project.openclaw import project_openclaw
            from memory_hub.project.chatgpt import project_chatgpt
            with st.spinner("Generating projections..."):
                for fn in [project_claude_chat, project_claude_code, project_openclaw, project_chatgpt]:
                    try:
                        fn(DB_PATH) if fn.__name__ == "project_claude_chat" else fn(db_path=DB_PATH)
                    except Exception as e:
                        st.warning(f"{fn.__name__}: {e}")
            st.success("All projections generated!")
            st.rerun()

    with qa_col3:
        if st.button("🔄 Run Weekly Sync", use_container_width=True):
            with st.spinner("Running weekly sync..."):
                from memory_hub.sync import sync_weekly
                results = sync_weekly(db_path=DB_PATH)
            st.success(f"Weekly sync complete — {len(results['steps'])} steps")
            for step in results["steps"]:
                st.caption(step)

    st.markdown("---")

    # ── Recent ingest log ────────────────────────────────────────────────────
    st.subheader("Recent Activity")
    with get_connection(DB_PATH) as conn:
        logs = conn.execute(
            "SELECT source, file_path, events_added, events_skipped, completed_at "
            "FROM ingest_log ORDER BY started_at DESC LIMIT 5"
        ).fetchall()
    if logs:
        import pandas as pd
        df = pd.DataFrame(
            [dict(r) for r in logs],
            columns=["source", "file_path", "events_added", "events_skipped", "completed_at"],
        )
        df["file_path"] = df["file_path"].apply(lambda x: Path(x).name if x else "")
        df.columns = ["Source", "File", "Added", "Skipped", "Completed"]
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.caption("No ingest activity yet.")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: Setup Wizard
# ══════════════════════════════════════════════════════════════════════════════

elif page == "🧭 Setup Wizard":
    st.title("🧭 Setup Wizard")
    st.caption("Follow these steps to get memory-hub running. You only need to do this once.")

    # Progress indicator
    steps_done = sum([
        _db_ready(),
        PROFILE_MANUAL_PATH.exists(),
        (RAW_DIR / "chatgpt_exports").exists() and any((RAW_DIR / "chatgpt_exports").glob("*.md")),
        (RAW_DIR / "chatgpt_exports").exists() and any((RAW_DIR / "chatgpt_exports").glob("*.zip")),
        (RAW_DIR / "claude_exports").exists() and any((RAW_DIR / "claude_exports").glob("*.zip")),
        PROFILE_GENERATED_PATH.exists(),
    ])
    st.progress(steps_done / 7, text=f"Step {steps_done}/7 complete")
    st.markdown("---")

    # ── Step 1: Request ChatGPT Export ──────────────────────────────────────
    with st.expander("📤 Step 1 — Request your ChatGPT data export", expanded=not _db_ready()):
        st.markdown("""
**Do this now — it takes hours to arrive via email.**

1. Go to [chat.openai.com](https://chat.openai.com) → **Settings → Data Controls**
2. Click **Export Data** → confirm the email
3. Wait for the download link (usually 1–24 hours)
4. Download the ZIP when it arrives

> **While you wait**, continue with Steps 2–5 to set everything else up.
""")
        st.checkbox("✅ I've requested my ChatGPT export and am waiting for the email",
                    key="chatgpt_export_requested")

    # ── Step 2: Initialize ─────────────────────────────────────────────────
    with st.expander("🗄️ Step 2 — Initialize the hub", expanded=not _db_ready()):
        st.markdown("""
Creates the database, all data directories, and starter files.
This is safe to run more than once.
""")
        if st.button("🚀 Initialize Now", type="primary"):
            for d in ALL_DIRS:
                d.mkdir(parents=True, exist_ok=True)
            init_db(DB_PATH)
            if not CHANGELOG_PATH.exists():
                CHANGELOG_PATH.write_text("# Changelog\n", encoding="utf-8")
            if not PROFILE_MANUAL_PATH.exists():
                PROFILE_MANUAL_PATH.write_text(
                    "# Manual Profile\n"
                    "# Edit this file to provide curated personal context.\n"
                    "# This file is NEVER auto-overwritten by memory-hub.\n\n"
                    "## Identity\n\n## Communication Style\n\n## Professional\n\n"
                    "## Interests\n\n## Relationships\n\n## Lifestyle\n\n## Financial Framework\n",
                    encoding="utf-8",
                )
            st.success("✅ Initialized! Database and directories are ready.")
            st.rerun()

        if _db_ready():
            st.success("✅ Already initialized")

    # ── Step 3: Ingest ChatGPT memory dump ──────────────────────────────
    with st.expander("💬 Step 3 — Import ChatGPT stored memories (optional)", expanded=_db_ready() and not PROFILE_GENERATED_PATH.exists()):
        st.markdown("""
Import a ChatGPT memory dump (`.md` file with `[date] - content` entries).
This is optional if you're importing the full ChatGPT conversation ZIP in Step 4.

**To create a memory dump:** Ask ChatGPT to list all stored memories about you.
Drop the `.md` file into `data/raw/chatgpt_exports/` or upload it here.
""")
        uploaded = st.file_uploader("Upload ChatGPT memory dump (.md)", type=["md"], key="chatgpt_mem_upload")
        if uploaded:
            dest = RAW_DIR / "chatgpt_exports" / uploaded.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(uploaded.getbuffer())
            st.success(f"Saved to {dest}")

        chatgpt_mds = list((RAW_DIR / "chatgpt_exports").glob("*.md")) if (RAW_DIR / "chatgpt_exports").exists() else []
        if chatgpt_mds:
            selected = st.selectbox("File to ingest", [f.name for f in chatgpt_mds])
            if st.button("Ingest ChatGPT Memory Dump", type="primary"):
                _require_db()
                from memory_hub.ingest.chatgpt_memory import ingest_chatgpt_memory
                chosen = RAW_DIR / "chatgpt_exports" / selected
                with st.spinner("Ingesting..."):
                    stats = ingest_chatgpt_memory(chosen, DB_PATH)
                st.success(f"✅ {stats['added']} entries added, {stats['skipped']} skipped")
        else:
            st.info("No `.md` files found in `data/raw/chatgpt_exports/`. Upload one above or copy it there.")

    # ── Step 4: Ingest ChatGPT export ──────────────────────────────────────
    with st.expander("💬 Step 4 — Import your ChatGPT full history (when ZIP arrives)", expanded=False):
        st.markdown("""
When your ChatGPT export ZIP arrives, drop it into `data/raw/chatgpt_exports/` or upload it here.
This may take a minute for large exports (thousands of conversations).
""")
        uploaded_zip = st.file_uploader("Upload ChatGPT export ZIP", type=["zip"], key="chatgpt_upload")
        if uploaded_zip:
            dest = RAW_DIR / "chatgpt_exports" / uploaded_zip.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(uploaded_zip.getbuffer())
            st.success(f"Saved to {dest}")

        chatgpt_zips = list((RAW_DIR / "chatgpt_exports").glob("*.zip")) if (RAW_DIR / "chatgpt_exports").exists() else []
        if chatgpt_zips:
            selected_zip = st.selectbox("ZIP to ingest", [f.name for f in chatgpt_zips])
            if st.button("Ingest ChatGPT History", type="primary"):
                _require_db()
                from memory_hub.ingest.chatgpt import ingest_chatgpt_zip
                chosen_zip = RAW_DIR / "chatgpt_exports" / selected_zip
                with st.spinner("Parsing conversations (this may take a moment)..."):
                    stats = ingest_chatgpt_zip(chosen_zip, DB_PATH)
                st.success(
                    f"✅ {stats['conversations']:,} conversations — "
                    f"{stats['messages_added']:,} messages added, "
                    f"{stats['messages_skipped']:,} skipped"
                )
        else:
            st.info("No ZIP files yet. This step becomes available once your ChatGPT export arrives.")

    # ── Step 5: Ingest Claude export ──────────────────────────────────────
    with st.expander("🟣 Step 5 — Import your Claude export", expanded=False):
        st.markdown("""
Export from [claude.ai](https://claude.ai) → **Settings → Privacy → Export Data**.
Upload the ZIP or drop it into `data/raw/claude_exports/`.
This imports both conversations and Claude's stored memories about you.
""")
        uploaded_claude_wiz = st.file_uploader("Upload Claude export ZIP", type=["zip"], key="claude_wiz_upload")
        if uploaded_claude_wiz:
            dest = RAW_DIR / "claude_exports" / uploaded_claude_wiz.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(uploaded_claude_wiz.getbuffer())
            st.success(f"Saved to {dest}")

        claude_wiz_zips = list((RAW_DIR / "claude_exports").glob("*.zip")) if (RAW_DIR / "claude_exports").exists() else []
        if claude_wiz_zips:
            selected_claude = st.selectbox("ZIP to ingest", [f.name for f in claude_wiz_zips], key="claude_wiz_select")
            if st.button("Ingest Claude Export", type="primary", key="claude_wiz_btn"):
                _require_db()
                from memory_hub.ingest.claude import ingest_claude_zip
                chosen = RAW_DIR / "claude_exports" / selected_claude
                with st.spinner("Parsing conversations and memories..."):
                    stats = ingest_claude_zip(chosen, DB_PATH)
                st.success(
                    f"✅ {stats['conversations']:,} conversations — "
                    f"{stats['messages_added']:,} messages added, "
                    f"{stats['messages_skipped']:,} skipped"
                )
                if stats["memories_added"]:
                    st.info(f"Also imported {stats['memories_added']} stored memories.")
        else:
            st.info("No ZIP files found in `data/raw/claude_exports/`. Upload one above or export from claude.ai.")

    # ── Step 5b: GitHub + Claude Code (optional) ─────────────────────────
    with st.expander("🐙 Step 5b — Connect GitHub & Claude Code (optional)", expanded=False):
        st.markdown("""
**GitHub:** If you use GitHub, authenticate `gh` CLI to import repo metadata and READMEs as context.

```
gh auth login
```

**Claude Code:** If you use Claude Code CLI, you can import session logs from `~/.claude/projects/`.

Use the **Ingest Data** page tabs for full controls.
""")
        if st.button("⚡ Quick Ingest: GitHub + Claude Code", key="dev_ingest_wiz"):
            _require_db()
            results_lines = []
            try:
                from memory_hub.ingest.github import ingest_github
                s = ingest_github(db_path=DB_PATH)
                results_lines.append(f"  GitHub: {s['repos_found']} repos, {s['events_added']:,} events added")
            except Exception as e:
                results_lines.append(f"  GitHub: skipped ({e})")
            try:
                from memory_hub.ingest.claude_code import ingest_claude_code
                s = ingest_claude_code(db_path=DB_PATH)
                results_lines.append(f"  Claude Code: {s['sessions_found']} sessions, {s['messages_added']:,} messages added")
            except Exception as e:
                results_lines.append(f"  Claude Code: skipped ({e})")
            st.success("Done!\n" + "\n".join(results_lines))

    # ── Step 6: Build profile ──────────────────────────────────────────────
    with st.expander("🔬 Step 6 — Build your memory profile", expanded=_db_ready() and not PROFILE_GENERATED_PATH.exists()):
        st.markdown("""
Reconcile scans all ingested events and extracts facts (identity, preferences, work, interests, etc.)
into the canonical database. It then generates `profile.generated.md` automatically.

After reconciling, review the generated profile and copy anything you want to keep permanently
into `profile.manual.md` — the manual file is **never** auto-overwritten.
""")
        if st.button("🔬 Run Reconcile", type="primary"):
            _require_db()
            with st.spinner("Extracting facts..."):
                from memory_hub.reconcile import reconcile
                rec = reconcile(DB_PATH)
            st.success(
                f"✅ {rec['facts_added']} new facts, "
                f"{rec['facts_confirmed']} confirmed, "
                f"{rec['conflicts_added']} conflicts"
            )

        if PROFILE_GENERATED_PATH.exists():
            st.success("✅ Profile generated")
            if st.checkbox("Preview generated profile"):
                st.code(PROFILE_GENERATED_PATH.read_text(encoding="utf-8"), language="markdown")

    # ── Step 7: Deploy ─────────────────────────────────────────────────────
    with st.expander("🚀 Step 7 — Deploy to your AI platforms", expanded=PROFILE_GENERATED_PATH.exists()):
        st.markdown("""
Generate platform-specific memory files. Use the **Generate Projections** and **Deploy to Platforms**
pages for detailed per-platform controls.

Quick deploy to Claude Code (writes to `~/.claude/`):
""")
        if st.button("⚡ Quick Deploy to Claude Code"):
            _require_db()
            from memory_hub.project.claude_code import project_claude_code
            with st.spinner("Deploying..."):
                files = project_claude_code(deploy=True, db_path=DB_PATH)
            st.success("✅ Deployed to ~/.claude/")
            for name, path in files.items():
                st.caption(f"  {name}: {path}")

        st.markdown("""
For Claude.ai, OpenClaw, and ChatGPT: go to **Generate Projections** and **Deploy to Platforms**.
""")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: Ingest Data
# ══════════════════════════════════════════════════════════════════════════════

elif page == "📥 Ingest Data":
    st.title("📥 Ingest Data")
    _require_db()

    tab_cg, tab_cl, tab_claude, tab_gh, tab_cc = st.tabs([
        "💬 ChatGPT Conversations", "💬 ChatGPT Memories", "🟣 Claude Export",
        "🐙 GitHub", "🖥️ Claude Code",
    ])

    with tab_cg:
        st.subheader("ChatGPT Export Ingest")
        st.markdown("""
Drop your ChatGPT export ZIP into `data/raw/chatgpt_exports/` or upload it here.
Duplicate messages are automatically skipped on re-ingest.
""")
        uploaded_zip = st.file_uploader("Upload ChatGPT export ZIP", type=["zip"], key="ingest_cg_up")
        if uploaded_zip:
            dest = RAW_DIR / "chatgpt_exports" / uploaded_zip.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(uploaded_zip.getbuffer())
            st.success(f"Saved: {dest.name}")

        zips = sorted((RAW_DIR / "chatgpt_exports").glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True) \
            if (RAW_DIR / "chatgpt_exports").exists() else []
        if zips:
            chosen = st.selectbox("Select ZIP to ingest", [z.name for z in zips], key="cg_select")
            if st.button("Ingest ChatGPT", type="primary", key="cg_ingest"):
                from memory_hub.ingest.chatgpt import ingest_chatgpt_zip
                with st.spinner("Parsing... (large exports may take 30–60s)"):
                    s = ingest_chatgpt_zip(RAW_DIR / "chatgpt_exports" / chosen, DB_PATH)
                st.success(
                    f"✅ {s['conversations']:,} conversations — "
                    f"{s['messages_added']:,} added, {s['messages_skipped']:,} skipped"
                )
        else:
            st.info("No ZIP files found in `data/raw/chatgpt_exports/`.")

        # History
        st.markdown("---")
        st.markdown("**Past ingests:**")
        with get_connection(DB_PATH) as conn:
            logs = conn.execute(
                "SELECT file_path, events_added, events_skipped, completed_at "
                "FROM ingest_log WHERE source='chatgpt' ORDER BY started_at DESC LIMIT 10"
            ).fetchall()
        if logs:
            import pandas as pd
            df = pd.DataFrame([dict(r) for r in logs])
            df["file_path"] = df["file_path"].apply(lambda x: Path(x).name if x else "")
            df.columns = ["File", "Added", "Skipped", "Completed"]
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.caption("No ChatGPT ingests yet.")

    with tab_cl:
        st.subheader("ChatGPT Memory Dump Ingest")
        st.markdown("""
Import a ChatGPT memory dump — a `.md` file with `[date] - content` entries.
Create one by asking ChatGPT to list all stored memories about you.
Upload the file or drop it into `data/raw/chatgpt_exports/`.
""")
        uploaded_md = st.file_uploader("Upload ChatGPT memory dump (.md)", type=["md"], key="ingest_mem_up")
        if uploaded_md:
            dest = RAW_DIR / "chatgpt_exports" / uploaded_md.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(uploaded_md.getbuffer())
            st.success(f"Saved: {dest.name}")

        mds = sorted((RAW_DIR / "chatgpt_exports").glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True) \
            if (RAW_DIR / "chatgpt_exports").exists() else []
        if mds:
            chosen_md = st.selectbox("Select file to ingest", [m.name for m in mds], key="mem_select")
            if st.button("Ingest ChatGPT Memory Dump", type="primary", key="mem_ingest"):
                from memory_hub.ingest.chatgpt_memory import ingest_chatgpt_memory
                with st.spinner("Parsing..."):
                    s = ingest_chatgpt_memory(RAW_DIR / "chatgpt_exports" / chosen_md, DB_PATH)
                st.success(f"✅ {s['added']} entries added, {s['skipped']} skipped")
        else:
            st.info("No `.md` files found in `data/raw/chatgpt_exports/`.")

        st.markdown("---")
        st.markdown("**Past memory dump ingests:**")
        with get_connection(DB_PATH) as conn:
            logs = conn.execute(
                "SELECT file_path, events_added, events_skipped, completed_at "
                "FROM ingest_log WHERE source='chatgpt' AND file_path LIKE '%.md' "
                "ORDER BY started_at DESC LIMIT 10"
            ).fetchall()
        if logs:
            import pandas as pd
            df = pd.DataFrame([dict(r) for r in logs])
            df["file_path"] = df["file_path"].apply(lambda x: Path(x).name if x else "")
            df.columns = ["File", "Added", "Skipped", "Completed"]
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.caption("No memory dump ingests yet.")

    with tab_claude:
        st.subheader("Claude Export Ingest")
        st.markdown("""
Import a Claude export ZIP (or unzipped folder) containing `conversations.json` and `memories.json`.
Export from [claude.ai](https://claude.ai) → Settings → Privacy → Export Data.
Upload the file or drop it into `data/raw/claude_exports/`.
""")
        uploaded_claude = st.file_uploader("Upload Claude export ZIP", type=["zip"], key="ingest_claude_up")
        if uploaded_claude:
            dest = RAW_DIR / "claude_exports" / uploaded_claude.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(uploaded_claude.getbuffer())
            st.success(f"Saved: {dest.name}")

        claude_zips = sorted(
            (RAW_DIR / "claude_exports").glob("*.zip"),
            key=lambda p: p.stat().st_mtime, reverse=True
        ) if (RAW_DIR / "claude_exports").exists() else []
        if claude_zips:
            chosen_claude = st.selectbox("Select ZIP to ingest", [z.name for z in claude_zips], key="claude_select")
            if st.button("Ingest Claude Export", type="primary", key="claude_ingest"):
                from memory_hub.ingest.claude import ingest_claude_zip
                with st.spinner("Parsing conversations and memories..."):
                    s = ingest_claude_zip(RAW_DIR / "claude_exports" / chosen_claude, DB_PATH)
                st.success(
                    f"✅ {s['conversations']:,} conversations — "
                    f"{s['messages_added']:,} messages added, {s['messages_skipped']:,} skipped"
                )
                if s["memories_added"]:
                    st.info(f"Also imported {s['memories_added']} stored memories.")
        else:
            st.info("No ZIP files found in `data/raw/claude_exports/`.")

        st.markdown("---")
        st.markdown("**Past Claude ingests:**")
        with get_connection(DB_PATH) as conn:
            logs = conn.execute(
                "SELECT file_path, events_added, events_skipped, completed_at "
                "FROM ingest_log WHERE source='claude' ORDER BY started_at DESC LIMIT 10"
            ).fetchall()
        if logs:
            import pandas as pd
            df = pd.DataFrame([dict(r) for r in logs])
            df["file_path"] = df["file_path"].apply(lambda x: Path(x).name if x else "")
            df.columns = ["File", "Added", "Skipped", "Completed"]
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.caption("No Claude ingests yet.")

    # ── Tab: GitHub ───────────────────────────────────────────────────────
    with tab_gh:
        st.subheader("GitHub Repos & READMEs")
        st.markdown("""
Ingests repo metadata (name, description, languages) and README content from your GitHub account.
Requires `gh` CLI to be authenticated (`gh auth login`).
Repo summaries are synthesized into natural-language events for fact extraction.
""")
        # Check gh auth status
        import subprocess
        gh_user = None
        try:
            result = subprocess.run(
                ["gh", "api", "user", "--jq", ".login"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                gh_user = result.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        if gh_user:
            st.success(f"Authenticated as **{gh_user}**")
            if st.button("Ingest GitHub Repos", type="primary", key="gh_ingest"):
                from memory_hub.ingest.github import ingest_github
                with st.spinner("Fetching repos and READMEs from GitHub API..."):
                    s = ingest_github(gh_user, DB_PATH)
                st.success(
                    f"✅ {s['repos_found']} repos, {s['readmes_fetched']} READMEs — "
                    f"{s['events_added']:,} events added, {s['events_skipped']:,} skipped"
                )
        else:
            st.warning("GitHub CLI not authenticated. Run `gh auth login` in your terminal first.")

        st.markdown("---")
        st.markdown("**Past GitHub ingests:**")
        with get_connection(DB_PATH) as conn:
            logs = conn.execute(
                "SELECT file_path, events_added, events_skipped, completed_at "
                "FROM ingest_log WHERE source='github' ORDER BY started_at DESC LIMIT 10"
            ).fetchall()
        if logs:
            import pandas as pd
            df = pd.DataFrame([dict(r) for r in logs])
            df.columns = ["Source", "Added", "Skipped", "Completed"]
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.caption("No GitHub ingests yet.")

    # ── Tab: Claude Code ──────────────────────────────────────────────────
    with tab_cc:
        st.subheader("Claude Code CLI Sessions")
        from memory_hub.ingest.claude_code import CLAUDE_CODE_PROJECTS_DIR
        st.markdown(f"""
Ingests session JSONL files from `{CLAUDE_CODE_PROJECTS_DIR}`.
Only user and assistant messages are imported. Thinking blocks and tool calls are skipped.
Re-ingesting is safe — duplicate messages are skipped automatically.
""")
        cc_exists = CLAUDE_CODE_PROJECTS_DIR.exists()
        if cc_exists:
            jsonl_count = len(list(CLAUDE_CODE_PROJECTS_DIR.rglob("*.jsonl")))
            st.info(f"Found {jsonl_count} JSONL session files across all projects.")
        else:
            st.warning(f"`{CLAUDE_CODE_PROJECTS_DIR}` not found. Install Claude Code CLI first.")

        if st.button("Ingest Claude Code Sessions", type="primary", key="cc_ingest", disabled=not cc_exists):
            from memory_hub.ingest.claude_code import ingest_claude_code
            with st.spinner("Scanning session files..."):
                s = ingest_claude_code(db_path=DB_PATH)
            st.success(
                f"✅ {s['files_found']} files, {s['sessions_found']} sessions — "
                f"{s['messages_added']:,} messages added, {s['messages_skipped']:,} skipped"
            )

        st.markdown("---")
        st.markdown("**Past Claude Code ingests:**")
        with get_connection(DB_PATH) as conn:
            logs = conn.execute(
                "SELECT file_path, events_added, events_skipped, completed_at "
                "FROM ingest_log WHERE source='claude_code' ORDER BY started_at DESC LIMIT 10"
            ).fetchall()
        if logs:
            import pandas as pd
            df = pd.DataFrame([dict(r) for r in logs])
            df.columns = ["Directory", "Added", "Skipped", "Completed"]
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.caption("No Claude Code ingests yet.")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: Reconcile & Facts
# ══════════════════════════════════════════════════════════════════════════════

elif page == "🔬 Reconcile & Facts":
    st.title("🔬 Reconcile & Facts")
    _require_db()

    # ── Run reconcile ────────────────────────────────────────────────────────
    col_btn, col_info = st.columns([2, 5])
    with col_btn:
        if st.button("🔬 Run Reconcile Now", type="primary", use_container_width=True):
            with st.spinner("Scanning events and extracting facts..."):
                from memory_hub.reconcile import reconcile
                rec = reconcile(DB_PATH)
            st.success(
                f"✅ {rec['facts_added']} new facts, "
                f"{rec['facts_confirmed']} confirmed, "
                f"{rec['conflicts_added']} conflicts"
            )
    with col_info:
        with get_connection(DB_PATH) as conn:
            last_rec = conn.execute(
                "SELECT ran_at FROM reconcile_log ORDER BY ran_at DESC LIMIT 1"
            ).fetchone()
        if last_rec:
            st.info(f"Last reconcile: {_format_dt(last_rec['ran_at'])}")

    st.markdown("---")

    # ── Facts table ──────────────────────────────────────────────────────────
    st.subheader("Active Facts")

    with get_connection(DB_PATH) as conn:
        facts = get_active_facts(conn)

    if facts:
        import pandas as pd
        facts_list = [dict(f) for f in facts]
        df = pd.DataFrame(facts_list, columns=[
            "fact_id", "category", "statement", "evidence_event_ids",
            "confidence", "first_seen", "last_seen", "ttl_class", "active",
            "created_at", "updated_at",
        ])
        df_display = df[["category", "statement", "confidence", "first_seen", "last_seen", "ttl_class"]].copy()
        df_display["confidence"] = df_display["confidence"].round(2)
        df_display["first_seen"] = df_display["first_seen"].apply(lambda x: (x or "")[:16])
        df_display["last_seen"] = df_display["last_seen"].apply(lambda x: (x or "")[:16])
        df_display.columns = ["Category", "Statement", "Confidence", "First Seen", "Last Seen", "TTL"]

        # Filter by category
        cats = ["All"] + sorted(df_display["Category"].unique().tolist())
        selected_cat = st.selectbox("Filter by category", cats)
        if selected_cat != "All":
            df_display = df_display[df_display["Category"] == selected_cat]

        st.dataframe(df_display, use_container_width=True, hide_index=True, height=400)
        st.caption(f"{len(df_display)} facts shown")
    else:
        st.info("No facts yet. Run reconcile after ingesting data.")

    st.markdown("---")

    # ── Profile side-by-side ─────────────────────────────────────────────────
    st.subheader("Profile Files")
    pc1, pc2 = st.columns(2)
    with pc1:
        st.markdown("**📝 Manual Profile** _(human-edited, never overwritten)_")
        if PROFILE_MANUAL_PATH.exists():
            manual_text = st.text_area(
                "manual.md",
                PROFILE_MANUAL_PATH.read_text(encoding="utf-8"),
                height=400,
                key="manual_editor",
                label_visibility="collapsed",
            )
            if st.button("💾 Save Manual Profile"):
                PROFILE_MANUAL_PATH.write_text(manual_text, encoding="utf-8")
                st.success("Saved!")
        else:
            st.info("Manual profile not found. Run init first.")

    with pc2:
        st.markdown("**⚡ Generated Profile** _(auto-rebuilt by reconcile)_")
        if PROFILE_GENERATED_PATH.exists():
            st.code(PROFILE_GENERATED_PATH.read_text(encoding="utf-8"), language="markdown")
        else:
            st.info("No generated profile yet. Run reconcile first.")

    st.markdown("---")

    # ── Pending conflicts ────────────────────────────────────────────────────
    st.subheader("Pending Conflicts")
    with get_connection(DB_PATH) as conn:
        conflicts = get_pending_conflicts(conn)

    if conflicts:
        import pandas as pd
        cdf = pd.DataFrame(
            [dict(c) for c in conflicts],
            columns=["conflict_id", "fact_id", "field", "old_value", "new_value",
                     "old_source", "new_source", "resolution", "created_at", "resolved_at"],
        )
        cdf_display = cdf[["field", "old_value", "new_value", "old_source", "new_source", "created_at"]].copy()
        cdf_display["created_at"] = cdf_display["created_at"].apply(lambda x: (x or "")[:16])
        cdf_display.columns = ["Field", "Old Value", "New Value", "Old Source", "New Source", "Detected"]
        st.dataframe(cdf_display, use_container_width=True, hide_index=True)
        st.caption(f"{len(cdf_display)} pending conflicts. Resolve by editing the manual profile.")
    else:
        st.success("No pending conflicts!")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: Generate Projections
# ══════════════════════════════════════════════════════════════════════════════

elif page == "⚙️ Generate Projections":
    st.title("⚙️ Generate Projections")
    st.caption("Generate platform-specific memory files from your canonical facts. Safe to run anytime — no deployment happens here.")
    _require_db()

    with get_connection(DB_PATH) as conn:
        stats = get_stats(conn)

    # ── Generate All ─────────────────────────────────────────────────────────
    if st.button("⚡ Generate All Projections", type="primary"):
        from memory_hub.project.claude_chat import project_claude_chat
        from memory_hub.project.claude_code import project_claude_code
        from memory_hub.project.openclaw import project_openclaw
        from memory_hub.project.chatgpt import project_chatgpt

        results = {}
        progress = st.progress(0, "Starting...")
        for i, (name, fn, kwargs) in enumerate([
            ("Claude.ai", project_claude_chat, {"db_path": DB_PATH}),
            ("Claude Code", project_claude_code, {"db_path": DB_PATH}),
            ("OpenClaw", project_openclaw, {"db_path": DB_PATH}),
            ("ChatGPT", project_chatgpt, {"db_path": DB_PATH}),
        ]):
            progress.progress((i + 1) / 4, f"Generating {name}...")
            try:
                results[name] = fn(**kwargs)
            except Exception as e:
                results[name] = f"ERROR: {e}"
        progress.empty()

        for name, out in results.items():
            if isinstance(out, str) and out.startswith("ERROR"):
                st.error(f"{name}: {out}")
            else:
                count = len(out) if isinstance(out, (list, dict)) else 1
                st.success(f"✅ {name}: {count} files generated")
        st.rerun()

    st.markdown("---")

    # ── Per-platform sections ─────────────────────────────────────────────────
    platforms_config = [
        ("🤖 Claude.ai", "claude_chat", PROJ_CLAUDE_AI),
        ("💻 Claude Code", "claude_code", PROJ_CLAUDE_CODE),
        ("🦅 OpenClaw", "openclaw", PROJ_OPENCLAW),
        ("💬 ChatGPT", "chatgpt", PROJ_CHATGPT),
    ]

    for label, target, proj_dir in platforms_config:
        last_gen = stats["projections"].get(target)
        icon = _platform_status_icon(last_gen)
        with st.expander(f"{label}  {icon} Last generated: {_format_dt(last_gen)}"):
            col_gen, col_preview = st.columns([1, 3])
            with col_gen:
                if st.button(f"Generate {label}", key=f"gen_{target}"):
                    if target == "claude_chat":
                        from memory_hub.project.claude_chat import project_claude_chat
                        out = project_claude_chat(DB_PATH)
                    elif target == "claude_code":
                        from memory_hub.project.claude_code import project_claude_code
                        out = project_claude_code(db_path=DB_PATH)
                    elif target == "openclaw":
                        from memory_hub.project.openclaw import project_openclaw
                        out = project_openclaw(db_path=DB_PATH)
                    else:
                        from memory_hub.project.chatgpt import project_chatgpt
                        out = project_chatgpt(DB_PATH)
                    count = len(out) if isinstance(out, (list, dict)) else 1
                    st.success(f"{count} files")
                    st.rerun()

            with col_preview:
                if proj_dir.exists():
                    files = [f for f in proj_dir.iterdir() if f.is_file()]
                    if files:
                        chosen_file = st.selectbox(
                            "Preview file", [f.name for f in files], key=f"preview_{target}"
                        )
                        if chosen_file:
                            content = (proj_dir / chosen_file).read_text(encoding="utf-8")
                            st.code(content[:3000] + ("..." if len(content) > 3000 else ""),
                                    language="markdown")
                    else:
                        st.caption("No files generated yet.")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: Deploy to Platforms
# ══════════════════════════════════════════════════════════════════════════════

elif page == "🚀 Deploy to Platforms":
    st.title("🚀 Deploy to Platforms")
    st.caption("Copy or deploy your generated memory files to each AI platform.")
    _require_db()

    # ── Claude.ai ─────────────────────────────────────────────────────────────
    with st.expander("🤖 Claude.ai Memory Import", expanded=True):
        st.markdown("""
**Claude.ai doesn't have an API import** — you paste memory directly into the chat.

**Steps:**
1. Generate the chunks below (or they're already in `data/projections/claude_ai/`)
2. Open each file below and click **Copy**
3. Go to [claude.ai](https://claude.ai) → start a new chat
4. Paste the content and say: *"Please save these as your memories about me."*
5. Repeat for each chunk
""")
        if PROJ_CLAUDE_AI.exists():
            files = sorted(PROJ_CLAUDE_AI.glob("*.md"))
            if files:
                for f in files:
                    content = f.read_text(encoding="utf-8")
                    with st.container():
                        col_name, col_copy = st.columns([3, 1])
                        with col_name:
                            st.markdown(f"**{f.name}** ({len(content)} chars)")
                        with col_copy:
                            st.code(content, language="markdown")
            else:
                st.info("No files yet. Go to Generate Projections first.")
        else:
            st.info("No files yet. Go to Generate Projections first.")

    # ── Claude Code ───────────────────────────────────────────────────────────
    with st.expander("💻 Claude Code Deploy"):
        st.markdown("""
Deploys to `~/.claude/CLAUDE.md` (using safe marker blocks) and `~/.claude/rules/`.
Your existing CLAUDE.md content outside the marker block is preserved.
""")
        col_prev, col_deploy = st.columns(2)
        with col_prev:
            if PROJ_CLAUDE_CODE.exists():
                cc_files = list(PROJ_CLAUDE_CODE.iterdir())
                if cc_files:
                    chosen_cc = st.selectbox("Preview file", [f.name for f in cc_files])
                    if chosen_cc:
                        st.code(
                            (PROJ_CLAUDE_CODE / chosen_cc).read_text(encoding="utf-8"),
                            language="markdown",
                        )
        with col_deploy:
            st.markdown("""
**What gets deployed:**
- `~/.claude/CLAUDE.md` — personal context block (inside markers)
- `~/.claude/rules/personal-context.md`
- `~/.claude/rules/work-domain.md`
""")
            if st.button("🚀 Deploy to Claude Code", type="primary"):
                from memory_hub.project.claude_code import project_claude_code
                with st.spinner("Deploying..."):
                    files = project_claude_code(deploy=True, db_path=DB_PATH)
                st.success("✅ Deployed to ~/.claude/")
                for name, path in files.items():
                    st.caption(f"  {name}: {path}")

    # ── OpenClaw ─────────────────────────────────────────────────────────────
    with st.expander("🦅 OpenClaw Memory Deploy"):
        st.markdown("""
Writes `MEMORY.md` and `memory/YYYY-MM-DD.md` to your OpenClaw workspace memory directory.

**Finding your OpenClaw memory directory:**
It's typically inside your OpenClaw workspace. Check OpenClaw → Settings → Memory for the exact path.
""")
        openclaw_dir_input = st.text_input(
            "OpenClaw memory directory path",
            placeholder="e.g. /path/to/openclaw/workspace/memory",
            key="openclaw_deploy_dir",
        )
        col_oc_prev, col_oc_dep = st.columns(2)
        with col_oc_prev:
            if PROJ_OPENCLAW.exists() and (PROJ_OPENCLAW / "MEMORY.md").exists():
                st.code((PROJ_OPENCLAW / "MEMORY.md").read_text(encoding="utf-8")[:2000],
                        language="markdown")
        with col_oc_dep:
            if st.button("🚀 Deploy to OpenClaw", type="primary"):
                if not openclaw_dir_input.strip():
                    st.error("Please enter the OpenClaw memory directory path.")
                else:
                    from memory_hub.project.openclaw import project_openclaw
                    with st.spinner("Deploying..."):
                        files = project_openclaw(
                            deploy=True,
                            openclaw_memory_dir=Path(openclaw_dir_input.strip()),
                            db_path=DB_PATH,
                        )
                    st.success(f"✅ Deployed to {openclaw_dir_input}")

    # ── ChatGPT ───────────────────────────────────────────────────────────────
    with st.expander("💬 ChatGPT Profile Pack"):
        st.markdown("""
ChatGPT custom instructions don't have an API — copy and paste into
[chatgpt.com → Settings → Personalization → Custom Instructions](https://chatgpt.com).
""")
        if PROJ_CHATGPT.exists():
            cg_files = list(PROJ_CHATGPT.glob("*.md"))
            if cg_files:
                chosen_cg = st.selectbox("View file", [f.name for f in cg_files])
                if chosen_cg:
                    content = (PROJ_CHATGPT / chosen_cg).read_text(encoding="utf-8")
                    st.code(content, language="markdown")
                    st.caption(f"{len(content)} characters")
            else:
                st.info("Generate ChatGPT projections first.")
        else:
            st.info("Generate ChatGPT projections first.")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: Search History
# ══════════════════════════════════════════════════════════════════════════════

elif page == "🔍 Search History":
    st.title("🔍 Search History")
    st.caption("Full-text search across all ingested conversations.")
    _require_db()

    col_q, col_lim = st.columns([5, 1])
    with col_q:
        query = st.text_input("Search query", placeholder="e.g. project name, topic, person, goal...")
    with col_lim:
        limit = st.number_input("Max results", min_value=5, max_value=100, value=20, step=5)

    source_filter = st.multiselect("Filter by source", ["chatgpt", "claude", "openclaw"], default=[])

    if query.strip():
        with get_connection(DB_PATH) as conn:
            results = search_events(conn, query.strip(), limit=limit)

        if source_filter:
            results = [r for r in results if r["source"] in source_filter]

        if results:
            st.markdown(f"**{len(results)} results** for `{query}`")
            for row in results:
                with st.container():
                    col_meta, col_snip = st.columns([2, 5])
                    with col_meta:
                        st.markdown(f"**{row['source'].upper()}**")
                        st.caption(f"📅 {(row['timestamp_utc'] or '')[:10]}")
                        st.caption(f"💬 {(row['conversation_title'] or '')[:40]}")
                    with col_snip:
                        # Strip HTML bold tags for display
                        snippet = (row["snippet"] or "").replace("<b>", "**").replace("</b>", "**")
                        st.markdown(snippet)
                    st.markdown("---")
        else:
            st.info(f"No results for `{query}`")
    else:
        with get_connection(DB_PATH) as conn:
            total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        st.info(f"Enter a search query above. {total:,} events indexed.")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: Sync & Reports
# ══════════════════════════════════════════════════════════════════════════════

elif page == "🔄 Sync & Reports":
    st.title("🔄 Sync & Reports")
    _require_db()

    # ── Manual sync ───────────────────────────────────────────────────────────
    st.subheader("Manual Sync")
    sync_col1, sync_col2 = st.columns(2)

    with sync_col1:
        st.markdown("**Weekly Sync**")
        st.caption("Ingest ChatGPT memories → Reconcile → Project Claude + OpenClaw → Report")
        deploy_weekly = st.checkbox("Deploy projections", key="weekly_deploy")
        if st.button("🔄 Run Weekly Sync", type="primary", use_container_width=True):
            with st.spinner("Running weekly sync..."):
                from memory_hub.sync import sync_weekly
                results = sync_weekly(deploy=deploy_weekly, db_path=DB_PATH)
            st.success("Weekly sync complete!")
            for step in results["steps"]:
                st.caption(step)
            st.caption(f"Report: {results.get('report_path', '')}")

    with sync_col2:
        st.markdown("**Monthly Sync**")
        st.caption("Ingest ChatGPT conversations + memories → Reconcile → All projections → Report")
        deploy_monthly = st.checkbox("Deploy projections", key="monthly_deploy")
        if st.button("🔄 Run Monthly Sync", type="primary", use_container_width=True):
            with st.spinner("Running monthly sync (this may take a minute)..."):
                from memory_hub.sync import sync_monthly
                results = sync_monthly(deploy=deploy_monthly, db_path=DB_PATH)
            st.success("Monthly sync complete!")
            for step in results["steps"]:
                st.caption(step)
            st.caption(f"Report: {results.get('report_path', '')}")

    st.markdown("---")

    # ── Windows Task Scheduler setup ──────────────────────────────────────────
    st.subheader("Automate with Windows Task Scheduler")
    st.markdown("""
Set up automatic weekly and monthly syncs using Windows Task Scheduler.
The PowerShell scripts are in `scripts/` (created during init).
""")

    hub_exe = sys.executable.replace("\\", "/")
    proj_root = str(SCRIPTS_DIR.parent).replace("\\", "\\\\")

    with st.expander("📋 PowerShell scripts and Task Scheduler commands"):
        st.markdown("**`scripts/run_weekly.ps1`:**")
        st.code(
            f'Set-Location "{SCRIPTS_DIR.parent}"\n'
            f'$timestamp = Get-Date -Format "yyyy-MM-dd_HHmmss"\n'
            f'& "{hub_exe}" -m memory_hub.cli sync --profile weekly 2>&1 | '
            f'Tee-Object -FilePath "reports\\sync_weekly_$timestamp.log"',
            language="powershell",
        )

        st.markdown("**`scripts/run_monthly.ps1`:**")
        st.code(
            f'Set-Location "{SCRIPTS_DIR.parent}"\n'
            f'$timestamp = Get-Date -Format "yyyy-MM-dd_HHmmss"\n'
            f'& "{hub_exe}" -m memory_hub.cli sync --profile monthly 2>&1 | '
            f'Tee-Object -FilePath "reports\\sync_monthly_$timestamp.log"',
            language="powershell",
        )

        st.markdown("**Register tasks (run once in PowerShell as Admin):**")
        ps1_weekly = str(SCRIPTS_DIR / "run_weekly.ps1").replace("\\", "\\\\")
        ps1_monthly = str(SCRIPTS_DIR / "run_monthly.ps1").replace("\\", "\\\\")
        st.code(
            f'schtasks /create /tn "MemoryHub-Weekly" /tr '
            f'"powershell -ExecutionPolicy Bypass -File {ps1_weekly}" /sc weekly /d SUN /st 20:00\n'
            f'schtasks /create /tn "MemoryHub-Monthly" /tr '
            f'"powershell -ExecutionPolicy Bypass -File {ps1_monthly}" /sc monthly /d 1 /st 20:00',
            language="powershell",
        )

        if st.button("📝 Write PowerShell scripts to disk"):
            SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
            weekly_script = SCRIPTS_DIR / "run_weekly.ps1"
            monthly_script = SCRIPTS_DIR / "run_monthly.ps1"
            weekly_script.write_text(
                f'Set-Location "{SCRIPTS_DIR.parent}"\n'
                f'$timestamp = Get-Date -Format "yyyy-MM-dd_HHmmss"\n'
                f'& "{sys.executable}" -m memory_hub.cli sync --profile weekly 2>&1 | '
                f'Tee-Object -FilePath "reports\\sync_weekly_$timestamp.log"\n',
                encoding="utf-8",
            )
            monthly_script.write_text(
                f'Set-Location "{SCRIPTS_DIR.parent}"\n'
                f'$timestamp = Get-Date -Format "yyyy-MM-dd_HHmmss"\n'
                f'& "{sys.executable}" -m memory_hub.cli sync --profile monthly 2>&1 | '
                f'Tee-Object -FilePath "reports\\sync_monthly_$timestamp.log"\n',
                encoding="utf-8",
            )
            st.success(f"✅ Scripts written to {SCRIPTS_DIR}")

    st.markdown("---")

    # ── Past reports ─────────────────────────────────────────────────────────
    st.subheader("Past Sync Reports")
    if REPORTS_DIR.exists():
        reports = sorted(REPORTS_DIR.glob("sync_*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        if reports:
            chosen_report = st.selectbox("Select report", [r.name for r in reports])
            if chosen_report:
                content = (REPORTS_DIR / chosen_report).read_text(encoding="utf-8")
                st.markdown(content)
        else:
            st.info("No sync reports yet. Run a sync above.")
    else:
        st.info("Reports directory not found. Run init first.")
