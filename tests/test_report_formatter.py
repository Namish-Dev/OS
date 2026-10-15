"""Tests for the human-readable daily report formatter."""

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.daily_attribution import ActivityInterval, AttributedBlock, FactualBlock
from core.daily_report import DailySummary, ReportGroup, build_daily_summaries, build_report_groups
from core.report_formatter import (
    _build_narrative,
    _describe_other_block,
    _fmt_duration,
    _format_question,
    _format_resource,
    _friendly,
    format_daily_report,
)
from core.review_queue import ReviewItem


# ---- Helpers ---------------------------------------------------------

def _make_interval(event_id, start, event_dict):
    """Create an ActivityInterval with the given event dict."""
    return ActivityInterval(event_id, start, start + timedelta(minutes=2), event_dict)


def _make_block(event_id, start, label, category, source="llm", reason="test", **context):
    """Build a full AttributedBlock from keyword context."""
    event = {
        "id": event_id,
        "timestamp": start.isoformat(),
        "application": context.get("application", "Visual Studio Code"),
        "process": context.get("process", "code"),
        "window_title": context.get("window_title", "test.py - TestProject - Visual Studio Code"),
        "workspace": context.get("workspace"),
        "file": context.get("file"),
        "note": context.get("note"),
        "vault": context.get("vault"),
        "domain": context.get("domain"),
        "url": context.get("url"),
        "page_title": context.get("page_title"),
        "path": context.get("path"),
    }
    interval = _make_interval(event_id, start, event)
    factual = FactualBlock(f"b{event_id}", interval.start, interval.end, [interval])
    return AttributedBlock(factual, label, category, "inferred", source, reason)


def _make_summary(label, blocks, **kwargs):
    """Build a DailySummary from attributed blocks via the report pipeline."""
    groups = build_report_groups(blocks)
    summaries = build_daily_summaries(groups)
    for s in summaries:
        if s.label == label:
            return s
    # Build one manually if no project blocks (shouldn't happen in normal use)
    return DailySummary(label=label, **kwargs)


# ---- _fmt_duration ---------------------------------------------------

def test_duration_under_one_minute():
    assert _fmt_duration(0.3) == "< 1 minute"

def test_duration_one_minute():
    assert _fmt_duration(1) == "1 minute"

def test_duration_multiple_minutes():
    assert _fmt_duration(48) == "48 minutes"

def test_duration_hours_and_minutes():
    assert _fmt_duration(72) == "1h 12m"

def test_duration_exact_hour():
    assert _fmt_duration(60) == "1h"


# ---- _friendly -------------------------------------------------------

def test_friendly_known_domain():
    assert _friendly("github.com") == "GitHub"
    assert _friendly("claude.ai") == "Claude"
    assert _friendly("youtube.com") == "YouTube"

def test_friendly_unknown_domain():
    assert _friendly("tutedude.com") == "tutedude.com"


# ---- _build_narrative ------------------------------------------------

def test_narrative_vscode_workspace():
    start = datetime(2026, 9, 15, 9, 0)
    blocks = [
        _make_block(1, start, "Personal OS", "Coding", workspace="OS", file="tracker.py"),
    ]
    summary = _make_summary("Personal OS", blocks)
    narrative = _build_narrative(summary)
    assert "VS Code" in narrative
    assert "OS" in narrative

def test_narrative_with_localhost():
    start = datetime(2026, 9, 15, 9, 0)
    blocks = [
        _make_block(1, start, "MyApp", "Coding", workspace="my-app", file="App.jsx"),
        _make_block(2, start + timedelta(minutes=2), "MyApp", "Coding",
                    application="Google Chrome", domain="localhost", page_title="my-app"),
    ]
    summary = _make_summary("MyApp", blocks)
    narrative = _build_narrative(summary)
    assert "local browser preview" in narrative

def test_narrative_with_ai():
    start = datetime(2026, 9, 15, 9, 0)
    blocks = [
        _make_block(1, start, "MyApp", "Coding", workspace="my-app", file="main.py"),
        _make_block(2, start + timedelta(minutes=2), "MyApp", "Research",
                    application="Google Chrome", domain="claude.ai", page_title="Claude"),
    ]
    summary = _make_summary("MyApp", blocks)
    narrative = _build_narrative(summary)
    assert "AI assistance" in narrative


# ---- _format_resource ------------------------------------------------

def test_resource_localhost():
    line = _format_resource("localhost", set())
    assert "local application preview" in line

def test_resource_ai_with_title():
    line = _format_resource("claude.ai", {"Building a RAG pipeline"})
    assert "Claude" in line
    assert "Building a RAG pipeline" in line

def test_resource_generic_domain():
    line = _format_resource("github.com", set())
    assert "GitHub" in line


# ---- _describe_other_block ------------------------------------------

def test_describe_youtube():
    start = datetime(2026, 9, 15, 14, 0)
    block = _make_block(
        10, start, "Unclassified", "Other",
        application="Google Chrome",
        domain="youtube.com",
        page_title="I GAVE JARVIS VISION and it satisfies me",
    )
    desc = _describe_other_block(block)
    assert "YouTube video" in desc
    assert "JARVIS" in desc

def test_describe_google_search():
    start = datetime(2026, 9, 15, 14, 5)
    block = _make_block(
        11, start, "Unclassified", "Other",
        application="Google Chrome",
        domain="google.com",
        page_title="Android app standby mode - Google Search",
    )
    desc = _describe_other_block(block)
    assert "Google search" in desc
    assert "Android app standby mode" in desc

def test_describe_entertainment():
    start = datetime(2026, 9, 15, 14, 10)
    block = _make_block(
        12, start, "Entertainment", "Entertainment",
        application="Google Chrome",
        domain="netflix.com",
        page_title="Stranger Things",
    )
    desc = _describe_other_block(block)
    assert "Netflix" in desc

def test_describe_generic_web():
    start = datetime(2026, 9, 15, 14, 15)
    block = _make_block(
        13, start, "Unclassified", "Other",
        application="Google Chrome",
        domain="tutedude.com",
        page_title="AI/ML Fundamentals Course",
    )
    desc = _describe_other_block(block)
    assert "AI/ML Fundamentals Course" in desc
    assert "tutedude.com" in desc

def test_describe_no_title():
    start = datetime(2026, 9, 15, 14, 20)
    block = _make_block(
        14, start, "Unclassified", "Other",
        application="Google Chrome",
        domain="example.com",
        page_title=None,
    )
    desc = _describe_other_block(block)
    assert "example.com" in desc


# ---- _format_question ------------------------------------------------

def test_question_workspace():
    item = ReviewItem(
        signature="workspace::macos-rag-finder",
        label="macos-rag-finder",
        kind="VS Code workspace",
        category="Coding",
        workspace="macos-rag-finder",
    )
    q = _format_question(1, item)
    assert "VS Code workspace" in q
    assert "macos-rag-finder" in q
    assert "project" in q.lower()

def test_question_youtube():
    item = ReviewItem(
        signature="web::youtube.com::test video",
        label="I GAVE JARVIS VISION",
        kind="YouTube video",
        category="Entertainment",
        domain="youtube.com",
    )
    q = _format_question(2, item)
    assert "YouTube video" in q
    assert "JARVIS" in q

def test_question_domain():
    item = ReviewItem(
        signature="web::tutedude.com::course",
        label="AI/ML Course",
        kind="Web page",
        category="Other",
        domain="tutedude.com",
    )
    q = _format_question(3, item)
    assert "tutedude.com" in q
    assert "learning topic" in q.lower()


# ---- format_daily_report (end-to-end) --------------------------------

def test_full_report_structure():
    """The complete report should have all the expected sections."""
    start = datetime(2026, 9, 15, 9, 0)

    project_blocks = [
        _make_block(1, start, "macos-rag-finder", "Coding",
                    source="workspace_candidate",
                    workspace="macos-rag-finder", file="App.jsx"),
        _make_block(2, start + timedelta(minutes=2), "macos-rag-finder", "Coding",
                    source="direct_workspace_resource",
                    application="Google Chrome", domain="localhost",
                    page_title="macos-rag-finder"),
    ]
    other_blocks = [
        _make_block(3, start + timedelta(minutes=10), "Unclassified", "Other",
                    application="Google Chrome", domain="youtube.com",
                    page_title="I GAVE JARVIS VISION"),
    ]

    all_blocks = project_blocks + other_blocks
    groups = build_report_groups(all_blocks)
    summaries = build_daily_summaries(groups)
    other_groups = [g for g in groups if g.label in {"Unclassified", "Entertainment"}]

    workspace_item = ReviewItem(
        signature="workspace::macos-rag-finder",
        label="macos-rag-finder",
        kind="VS Code workspace",
        category="Coding",
        workspace="macos-rag-finder",
    )

    report = format_daily_report(
        date="2026-09-15",
        summaries=summaries,
        other_groups=other_groups,
        review_items=[workspace_item],
    )

    # Header
    assert "Daily summary" in report
    assert "September 2026" in report

    # Project section
    assert "macos-rag-finder" in report
    assert "What you did:" in report
    assert "VS Code" in report

    # Resources
    assert "Related resources:" in report
    assert "localhost" in report

    # Other activity
    assert "Other activity" in report
    assert "YouTube video" in report
    assert "JARVIS" in report

    # Confirmation
    assert "Needs your confirmation:" in report
    assert "VS Code workspace" in report


def test_report_no_activity():
    """An empty report should still produce a readable message."""
    report = format_daily_report(
        date="2026-09-15",
        summaries=[],
        other_groups=[],
        review_items=[],
    )
    assert "No project activity detected today" in report


def test_unclassified_time_not_in_project():
    """Unclassified activity must not inflate project totals."""
    start = datetime(2026, 9, 15, 9, 0)
    blocks = [
        _make_block(1, start, "TestProject", "Coding", workspace="test-proj", file="main.py"),
        _make_block(2, start + timedelta(minutes=2), "Unclassified", "Other",
                    application="Google Chrome", domain="youtube.com",
                    page_title="Cat videos"),
        _make_block(3, start + timedelta(minutes=4), "TestProject", "Coding",
                    workspace="test-proj", file="utils.py"),
    ]
    groups = build_report_groups(blocks)
    summaries = build_daily_summaries(groups)

    assert len(summaries) == 1
    assert summaries[0].label == "TestProject"
    # 2 blocks × 2 min each = 4 minutes (YouTube's 2 min excluded)
    assert summaries[0].duration_minutes == 4
