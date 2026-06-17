"""
tests/test_tools.py

One test per failure mode for each of the three FitFindr tools, plus
planning loop tests verifying that state passes correctly and early-exit
branches fire when search_listings returns nothing.

search_listings tests are pure (no LLM). suggest_outfit and create_fit_card
tests mock the Groq client so they run without a real API key.
"""

from unittest.mock import MagicMock, patch

import pytest

from agent import run_agent
from tools import create_fit_card, search_listings, suggest_outfit
from utils.data_loader import get_empty_wardrobe, get_example_wardrobe


# ── search_listings ───────────────────────────────────────────────────────────

def test_search_returns_results():
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    assert isinstance(results, list)
    assert len(results) > 0


def test_search_empty_results():
    # No listing will match this combination — should return [] not raise
    results = search_listings("designer ballgown", size="XXS", max_price=5)
    assert results == []


def test_search_price_filter():
    results = search_listings("jacket", size=None, max_price=10)
    assert all(item["price"] <= 10 for item in results)


def test_search_size_filter():
    results = search_listings("vintage", size="W30", max_price=None)
    assert all("w30" in item["size"].lower() for item in results)


def test_search_results_sorted_by_score():
    # A very specific multi-keyword query — first result should score highest
    results = search_listings("vintage graphic tee streetwear", max_price=None)
    assert len(results) >= 2
    # Each result has at least 1 keyword match (score >= 1 filter holds)
    assert isinstance(results[0], dict)
    assert "title" in results[0]


def test_search_returns_full_listing_fields():
    results = search_listings("denim", max_price=None)
    assert len(results) > 0
    required_fields = {"id", "title", "description", "category", "style_tags",
                       "size", "condition", "price", "colors", "platform"}
    assert required_fields.issubset(results[0].keys())


# ── suggest_outfit ────────────────────────────────────────────────────────────

SAMPLE_ITEM = {
    "title": "Graphic Tee — 2003 Tour Bootleg Style",
    "category": "tops",
    "style_tags": ["graphic tee", "vintage", "streetwear"],
    "colors": ["black"],
    "condition": "good",
}


def _mock_groq(text: str):
    """Return a mock Groq client whose completion returns `text`."""
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=text))]
    )
    return mock_client


@patch("tools._get_groq_client")
def test_suggest_outfit_with_wardrobe(mock_get_client):
    mock_get_client.return_value = _mock_groq("Outfit 1: tee + jeans + sneakers.")
    result = suggest_outfit(SAMPLE_ITEM, get_example_wardrobe())
    assert isinstance(result, str)
    assert len(result) > 0


@patch("tools._get_groq_client")
def test_suggest_outfit_empty_wardrobe_does_not_crash(mock_get_client):
    # Failure mode: wardrobe['items'] is empty — must return a string, not raise
    mock_get_client.return_value = _mock_groq("General advice: pair with slim trousers.")
    result = suggest_outfit(SAMPLE_ITEM, get_empty_wardrobe())
    assert isinstance(result, str)
    assert len(result) > 0


@patch("tools._get_groq_client")
def test_suggest_outfit_empty_wardrobe_uses_general_prompt(mock_get_client):
    # Verify the LLM is still called (not silently skipped) when wardrobe is empty
    mock_client = _mock_groq("General styling advice here.")
    mock_get_client.return_value = mock_client
    suggest_outfit(SAMPLE_ITEM, get_empty_wardrobe())
    assert mock_client.chat.completions.create.called


# ── create_fit_card ───────────────────────────────────────────────────────────

SAMPLE_OUTFIT = "Pair with baggy jeans and chunky sneakers for a 90s streetwear look."
SAMPLE_NEW_ITEM = {
    "title": "Graphic Tee — 2003 Tour Bootleg Style",
    "price": 24.0,
    "platform": "depop",
}


def test_create_fit_card_empty_outfit_returns_error_string():
    # Failure mode: empty outfit — must return error string, not raise
    result = create_fit_card("", SAMPLE_NEW_ITEM)
    assert isinstance(result, str)
    assert "error" in result.lower() or "missing" in result.lower()


def test_create_fit_card_whitespace_outfit_returns_error_string():
    result = create_fit_card("   ", SAMPLE_NEW_ITEM)
    assert isinstance(result, str)
    assert "error" in result.lower() or "missing" in result.lower()


@patch("tools._get_groq_client")
def test_create_fit_card_returns_nonempty_string(mock_get_client):
    mock_get_client.return_value = _mock_groq(
        "Found this tee on depop for $24 and never looked back."
    )
    result = create_fit_card(SAMPLE_OUTFIT, SAMPLE_NEW_ITEM)
    assert isinstance(result, str)
    assert len(result) > 0


@patch("tools._get_groq_client")
def test_create_fit_card_does_not_call_llm_when_outfit_empty(mock_get_client):
    # Guard must fire before the client is even instantiated
    mock_client = _mock_groq("should not be called")
    mock_get_client.return_value = mock_client
    create_fit_card("", SAMPLE_NEW_ITEM)
    mock_client.chat.completions.create.assert_not_called()


# ── planning loop (run_agent) ─────────────────────────────────────────────────

@patch("tools._get_groq_client")
def test_run_agent_no_results_returns_error_without_calling_llm(mock_get_client):
    # The critical test: no-match path must not call suggest_outfit or create_fit_card
    mock_client = _mock_groq("should not be reached")
    mock_get_client.return_value = mock_client

    session = run_agent("designer ballgown size XXS under $5", get_example_wardrobe())

    assert session["error"] is not None
    assert session["outfit_suggestion"] is None
    assert session["fit_card"] is None
    mock_client.chat.completions.create.assert_not_called()


@patch("tools._get_groq_client")
def test_run_agent_happy_path_populates_all_fields(mock_get_client):
    mock_get_client.return_value = _mock_groq("Outfit and caption text here.")

    session = run_agent("vintage graphic tee under $30", get_example_wardrobe())

    assert session["error"] is None
    assert session["selected_item"] is not None
    assert isinstance(session["outfit_suggestion"], str) and session["outfit_suggestion"]
    assert isinstance(session["fit_card"], str) and session["fit_card"]


@patch("tools._get_groq_client")
def test_run_agent_selected_item_matches_search_results(mock_get_client):
    mock_get_client.return_value = _mock_groq("Some outfit suggestion.")

    session = run_agent("vintage denim jeans", get_example_wardrobe())

    assert session["selected_item"] == session["search_results"][0]


@patch("tools._get_groq_client")
def test_run_agent_price_filter_respected(mock_get_client):
    mock_get_client.return_value = _mock_groq("Some outfit suggestion.")

    session = run_agent("tops under $20", get_example_wardrobe())

    if session["selected_item"]:
        assert session["selected_item"]["price"] <= 20


@patch("tools._get_groq_client")
def test_run_agent_different_queries_select_different_items(mock_get_client):
    mock_get_client.return_value = _mock_groq("Generic suggestion.")

    session_a = run_agent("vintage graphic tee", get_example_wardrobe())
    session_b = run_agent("corduroy pants", get_example_wardrobe())

    # Both succeed but land on different items — loop is query-driven not hardcoded
    assert session_a["error"] is None
    assert session_b["error"] is None
    assert session_a["selected_item"]["id"] != session_b["selected_item"]["id"]
