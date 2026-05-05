from app.services.keyword_filter import (
    extract_match_contexts,
    get_available_keyword_groups,
    get_keywords_from_groups,
    merge_keywords,
    normalize_keyword,
    normalize_keywords,
    parse_keywords,
)


# ---------------------------------------------------------------------------
# normalize_keyword / normalize_keywords
# ---------------------------------------------------------------------------


def test_normalize_keyword_strips_and_lowercases():
    assert normalize_keyword("  Nutrition Facts  ") == "nutrition facts"


def test_normalize_keyword_collapses_whitespace():
    assert normalize_keyword("supply   chain") == "supply chain"


def test_normalize_keywords_deduplicates():
    result = normalize_keywords(["food", "FOOD", "Food"])
    assert result == ["food"]


def test_normalize_keywords_removes_empty():
    result = normalize_keywords(["food", "", "  ", "drink"])
    assert result == ["food", "drink"]


# ---------------------------------------------------------------------------
# get_available_keyword_groups / get_keywords_from_groups
# ---------------------------------------------------------------------------


def test_get_available_keyword_groups_returns_dict():
    groups = get_available_keyword_groups()
    assert isinstance(groups, dict)
    assert "inhaltsstoffe" in groups
    assert "lieferkette" in groups
    assert "nachhaltigkeit" in groups


def test_get_keywords_from_groups_known_group():
    keywords = get_keywords_from_groups(["inhaltsstoffe"])
    assert "ingredient" in keywords or "ingredients" in keywords


def test_get_keywords_from_groups_unknown_group():
    keywords = get_keywords_from_groups(["nonexistent"])
    assert keywords == []


# ---------------------------------------------------------------------------
# merge_keywords
# ---------------------------------------------------------------------------


def test_merge_keywords_combines_custom_and_group():
    result = merge_keywords(raw_keywords="custom_kw", selected_groups=["inhaltsstoffe"])
    assert "custom_kw" in result
    assert "ingredient" in result or "ingredients" in result


def test_merge_keywords_empty_inputs():
    result = merge_keywords(raw_keywords="", selected_groups=[])
    assert result == []


# ---------------------------------------------------------------------------
# parse_keywords
# ---------------------------------------------------------------------------


def test_parse_keywords():
    assert parse_keywords("a, b, c") == ["a", "b", "c"]


def test_parse_keywords_semicolons():
    assert parse_keywords("a; b; c") == ["a", "b", "c"]


def test_parse_keywords_empty():
    assert parse_keywords("") == []


# ---------------------------------------------------------------------------
# extract_match_contexts
# ---------------------------------------------------------------------------


def test_extract_match_contexts():
    contexts = extract_match_contexts("Nutrition facts are listed here.", "nutrition", window=10)
    assert len(contexts) == 1
    assert contexts[0]["keyword"].lower() == "nutrition"


def test_extract_match_contexts_can_use_full_block_as_context():
    contexts = extract_match_contexts(
        "Nutrition facts are listed here.",
        "nutrition",
        context_override="Nutrition facts are listed here.",
        source_type="text_block",
        tag="p",
        block_id="block-1",
    )
    assert len(contexts) == 1
    assert contexts[0]["context"] == "Nutrition facts are listed here."
    assert contexts[0]["tag"] == "p"
    assert contexts[0]["block_id"] == "block-1"


def test_filter_results_groups_keywords_by_text_block():
    from app.services.keyword_filter import filter_results_by_keywords

    results = [
        {
            "searchable_text": "Nutrition facts and ingredients for this product. Unrelated footer text.",
            "attribute_texts": [],
            "text_blocks": [
                {
                    "block_id": "block-0",
                    "source_type": "text_block",
                    "tag": "p",
                    "text": "Nutrition facts and ingredients for this product.",
                },
                {
                    "block_id": "block-1",
                    "source_type": "text_block",
                    "tag": "p",
                    "text": "Unrelated footer text.",
                },
            ],
        }
    ]

    hits, misses = filter_results_by_keywords(results, ["nutrition", "ingredients"])

    assert len(hits) == 1
    assert len(misses) == 0
    assert hits[0]["matched_block_count"] == 1
    assert hits[0]["match_occurrence_count"] == 2
    assert hits[0]["keyword_matches"] == ["nutrition", "ingredients"]
    assert hits[0]["matched_blocks"][0]["text"] == "Nutrition facts and ingredients for this product."
    assert hits[0]["matched_blocks"][0]["keywords"] == ["nutrition", "ingredients"]
    assert "[nutrition, ingredients] Nutrition facts and ingredients for this product." in hits[0]["match_summary"]
