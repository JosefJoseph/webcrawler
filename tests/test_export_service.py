from pathlib import Path

import app.services.export_service as export_service


def test_export_pdf_writes_pdf_file(tmp_path, monkeypatch):
    monkeypatch.setattr(export_service, "EXPORT_DIR", tmp_path)

    output_path = export_service.export_pdf(
        [
            {
                "url": "https://example.com",
                "depth": 1,
                "status": "ok",
                "fetch_method": "requests",
                "title": "Example",
                "match_summary": "[nutrition] Example summary",
                "matched_block_count": 1,
                "match_occurrence_count": 1,
                "matched_blocks": [
                    {
                        "keywords": ["nutrition"],
                        "source_type": "text_block",
                        "tag": "p",
                        "match_count": 1,
                        "text": "Nutrition facts are listed here.",
                    }
                ],
            }
        ],
        filename="results.pdf",
    )

    path = Path(output_path)
    assert path.exists()
    assert path.suffix == ".pdf"
    assert path.read_bytes().startswith(b"%PDF")