"""
Personal OS — Review Unclassified Activity.

Finds activity the system had no confident project match for
(e.g. a YouTube video, a random article) and asks you, once per
distinct piece of content:

    "Is this related to a project you're working on?"

Your answer teaches the system: it extracts distinctive keywords
from the content and adds them to config/projects.json (or
config/distractions.json), so similar content is recognized
automatically next time — no further prompting needed.

This is a CLI stand-in for what would eventually be a real-time
notification. The underlying logic (core/review_queue.py,
core/classification_learning.py) is the same either way — only the
delivery mechanism differs.

Usage:
    python activity/review_unclassified.py
    python activity/review_unclassified.py --limit 200
"""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.classification_learning import (
    extract_keywords, add_project_keywords, add_distraction_keywords,
    add_project_workspace, add_project_vault,
)
from core.llm_client import LLMClient
from core.llm_classifier import classify_with_llm
from core.project_matcher import (
    ProjectMatcher, DEFAULT_PROJECTS_PATH, DEFAULT_DISTRACTIONS_PATH, DISTRACTION,
)
from core.review_queue import find_review_items
from core.sessionizer import _fetch_events, _event_context  # reuse, not duplicate


def _apply_learning(label: str, item) -> None:
    """Extract keywords from `item` and persist them under `label`,
    the same learning step whether the confirmation came from the
    LLM or from the human.

    Two important safety rules, both learned the hard way:

    1. The domain is NEVER included in keyword-extraction text.
       A domain like "youtube.com" hosts every kind of content —
       learning it as a project keyword would silently misclassify
       every future visit to that site as this project, forever.

    2. If the item came from a known workspace/vault, we skip
       filename-based keyword learning entirely and rely on the
       workspace/vault exact-match binding instead. A filename like
       "classifier.py" is generic enough that it could belong to a
       completely different future project — the workspace binding
       is the safe, specific signal; the filename isn't."""

    exclude = set()
    if item.domain:
        exclude.add(item.domain.lower())
        exclude.add(item.domain.split(".")[0].lower())

    keywords = extract_keywords(item.label, existing_keywords=exclude)

    if label == DISTRACTION:
        add_distraction_keywords(DEFAULT_DISTRACTIONS_PATH, keywords)
        return keywords

    if item.workspace or item.vault:
        keywords = []  # workspace/vault binding below is the safe signal
    elif not keywords:
        # Nothing distinctive extracted — only fall back to the raw
        # label if it isn't itself just the domain name (e.g. a bare
        # "YouTube" label with no real title). If even the label is
        # domain-derived, there's genuinely nothing safe to learn
        # here — better to learn nothing than something wrong.
        label_lower = item.label.strip().lower()
        if label_lower and label_lower not in exclude:
            keywords = [label_lower]

    if keywords:
        add_project_keywords(DEFAULT_PROJECTS_PATH, label, keywords)

    if item.workspace:
        add_project_workspace(DEFAULT_PROJECTS_PATH, label, item.workspace)

    if item.vault:
        add_project_vault(DEFAULT_PROJECTS_PATH, label, item.vault)

    return keywords



def _prompt_for_item(item, project_names: list[str], llm_checked: bool = False) -> None:

    print()
    print(f"[{item.kind}] {item.label}")
    if item.domain:
        print(f"  ({item.domain})")
    if item.url:
        print(f"  URL: {item.url}")
    if item.workspace:
        print(f"  Workspace: {item.workspace}")
    if item.vault:
        print(f"  Vault: {item.vault}")
    if llm_checked:
        print(f"  (LLM checked this — wasn't confident enough, asking you)")
    print(f"  Category: {item.category}  |  {len(item.event_ids)} occurrence(s)")
    print()

    for i, name in enumerate(project_names, start=1):
        print(f"  [{i}] Add to \"{name}\"")

    print(f"  [N] Add to a new project")
    print(f"  [D] Distraction")
    print(f"  [I] Ignore (skip, don't classify)")
    print()

    choice = input("Your choice: ").strip().lower()

    if choice == "i" or choice == "":
        print("  → Ignored.")
        return

    if choice == "d":
        keywords = _apply_learning(DISTRACTION, item)
        print(f"  → Marked as Distraction. Learned keywords: {keywords or '(none found)'}")
        return

    if choice == "n":
        new_name = input("  New project name: ").strip()
        if not new_name:
            print("  → No name given, skipped.")
            return
        keywords = _apply_learning(new_name, item)
        print(f"  → Added to \"{new_name}\". Learned keywords: {keywords}")
        return

    if choice.isdigit() and 1 <= int(choice) <= len(project_names):
        project_name = project_names[int(choice) - 1]
        keywords = _apply_learning(project_name, item)
        print(f"  → Added to \"{project_name}\". Learned keywords: {keywords or '(none found)'}")
        return

    print("  → Not understood, skipped.")


def main():

    parser = argparse.ArgumentParser(description="Review unclassified Personal OS activity")
    parser.add_argument("--limit", type=int, default=None, help="Only consider the most recent N events")
    parser.add_argument("--no-llm", action="store_true", help="Skip the local LLM step, go straight to manual review")
    args = parser.parse_args()

    matcher = ProjectMatcher()
    events = _fetch_events(limit=args.limit)

    items = find_review_items(events, matcher, context_fn=_event_context)

    if not items:
        print("Nothing to review — everything either matched a project or was already reviewed.")
        return

    project_names = [p["name"] for p in matcher._projects]  # display only

    llm_client = None
    if not args.no_llm:
        candidate_client = LLMClient()
        if candidate_client.is_available():
            llm_client = candidate_client
            print(f"Local LLM available ({llm_client.model}) — trying it before asking you.")
            print("(First response may take a minute or two while the model loads — after that it's fast.)\n")
        else:
            print("Local LLM not reachable (is Ollama running?) — falling back to manual review only.\n")

    print(f"{len(items)} unclassified item(s) found.\n")
    print("For each, choose where it belongs. Answering teaches Personal OS —")
    print("similar content won't be asked about again.\n")
    print("-" * 60)

    llm_resolved_count = 0
    llm_tried_count = 0

    for item in items:

        if llm_client is not None:

            llm_label, llm_confidence = classify_with_llm(
                llm_client, item.label, item.kind, item.category, item.domain,
                project_names, url=item.url, workspace=item.workspace, vault=item.vault,
            )
            llm_tried_count += 1

            if llm_confidence == "high":
                keywords = _apply_learning(llm_label, item)
                print(f"\n[{item.kind}] {item.label}")
                print(f"  → LLM classified as \"{llm_label}\" (auto-applied). Learned keywords: {keywords}")
                print("-" * 60)
                llm_resolved_count += 1
                continue

        _prompt_for_item(item, project_names, llm_checked=(llm_client is not None))
        print("-" * 60)

    print(
        f"\nDone. {llm_resolved_count} item(s) auto-classified by the local LLM, "
        f"{len(items) - llm_resolved_count} needed your input."
    )
    print("Re-run activity/session_report.py to see updated sessions.")


if __name__ == "__main__":
    main()