from app.services.path_filter_service import (
    build_common_path_suggestions,
    parse_path_filters,
    split_rows_by_path_filter,
)


def test_parse_path_filters_parses_comma_separated_values() -> None:
    filters = parse_path_filters(" /faq , /food-details/.../nutrients ,, ")
    assert filters == ["/faq", "/food-details/.../nutrients"]


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


def test_build_common_path_suggestions_returns_prefixes() -> None:
    rows = [
        {"url": "https://fdc.nal.usda.gov/food-details/123/nutrients"},
        {"url": "https://fdc.nal.usda.gov/food-details/456/ingredients"},
        {"url": "https://fdc.nal.usda.gov/faq"},
    ]

    suggestions = build_common_path_suggestions(rows, limit=3)

    assert "/food-details" in suggestions
    assert len(suggestions) <= 3
