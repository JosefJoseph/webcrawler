from app.services.result_state_service import (
    compute_removed_count,
    remove_excluded_results,
    remove_result_by_url,
    restore_original_results,
)


def test_remove_result_by_url_removes_target() -> None:
    rows = [{"url": "https://a"}, {"url": "https://b"}]
    result = remove_result_by_url(rows, "https://a")

    assert result == [{"url": "https://b"}]


def test_remove_excluded_results_returns_removed_count() -> None:
    current = [{"url": "https://a"}, {"url": "https://b"}, {"url": "https://c"}]
    visible = [{"url": "https://a"}, {"url": "https://c"}]

    kept_rows, removed_count = remove_excluded_results(current, visible)

    assert kept_rows == visible
    assert removed_count == 1


def test_restore_original_results_returns_copy() -> None:
    original = [{"url": "https://a"}]
    restored = restore_original_results(original)

    assert restored == original
    assert restored is not original


def test_compute_removed_count_is_non_negative() -> None:
    original = [{"url": "https://a"}, {"url": "https://b"}]
    current = [{"url": "https://a"}]

    assert compute_removed_count(original, current) == 1
