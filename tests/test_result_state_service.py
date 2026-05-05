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


def test_compute_removed_count_zero_when_equal() -> None:
    rows = [{"url": "https://a"}]
    assert compute_removed_count(rows, rows) == 0


def test_compute_removed_count_never_negative() -> None:
    original = [{"url": "https://a"}]
    current = [{"url": "https://a"}, {"url": "https://b"}]
    assert compute_removed_count(original, current) == 0


def test_remove_result_by_url_no_match() -> None:
    rows = [{"url": "https://a"}, {"url": "https://b"}]
    result = remove_result_by_url(rows, "https://c")
    assert len(result) == 2


def test_restore_original_results_empty() -> None:
    assert restore_original_results([]) == []
