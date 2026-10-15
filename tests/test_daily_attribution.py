"""Tests for factual interval timing and constrained day-end attribution."""

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.daily_attribution import attribute_blocks, build_factual_blocks, derive_intervals
from core.project_matcher import CONFIDENCE_NONE, UNASSIGNED


def _event(event_id, timestamp, application="Visual Studio Code", **context):
    return {
        "id": event_id, "timestamp": timestamp, "application": application,
        "process": "code", "window_title": "context.py - personal-agent - Visual Studio Code",
        "workspace": context.get("workspace"), "file": context.get("file"),
        "note": None, "vault": None, "domain": context.get("domain"),
        "url": None, "page_title": context.get("page_title"), "path": None,
    }


class _Matcher:
    _projects = [{"name": "Personal AI Assistant"}]

    def match_with_confidence(self, _title, _context):
        return UNASSIGNED, CONFIDENCE_NONE


class _Client:
    def __init__(self, response):
        self.response = response

    def is_available(self):
        return True

    def generate(self, _prompt, system=None):
        assert system
        return json.dumps(self.response)


def test_heartbeats_create_measured_time_and_condense_identical_facts():
    events = [
        _event(1, "2026-09-11T09:00:00", workspace="personal-agent", file="context.py"),
        _event(2, "2026-09-11T09:01:00", workspace="personal-agent", file="context.py"),
        _event(3, "2026-09-11T09:02:00", workspace="personal-agent", file="context.py"),
    ]
    intervals = derive_intervals(events, final_end=datetime.fromisoformat("2026-09-11T09:03:00"))
    blocks = build_factual_blocks(intervals)

    assert len(intervals) == 3
    assert len(blocks) == 1
    assert blocks[0].duration_minutes == 3
    assert "file=context.py" in blocks[0].evidence()


def test_model_labels_facts_but_cannot_change_measured_duration():
    events = [
        _event(1, "2026-09-11T09:00:00", workspace="personal-agent", file="context.py"),
        _event(2, "2026-09-11T09:02:00", application="Google Chrome", domain="youtube.com", page_title="Local LLM agents tutorial"),
    ]
    blocks = build_factual_blocks(derive_intervals(events, final_end=datetime.fromisoformat("2026-09-11T09:04:00")))
    client = _Client([
        {"id": "b1", "label": "Personal AI Assistant", "category": "Coding", "reason": "VS Code file and workspace."},
        {"id": "b2", "label": "Personal AI Assistant", "category": "Research", "reason": "Observed local-agent tutorial."},
    ])

    attributed = attribute_blocks(blocks, _Matcher(), client)

    # A newly observed VS Code workspace is preserved as the proposed project
    # label instead of letting the model guess over the direct OS evidence.
    assert [block.label for block in attributed] == ["personal-agent", "Personal AI Assistant"]
    assert [block.duration_minutes for block in attributed] == [2, 2]
    assert attributed[0].source == "workspace_candidate"
    assert attributed[1].source == "llm"


def test_unknown_workspace_becomes_one_proposed_project_and_local_preview_joins_it():
    events = [
        _event(1, "2026-09-11T09:00:00", workspace="macos-rag-finder", file="App.jsx"),
        _event(2, "2026-09-11T09:02:00", application="Google Chrome", domain="localhost",
               page_title="macos-rag-finder"),
        _event(3, "2026-09-11T09:04:00", application="Google Chrome", domain="youtube.com",
               page_title="Unrelated tutorial"),
    ]
    blocks = build_factual_blocks(derive_intervals(
        events, final_end=datetime.fromisoformat("2026-09-11T09:06:00")
    ))

    attributed = attribute_blocks(blocks, _Matcher(), client=None)

    assert [block.label for block in attributed] == [
        "macos-rag-finder", "macos-rag-finder", "Unclassified"
    ]
    assert attributed[0].source == "workspace_candidate"
    assert attributed[1].source == "direct_workspace_resource"


def test_invalid_model_category_falls_back_to_unclassified_facts():
    blocks = build_factual_blocks(derive_intervals(
        [_event(1, "2026-09-11T09:00:00")],
        final_end=datetime.fromisoformat("2026-09-11T09:02:00"),
    ))
    attributed = attribute_blocks(blocks, _Matcher(), _Client([
        {"id": "b1", "label": "Pretend Project", "category": "Invented", "reason": "No evidence."},
    ]))

    assert attributed[0].label == "Unclassified"
    assert attributed[0].source == "fallback"
