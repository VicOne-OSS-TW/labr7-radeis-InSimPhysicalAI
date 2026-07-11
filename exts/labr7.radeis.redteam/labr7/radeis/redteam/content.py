"""Reader for user-facing descriptive text bundled as generated/text_content.json
(compiled from an internal Markdown source); this module reads and caches it.
"""
from __future__ import annotations

import json
import os

_CACHE: dict | None = None
_JSON_PATH = os.path.join(os.path.dirname(__file__), "generated", "text_content.json")


def _load() -> dict:
    global _CACHE
    if _CACHE is None:
        with open(_JSON_PATH, encoding="utf-8") as f:
            _CACHE = json.load(f)
    return _CACHE


def get_text_content(content_id: str) -> str:
    """Return the text for `content_id` from generated/text_content.json."""
    return _load()[content_id]
