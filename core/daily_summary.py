"""
Personal OS — Daily Summary.

Prints a narrative of a whole day's activity, built by having the
local LLM read the full chronological event log and group it into
meaningful blocks — able to recognize, for example, that a YouTube
video sitting between two coding sessions on the same project is
related research, not a separate distraction. A rule-based,
event-at-a-time classifier can't make that connective judgment; this
is why the grouping happens here instead of in session_report.py.

Requires Ollama (or another local LLM server) running — there's no
non-LLM fallback for this specific feature.

Usage:
    python activity/daily_summary.py                  # today
    python activity/daily_summary.py --date 2026-08-30
"""

import argparse
import sys
from datetime import date as date_cls
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.daily_attribution import build_daily_attribution, summarize_time_by_label


def _format_duration(minutes: float) -> str:
    total = round(minutes)
    hours, mins = divmod(total, 60)
    if hours:
        return f"{hours}h {mins}m"
    return f"{mins}m"


def main():

    parser = argparse.ArgumentParser(description="Personal OS daily narrative (LLM-driven)")
    parser.add_argument(
        "--date", default=None,
        help="YYYY-MM-DD (defaults to today)",
    )
    args = parser.parse_args()

    date_str = args.date or date_cls.today().isoformat()

    print(f"Building evidence-backed narrative for {date_str}...\n")
    blocks = build_daily_attribution(date_str)

    if not blocks:
        print("No bounded activity intervals found for this day.")
        return

    print(f"{date_str} — Activity Narrative")
    print("=" * 60)

    for block in blocks:
        start_str = block.start.strftime("%H:%M")
        end_str = block.end.strftime("%H:%M")
        print(f"{start_str}\u2013{end_str}  [{block.category}] {block.label}")
        print(
            f"           {block.reason} "
            f"({block.source}; confidence: {block.confidence})"
        )
        print(f"           Evidence: {'; '.join(block.evidence)}")

    print()
    print("-" * 60)
    print("Total time by project/topic:")

    totals = summarize_time_by_label(blocks)

    for label, minutes in totals.items():
        print(f"  {label:<30} {_format_duration(minutes)}")


if __name__ == "__main__":
    main()
