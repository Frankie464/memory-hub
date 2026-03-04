"""Ingest GitHub repo metadata and READMEs via gh CLI."""
import base64
import hashlib
import json
import subprocess
from pathlib import Path

from memory_hub.config import DB_PATH
from memory_hub.db import get_connection, insert_event, log_ingest_start, log_ingest_complete


def _event_id(owner: str, repo: str, data_type: str) -> str:
    """Deterministic event ID: SHA256(github:{owner}/{repo}:{type})."""
    raw = f"github:{owner}/{repo}:{data_type}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _run_gh(*args: str) -> str:
    """Run a gh CLI command and return stdout. Raises on failure."""
    result = subprocess.run(
        ["gh", *args],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        if "not logged in" in stderr.lower() or "auth login" in stderr.lower():
            raise RuntimeError(
                "GitHub CLI not authenticated. Run: gh auth login"
            )
        raise RuntimeError(f"gh {' '.join(args)} failed: {stderr}")
    return result.stdout.strip()


def _get_username() -> str:
    """Auto-detect authenticated GitHub username."""
    return _run_gh("api", "user", "--jq", ".login")


def _get_user_profile() -> dict:
    """Fetch user profile data."""
    raw = _run_gh("api", "user")
    return json.loads(raw)


def _get_repos(username: str) -> list[dict]:
    """Fetch non-fork repos with metadata."""
    raw = _run_gh(
        "repo", "list", username,
        "--json", "name,description,primaryLanguage,languages,isFork,isPrivate",
        "--limit", "100",
    )
    repos = json.loads(raw)
    return [r for r in repos if not r.get("isFork", False)]


def _get_readme(owner: str, repo: str) -> str | None:
    """Fetch README content (base64-decoded). Returns None if not found."""
    try:
        raw = _run_gh("api", f"repos/{owner}/{repo}/readme")
        data = json.loads(raw)
        content_b64 = data.get("content", "")
        return base64.b64decode(content_b64).decode("utf-8", errors="replace")
    except (RuntimeError, json.JSONDecodeError, KeyError):
        return None


def _synthesize_profile_event(profile: dict) -> str:
    """Build a natural-language event from GitHub user profile."""
    parts = []
    name = profile.get("name") or profile.get("login", "")
    if name:
        parts.append(f"I am {name}")
    location = profile.get("location")
    if location:
        parts.append(f"I live in {location}")
    bio = profile.get("bio")
    if bio:
        parts.append(bio)
    company = profile.get("company")
    if company:
        parts.append(f"I work at {company}")
    return ". ".join(parts) + "." if parts else ""


def _synthesize_repo_event(repo: dict) -> str:
    """Build a natural-language event from repo metadata."""
    name = repo.get("name", "")
    desc = repo.get("description") or ""
    langs = [l.get("node", {}).get("name", "") for l in repo.get("languages", [])]
    langs = [l for l in langs if l]
    lang_str = ", ".join(langs) if langs else ""

    parts = [f"I built a project called {name}"]
    if lang_str:
        parts[0] += f" using {lang_str}"
    if desc:
        parts.append(desc)
    return ". ".join(parts) + "."


def ingest_github(username: str | None = None, db_path: Path = DB_PATH) -> dict:
    """
    Ingest GitHub repo metadata and READMEs via gh CLI.

    Creates synthesized natural-language events from structured data
    so the reconcile pipeline can extract facts.

    Returns stats dict.
    """
    stats = {
        "repos_found": 0,
        "readmes_fetched": 0,
        "events_added": 0,
        "events_skipped": 0,
    }

    # Auto-detect username if not provided
    if not username:
        username = _get_username()

    with get_connection(db_path) as conn:
        log_id = log_ingest_start(conn, "github", f"github.com/{username}")

        # ── User profile event ──
        try:
            profile = _get_user_profile()
            profile_text = _synthesize_profile_event(profile)
            if profile_text:
                event = {
                    "event_id": _event_id(username, "_profile", "profile"),
                    "source": "github",
                    "timestamp_utc": profile.get("updated_at"),
                    "role": "system",
                    "content": profile_text,
                    "conversation_id": f"github:{username}",
                    "conversation_title": "GitHub Profile",
                    "topic_tags": "[]",
                }
                if insert_event(conn, event):
                    stats["events_added"] += 1
                else:
                    stats["events_skipped"] += 1
        except RuntimeError:
            pass  # Profile fetch failed, continue with repos

        # ── Repo events ──
        repos = _get_repos(username)
        stats["repos_found"] = len(repos)

        for repo in repos:
            repo_name = repo["name"]

            # Synthesized repo summary event
            summary_text = _synthesize_repo_event(repo)
            event = {
                "event_id": _event_id(username, repo_name, "summary"),
                "source": "github",
                "timestamp_utc": None,
                "role": "system",
                "content": summary_text,
                "conversation_id": f"github:{username}/{repo_name}",
                "conversation_title": f"GitHub: {repo_name}",
                "topic_tags": "[]",
            }
            if insert_event(conn, event):
                stats["events_added"] += 1
            else:
                stats["events_skipped"] += 1

            # README event (raw content — may contain first-person descriptions)
            readme = _get_readme(username, repo_name)
            if readme and len(readme.strip()) > 50:
                stats["readmes_fetched"] += 1
                event = {
                    "event_id": _event_id(username, repo_name, "readme"),
                    "source": "github",
                    "timestamp_utc": None,
                    "role": "system",
                    "content": readme,
                    "conversation_id": f"github:{username}/{repo_name}",
                    "conversation_title": f"GitHub: {repo_name}",
                    "topic_tags": "[]",
                }
                if insert_event(conn, event):
                    stats["events_added"] += 1
                else:
                    stats["events_skipped"] += 1

        log_ingest_complete(conn, log_id, stats["events_added"], stats["events_skipped"])

    return stats
