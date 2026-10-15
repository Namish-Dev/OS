"""Personal OS — Project-Focused Daily Report.

Prints a clean, human-readable daily summary grouped by project,
with plain-language "What you did" descriptions, related resources,
separated unrelated activity, and inline confirmation questions.

Usage:
    python activity/daily_report.py                  # today
    python activity/daily_report.py --date 2026-08-30
    python activity/daily_report.py --no-llm         # rules only
"""

import argparse
import sys
from datetime import date as date_cls
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.daily_attribution import build_daily_attribution
from core.daily_report import build_daily_summaries, build_report_groups
from core.llm_client import LLMClient
from core.project_matcher import ProjectMatcher
from core.report_formatter import format_daily_report
from core.review_queue import find_review_items
from core.sessionizer import _event_context, _fetch_events


def _print_console_safe(text: str) -> None:
    """Do not crash reports on a legacy Windows terminal code page."""
    encoding = sys.stdout.encoding or "utf-8"
    print(text.encode(encoding, errors="replace").decode(encoding))


def main() -> None:
    parser = argparse.ArgumentParser(description="Personal OS daily report")
    parser.add_argument("--date", default=None, help="YYYY-MM-DD (defaults to today)")
    parser.add_argument("--no-llm", action="store_true", help="Use rules only; do not call local Ollama")
    args = parser.parse_args()
    day = args.date or date_cls.today().isoformat()

    # Attribution pipeline — unchanged
    client = None if args.no_llm else LLMClient()
    ai_available = bool(client and client.is_available())
    blocks = build_daily_attribution(day, client=client if ai_available else None)
    groups = build_report_groups(blocks)

    if not groups:
        print(f"Daily summary — {day}")
        print("No observed activity intervals found.")
        return

    # Build the structured data the formatter needs
    summaries = build_daily_summaries(groups)
    other_groups = [g for g in groups if g.label in {"Unclassified", "Entertainment"}]
    events = _fetch_events(since=f"{day}T00:00:00", until=f"{day}T23:59:59.999999")
    pending = find_review_items(events, ProjectMatcher(), context_fn=_event_context)

    # Render and print the formatted report
    report = format_daily_report(
        date=day,
        summaries=summaries,
        other_groups=other_groups,
        review_items=pending,
        ai_available=ai_available,
    )
    _print_console_safe(report)


if __name__ == "__main__":
    main()

