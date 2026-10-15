"""Tests for user-confirmed, non-project topic learning."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.classification_learning import add_topic_rule
from core.topic_matcher import TopicMatcher


def test_learned_domain_becomes_a_topic_rule(tmp_path):
    config = tmp_path / "topics.json"
    config.write_text(json.dumps({"topics": []}), encoding="utf-8")

    add_topic_rule(config, "AI/ML", "Learning", domains=["tutedude.com"])

    assert TopicMatcher(config).match({"domain": "tutedude.com"}) == ("AI/ML", "Learning")


def test_unknown_domain_is_not_assigned_a_genre(tmp_path):
    config = tmp_path / "topics.json"
    config.write_text(json.dumps({"topics": []}), encoding="utf-8")

    assert TopicMatcher(config).match({"domain": "new-site.example"}) is None
