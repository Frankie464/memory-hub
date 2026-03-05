"""LLM helpers for memory-hub — fact extraction and conversation summarization.

Uses the Anthropic API (claude-haiku-4-5 by default for cost efficiency).
Falls back gracefully if ANTHROPIC_API_KEY is not set.
"""
import json
import logging
import os
import re

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-haiku-4-5"
BATCH_SIZE = 20  # user messages per LLM call

VALID_CATEGORIES = frozenset({
    "identity", "work", "preference", "relationship",
    "financial", "lifestyle", "interest",
})

FACT_EXTRACTION_PROMPT = """\
Analyze these conversation messages from a user named the user. \
Extract factual statements ONLY about the user (the "user" role messages represent the user speaking).

Rules:
- ONLY extract clearly stated or strongly implied facts about the user personally
- Skip: opinions about external topics, transient requests, conversational filler, \
  assistant responses, generic questions
- Skip vague matches like "Preference: her", "Preference: the app", "Location: Cowork"
- Good examples: "Lives in Springfield", "Works at Acme as Software Engineer", \
  "Drives a [VEHICLE]", "Has a partner"
- Bad examples: "Preference: the money guy", "Location: Springfield Springfield and wants an app..."

Categories: identity, work, preference, relationship, financial, lifestyle, interest

Return a JSON array only. No commentary. Empty array [] if nothing worth extracting.

Format:
[
  {{"category": "identity", "statement": "Lives in Springfield", "confidence": 1.0}},
  {{"category": "work", "statement": "Software Engineer at Acme", "confidence": 1.0}}
]

Messages to analyze:
{messages}"""

SUMMARY_PROMPT = """\
Summarize this conversation between the user and an AI assistant.

Title: {title}
Source: {source}
Messages ({count} total, showing sample):
{messages}

Return JSON only. No commentary.
{{
  "summary": "2-3 sentence summary of what was discussed and any outcomes or decisions",
  "key_topics": ["topic1", "topic2"],
  "key_decisions": ["decision1"]
}}

key_decisions should be empty [] if no concrete decisions were made."""


def is_available() -> bool:
    """Return True if the Anthropic API key is configured."""
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _get_client():
    """Get Anthropic client. Raises ImportError or AuthenticationError if unavailable."""
    from anthropic import Anthropic
    return Anthropic()


def _parse_json_response(text: str, fallback=None):
    """Extract and parse JSON from LLM response text."""
    if fallback is None:
        fallback = []
    # Strip markdown code fences if present
    text = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON array or object in the text
        m = re.search(r"(\[.*\]|\{.*\})", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
    logger.warning("Failed to parse LLM JSON response: %s", text[:200])
    return fallback


def extract_facts(messages: list[dict], model: str = DEFAULT_MODEL) -> list[dict]:
    """
    Extract structured facts about the user from a batch of messages.

    Args:
        messages: list of dicts with keys: role, content, conversation_title
        model: Anthropic model to use

    Returns:
        list of dicts with keys: category, statement, confidence
    """
    if not is_available():
        return []

    # Only send user-role messages to reduce noise
    user_msgs = [m for m in messages if m.get("role") == "user"]
    if not user_msgs:
        return []

    text_block = "\n\n".join(
        f"[{m.get('conversation_title', 'Unknown')}]: {str(m.get('content', ''))[:600]}"
        for m in user_msgs
    )

    try:
        client = _get_client()
        response = client.messages.create(
            model=model,
            max_tokens=1500,
            messages=[{
                "role": "user",
                "content": FACT_EXTRACTION_PROMPT.format(messages=text_block),
            }],
        )
        raw = response.content[0].text
        facts = _parse_json_response(raw, fallback=[])

        # Validate and clean
        cleaned = []
        for f in facts:
            if not isinstance(f, dict):
                continue
            category = f.get("category", "").strip().lower()
            statement = str(f.get("statement", "")).strip()
            confidence = float(f.get("confidence", 0.8))
            if category in VALID_CATEGORIES and len(statement) >= 5:
                cleaned.append({
                    "category": category,
                    "statement": statement,
                    "confidence": min(1.0, max(0.0, confidence)),
                })
        return cleaned

    except Exception as e:
        logger.warning("LLM fact extraction failed: %s", e)
        return []


def summarize_conversation(
    conversation_id: str,
    title: str,
    source: str,
    messages: list[dict],
    model: str = DEFAULT_MODEL,
) -> dict | None:
    """
    Generate a summary for a conversation.

    Args:
        conversation_id: unique conversation ID
        title: conversation title
        source: data source (claude, chatgpt, etc.)
        messages: list of message dicts (role + content)
        model: Anthropic model to use

    Returns:
        dict with summary, key_topics, key_decisions — or None on failure
    """
    if not is_available():
        return None
    if not messages:
        return None

    # Sample messages: first 3 + last 5 to give context without blowing token budget
    sample = messages[:3] + messages[-5:] if len(messages) > 8 else messages
    text_block = "\n".join(
        f"[{m.get('role', '?')}]: {str(m.get('content', ''))[:400]}"
        for m in sample
    )

    try:
        client = _get_client()
        response = client.messages.create(
            model=model,
            max_tokens=500,
            messages=[{
                "role": "user",
                "content": SUMMARY_PROMPT.format(
                    title=title or "Untitled",
                    source=source,
                    count=len(messages),
                    messages=text_block,
                ),
            }],
        )
        raw = response.content[0].text
        result = _parse_json_response(raw, fallback={})
        if isinstance(result, dict) and result.get("summary"):
            return {
                "summary": str(result.get("summary", "")).strip(),
                "key_topics": result.get("key_topics", []),
                "key_decisions": result.get("key_decisions", []),
            }
    except Exception as e:
        logger.warning("LLM summarization failed for %s: %s", conversation_id, e)
    return None
