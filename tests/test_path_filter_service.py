from app.services.path_filter_service import (
    build_common_path_suggestions,
    compile_path_filter_pattern,
    matches_any_path_filter,
    parse_path_filters,
    split_rows_by_path_filter,
)


# ---------------------------------------------------------------------------
# parse_path_filters
# ---------------------------------------------------------------------------


def test_parse_path_filters_parses_comma_separated_values() -> None:
    filters = parse_path_filters(" /faq , /food-details/.../nutrients ,, ")
    assert filters == ["/faq", "/food-details/.../nutrients"]


def test_parse_path_filters_empty_input() -> None:
    assert parse_path_filters("") == []


def test_parse_path_filters_single_filter() -> None:
    assert parse_path_filters("/products") == ["/products"]


# ---------------------------------------------------------------------------
# compile_path_filter_pattern
# ---------------------------------------------------------------------------


def test_compile_path_filter_pattern_exact():
    pattern = compile_path_filter_pattern("/faq")
    assert pattern.search("/faq")
    assert not pattern.search("/about")


def test_compile_path_filter_pattern_wildcard():
    pattern = compile_path_filter_pattern("/food/.../nutrients")
    assert pattern.search("/food/123/nutrients")
    assert pattern.search("/food/abc/def/nutrients")
    assert not pattern.search("/food/123/ingredients")


# ---------------------------------------------------------------------------
# matches_any_path_filter
# ---------------------------------------------------------------------------


def test_matches_any_path_filter_match():
    match, matched = matches_any_path_filter("/food/123/nutrients", ["/food/.../nutrients"])
    assert match is True
    assert matched == "/food/.../nutrients"


def test_matches_any_path_filter_no_match():
    match, matched = matches_any_path_filter("/about", ["/food/.../nutrients"])
    assert match is False
    assert matched == ""


# ---------------------------------------------------------------------------
# split_rows_by_path_filter
# ---------------------------------------------------------------------------


def test_split_rows_by_path_filter_supports_wildcard() -> None:
    rows = [
        {"url": "https://fdc.nal.usda.gov/faq"},
        {"url": "https://fdc.nal.usda.gov/food-details/123/nutrients"},
        {"url": "https://fdc.nal.usda.gov/help"},
    ]

    visible, excluded = split_rows_by_path_filter(rows, ["/food-details/.../nutrients", "/faq"])

    assert len(visible) == 2
    assert len(excluded) == 1
    assert excluded[0]["url"].endswith("/help")


def test_split_rows_by_path_filter_no_filters() -> None:
    rows = [{"url": "https://example.com/a"}, {"url": "https://example.com/b"}]
    visible, excluded = split_rows_by_path_filter(rows, [])
    assert visible == rows
    assert excluded == []


# ---------------------------------------------------------------------------
# build_common_path_suggestions
# ---------------------------------------------------------------------------


def test_build_common_path_suggestions_returns_prefixes() -> None:
    rows = [
        {"url": "https://fdc.nal.usda.gov/food-details/123/nutrients"},
        {"url": "https://fdc.nal.usda.gov/food-details/456/ingredients"},
        {"url": "https://fdc.nal.usda.gov/faq"},
    ]

    suggestions = build_common_path_suggestions(rows, limit=3)

    assert "/food-details" in suggestions
    assert len(suggestions) <= 3


def test_build_common_path_suggestions_empty_rows() -> None:
    suggestions = build_common_path_suggestions([], limit=5)
    assert suggestions == []
