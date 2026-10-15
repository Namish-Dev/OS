"""
Personal OS — Review Queue.

Finds events the ProjectMatcher had NO confidence about (nothing
matched at all — not even a weak workspace-name match) and groups
them by a content "signature", so the user is asked about each
distinct piece of content once, not once per raw event.

This is the "brain" behind the confirm-and-learn flow described in
the product design: high/medium/low-confidence matches never show
up here at all (matching "no popup needed because confidence is
high") — only genuinely unrecognized content does.

Kept separate from the interactive CLI (activity/review_unclassified.py)
so it's fully unit-testable without simulating stdin input.

Platform-independent.
"""

from dataclasses import dataclass, field

from core.activity_classifier import classify_event
from core.project_matcher import ProjectMatcher, CONFIDENCE_NONE
from core.topic_matcher import TopicMatcher


@dataclass
class ReviewItem:
    """One distinct piece of unclassified content, possibly seen
    across multiple raw events (e.g. the same video/page revisited)."""

    signature: str
    label: str              # short human label, e.g. a page/video/file title
    kind: str                # "YouTube video", "File", "Note", "Web page", ...
    category: str            # from activity_classifier (Research, Entertainment, ...)
    event_ids: list = field(default_factory=list)
    domain: str | None = None
    url: str | None = None
    workspace: str | None = None   # e.g. VS Code folder/workspace name
    vault: str | None = None       # e.g. Obsidian vault name


def build_signature(application: str | None, context: dict) -> str:
    """
    A stable string identifying "this specific piece of content",
    used to de-duplicate review items so revisiting the same video
    or page doesn't ask twice in one review pass.
    """

    domain = context.get("domain")
    page_title = context.get("page_title")
    note = context.get("note")
    file = context.get("file")

    if domain and page_title:
        return f"web::{domain}::{page_title.strip().lower()}"

    if note:
        return f"note::{note.strip().lower()}"

    if file:
        return f"file::{file.strip().lower()}"

    if domain:
        return f"web::{domain}"

    return "unknown"


def _describe(application: str | None, context: dict) -> tuple[str, str]:
    """Return (label, kind) — a short display label and content kind."""

    domain = context.get("domain")
    page_title = context.get("page_title")
    note = context.get("note")
    file = context.get("file")

    if domain == "youtube.com" and page_title:
        return page_title, "YouTube video"

    if domain and page_title:
        return page_title, "Web page"

    if note:
        return note, "Note"

    if file:
        return file, "File"

    return (application or "Unknown"), "Activity"


def _is_uninformative_title(page_title: str | None, domain: str | None) -> bool:
    """
    True for titles that carry no real signal — e.g. just visiting
    youtube.com's homepage, where the page title is literally
    "YouTube". Neither a human nor an LLM can classify a bare
    homepage visit, so there's no point asking about it.
    """

    if not page_title or not domain:
        return False

    title_clean = page_title.strip().lower()

    # e.g. "youtube.com" -> "youtube", "github.com" -> "github"
    domain_base = domain.split(".")[0].lower()

    return title_clean in {domain_base, "home", ""}


def find_review_items(
    events: list[dict],
    matcher: ProjectMatcher,
    context_fn,
    topic_matcher: TopicMatcher | None = None,
) -> list[ReviewItem]:
    """
    Args:
        events:     flat event rows, as produced by
                    core.sessionizer._fetch_events()
        matcher:    a ProjectMatcher instance
        context_fn: callable(event) -> context dict, so this stays
                    decoupled from sessionizer's internal row shape
                    (pass core.sessionizer._event_context)

    Returns one ReviewItem per distinct signature, in first-seen order.
    Skips content with no real signal to classify from (e.g. a bare
    homepage visit).
    """

    items_by_signature: dict[str, ReviewItem] = {}
    topic_matcher = topic_matcher or TopicMatcher()

    # Find unconfirmed workspaces before inspecting browser items. A local
    # preview named after one of these workspaces is evidence for that same
    # one-time project question, not a second item to review.
    proposed_workspaces: set[str] = set()
    for event in events:
        context = context_fn(event)
        workspace = (context.get("workspace") or "").strip()
        if not workspace:
            continue
        _label, confidence = matcher.match_with_confidence(event.get("window_title"), context)
        if confidence == CONFIDENCE_NONE:
            proposed_workspaces.add(workspace.lower())

    for event in events:

        context = context_fn(event)
        application = event.get("application")

        # VS Code's welcome tab is application chrome, not a project file and
        # never gives the user a useful classification question.
        if (
            (application or "").lower() == "visual studio code"
            and (context.get("file") or "").strip().lower() in {"welcome", "getting started"}
            and not context.get("workspace")
        ):
            continue

        if _is_uninformative_title(context.get("page_title"), context.get("domain")):
            continue

        _label_result, confidence = matcher.match_with_confidence(
            event.get("window_title"), context
        )

        if confidence != CONFIDENCE_NONE:
            continue

        if topic_matcher.match(context):
            continue

        browser_text = " ".join(str(context.get(key) or "") for key in ("page_title", "url"))
        if not context.get("workspace") and any(name in browser_text.lower() for name in proposed_workspaces):
            continue

        category = classify_event(application, context)

        # The workspace is the unit the user recognises as a project. Ask
        # once about it before asking about any filenames inside it.
        workspace = (context.get("workspace") or "").strip()
        if workspace:
            signature = f"workspace::{workspace.lower()}"
            if signature not in items_by_signature:
                items_by_signature[signature] = ReviewItem(
                    signature=signature,
                    label=workspace,
                    kind="VS Code workspace",
                    category="Coding",
                    workspace=workspace,
                )
            items_by_signature[signature].event_ids.append(event["id"])
            continue

        signature = build_signature(application, context)

        if signature == "unknown":
            continue

        if signature not in items_by_signature:
            label, kind = _describe(application, context)
            items_by_signature[signature] = ReviewItem(
                signature=signature,
                label=label,
                kind=kind,
                category=category,
                domain=context.get("domain"),
                url=context.get("url"),
                workspace=context.get("workspace"),
                vault=context.get("vault"),
            )

        items_by_signature[signature].event_ids.append(event["id"])

    return list(items_by_signature.values())
