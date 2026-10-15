"""
Personal OS — Daily Narrative.

Instead of splitting activity into sessions using rigid rules (new
session the instant the project label changes), this reads a whole
day's raw activity at once and asks the local LLM to group it into
meaningful blocks — the same way a person reviewing their own day
would: "that YouTube video sitting between two coding blocks was
clearly research for the same project, not a separate distraction."

A rule-based, event-at-a-time classifier structurally can't make
that kind of connective judgment — it only ever sees one event in
isolation. This is the whole point of handing the FULL chronological
picture to the LLM instead.

Why chunking is necessary: a full day can be hundreds of raw events.
Small local models (this targets ~4B-parameter models) degrade with
long, loosely-related context, so the day is split into chunks at
natural time gaps, classified chunk-by-chunk, then merged into one
narrative. This is an explicit quality/context-window trade-off, not
a stylistic choice.

This module depends on the LLM being available — unlike the
rule-based sessionizer, there's no meaningful fallback; if you want
this feature, Ollama needs to be running.

Platform-independent.
"""

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from core.llm_client import LLMClient, LLMUnavailableError
from core.project_matcher import ProjectMatcher
from core.sessionizer import _fetch_events, _event_context

# A gap longer than this between two consecutive events starts a new
# chunk boundary — keeps each LLM call focused on a contiguous block
# of real activity, and keeps chunks a manageable size for a small
# local model's context window.
CHUNK_GAP_MINUTES = 20

# Hard cap on events per chunk regardless of gaps, so one very dense
# stretch of rapid-fire events still doesn't overload the prompt.
MAX_EVENTS_PER_CHUNK = 40

_SYSTEM_PROMPT = (
    "You are analyzing a chronological log of someone's computer activity "
    "for one day. Group the events into contiguous blocks of related "
    "activity — the same way a person reviewing their own day would treat "
    "a YouTube video sitting between two coding sessions on the same "
    "project as related research, not a separate unrelated event. "
    "Respond with ONLY a JSON array, no other text, no markdown fences. "
    "Each array item must have exactly these fields: "
    '"start" (the timestamp of the first event in this block, copied '
    'exactly from the log), "end" (the timestamp of the last event in '
    'this block, copied exactly from the log), "label" (a project name '
    'from the provided list, or "Distraction", or a short new topic name '
    'if it is clearly a distinct learning/research topic not tied to any '
    'project), "category" (one of: Coding, Research, Learning, Notes, '
    'Communication, Entertainment, Other), "description" (one short '
    "sentence on what was actually happening)."
)


@dataclass
class NarrativeBlock:
    start: datetime
    end: datetime
    label: str
    category: str
    description: str

    @property
    def duration_minutes(self) -> float:
        return max(0.0, (self.end - self.start).total_seconds() / 60.0)


def _format_event_line(event: dict, context: dict) -> str:

    parts = [event["timestamp"], event.get("application") or "?"]

    if context.get("file"):
        parts.append(f"file={context['file']}")
    if context.get("workspace"):
        parts.append(f"workspace={context['workspace']}")
    if context.get("note"):
        parts.append(f"note={context['note']}")
    if context.get("vault"):
        parts.append(f"vault={context['vault']}")
    if context.get("domain"):
        parts.append(f"domain={context['domain']}")
    if context.get("page_title"):
        parts.append(f"title={context['page_title']}")

    return " | ".join(parts)


def _chunk_events(events: list[dict]) -> list[list[dict]]:
    """Split events into chunks at natural time gaps and a hard size cap."""

    if not events:
        return []

    chunks: list[list[dict]] = [[events[0]]]

    for prev, curr in zip(events, events[1:]):

        prev_ts = datetime.fromisoformat(prev["timestamp"])
        curr_ts = datetime.fromisoformat(curr["timestamp"])
        gap_minutes = (curr_ts - prev_ts).total_seconds() / 60.0

        if gap_minutes > CHUNK_GAP_MINUTES or len(chunks[-1]) >= MAX_EVENTS_PER_CHUNK:
            chunks.append([])

        chunks[-1].append(curr)

    return chunks


def _build_chunk_prompt(chunk: list[dict], project_names: list[str]) -> str:

    lines = ["Projects:"]
    for name in project_names:
        lines.append(f"- {name}")

    lines.append("")
    lines.append("Activity log (chronological):")

    for event in chunk:
        context = _event_context(event)
        lines.append(_format_event_line(event, context))

    return "\n".join(lines)


def _parse_chunk_response(raw_response: str) -> list[dict]:
    """
    Defensively parse the LLM's JSON response — small local models
    sometimes wrap JSON in markdown fences or add stray text despite
    instructions not to.
    """

    text = raw_response.strip()

    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    try:
        parsed = json.loads(text)
    except ValueError:
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1 or end <= start:
            return []
        try:
            parsed = json.loads(text[start:end + 1])
        except ValueError:
            return []

    if not isinstance(parsed, list):
        return []

    return [item for item in parsed if isinstance(item, dict)]


def _blocks_from_chunk_data(chunk_data: list[dict]) -> list[NarrativeBlock]:

    blocks = []

    for item in chunk_data:
        try:
            start = datetime.fromisoformat(item["start"])
            end = datetime.fromisoformat(item["end"])
        except (KeyError, ValueError, TypeError):
            continue

        blocks.append(NarrativeBlock(
            start=start,
            end=end,
            label=str(item.get("label", "Unassigned")),
            category=str(item.get("category", "Other")),
            description=str(item.get("description", "")),
        ))

    return blocks


def build_daily_narrative(
    date: str,
    client: LLMClient | None = None,
    matcher: ProjectMatcher | None = None,
) -> list[NarrativeBlock]:
    """
    Build a day's narrative by chunking raw events and asking the
    local LLM to group each chunk into meaningful activity blocks.

    Args:
        date:    "YYYY-MM-DD" — the day to summarize.
        client:  Optional LLMClient (constructed if not given).
        matcher: Optional ProjectMatcher, used only to supply the
                 known project names as context to the LLM.

    Returns a chronological list of NarrativeBlock. Raises
    LLMUnavailableError if the local LLM can't be reached — this
    feature has no meaningful non-LLM fallback.
    """

    client = client or LLMClient()
    matcher = matcher or ProjectMatcher()

    if not client.is_available():
        raise LLMUnavailableError(
            "Daily narrative requires the local LLM (Ollama) to be running."
        )

    day_start = f"{date}T00:00:00"
    day_end_dt = datetime.fromisoformat(day_start) + timedelta(days=1)
    day_end = day_end_dt.isoformat()

    events = _fetch_events(since=day_start, until=day_end)

    if not events:
        return []

    project_names = [p["name"] for p in matcher._projects]

    all_blocks: list[NarrativeBlock] = []

    for chunk in _chunk_events(events):

        prompt = _build_chunk_prompt(chunk, project_names)

        raw_response = client.generate(prompt, system=_SYSTEM_PROMPT)

        chunk_data = _parse_chunk_response(raw_response)
        all_blocks.extend(_blocks_from_chunk_data(chunk_data))

    return all_blocks


def summarize_time_by_label(blocks: list[NarrativeBlock]) -> dict[str, float]:
    """Total minutes per label (project/topic/Distraction), descending."""

    totals: dict[str, float] = {}

    for block in blocks:
        totals[block.label] = totals.get(block.label, 0.0) + block.duration_minutes

    return dict(sorted(totals.items(), key=lambda kv: -kv[1]))