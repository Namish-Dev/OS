"""Tests for clean report grouping."""

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.daily_attribution import ActivityInterval, AttributedBlock, FactualBlock
from core.daily_report import build_daily_summaries, build_report_groups, summarize_groups


def _block(identifier, start, label, category, domain=None):
    event = {
        "id": identifier,
        "timestamp": start.isoformat(),
        "application": "Visual Studio Code",
        "process": "code",
        "window_title": "context.py",
        "workspace": "personal-agent",
        "file": "context.py",
        "note": None,
        "vault": None,
        "domain": domain,
        "url": None,
        "page_title": None,
        "path": None,
    }
    interval = ActivityInterval(identifier, start, start + timedelta(minutes=2), event)
    factual = FactualBlock(identifier, interval.start, interval.end, [interval])
    return AttributedBlock(factual, label, category, "inferred", "llm", "Observed workspace and file evidence.")


def test_report_groups_hide_filenames_and_collect_resources():
    start = datetime(2026, 9, 15, 9, 0)
    groups = build_report_groups([
        _block(1, start, "Personal AI Assistant", "Coding"),
        _block(2, start + timedelta(minutes=2), "Personal AI Assistant", "Coding", "github.com"),
        _block(3, start + timedelta(minutes=4), "Entertainment", "Entertainment", "youtube.com"),
    ])

    assert len(groups) == 2
    assert groups[0].label == "Personal AI Assistant"
    assert groups[0].resources == {"github.com"}
    assert summarize_groups(groups)["Personal AI Assistant"] == 4


def test_report_omits_zero_length_switch_events():
    start = datetime(2026, 9, 15, 9, 0)
    groups = build_report_groups([_block(1, start, "Unclassified", "Other")])
    assert len(groups) == 1


def test_daily_summary_keeps_unclassified_time_out_of_a_workspace_project():
    start = datetime(2026, 9, 15, 9, 0)
    groups = build_report_groups([
        _block(1, start, "macos-rag-finder", "Coding"),
        _block(2, start + timedelta(minutes=2), "Unclassified", "Other", "youtube.com"),
        _block(3, start + timedelta(minutes=4), "macos-rag-finder", "Coding", "localhost"),
    ])

    summaries = build_daily_summaries(groups)

    assert len(summaries) == 1
    assert summaries[0].label == "macos-rag-finder"
    assert summaries[0].duration_minutes == 4
    assert summaries[0].resources == {"localhost"}
