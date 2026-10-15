"""Tests for the read-only Git context collector."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sensors.linux.git_context import GitContextCollector


def test_collects_only_repository_summary(tmp_path):
    calls = []

    def runner(command):
        calls.append(command)
        suffix = command[3:]
        responses = {
            ("rev-parse", "--show-toplevel"): "/home/user/Projects/personal-agent",
            ("branch", "--show-current"): "context-engine",
            ("status", "--porcelain=v1"): " M context.py\n?? scratch.txt",
            ("log", "--since=midnight", "--format=%H"): "one\ntwo",
            ("log", "-1", "--format=%cI"): "2026-09-11T09:00:00+05:30",
        }
        return responses[tuple(suffix)]

    context = GitContextCollector(runner=runner).collect(tmp_path)

    assert context["git"]["branch"] == "context-engine"
    assert context["git"]["modified_files"] == 1
    assert context["git"]["untracked_files"] == 1
    assert context["git"]["commits_today"] == 2
    assert len(calls) == 5


def test_missing_project_path_collects_nothing(tmp_path):
    assert GitContextCollector().collect(tmp_path / "missing") == {}
