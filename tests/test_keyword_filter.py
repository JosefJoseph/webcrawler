from app.services.keyword_filter import extract_match_contexts, parse_keywords

def test_parse_keywords():
    assert parse_keywords("a, b, c") == ["a", "b", "c"]

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
