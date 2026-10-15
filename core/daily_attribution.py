"""Evidence-backed day-end project, topic, and entertainment attribution.

Raw activity events remain the source of truth. The local model can label
factual blocks, but it never supplies timestamps or durations.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from core.activity_classifier import classify_event
from core.llm_client import LLMClient, LLMUnavailableError
from core.project_matcher import CONFIDENCE_NONE, DISTRACTION, UNASSIGNED, ProjectMatcher
from core.sessionizer import _event_context, _fetch_events
from core.topic_matcher import TopicMatcher

MAX_OBSERVED_INTERVAL_MINUTES = 2
VALID_CATEGORIES = {"Coding", "Research", "Learning", "Notes", "Communication", "Entertainment", "Other"}
_SYSTEM_PROMPT = (
    "Label a factual computer-activity timeline. Return ONLY a JSON array of "
    "objects with id, label, category, reason. Reuse ids exactly. Do not add, "
    "remove, merge, reorder blocks, or provide times. Related tutorials/docs "
    "need supporting evidence; unrelated streaming/browsing is Entertainment. "
    "A VS Code workspace name is direct evidence of a proposed project. Reuse "
    "that exact workspace label for code in it, even before it is confirmed; it "
    "will be marked as needing confirmation by the app. Never attach a browser "
    "page to a project merely because it happened nearby in time or contains a "
    "vaguely related word. You may treat a repeated technical conversation as a "
    "supporting resource only when it alternates tightly with a proposed VS Code "
    "workspace and that workspace's local preview; videos and unrelated searches "
    "still remain Unclassified. A local preview whose title or URL explicitly "
    "names a workspace is direct evidence. Use Unclassified when uncertain. Cite only "
    "observed facts in reason."
)


@dataclass(frozen=True)
class ActivityInterval:
    event_id: int
    start: datetime
    end: datetime
    event: dict

    @property
    def duration_minutes(self) -> float:
        return max(0.0, (self.end - self.start).total_seconds() / 60)


@dataclass
class FactualBlock:
    id: str
    start: datetime
    end: datetime
    intervals: list[ActivityInterval] = field(default_factory=list)

    @property
    def duration_minutes(self) -> float:
        return max(0.0, (self.end - self.start).total_seconds() / 60)

    @property
    def representative_event(self) -> dict:
        return self.intervals[-1].event

    def context(self) -> dict:
        return _event_context(self.representative_event)

    def evidence(self) -> list[str]:
        event, context = self.representative_event, self.context()
        facts = [f"application={event.get('application') or event.get('process') or 'Unknown'}"]
        for key in ("workspace", "file", "note", "vault", "domain", "page_title", "path"):
            if context.get(key):
                facts.append(f"{key}={context[key]}")
        # The browser window title is a useful fallback when an extension
        # reports a generic/stale title such as simply "YouTube".
        title = event.get("window_title")
        if title and title != context.get("page_title"):
            facts.append(f"window_title={title}")
        return facts


@dataclass(frozen=True)
class AttributedBlock:
    factual: FactualBlock
    label: str
    category: str
    confidence: str
    source: str
    reason: str

    @property
    def start(self) -> datetime:
        return self.factual.start

    @property
    def end(self) -> datetime:
        return self.factual.end

    @property
    def duration_minutes(self) -> float:
        return self.factual.duration_minutes

    @property
    def evidence(self) -> list[str]:
        return self.factual.evidence()


def derive_intervals(events: list[dict], *, final_end: datetime | None = None, max_minutes: int = MAX_OBSERVED_INTERVAL_MINUTES) -> list[ActivityInterval]:
    """Bound each event by the next fact (or a short cap), never a guessed span."""
    intervals, cap = [], timedelta(minutes=max_minutes)
    for index, event in enumerate(events):
        start = datetime.fromisoformat(event["timestamp"])
        following = datetime.fromisoformat(events[index + 1]["timestamp"]) if index + 1 < len(events) else final_end
        if following is None:
            continue
        end = min(following, start + cap)
        if end > start:
            intervals.append(ActivityInterval(int(event["id"]), start, end, event))
    return intervals


def _signature(interval: ActivityInterval) -> tuple:
    event, context = interval.event, _event_context(interval.event)
    return tuple([event.get("application") or event.get("process")] + [context.get(key) for key in ("workspace", "file", "note", "vault", "domain", "page_title", "path")])


def build_factual_blocks(intervals: list[ActivityInterval]) -> list[FactualBlock]:
    """Condense adjacent identical observations without changing their facts."""
    blocks: list[FactualBlock] = []
    for interval in intervals:
        if blocks and _signature(blocks[-1].intervals[-1]) == _signature(interval):
            blocks[-1].end = interval.end
            blocks[-1].intervals.append(interval)
        else:
            blocks.append(FactualBlock(f"b{len(blocks) + 1}", interval.start, interval.end, [interval]))
    return blocks


def _workspace_candidates(blocks: list[FactualBlock], matcher: ProjectMatcher) -> dict[str, str]:
    """Return unconfirmed VS Code workspaces that deserve one project question.

    A workspace is a much stronger and less ambiguous signal than an individual
    filename.  We use its exact name as a *provisional* label; it is never
    persisted as a project until the user confirms it in the review flow.
    """
    candidates: dict[str, str] = {}
    for block in blocks:
        event, context = block.representative_event, block.context()
        workspace = (context.get("workspace") or "").strip()
        if not workspace:
            continue
        label, _confidence = matcher.match_with_confidence(event.get("window_title"), context)
        if label == UNASSIGNED:
            candidates[workspace.lower()] = workspace
    return candidates


def _mentions_workspace(context: dict, workspace: str) -> bool:
    """True only when a browser item explicitly names the workspace.

    This deliberately does not use time proximity.  A generic Claude chat or
    video open between coding events is not evidence that it belongs to the
    project.
    """
    needle = workspace.strip().lower()
    if not needle:
        return False
    haystack = " ".join(str(context.get(key) or "") for key in ("page_title", "url", "path"))
    return needle in haystack.lower()


def _fallback(
    block: FactualBlock,
    matcher: ProjectMatcher,
    candidates: dict[str, str],
) -> AttributedBlock:
    event, context = block.representative_event, block.context()
    label, confidence = matcher.match_with_confidence(event.get("window_title"), context)
    category = classify_event(event.get("application"), context)
    topic = TopicMatcher().match(context)
    if topic:
        return AttributedBlock(block, topic[0], topic[1], "high", "user_rule", "Matched a user-confirmed topic rule.")
    if label == DISTRACTION or category == "Entertainment":
        return AttributedBlock(block, "Entertainment", "Entertainment", confidence, "rule", "Observed entertainment or configured distraction evidence.")
    if label != UNASSIGNED:
        return AttributedBlock(block, label, category, confidence, "rule", "Matched configured project evidence.")

    workspace = (context.get("workspace") or "").strip()
    if workspace and workspace.lower() in candidates:
        return AttributedBlock(
            block, candidates[workspace.lower()], "Coding", "proposed", "workspace_candidate",
            f"Observed VS Code workspace '{workspace}'; confirm this project once to remember it.",
        )

    for candidate in candidates.values():
        if _mentions_workspace(context, candidate):
            return AttributedBlock(
                block, candidate, "Coding", "proposed", "direct_workspace_resource",
                f"Observed a local resource explicitly named '{candidate}'.",
            )
    return AttributedBlock(block, "Unclassified", category, CONFIDENCE_NONE, "fallback", "No sufficient project evidence yet.")


def _prompt(blocks: list[FactualBlock], project_names: list[str], candidates: dict[str, str]) -> str:
    lines = ["Confirmed projects:", *[f"- {name}" for name in project_names], "", "Proposed VS Code workspaces:"]
    lines.extend(f"- {name}" for name in candidates.values())
    lines.extend(["", "Observed blocks:"])
    for block in blocks:
        lines.append(f"{block.id} | {block.start.isoformat()} | {round(block.duration_minutes, 1)} minutes | " + "; ".join(block.evidence()))
    return "\n".join(lines)


def _parse(raw: str) -> dict[str, dict]:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
    try:
        items = json.loads(text)
    except ValueError:
        return {}
    return {str(item.get("id")): item for item in items if isinstance(item, dict) and item.get("id")} if isinstance(items, list) else {}


def attribute_blocks(blocks: list[FactualBlock], matcher: ProjectMatcher, client: LLMClient | None = None) -> list[AttributedBlock]:
    """Use local LLM labels when available; preserve an honest offline fallback."""
    candidates = _workspace_candidates(blocks, matcher)
    fallback = {block.id: _fallback(block, matcher, candidates) for block in blocks}
    if not blocks or client is None or not client.is_available():
        return list(fallback.values())
    try:
        labels = _parse(client.generate(
            _prompt(blocks, [item["name"] for item in matcher._projects], candidates), system=_SYSTEM_PROMPT
        ))
    except LLMUnavailableError:
        return list(fallback.values())
    result = []
    allowed_labels = {"Unclassified", "Entertainment"}
    allowed_labels.update(item["name"] for item in matcher._projects)
    allowed_labels.update(candidates.values())
    for block in blocks:
        item = labels.get(block.id)
        # Do not let a model erase direct workspace/local-preview evidence.
        if fallback[block.id].source in {"workspace_candidate", "direct_workspace_resource", "rule", "user_rule"}:
            result.append(fallback[block.id])
            continue
        if not item:
            result.append(fallback[block.id])
            continue
        label = str(item.get("label") or "").strip()[:120]
        category = str(item.get("category") or "").strip()
        reason = str(item.get("reason") or "Local model associated observed evidence.").strip()[:300]
        if not label or label not in allowed_labels or category not in VALID_CATEGORIES:
            result.append(fallback[block.id])
        else:
            result.append(AttributedBlock(block, label, category, "inferred", "llm", reason))
    return result


def build_daily_attribution(date: str, client: LLMClient | None = None, matcher: ProjectMatcher | None = None) -> list[AttributedBlock]:
    matcher = matcher or ProjectMatcher()
    day_start = datetime.fromisoformat(f"{date}T00:00:00")
    day_end = day_start + timedelta(days=1)
    events = _fetch_events(since=day_start.isoformat(), until=day_end.isoformat())
    blocks = build_factual_blocks(derive_intervals(events, final_end=day_end))
    return attribute_blocks(blocks, matcher, client or LLMClient())


def summarize_time_by_label(blocks: list[AttributedBlock]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for block in blocks:
        totals[block.label] = totals.get(block.label, 0.0) + block.duration_minutes
    return dict(sorted(totals.items(), key=lambda item: -item[1]))
