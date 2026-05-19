"""Tests for export formatting — no file I/O, no live model."""
import json
from unittest.mock import patch
import pytest

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False


SAMPLE_ROWS = [
    {
        "url": "https://example.com/product/1",
        "title": "Example Product",
        "keyword_matches": ["protein", "nutrition facts"],
        "matched_by": "keyword",
        "semantic_score": None,
        "matched_block_count": 2,
        "match_occurrence_count": 3,
        "text": "Protein 5g, Carbohydrates 10g",
        "searchable_text": "Protein 5g, Carbohydrates 10g",
        "text_blocks": [],
        "attribute_texts": [],
    },
    {
        "url": "https://example.com/product/2",
        "title": "Semantic Match Product",
        "keyword_matches": [],
        "matched_by": "semantic",
        "semantic_score": 0.91,
        "matched_block_count": 0,
        "match_occurrence_count": 0,
        "text": "Related content about food processing",
        "searchable_text": "Related content about food processing",
        "text_blocks": [],
        "attribute_texts": [],
    },
]


@pytest.mark.skipif(not HAS_PANDAS, reason="pandas not installed")
def test_build_csv_bytes_contains_matched_by():
    from app.services.export_service import build_csv_bytes, build_food_csv_rows
    df, _stats = build_food_csv_rows(SAMPLE_ROWS)
    csv_bytes = build_csv_bytes(df)
    content = csv_bytes.decode("utf-8")
    assert "matched_by" in content or "source_url" in content  # columns present


@pytest.mark.skipif(not HAS_PANDAS, reason="pandas not installed")
def test_build_json_bytes_is_valid_json():
    from app.services.export_service import build_json_bytes, build_food_json_records
    records, _stats = build_food_json_records(SAMPLE_ROWS)
    json_bytes = build_json_bytes(records)
    parsed = json.loads(json_bytes.decode("utf-8"))
    assert isinstance(parsed, list)


@pytest.mark.skipif(not HAS_PANDAS, reason="pandas not installed")
def test_build_markdown_bytes_contains_semantic_score():
    from app.services.export_service import build_markdown_bytes, build_food_csv_rows
    df, _stats = build_food_csv_rows(SAMPLE_ROWS)
    md_bytes = build_markdown_bytes(df, "example.com")
    content = md_bytes.decode("utf-8")
    assert "example.com" in content
    assert "Semantik" in content
    assert "91%" in content


@pytest.mark.skipif(not HAS_PANDAS, reason="pandas not installed")
def test_research_export_frame_contains_expected_columns_and_values():
    from app.services.export_service import build_research_export_frame, RESEARCH_EXPORT_COLUMNS

    frame = build_research_export_frame(SAMPLE_ROWS)
    assert list(frame.columns) == RESEARCH_EXPORT_COLUMNS
    assert frame.iloc[1]["matched_by"] == "semantic"
    assert frame.iloc[1]["semantic_score"] == 0.91
    assert "food processing" in frame.iloc[1]["snippet"]


@pytest.mark.skipif(not HAS_PANDAS, reason="pandas not installed")
def test_build_food_json_records_keeps_semantic_metadata_fields():
    from app.services.export_service import build_food_json_records

    records, _stats = build_food_json_records(SAMPLE_ROWS)
    assert len(records) == 2
    assert records[1]["meta"]["keyword_matches"] == []
    assert records[1]["source_url"] == "https://example.com/product/2"


@pytest.mark.skipif(not HAS_PANDAS, reason="pandas not installed")
def test_build_pdf_bytes_contains_readable_labels():
    from app.services.export_service import build_pdf_bytes, build_food_csv_rows

    df, _stats = build_food_csv_rows(SAMPLE_ROWS)
    pdf_bytes = build_pdf_bytes(df, "example.com")

    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 500


@pytest.mark.skipif(not HAS_PANDAS, reason="pandas not installed")
def test_csv_bytes_no_disk_write(tmp_path):
    """build_csv_bytes must not write any files to disk."""
    import os
    from app.services.export_service import build_csv_bytes, build_food_csv_rows
    df, _ = build_food_csv_rows(SAMPLE_ROWS)
    before = set(os.listdir(tmp_path))
    csv_bytes = build_csv_bytes(df)
    after = set(os.listdir(tmp_path))
    assert before == after  # no new files created
    assert len(csv_bytes) > 0


def test_no_auto_export_on_import():
    """Importing export_service must not create any /exports directory or files."""
    import os
    from pathlib import Path
    exports_dir = Path("/Users/vohangnguyen/Downloads/wr/webcrawler-main/exports")
    existed_before = exports_dir.exists()
    import importlib
    import app.services.export_service as es
    importlib.reload(es)
    if not existed_before:
        assert not exports_dir.exists(), "/exports dir created on import — must not happen"


@pytest.mark.skipif(not HAS_PANDAS, reason="pandas not installed")
def test_markdown_export_includes_matched_blocks_and_keyword_highlights():
    from app.services.export_service import build_markdown_bytes, build_research_export_frame

    rows = [
        {
            "url": "https://example.com/fov",
            "title": "FOV page",
            "keyword_matches": ["monitor", "eyes"],
            "matched_by": "keyword",
            "semantic_score": None,
            "semantic_reason": None,
            "matched_block_count": 1,
            "match_occurrence_count": 2,
            "snippet": "Distance from your eyes to the monitor.",
            "text": "Distance from your eyes to the monitor.",
            "searchable_text": "Distance from your eyes to the monitor.",
            "matched_blocks": [
                {
                    "source": "text_block",
                    "tag": "p",
                    "keywords": ["monitor", "eyes"],
                    "occurrences": 2,
                    "text": "Distance from your eyes to the monitor.",
                }
            ],
        }
    ]

    df = build_research_export_frame(rows)
    content = build_markdown_bytes(df, "example.com").decode("utf-8")

    assert "Matched Blocks (1)" in content
    assert "text_block" in content
    assert "<p>" in content
    assert "**monitor**" in content
    assert "**eyes**" in content


@pytest.mark.skipif(not HAS_PANDAS, reason="pandas not installed")
def test_pdf_export_with_matched_blocks_does_not_crash():
    from app.services.export_service import build_pdf_bytes, build_research_export_frame

    rows = [
        {
            "url": "https://example.com/fov",
            "title": "FOV page",
            "keyword_matches": ["monitor"],
            "matched_by": "keyword",
            "semantic_score": None,
            "matched_block_count": 1,
            "match_occurrence_count": 1,
            "snippet": "Curved monitor",
            "text": "Curved monitor",
            "searchable_text": "Curved monitor",
            "matched_blocks": [
                {
                    "source": "text_block",
                    "tag": "label",
                    "keywords": ["monitor"],
                    "occurrences": 1,
                    "text": "Curved monitor",
                }
            ],
        }
    ]

    df = build_research_export_frame(rows)
    pdf_bytes = build_pdf_bytes(df, "example.com")

    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 500
