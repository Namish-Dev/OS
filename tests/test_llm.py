"""
Tests for core/llm_client.py and core/llm_classifier.py.

All network calls are mocked — these tests never require a real
Ollama server to be running.
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.llm_client import LLMClient, LLMUnavailableError
from core.llm_classifier import classify_with_llm, _parse_response
from core.project_matcher import UNASSIGNED, DISTRACTION, CONFIDENCE_HIGH, CONFIDENCE_NONE


# --------------------------------------------------------------------------
# LLMClient
# --------------------------------------------------------------------------

class TestLLMClient:

    def test_generate_returns_response_text(self):

        client = LLMClient()

        mock_response = MagicMock()
        mock_response.json.return_value = {"response": "  FastAPI Authentication  "}
        mock_response.raise_for_status.return_value = None

        with patch("core.llm_client.requests.post", return_value=mock_response) as mock_post:
            result = client.generate("some prompt", system="some system prompt")

        assert result == "FastAPI Authentication"
        assert mock_post.call_args.kwargs["json"]["prompt"] == "some prompt"
        assert mock_post.call_args.kwargs["json"]["system"] == "some system prompt"
        assert mock_post.call_args.kwargs["json"]["stream"] is False

    def test_generate_raises_on_connection_error(self):

        client = LLMClient()

        with patch("core.llm_client.requests.post", side_effect=requests.ConnectionError("refused")):
            try:
                client.generate("prompt")
                assert False, "expected LLMUnavailableError"
            except LLMUnavailableError:
                pass

    def test_generate_raises_on_missing_response_field(self):

        client = LLMClient()

        mock_response = MagicMock()
        mock_response.json.return_value = {"unexpected": "shape"}
        mock_response.raise_for_status.return_value = None

        with patch("core.llm_client.requests.post", return_value=mock_response):
            try:
                client.generate("prompt")
                assert False, "expected LLMUnavailableError"
            except LLMUnavailableError:
                pass

    def test_is_available_true_when_server_responds(self):

        client = LLMClient()

        mock_response = MagicMock()
        mock_response.ok = True

        with patch("core.llm_client.requests.get", return_value=mock_response):
            assert client.is_available() is True

    def test_is_available_false_when_server_unreachable(self):

        client = LLMClient()

        with patch("core.llm_client.requests.get", side_effect=requests.ConnectionError()):
            assert client.is_available() is False


# --------------------------------------------------------------------------
# _parse_response
# --------------------------------------------------------------------------

class TestParseResponse:

    def test_exact_project_name_match(self):
        result = _parse_response("FastAPI Authentication", ["FastAPI Authentication", "Personal OS"])
        assert result == "FastAPI Authentication"

    def test_matches_despite_extra_chatter(self):
        """Small local models don't always follow format instructions perfectly."""
        result = _parse_response(
            "I think this belongs to FastAPI Authentication because it mentions JWT.",
            ["FastAPI Authentication", "Personal OS"],
        )
        assert result == "FastAPI Authentication"

    def test_distraction_match(self):
        result = _parse_response("DISTRACTION", ["FastAPI Authentication"])
        assert result == DISTRACTION

    def test_unsure_returns_none(self):
        result = _parse_response("UNSURE", ["FastAPI Authentication"])
        assert result is None

    def test_empty_response_returns_none(self):
        result = _parse_response("", ["FastAPI Authentication"])
        assert result is None

    def test_longest_candidate_wins_to_avoid_partial_match(self):
        """A project named "FastAPI" shouldn't accidentally swallow a
        response that actually named "FastAPI Authentication"."""
        result = _parse_response(
            "FastAPI Authentication", ["FastAPI", "FastAPI Authentication"]
        )
        assert result == "FastAPI Authentication"

    def test_gibberish_returns_none(self):
        result = _parse_response("asdkjfh alksdjf", ["FastAPI Authentication"])
        assert result is None


# --------------------------------------------------------------------------
# classify_with_llm
# --------------------------------------------------------------------------

class TestClassifyWithLLM:

    def test_confident_project_match(self):

        client = MagicMock()
        client.generate.return_value = "FastAPI Authentication"

        label, confidence = classify_with_llm(
            client, "FastAPI JWT Tutorial", "YouTube video", "Learning",
            "youtube.com", ["FastAPI Authentication", "Personal OS"],
        )

        assert label == "FastAPI Authentication"
        assert confidence == CONFIDENCE_HIGH

    def test_distraction_match(self):

        client = MagicMock()
        client.generate.return_value = "DISTRACTION"

        label, confidence = classify_with_llm(
            client, "BTS Funny Moments", "YouTube video", "Entertainment",
            "youtube.com", ["FastAPI Authentication"],
        )

        assert label == DISTRACTION
        assert confidence == CONFIDENCE_HIGH

    def test_unsure_returns_unassigned_none_confidence(self):

        client = MagicMock()
        client.generate.return_value = "UNSURE"

        label, confidence = classify_with_llm(
            client, "Some ambiguous thing", "Web page", "Other",
            "example.com", ["FastAPI Authentication"],
        )

        assert label == UNASSIGNED
        assert confidence == CONFIDENCE_NONE

    def test_llm_unavailable_returns_unassigned_none_confidence(self):

        client = MagicMock()
        client.generate.side_effect = LLMUnavailableError("no server")

        label, confidence = classify_with_llm(
            client, "Anything", "Web page", "Other", None, ["FastAPI Authentication"],
        )

        assert label == UNASSIGNED
        assert confidence == CONFIDENCE_NONE

    def test_works_with_empty_project_list(self):
        """Should still be able to say DISTRACTION even with no projects configured."""

        client = MagicMock()
        client.generate.return_value = "DISTRACTION"

        label, confidence = classify_with_llm(
            client, "Funny cat video", "YouTube video", "Entertainment",
            "youtube.com", [],
        )

        assert label == DISTRACTION
        assert confidence == CONFIDENCE_HIGH