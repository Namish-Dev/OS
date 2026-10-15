"""Match activity to user-confirmed learning or personal-interest topics."""

import json
from pathlib import Path

DEFAULT_TOPICS_PATH = Path(__file__).resolve().parent.parent / "config" / "topics.json"


class TopicMatcher:
    """Only applies rules explicitly saved by the user; no website genre list."""

    def __init__(self, config_path: Path | str = DEFAULT_TOPICS_PATH):
        try:
            data = json.loads(Path(config_path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        self._topics = [item for item in data.get("topics", []) if item.get("name") and item.get("category")]

    def match(self, context: dict | None) -> tuple[str, str] | None:
        context = context or {}
        domain = (context.get("domain") or "").lower()
        searchable = " ".join(str(context.get(key) or "") for key in ("page_title", "url")).lower()
        for topic in self._topics:
            if domain and domain in {str(item).lower() for item in topic.get("domains", [])}:
                return topic["name"], topic["category"]
            if any(str(keyword).lower() in searchable for keyword in topic.get("keywords", []) if keyword):
                return topic["name"], topic["category"]
        return None
