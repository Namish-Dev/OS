"""Human-readable daily report built from the factual attribution blocks."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from core.daily_attribution import AttributedBlock

MIN_DISPLAY_MINUTES = 0.5


@dataclass
class ReportGroup:
    """A contiguous, readable activity section; raw filenames stay evidence only."""

    label: str
    category: str
    start: datetime
    end: datetime
    blocks: list[AttributedBlock] = field(default_factory=list)
    resources: set[str] = field(default_factory=set)
    resource_titles: set[str] = field(default_factory=set)
    workspaces: set[str] = field(default_factory=set)
    files: set[str] = field(default_factory=set)
    needs_confirmation: bool = False

    @property
    def duration_minutes(self) -> float:
        return max(0.0, (self.end - self.start).total_seconds() / 60.0)

    @property
    def evidence_summary(self) -> str:
        if self.workspaces:
            workspace = sorted(self.workspaces)[0]
            if self.needs_confirmation:
                return f"Worked in the VS Code workspace '{workspace}' (needs your one-time confirmation)."
            return f"Worked in the VS Code workspace '{workspace}'."
        reasons = []
        for block in self.blocks:
            if block.reason and block.reason not in reasons:
                reasons.append(block.reason)
        return " ".join(reasons[:2])


@dataclass
class DailySummary:
    """A whole-day view of one project/topic, not a raw event stream."""

    label: str
    groups: list[ReportGroup] = field(default_factory=list)
    resources: set[str] = field(default_factory=set)
    resource_titles: set[str] = field(default_factory=set)
    categories: set[str] = field(default_factory=set)
    workspaces: set[str] = field(default_factory=set)
    files: set[str] = field(default_factory=set)
    needs_confirmation: bool = False

    @property
    def duration_minutes(self) -> float:
        return sum(group.duration_minutes for group in self.groups)


def _facts(block: AttributedBlock) -> dict[str, set[str]]:
    """Collect reportable facts from every raw event in a factual block."""
    result = {"resources": set(), "titles": set(), "workspaces": set(), "files": set()}
    for interval in block.factual.intervals:
        event = interval.event
        context = {
            key: event.get(key)
            for key in ("domain", "page_title", "workspace", "file")
        }
        if context["domain"]:
            result["resources"].add(str(context["domain"]))
        if context["page_title"]:
            result["titles"].add(str(context["page_title"]))
        if context["workspace"]:
            result["workspaces"].add(str(context["workspace"]))
        if context["file"]:
            result["files"].add(str(context["file"]))
    return result


def build_report_groups(blocks: list[AttributedBlock], merge_gap_minutes: int = 5) -> list[ReportGroup]:
    """Merge adjacent blocks with the same final attribution."""
    groups: list[ReportGroup] = []
    for block in blocks:
        # Foreground switches can share a timestamp at second precision. They
        # are useful raw evidence but should not appear as fake 0-minute work
        # in the human-facing report.
        if block.duration_minutes < MIN_DISPLAY_MINUTES:
            continue
        facts = _facts(block)
        context_resources = facts["resources"]
        if groups:
            previous = groups[-1]
            gap = (block.start - previous.end).total_seconds() / 60.0
            if previous.label == block.label and previous.category == block.category and gap <= merge_gap_minutes:
                previous.end = max(previous.end, block.end)
                previous.blocks.append(block)
                previous.resources.update(context_resources)
                previous.resource_titles.update(facts["titles"])
                previous.workspaces.update(facts["workspaces"])
                previous.files.update(facts["files"])
                previous.needs_confirmation = previous.needs_confirmation or block.source in {
                    "workspace_candidate", "direct_workspace_resource"
                }
                continue
        group = ReportGroup(
            label=block.label,
            category=block.category,
            start=block.start,
            end=block.end,
            blocks=[block],
            resources=context_resources,
            resource_titles=facts["titles"],
            workspaces=facts["workspaces"],
            files=facts["files"],
            needs_confirmation=block.source in {"workspace_candidate", "direct_workspace_resource"},
        )
        groups.append(group)
    return groups


def summarize_groups(groups: list[ReportGroup]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for group in groups:
        totals[group.label] = totals.get(group.label, 0.0) + group.duration_minutes
    return dict(sorted(totals.items(), key=lambda item: -item[1]))


def build_daily_summaries(groups: list[ReportGroup]) -> list[DailySummary]:
    """Combine non-contiguous project activity into the report the user reads.

    Unclassified and entertainment blocks intentionally remain separate. They
    must never inflate a project's duration just because they occurred between
    two coding windows.
    """
    summaries: dict[str, DailySummary] = {}
    for group in groups:
        if group.label in {"Unclassified", "Entertainment"}:
            continue
        summary = summaries.setdefault(group.label, DailySummary(group.label))
        summary.groups.append(group)
        summary.resources.update(group.resources)
        summary.resource_titles.update(group.resource_titles)
        summary.categories.add(group.category)
        summary.workspaces.update(group.workspaces)
        summary.files.update(group.files)
        summary.needs_confirmation = summary.needs_confirmation or group.needs_confirmation
    return sorted(summaries.values(), key=lambda item: item.duration_minutes, reverse=True)
