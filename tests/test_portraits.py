"""Every partner has a face, and it is the one drawn in avatars.py.

The JPEGs are rendered from the SVGs by a script a developer runs by hand, so
the two can drift: add a persona and forget to re-render, and the chat quietly
falls back to text for that one partner. These tests catch that on the next
run instead of in production.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from bot import personas
from bot.services import portraits
from bot.webapp import avatars


@pytest.mark.parametrize("persona", personas.PERSONAS, ids=lambda p: p.key)
def test_every_partner_has_an_art_direction(persona):
    """A persona added without a Look gets the neutral grey card, which is the
    fallback for a mistake, not a design."""
    assert persona.key in avatars.LOOKS, f"no Look for {persona.key}"


@pytest.mark.parametrize("persona", personas.PERSONAS, ids=lambda p: p.key)
def test_every_portrait_is_valid_svg(persona):
    """Browsers render broken SVG as nothing at all, silently."""
    root = ET.fromstring(avatars.svg(persona.key, persona.name))
    assert root.tag.endswith("svg")
    assert root.get("viewBox") == "0 0 800 800"


@pytest.mark.parametrize("persona", personas.PERSONAS, ids=lambda p: p.key)
def test_every_portrait_has_been_rendered_for_the_chat(persona):
    """Telegram will not send SVG as a photo. If this fails, run
    `python -m scripts.render_avatars` and commit the result."""
    path = portraits.path_for(persona.key)
    assert path is not None, f"assets/personas/{persona.key}.jpg is missing"
    assert path.read_bytes()[:3] == b"\xff\xd8\xff", "not a JPEG"
    # Big enough to be a picture, small enough not to be a PNG in disguise.
    assert 10_000 < path.stat().st_size < 250_000


def test_the_initial_ignores_the_title():
    """Dr. Chen is a C, not a D."""
    assert ">C</text>" in avatars.svg("chen", "Dr. Chen")


def test_no_two_partners_share_an_emoji():
    """They did — Chen and Ethan both had the set square — and in a list of
    seven the emoji is how the eye tells them apart."""
    emojis = [p.emoji for p in personas.PERSONAS]
    assert len(emojis) == len(set(emojis))


def test_the_caption_says_who_they_are():
    ava = personas.get("ava")
    caption = portraits.caption_for(ava)
    assert "Ava" in caption and ava.tagline_ru in caption
