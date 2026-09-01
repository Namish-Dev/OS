"""
Tests for core/classification_learning.py, the confidence/distraction
additions to core/project_matcher.py, and core/review_queue.py.
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.classification_learning import (
    extract_keywords, add_project_keywords, add_distraction_keywords,
)
from core.project_matcher import (
    ProjectMatcher, UNASSIGNED, DISTRACTION,
    CONFIDENCE_HIGH, CONFIDENCE_MEDIUM, CONFIDENCE_LOW, CONFIDENCE_NONE,
)
from core.review_queue import build_signature, find_review_items


def _tmp_path():
    return Path(tempfile.mkdtemp())


# --------------------------------------------------------------------------
# extract_keywords
# --------------------------------------------------------------------------

class TestExtractKeywords:

    def test_extracts_distinctive_words(self):
        result = extract_keywords(
            "FastAPI JWT Authentication Tutorial", existing_keywords=set()
        )
        assert "jwt" in result
        assert "fastapi" in result

    def test_skips_stopwords(self):
        result = extract_keywords(
            "How to use the JWT with FastAPI", existing_keywords=set()
        )
        assert "how" not in result
        assert "the" not in result
        assert "with" not in result

    def test_skips_existing_keywords(self):
        result = extract_keywords(
            "FastAPI JWT Authentication", existing_keywords={"fastapi"}
        )
        assert "fastapi" not in result
        assert "jwt" in result

    def test_respects_max_new(self):
        result = extract_keywords(
            "alpha beta gamma delta epsilon", existing_keywords=set(), max_new=2
        )
        assert len(result) == 2

    def test_empty_text_returns_empty(self):
        assert extract_keywords("", existing_keywords=set()) == []


# --------------------------------------------------------------------------
# add_project_keywords / add_distraction_keywords
# --------------------------------------------------------------------------

class TestConfigMutation:

    def test_add_keywords_to_existing_project(self):

        tmp = _tmp_path() / "projects.json"
        tmp.write_text(json.dumps({
            "projects": [{"name": "FastAPI Authentication", "keywords": ["auth.py"]}]
        }))

        add_project_keywords(tmp, "FastAPI Authentication", ["jwt", "oauth2"])

        data = json.loads(tmp.read_text())
        keywords = data["projects"][0]["keywords"]

        assert "auth.py" in keywords
        assert "jwt" in keywords
        assert "oauth2" in keywords

    def test_creates_new_project_if_missing(self):

        tmp = _tmp_path() / "projects.json"
        tmp.write_text(json.dumps({"projects": []}))

        add_project_keywords(tmp, "Machine Learning", ["random", "forest"])

        data = json.loads(tmp.read_text())
        names = [p["name"] for p in data["projects"]]

        assert "Machine Learning" in names

    def test_does_not_duplicate_keywords(self):

        tmp = _tmp_path() / "projects.json"
        tmp.write_text(json.dumps({
            "projects": [{"name": "X", "keywords": ["jwt"]}]
        }))

        add_project_keywords(tmp, "X", ["JWT", "jwt", "oauth2"])

        data = json.loads(tmp.read_text())
        keywords = data["projects"][0]["keywords"]

        assert keywords.count("jwt") + keywords.count("JWT") == 1
        assert "oauth2" in keywords

    def test_add_distraction_keywords_creates_file(self):

        tmp = _tmp_path() / "distractions.json"

        add_distraction_keywords(tmp, ["bts", "funny"])

        data = json.loads(tmp.read_text())
        assert "bts" in data["keywords"]
        assert "funny" in data["keywords"]


# --------------------------------------------------------------------------
# ProjectMatcher — confidence + distraction
# --------------------------------------------------------------------------

class TestConfidenceAndDistraction:

    def _matcher(self, tmp_dir, projects=None, distractions=None):

        projects_path = tmp_dir / "projects.json"
        projects_path.write_text(json.dumps({"projects": projects or []}))

        distractions_path = tmp_dir / "distractions.json"
        distractions_path.write_text(json.dumps({"keywords": distractions or []}))

        return ProjectMatcher(config_path=projects_path, distractions_path=distractions_path)

    def test_high_confidence_on_file_match(self):

        tmp_dir = _tmp_path()
        matcher = self._matcher(tmp_dir, projects=[
            {"name": "FastAPI Authentication", "keywords": ["auth.py"]}
        ])

        label, confidence = matcher.match_with_confidence(None, {"file": "auth.py"})

        assert label == "FastAPI Authentication"
        assert confidence == CONFIDENCE_HIGH

    def test_medium_confidence_on_domain_match(self):

        tmp_dir = _tmp_path()
        matcher = self._matcher(tmp_dir, projects=[
            {"name": "FastAPI Authentication", "keywords": ["fastapi"]}
        ])

        label, confidence = matcher.match_with_confidence(
            None, {"domain": "fastapi.tiangolo.com"}
        )

        assert label == "FastAPI Authentication"
        assert confidence == CONFIDENCE_MEDIUM

    def test_low_confidence_on_workspace_only_match(self):

        tmp_dir = _tmp_path()
        matcher = self._matcher(tmp_dir, projects=[
            {"name": "Personal OS", "keywords": ["personal os"]}
        ])

        label, confidence = matcher.match_with_confidence(
            None, {"workspace": "Personal OS"}
        )

        assert label == "Personal OS"
        assert confidence == CONFIDENCE_LOW

    def test_no_match_is_none_confidence_and_unassigned(self):

        tmp_dir = _tmp_path()
        matcher = self._matcher(tmp_dir, projects=[
            {"name": "FastAPI Authentication", "keywords": ["fastapi"]}
        ])

        label, confidence = matcher.match_with_confidence(
            None, {"domain": "youtube.com", "page_title": "Random Forest Explained"}
        )

        assert label == UNASSIGNED
        assert confidence == CONFIDENCE_NONE

    def test_distraction_keyword_matches(self):

        tmp_dir = _tmp_path()
        matcher = self._matcher(
            tmp_dir,
            projects=[{"name": "FastAPI Authentication", "keywords": ["fastapi"]}],
            distractions=["bts", "funny moments"],
        )

        label, confidence = matcher.match_with_confidence(
            None, {"domain": "youtube.com", "page_title": "BTS Funny Moments"}
        )

        assert label == DISTRACTION
        assert confidence == CONFIDENCE_HIGH  # page_title is the high tier

    def test_project_keyword_beats_distraction_in_same_tier_by_length(self):
        """If both a project and a distraction keyword match in the
        same field, the more specific (longer) keyword should win."""

        tmp_dir = _tmp_path()
        matcher = self._matcher(
            tmp_dir,
            projects=[{"name": "Machine Learning", "keywords": ["random forest explained"]}],
            distractions=["random"],
        )

        label, confidence = matcher.match_with_confidence(
            None, {"domain": "youtube.com", "page_title": "Random Forest Explained"}
        )

        assert label == "Machine Learning"


# --------------------------------------------------------------------------
# review_queue
# --------------------------------------------------------------------------

class TestReviewQueue:

    def test_build_signature_dedupes_same_video(self):

        ctx = {"domain": "youtube.com", "page_title": "Random Forest Explained"}
        sig1 = build_signature(None, ctx)
        sig2 = build_signature(None, dict(ctx))

        assert sig1 == sig2

    def test_find_review_items_excludes_confident_matches(self):

        tmp_dir = _tmp_path()
        projects_path = tmp_dir / "projects.json"
        projects_path.write_text(json.dumps({
            "projects": [{"name": "Personal OS", "keywords": ["auth.py"]}]
        }))
        distractions_path = tmp_dir / "distractions.json"
        distractions_path.write_text(json.dumps({"keywords": []}))

        matcher = ProjectMatcher(config_path=projects_path, distractions_path=distractions_path)

        events = [
            {"id": 1, "application": "Visual Studio Code", "window_title": "auth.py",
             "file": "auth.py", "domain": None, "page_title": None, "note": None,
             "vault": None, "url": None, "path": None, "workspace": None},
            {"id": 2, "application": "Google Chrome", "window_title": "Random Forest - Chrome",
             "file": None, "domain": "youtube.com", "page_title": "Random Forest Explained",
             "note": None, "vault": None, "url": None, "path": None, "workspace": None},
        ]

        def context_fn(event):
            return {k: event.get(k) for k in
                    ["workspace", "file", "note", "vault", "domain", "url", "page_title", "path"]}

        items = find_review_items(events, matcher, context_fn)

        # Only the unmatched YouTube video should show up.
        assert len(items) == 1
        assert items[0].label == "Random Forest Explained"

    def test_find_review_items_dedupes_repeated_content(self):

        tmp_dir = _tmp_path()
        projects_path = tmp_dir / "projects.json"
        projects_path.write_text(json.dumps({"projects": []}))
        distractions_path = tmp_dir / "distractions.json"
        distractions_path.write_text(json.dumps({"keywords": []}))

        matcher = ProjectMatcher(config_path=projects_path, distractions_path=distractions_path)

        base_event = {
            "application": "Google Chrome", "window_title": "Random Forest - Chrome",
            "file": None, "domain": "youtube.com", "page_title": "Random Forest Explained",
            "note": None, "vault": None, "url": None, "path": None, "workspace": None,
        }

        events = [
            {**base_event, "id": 1},
            {**base_event, "id": 2},
            {**base_event, "id": 3},
        ]

        def context_fn(event):
            return {k: event.get(k) for k in
                    ["workspace", "file", "note", "vault", "domain", "url", "page_title", "path"]}

        items = find_review_items(events, matcher, context_fn)

        assert len(items) == 1
        assert items[0].event_ids == [1, 2, 3]


# --------------------------------------------------------------------------
# End-to-end: confirm once, auto-recognized after
# --------------------------------------------------------------------------

class TestLearningLoop:

    def test_confirming_a_video_makes_future_similar_videos_match(self):

        tmp_dir = _tmp_path()
        projects_path = tmp_dir / "projects.json"
        projects_path.write_text(json.dumps({"projects": []}))
        distractions_path = tmp_dir / "distractions.json"
        distractions_path.write_text(json.dumps({"keywords": []}))

        matcher = ProjectMatcher(config_path=projects_path, distractions_path=distractions_path)

        context = {"domain": "youtube.com", "page_title": "FastAPI JWT Authentication Tutorial"}

        # Before confirmation: no match.
        label, confidence = matcher.match_with_confidence(None, context)
        assert label == UNASSIGNED
        assert confidence == CONFIDENCE_NONE

        # User confirms: "Add to FastAPI Authentication".
        keywords = extract_keywords(context["page_title"], existing_keywords=set())
        add_project_keywords(projects_path, "FastAPI Authentication", keywords)

        # Reload matcher (a fresh instance, like a new review run would use).
        matcher2 = ProjectMatcher(config_path=projects_path, distractions_path=distractions_path)

        # A DIFFERENT but related video should now match automatically.
        new_context = {"domain": "youtube.com", "page_title": "Understanding JWT Tokens"}
        label2, confidence2 = matcher2.match_with_confidence(None, new_context)

        assert label2 == "FastAPI Authentication"
        assert confidence2 == CONFIDENCE_HIGH