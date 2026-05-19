"""Verify that crawling/filtering does not auto-write to /exports folder."""
import os
from pathlib import Path
from unittest.mock import MagicMock, patch


EXPORTS_DIR = Path("/Users/vohangnguyen/Downloads/wr/webcrawler-main/exports")


def test_filter_results_no_disk_write(tmp_path, monkeypatch):
    """Filtering results must not create files on disk."""
    from app.services.keyword_filter import filter_results_by_keywords

    results = [
        {
            "url": "https://example.com/p",
            "title": "Test Page",
            "searchable_text": "nutrition protein",
            "text": "nutrition protein",
            "text_blocks": [{"block_id": "b1", "source_type": "text_block", "tag": "p", "text": "nutrition protein"}],
            "attribute_texts": [],
        }
    ]
    before_exports = EXPORTS_DIR.exists()
    filter_results_by_keywords(results, ["nutrition"])
    if not before_exports:
        assert not EXPORTS_DIR.exists(), "filter_results_by_keywords must not create /exports"


def test_semantic_matcher_no_disk_write():
    """SemanticMatcher initialization must not create files on disk."""
    from app.services.semantic_matcher import SemanticMatcher

    matcher = SemanticMatcher()
    before = EXPORTS_DIR.exists()
    # Initialize will fail gracefully without torch — just check no files created
    matcher.initialize()
    if not before:
        assert not EXPORTS_DIR.exists()


def test_build_csv_bytes_no_side_effect():
    """build_csv_bytes must return bytes without any file I/O."""
    try:
        import pandas as pd
        from app.services.export_service import build_csv_bytes
    except ImportError:
        import pytest
        pytest.skip("pandas not installed")

    df = pd.DataFrame([{"source_url": "https://example.com", "page_title": "Test"}])
    before = set(os.listdir("."))
    result = build_csv_bytes(df)
    after = set(os.listdir("."))
    assert before == after
    assert isinstance(result, bytes)
    assert len(result) > 0


def test_build_markdown_bytes_no_side_effect():
    """build_markdown_bytes must return bytes without creating files."""
    try:
        import pandas as pd
        from app.services.export_service import build_markdown_bytes
    except ImportError:
        import pytest
        pytest.skip("pandas not installed")

    df = pd.DataFrame([{"source_url": "https://example.com", "page_title": "Test"}])
    before = set(os.listdir("."))
    result = build_markdown_bytes(df, "example.com")
    after = set(os.listdir("."))
    assert before == after
    assert isinstance(result, bytes)
    assert len(result) > 0


def test_build_pdf_bytes_no_side_effect():
    """build_pdf_bytes must return bytes without creating files."""
    try:
        import pandas as pd
        from app.services.export_service import build_pdf_bytes
    except ImportError:
        import pytest
        pytest.skip("pandas not installed")

    df = pd.DataFrame([{"source_url": "https://example.com", "page_title": "Test"}])
    before = set(os.listdir("."))
    result = build_pdf_bytes(df, "example.com")
    after = set(os.listdir("."))
    assert before == after
    assert isinstance(result, bytes)
    assert result.startswith(b"%PDF")


def test_generate_filename_has_no_exports_prefix():
    from app.services.export_service import generate_filename

    filename = generate_filename("crawl_results", "example.com", "csv")
    assert not filename.startswith("exports/")
    assert "example_com" in filename
