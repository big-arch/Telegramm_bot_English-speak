"""Provider selection and the Groq schema handling.

The free stack runs on a smaller model than a frontier one, so the paths that
keep its output usable — schema constraints going out, verbatim-quote grounding
coming back — are the ones worth testing.
"""

from __future__ import annotations

import pytest

from bot.config import settings
from bot.services.backends import get_backend
from bot.services.backends.groq_backend import _strictify
from bot.services.llm import Assessment


@pytest.fixture(autouse=True)
def _reset_backend_cache():
    get_backend.cache_clear()
    yield
    get_backend.cache_clear()


def test_groq_is_the_default_provider(monkeypatch):
    """One key covers speech and dialogue, and it works where Gemini does not."""
    monkeypatch.setattr(settings, "llm_provider", "groq")
    assert get_backend().name == "groq"


def test_unknown_provider_names_the_supported_ones(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "nonsense")
    with pytest.raises(RuntimeError) as excinfo:
        get_backend()
    assert "groq" in str(excinfo.value)


def test_missing_key_for_the_selected_provider_is_reported(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "groq")
    monkeypatch.setattr(settings, "groq_api_key", None)
    assert any("GROQ_API_KEY" in m for m in settings.missing_keys())


def test_strictify_locks_down_every_object_in_the_schema():
    """Constrained decoding rejects a schema that allows extra properties or
    leaves any property optional. Pydantic emits neither by itself."""
    strict = _strictify(Assessment.model_json_schema())

    def check(node):
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"])
            for value in node.values():
                check(value)
        elif isinstance(node, list):
            for value in node:
                check(value)

    check(strict)


def test_strictify_reaches_nested_models():
    """Assessment contains a list of Finding; the nested definition needs the
    same treatment or the whole schema is rejected."""
    strict = _strictify(Assessment.model_json_schema())
    finding = strict["$defs"]["Finding"]
    assert finding["additionalProperties"] is False
    assert "original_span" in finding["required"]


def test_strictify_does_not_mutate_the_original():
    schema = Assessment.model_json_schema()
    _strictify(schema)
    assert "additionalProperties" not in schema
