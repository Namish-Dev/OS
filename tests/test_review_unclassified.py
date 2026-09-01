"""
Tests for activity/review_unclassified.py's _apply_learning(), which
turns a confirmed classification into persisted config changes.

Covers two real bugs found in production use:
  1. Domain names (e.g. "youtube.com") leaking into learned keywords,
     which would silently misclassify every future visit to that
     domain as the confirmed project.
  2. Generic filenames (e.g. "classifier.py") being learned as
     keywords even when a safe workspace binding already exists,
     risking false-positive matches on unrelated future projects
     that happen to use the same common filename.
"""

import json
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import activity.review_unclassified as review_cli
from core.project_matcher import DISTRACTION


def _tmp_configs():
    tmp_dir = Path(tempfile.mkdtemp())
    projects_path = tmp_dir / "projects.json"
    projects_path.write_text(json.dumps({"projects": []}))
    distractions_path = tmp_dir / "distractions.json"
    distractions_path.write_text(json.dumps({"keywords": []}))
    return projects_path, distractions_path


@dataclass
class _FakeItem:
    """Mirrors core.review_queue.ReviewItem's fields used by _apply_learning."""
    label: str
    domain: str | None = None
    workspace: str | None = None
    vault: str | None = None


class TestApplyLearning:

    def test_domain_never_leaks_into_keywords(self, monkeypatch):

        projects_path, distractions_path = _tmp_configs()
        monkeypatch.setattr(review_cli, "DEFAULT_PROJECTS_PATH", projects_path)
        monkeypatch.setattr(review_cli, "DEFAULT_DISTRACTIONS_PATH", distractions_path)

        item = _FakeItem(label="YouTube", domain="youtube.com")

        keywords = review_cli._apply_learning("Personal OS", item)

        assert "youtube" not in [k.lower() for k in keywords]
        assert "youtube.com" not in [k.lower() for k in keywords]

        # With nothing safe to learn (label is itself just the
        # domain name), nothing should be persisted at all — better
        # to learn nothing than to learn something wrong.
        data = json.loads(projects_path.read_text())
        projects = data.get("projects", [])
        if projects:
            all_keywords = projects[0].get("keywords", [])
            assert "youtube" not in [k.lower() for k in all_keywords]
            assert "youtube.com" not in [k.lower() for k in all_keywords]

    def test_specific_title_still_extracts_real_keywords(self, monkeypatch):

        projects_path, distractions_path = _tmp_configs()
        monkeypatch.setattr(review_cli, "DEFAULT_PROJECTS_PATH", projects_path)
        monkeypatch.setattr(review_cli, "DEFAULT_DISTRACTIONS_PATH", distractions_path)

        item = _FakeItem(label="Understanding JWT Access Tokens", domain="youtube.com")

        keywords = review_cli._apply_learning("FastAPI Authentication", item)

        assert "jwt" in [k.lower() for k in keywords]
        assert "youtube" not in [k.lower() for k in keywords]
        assert "youtube.com" not in [k.lower() for k in keywords]

    def test_file_with_workspace_skips_filename_keyword_learning(self, monkeypatch):

        projects_path, distractions_path = _tmp_configs()
        monkeypatch.setattr(review_cli, "DEFAULT_PROJECTS_PATH", projects_path)
        monkeypatch.setattr(review_cli, "DEFAULT_DISTRACTIONS_PATH", distractions_path)

        item = _FakeItem(label="classifier.py", domain=None, workspace="OS")

        keywords = review_cli._apply_learning("Personal OS", item)

        assert keywords == []

        data = json.loads(projects_path.read_text())
        project = data["projects"][0]
        assert "classifier.py" not in project.get("keywords", [])
        assert "OS" in project.get("workspaces", [])

    def test_note_with_vault_skips_filename_keyword_learning(self, monkeypatch):

        projects_path, distractions_path = _tmp_configs()
        monkeypatch.setattr(review_cli, "DEFAULT_PROJECTS_PATH", projects_path)
        monkeypatch.setattr(review_cli, "DEFAULT_DISTRACTIONS_PATH", distractions_path)

        item = _FakeItem(label="pandas-categorical-exploration", vault="ML Notes")

        keywords = review_cli._apply_learning("Machine Learning", item)

        assert keywords == []

        data = json.loads(projects_path.read_text())
        project = data["projects"][0]
        assert "ML Notes" in project.get("vaults", [])

    def test_web_content_without_workspace_still_learns_keywords(self, monkeypatch):

        projects_path, distractions_path = _tmp_configs()
        monkeypatch.setattr(review_cli, "DEFAULT_PROJECTS_PATH", projects_path)
        monkeypatch.setattr(review_cli, "DEFAULT_DISTRACTIONS_PATH", distractions_path)

        item = _FakeItem(label="Random Forest Explained", domain="youtube.com")

        keywords = review_cli._apply_learning("Machine Learning", item)

        assert "random" in [k.lower() for k in keywords]
        assert "forest" in [k.lower() for k in keywords]

    def test_distraction_also_excludes_domain(self, monkeypatch):

        projects_path, distractions_path = _tmp_configs()
        monkeypatch.setattr(review_cli, "DEFAULT_PROJECTS_PATH", projects_path)
        monkeypatch.setattr(review_cli, "DEFAULT_DISTRACTIONS_PATH", distractions_path)

        item = _FakeItem(label="BTS Funny Moments", domain="youtube.com")

        keywords = review_cli._apply_learning(DISTRACTION, item)

        assert "youtube" not in [k.lower() for k in keywords]

        data = json.loads(distractions_path.read_text())
        assert "youtube" not in [k.lower() for k in data.get("keywords", [])]