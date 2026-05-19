import json
import pytest
from pathlib import Path
from app.services.local_settings_service import (
    load_local_settings,
    save_local_settings,
    clear_local_settings,
    merge_with_defaults,
)


def test_load_missing_returns_empty(tmp_path):
    path = tmp_path / "settings.json"
    assert load_local_settings(path) == {}


def test_save_and_load_roundtrip(tmp_path):
    path = tmp_path / "settings.json"
    data = {"website": "https://example.com", "max_pages": 5, "semantic_search": True}
    save_local_settings(data, path)
    loaded = load_local_settings(path)
    assert loaded == data


def test_corrupted_json_returns_empty(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("not valid json {{{", encoding="utf-8")
    assert load_local_settings(path) == {}


def test_non_dict_json_returns_empty(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    assert load_local_settings(path) == {}


def test_clear_removes_file(tmp_path):
    path = tmp_path / "settings.json"
    save_local_settings({"x": 1}, path)
    assert path.exists()
    clear_local_settings(path)
    assert not path.exists()


def test_clear_nonexistent_file_does_not_raise(tmp_path):
    path = tmp_path / "nonexistent.json"
    clear_local_settings(path)  # should not raise


def test_merge_keeps_only_known_keys():
    defaults = {"a": 1, "b": 2}
    saved = {"a": 99, "c": 999}
    merged = merge_with_defaults(saved, defaults)
    assert merged == {"a": 99, "b": 2}
    assert "c" not in merged


def test_merge_applies_defaults_for_missing_keys():
    defaults = {"a": 1, "b": 2, "c": 3}
    saved = {"a": 99}
    merged = merge_with_defaults(saved, defaults)
    assert merged["a"] == 99
    assert merged["b"] == 2
    assert merged["c"] == 3


def test_merge_empty_saved_returns_defaults():
    defaults = {"a": 1, "b": "hello"}
    merged = merge_with_defaults({}, defaults)
    assert merged == defaults


def test_save_does_not_crash_on_write_error(tmp_path):
    path = tmp_path / "nested" / "deep" / "settings.json"
    save_local_settings({"x": 1}, path)  # should not raise (silently fails)
