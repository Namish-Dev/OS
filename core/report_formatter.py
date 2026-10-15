"""
Personal OS — Report Formatter.

Transforms the structured daily attribution data (DailySummary,
ReportGroup, ReviewItem) into the clean, human-readable daily
report the user wants.

This is purely a presentation layer — it never touches the database,
sensors, or classification logic.  It reads the output of
core/daily_report.py and core/review_queue.py and formats it.

Platform-independent.
"""

from __future__ import annotations

from datetime import datetime

# ---------------------------------------------------------------------------
# Human-friendly domain mappings
# ---------------------------------------------------------------------------

_DOMAIN_FRIENDLY: dict[str, str] = {
    "claude.ai": "Claude",
    "chatgpt.com": "ChatGPT",
    "chat.openai.com": "ChatGPT",
    "gemini.google.com": "Gemini",
    "github.com": "GitHub",
    "gitlab.com": "GitLab",
    "stackoverflow.com": "Stack Overflow",
    "youtube.com": "YouTube",
    "google.com": "Google Search",
    "docs.python.org": "Python docs",
    "developer.mozilla.org": "MDN Web Docs",
    "pypi.org": "PyPI",
    "npmjs.com": "npm",
    "localhost": "localhost",
    "127.0.0.1": "localhost",
    "0.0.0.0": "localhost",
    "reddit.com": "Reddit",
    "twitter.com": "Twitter/X",
    "x.com": "Twitter/X",
    "netflix.com": "Netflix",
    "twitch.tv": "Twitch",
    "en.wikipedia.org": "Wikipedia",
}

_AI_DOMAINS = {"claude.ai", "chatgpt.com", "chat.openai.com", "gemini.google.com"}
_LOCAL_DOMAINS = {"localhost", "127.0.0.1", "0.0.0.0"}
_DOC_DOMAINS = {"docs.python.org", "developer.mozilla.org", "devdocs.io", "docs.rs"}
_ENTERTAINMENT_DOMAINS = {"netflix.com", "twitch.tv", "disneyplus.com", "primevideo.com"}

# Titles that carry no real signal — a bare homepage, a generic
# browser tab name, etc.
_GENERIC_TITLES = frozenset({
    "youtube", "google chrome", "new tab", "google", "home", "",
    "brave", "microsoft edge", "edge",
})


# ---------------------------------------------------------------------------
# Duration formatting
# ---------------------------------------------------------------------------

def _fmt_duration(minutes: float) -> str:
    """Format minutes into a human-readable string.

    Examples: "< 1 minute", "4 minutes", "1h 12m".
    """
    total = round(minutes)
    if total < 1:
        return "< 1 minute"
    hours, mins = divmod(total, 60)
    if hours and mins:
        return f"{hours}h {mins}m"
    if hours:
        return f"{hours}h"
    return f"{mins} minute{'s' if mins != 1 else ''}"


# ---------------------------------------------------------------------------
# Domain helpers
# ---------------------------------------------------------------------------

def _friendly(domain: str) -> str:
    """Return a human-friendly name for a domain."""
    return _DOMAIN_FRIENDLY.get(domain.lower(), domain)


# ---------------------------------------------------------------------------
# Narrative generation ("What you did")
# ---------------------------------------------------------------------------

def _collect_resource_map(summary) -> dict[str, set[str]]:
    """Walk a DailySummary's evidence and build domain → {page_titles}.

    This reconstructs the domain-to-title relationship that the flat
    `resources` / `resource_titles` sets on DailySummary lose.
    """
    mapping: dict[str, set[str]] = {}
    for group in summary.groups:
        for block in group.blocks:
            for interval in block.factual.intervals:
                event = interval.event
                domain = event.get("domain")
                title = event.get("page_title")
                if not domain:
                    continue
                titles = mapping.setdefault(domain, set())
                if title and title.strip().lower() not in _GENERIC_TITLES and \
                        title.strip().lower() != domain.lower() and \
                        title.strip().lower() != _friendly(domain).lower():
                    titles.add(title.strip())
    return mapping


def _build_narrative(summary) -> str:
    """Generate a plain-language 'What you did' sentence from evidence."""
    domains = {d.lower() for d in summary.resources}
    has_workspace = bool(summary.workspaces)
    has_localhost = bool(domains & _LOCAL_DOMAINS)
    has_ai = bool(domains & _AI_DOMAINS)
    has_docs = bool(domains & _DOC_DOMAINS)
    categories = {c.lower() for c in summary.categories}

    # Primary activity clause
    if has_workspace:
        workspace = sorted(summary.workspaces)[0]
        if has_localhost:
            primary = (
                f"Worked on the {workspace} application in VS Code "
                f"and tested it in the local browser preview"
            )
        else:
            primary = f"Worked on the {workspace} project in VS Code"
    elif "notes" in categories:
        primary = "Took and organized notes in Obsidian"
    elif "research" in categories:
        primary = "Researched and read documentation online"
    elif "coding" in categories:
        primary = "Wrote and edited code"
    else:
        primary = "Worked on this project"

    # Optional secondary activities (only when not already covered)
    extras: list[str] = []
    if has_ai and "ai" not in primary.lower():
        extras.append("used AI assistance")
    if has_docs and "documentation" not in primary.lower():
        extras.append("consulted documentation")

    if len(extras) == 1:
        primary += f" and {extras[0]}"
    elif len(extras) > 1:
        primary += ", " + ", ".join(extras[:-1]) + f", and {extras[-1]}"

    return primary + "."


# ---------------------------------------------------------------------------
# Related resources
# ---------------------------------------------------------------------------

def _format_resource(domain: str, titles: set[str]) -> str:
    """Format one resource bullet line."""
    name = _friendly(domain)
    dl = domain.lower()

    if dl in _LOCAL_DOMAINS:
        return f"- {name} — local application preview"

    if dl in _AI_DOMAINS:
        useful = [t for t in sorted(titles) if len(t) > 5]
        if useful:
            return f"- {name} — {useful[0]}"
        return f"- {name} — AI assistant"

    if dl in _DOC_DOMAINS:
        useful = [t for t in sorted(titles) if len(t) > 5]
        if useful:
            return f"- {name} — {useful[0]}"
        return f"- {name}"

    # Generic resource — attach a title when there's exactly one useful one
    if titles:
        useful = [t for t in sorted(titles) if len(t) > 3]
        if useful and len(useful) == 1:
            return f"- {name} — {useful[0]}"

    return f"- {name}"


# ---------------------------------------------------------------------------
# Other activity descriptions
# ---------------------------------------------------------------------------

def _describe_other_block(block) -> str:
    """Build a human description for one 'other activity' block."""
    duration = _fmt_duration(block.duration_minutes)

    # Collect evidence from all intervals in this block
    titles: set[str] = set()
    domains: set[str] = set()
    for interval in block.factual.intervals:
        event = interval.event
        pt = (event.get("page_title") or "").strip()
        d = (event.get("domain") or "").strip().lower()
        wt = (event.get("window_title") or "").strip()

        if pt and pt.lower() not in _GENERIC_TITLES:
            titles.add(pt)
        if d:
            domains.add(d)
        if not pt and wt and wt.lower() not in _GENERIC_TITLES:
            titles.add(wt)

    # YouTube video
    if "youtube.com" in domains and titles:
        best = sorted(titles, key=len, reverse=True)[0]
        short = best[:60] + "\u2026" if len(best) > 60 else best
        return f'{duration}: YouTube video, \u201c{short}\u201d'

    # Google search
    if "google.com" in domains:
        cleaned = [
            t.replace(" - Google Search", "").replace(" - Google", "").strip()
            for t in titles
        ]
        cleaned = [t for t in cleaned if t]
        if cleaned:
            return f"{duration}: Google search about {cleaned[0]}"
        return f"{duration}: Google search"

    # Known entertainment domain
    ent = domains & _ENTERTAINMENT_DOMAINS
    if ent:
        label = _friendly(sorted(ent)[0])
        if titles:
            best = sorted(titles, key=len, reverse=True)[0]
            return f'{duration}: {label}, \u201c{best}\u201d'
        return f"{duration}: {label}"

    # Generic web page with title
    if titles and domains:
        best = sorted(titles, key=len, reverse=True)[0]
        short = best[:60] + "\u2026" if len(best) > 60 else best
        return f"{duration}: {short} ({_friendly(sorted(domains)[0])})"

    if domains:
        return f"{duration}: browsing {_friendly(sorted(domains)[0])}"

    if titles:
        return f"{duration}: {sorted(titles, key=len, reverse=True)[0]}"

    return f"{duration}: other activity"


# ---------------------------------------------------------------------------
# Confirmation questions
# ---------------------------------------------------------------------------

def _format_question(index: int, item) -> str:
    """Format one confirmation question for the user."""
    lines: list[str] = []

    if item.kind == "VS Code workspace":
        lines.append(f"{index}. I found the VS Code workspace `{item.label}`.")
        lines.append(f'   Should I save it as a project named "{item.label}"?')

    elif item.domain == "youtube.com":
        short = item.label[:60] + "\u2026" if len(item.label) > 60 else item.label
        lines.append(f'{index}. Is the YouTube video \u201c{short}\u201d related to a project?')
        lines.append("   If yes, which project?")

    elif item.domain:
        lines.append(f"{index}. Is `{item.domain}` related to a learning topic?")
        lines.append("   If yes, tell me the topic, for example: AI/ML.")

    elif item.kind == "File":
        lines.append(f"{index}. I saw the file `{item.label}` in an unrecognized workspace.")
        lines.append("   Is it related to a project?")

    else:
        lines.append(f'{index}. I saw \u201c{item.label}\u201d ({item.kind}).')
        lines.append("   Is this related to a project or topic?")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def format_daily_report(
    date: str,
    summaries: list,
    other_groups: list,
    review_items: list,
    *,
    ai_available: bool = False,
) -> str:
    """Render the complete daily report as human-readable text.

    Args:
        date:          "YYYY-MM-DD" of the day being reported.
        summaries:     list of DailySummary (projects / topics).
        other_groups:  list of ReportGroup (Unclassified / Entertainment).
        review_items:  list of ReviewItem (questions for the user).
        ai_available:  whether the local LLM was used for attribution.

    Returns:
        A single formatted string suitable for terminal output.
    """

    # Format the date in a human-friendly way (platform-safe: no %-d)
    try:
        dt = datetime.strptime(date, "%Y-%m-%d")
        date_display = f"{dt.day} {dt.strftime('%B %Y')}"
    except (ValueError, Exception):
        date_display = date

    lines: list[str] = []
    lines.append(f"Daily summary \u2014 {date_display}")
    lines.append("")

    # ---- Projects / topics -------------------------------------------
    if summaries:
        for summary in summaries:
            suffix = " (needs confirmation)" if summary.needs_confirmation else ""
            lines.append(f"{summary.label}{suffix}")
            lines.append(f"Worked for {_fmt_duration(summary.duration_minutes)}")
            lines.append("")
            lines.append("What you did:")
            lines.append(_build_narrative(summary))
            if summary.files:
                file_names = sorted(summary.files)
                if len(file_names) <= 6:
                    files_str = ", ".join(file_names)
                else:
                    files_str = ", ".join(file_names[:5]) + f", and {len(file_names) - 5} more"
                lines.append(f"Files: {files_str}")
            lines.append("")

            resource_map = _collect_resource_map(summary)
            if resource_map:
                lines.append("Related resources:")
                for domain in sorted(resource_map.keys()):
                    lines.append(_format_resource(domain, resource_map[domain]))
                lines.append("")
    else:
        lines.append("No project activity detected today.")
        lines.append("")

    # ---- Other (entertainment / unclassified) -------------------------
    # Each attributed block inside a group may represent different
    # content (e.g. a YouTube video followed by a Google search, both
    # labelled "Unclassified").  Describe each block individually so
    # the user sees meaningful line items, not merged blobs.
    other_blocks = []
    for group in other_groups:
        for block in group.blocks:
            if block.duration_minutes >= 0.5:
                other_blocks.append(block)

    if other_blocks:
        lines.append("Other activity \u2014 not counted as project work:")
        for block in other_blocks:
            lines.append(f"- {_describe_other_block(block)}")
        lines.append("")

    # ---- Confirmation questions ---------------------------------------
    if review_items:
        lines.append("Needs your confirmation:")
        for i, item in enumerate(review_items[:5], start=1):
            lines.append(_format_question(i, item))
            lines.append("")
        if len(review_items) > 5:
            remaining = len(review_items) - 5
            lines.append(
                f"...and {remaining} more. Run: python activity/review_unclassified.py"
            )
            lines.append("")

    # ---- Attribution note --------------------------------------------
    if ai_available:
        lines.append("Attribution: local AI (Ollama)")
    else:
        lines.append("Attribution: rules/fallback; Ollama unavailable")

    return "\n".join(lines).rstrip() + "\n"
