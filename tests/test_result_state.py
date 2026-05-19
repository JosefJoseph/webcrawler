"""Tests for result state management."""
from app.services.result_state_service import (
    remove_result_by_url,
    restore_original_results,
    compute_removed_count,
)


SAMPLE_RESULTS = [
    {"url": "https://example.com/a", "title": "Page A"},
    {"url": "https://example.com/b", "title": "Page B"},
    {"url": "https://example.com/c", "title": "Page C"},
]


def test_remove_result_by_url():
    updated = remove_result_by_url(SAMPLE_RESULTS, "https://example.com/b")
    assert len(updated) == 2
    assert all(r["url"] != "https://example.com/b" for r in updated)


def test_remove_nonexistent_url_unchanged():
    updated = remove_result_by_url(SAMPLE_RESULTS, "https://example.com/z")
    assert len(updated) == 3


def test_restore_original_is_deep_copy():
    original = [{"url": "https://example.com/a", "title": "Page A"}]
    restored = restore_original_results(original)
    restored[0]["title"] = "Modified"
    assert original[0]["title"] == "Page A"


def test_compute_removed_count():
    current = [SAMPLE_RESULTS[0], SAMPLE_RESULTS[2]]
    count = compute_removed_count(SAMPLE_RESULTS, current)
    assert count == 1


def test_remove_result_original_not_mutated():
    original_copy = [dict(r) for r in SAMPLE_RESULTS]
    remove_result_by_url(SAMPLE_RESULTS, "https://example.com/a")
    assert len(SAMPLE_RESULTS) == 3  # original unchanged
