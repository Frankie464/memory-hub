"""Fact extraction from events + conflict detection."""
import hashlib
import json
import re
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from memory_hub.config import DB_PATH, PROFILE_GENERATED_PATH, PROFILE_MANUAL_PATH
from memory_hub.db import get_connection, get_active_facts, sanitize_statement, upsert_fact

# ── Pattern definitions ────────────────────────────────────────────────────────

PATTERNS = {
    "identity": [
        (re.compile(r"\bmy name is ([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\b"), "Name: {}"),
        (re.compile(r"\bi(?:'m| am) ([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\b"), "Goes by: {}"),
        (re.compile(r"\bborn in (\d{4})\b"), "Birth year: {}"),
        (re.compile(r"\bi(?:'m| am) (\d+) years? old\b"), "Age: {}"),
        (re.compile(r"\blive(?:s)? in ([A-Z][A-Za-z\s]+(?:area|,\s*[A-Z]{2})?)\b"), "Location: {}"),
    ],
    "work": [
        (re.compile(r"\bwork(?:ing)? (?:at|for|@) ([A-Z][A-Za-z\s]+?(?:Inc|LLC|Corp|Company)?)[\.,\b]"), "Employer: {}"),
        (re.compile(r"\b(?:my job|my role|my position) (?:is|as) ([a-zA-Z\s]+?)[,\.\n]"), "Role: {}"),
        (re.compile(r"\b[ROLE]\b"), "Domain: work domain"),
        (re.compile(r"\bAcme\b"), "Employer: Acme"),
        (re.compile(r"\b[vendor]\b"), "Tool: [vendor] VNA"),
        (re.compile(r"\b[protocol]\b"), "Protocol: [protocol]"),
    ],
    "preference": [
        (re.compile(r"\bi (?:prefer|like|love|hate|dislike|use) ([a-zA-Z\s]+?)[,\.\n]", re.IGNORECASE), "Preference: {}"),
        (re.compile(r"\bdon't use em dash", re.IGNORECASE), "Style: No em dashes"),
        (re.compile(r"\bno sycophancy\b", re.IGNORECASE), "Style: Anti-sycophancy"),
        (re.compile(r"\bdirect(?:ness)?\b", re.IGNORECASE), "Style: Direct communication"),
    ],
    "relationship": [
        (re.compile(r"\bmy girlfriend ([A-Z][a-z]+)\b"), "Girlfriend: {}"),
        (re.compile(r"\bmy roommate(?:s)? ([A-Z][a-z]+(?:,?\s+and\s+[A-Z][a-z]+)*)\b"), "Roommate(s): {}"),
        (re.compile(r"\bmy (?:sister|sibling) ([A-Z][a-z]+)\b"), "Sister: {}"),
        (re.compile(r"\b[redacted]\b"), "Partner: [redacted]"),
    ],
    "financial": [
        (re.compile(r"\b\$(\d{1,3}(?:,\d{3})*(?:k|K)?)\s*(?:salary|a year|annual)\b"), "Salary: ${}"),
        (re.compile(r"\b401k\b", re.IGNORECASE), "Account: 401k"),
        (re.compile(r"\bHSA\b"), "Account: HSA"),
        (re.compile(r"\bRoth IRA\b", re.IGNORECASE), "Account: Roth IRA"),
        (re.compile(r"\bFIRE\b"), "Goal: FIRE (Financial Independence)"),
    ],
    "lifestyle": [
        (re.compile(r"\b[VEHICLE]\b"), "Vehicle: [VEHICLE] (EV)"),
        (re.compile(r"\belectric vehicle\b|EV commute\b", re.IGNORECASE), "Transport: EV"),
        (re.compile(r"\bChi(?:cago)?\b"), "Location: Springfield area"),
        (re.compile(r"\bcannabis\b|\bweed\b|\bmarijuana\b", re.IGNORECASE), "Lifestyle: Cannabis user"),
        (re.compile(r"\btherapy\b|\btherapist\b", re.IGNORECASE), "Health: In therapy"),
    ],
    "interest": [
        (re.compile(r"\bLeague of Legends\b", re.IGNORECASE), "Gaming: League of Legends"),
        (re.compile(r"\bFallout\b", re.IGNORECASE), "Gaming: Fallout"),
        (re.compile(r"\bWes Anderson\b", re.IGNORECASE), "Movies: Wes Anderson fan"),
        (re.compile(r"\b3D print\b", re.IGNORECASE), "Hobby: 3D printing"),
        (re.compile(r"\bespresso\b", re.IGNORECASE), "Interest: Coffee/espresso"),
        (re.compile(r"\bPi.hole\b", re.IGNORECASE), "Tech: Pi-hole home network"),
        (re.compile(r"\bPiVPN\b", re.IGNORECASE), "Tech: PiVPN home network"),
        (re.compile(r"\bBambu\b", re.IGNORECASE), "Hobby: 3D printing (Bambu)"),
    ],
}

# Topics for frequency-based interest detection
TOPIC_KEYWORDS = {
    "work domain": ["[role]", "s-parameter", "vna", "smith chart", "microwave", "antenna", "rf design"],
    "Personal finance": ["401k", "hsa", "roth", "etf", "investing", "portfolio", "savings"],
    "Apple ecosystem": ["iphone", "apple watch", "airpods", "macbook", "ios"],
    "Home networking": ["pihole", "pi-hole", "unbound", "pivpn", "orbi", "router"],
    "Fitness": ["gym", "workout", "push", "pull", "legs", "cardio", "protein"],
    "Cannabis": ["cannabis", "weed", "strain", "vape", "dispensary"],
}


def _fact_id(category: str, statement: str) -> str:
    raw = f"{category}:{statement.lower().strip()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _detect_topic_interests(events: list) -> list:
    """Find topics mentioned 3+ times across user messages."""
    all_text = " ".join(
        e["content"].lower()
        for e in events
        if e["role"] in ("user", "system", None)
    )
    interests = []
    for topic, keywords in TOPIC_KEYWORDS.items():
        count = sum(all_text.count(kw) for kw in keywords)
        if count >= 3:
            interests.append(f"Strong interest: {topic}")
    return interests


def reconcile(db_path: Path = DB_PATH) -> dict:
    """
    Scan all events, extract candidate facts, detect conflicts, update facts DB.
    Returns stats dict.
    """
    stats = {"facts_added": 0, "facts_confirmed": 0, "conflicts_added": 0}
    now = _now_iso()

    with get_connection(db_path) as conn:
        # Fetch events not yet reconciled (all for simplicity; dedup handles re-runs)
        events = conn.execute("SELECT * FROM events").fetchall()
        events = [dict(e) for e in events]

        candidate_statements = []  # (category, statement, evidence_ids)

        # Pattern-based extraction
        for event in events:
            content = event.get("content", "")
            ev_id = event["event_id"]
            for category, pattern_list in PATTERNS.items():
                for pattern, template in pattern_list:
                    m = pattern.search(content)
                    if m:
                        if "{}" in template and m.lastindex:
                            statement = template.format(m.group(1).strip())
                        else:
                            statement = template
                        statement = sanitize_statement(statement)
                        if statement:
                            candidate_statements.append((category, statement, ev_id))

        # Frequency-based topic interests from ALL events
        topic_interests = _detect_topic_interests(events)
        for stmt in topic_interests:
            candidate_statements.append(("interest", stmt, None))

        # Dedup candidates (same category+statement → group evidence_ids)
        merged: dict[str, dict] = {}
        for category, statement, ev_id in candidate_statements:
            key = _fact_id(category, statement)
            if key not in merged:
                merged[key] = {
                    "fact_id": key,
                    "category": category,
                    "statement": statement,
                    "evidence_event_ids": [],
                    "confidence": 0.5,
                    "first_seen": now,
                    "last_seen": now,
                    "ttl_class": "permanent",
                }
            if ev_id:
                merged[key]["evidence_event_ids"].append(ev_id)
            # Boost confidence for repeated mentions (caps at 1.0)
            merged[key]["confidence"] = min(1.0, merged[key]["confidence"] + 0.05)

        for key, fact in merged.items():
            fact["evidence_event_ids"] = json.dumps(list(set(fact["evidence_event_ids"])))
            result = upsert_fact(conn, fact)
            if result == "inserted":
                stats["facts_added"] += 1
            else:
                stats["facts_confirmed"] += 1

        # Log the reconcile run
        log_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO reconcile_log (log_id, facts_added, facts_confirmed, conflicts_added)
               VALUES (?,?,?,?)""",
            (log_id, stats["facts_added"], stats["facts_confirmed"], stats["conflicts_added"]),
        )

    # Regenerate the generated profile
    _generate_profile(db_path)
    return stats


def _generate_profile(db_path: Path = DB_PATH) -> None:
    """Write user_profile.generated.md from active facts. Never touches manual.md."""
    now = datetime.now().strftime("%Y-%m-%d")

    with get_connection(db_path) as conn:
        facts = get_active_facts(conn)

    by_category: dict[str, list] = {}
    for f in facts:
        cat = f["category"]
        by_category.setdefault(cat, []).append(f["statement"])

    order = ["identity", "preference", "work", "interest", "relationship", "lifestyle", "financial"]
    category_labels = {
        "identity": "Identity",
        "preference": "Communication Style",
        "work": "Professional",
        "interest": "Interests & Domains",
        "relationship": "Relationships",
        "lifestyle": "Lifestyle",
        "financial": "Financial Framework",
    }

    lines = [
        "# the user — Auto-Generated Profile",
        f"# Generated by memory-hub on {now}",
        "# Source: canonical facts database",
        "# NOTE: For manual edits, use user_profile.manual.md",
        "",
    ]

    for cat in order:
        if cat in by_category:
            lines.append(f"## {category_labels.get(cat, cat.title())}")
            for stmt in by_category[cat]:
                lines.append(f"- {stmt}")
            lines.append("")

    # Any categories not in the order list
    for cat, stmts in by_category.items():
        if cat not in order:
            lines.append(f"## {cat.title()}")
            for stmt in stmts:
                lines.append(f"- {stmt}")
            lines.append("")

    PROFILE_GENERATED_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_GENERATED_PATH.write_text("\n".join(lines), encoding="utf-8")
