from pathlib import Path

import pandas as pd

import app.services.export_service as export_service


def test_export_to_pdf_writes_pdf_file(tmp_path):
    output_file = str(tmp_path / "results.pdf")

    df = pd.DataFrame(
        [
            {
                "url": "https://example.com",
                "depth": 1,
                "status": "ok",
                "fetch_method": "requests",
                "title": "Example",
            }
        ]
    )

    result_path = export_service.export_to_pdf(df, "example.com", output_file)

    path = Path(result_path)
    assert path.exists()
    assert path.suffix == ".pdf"
    assert path.read_bytes().startswith(b"%PDF")


def test_export_to_csv_writes_csv_file(tmp_path):
    output_file = str(tmp_path / "results.csv")

    df = pd.DataFrame([{"url": "https://example.com", "title": "Test"}])
    result_path = export_service.export_to_csv(df, "example.com", output_file)

    path = Path(result_path)
    assert path.exists()
    assert path.suffix == ".csv"


def test_export_to_json_writes_json_file(tmp_path):
    output_file = str(tmp_path / "results.json")

    records = [{"url": "https://example.com", "title": "Test"}]
    result_path = export_service.export_to_json(records, "example.com", output_file)

    path = Path(result_path)
    assert path.exists()
    assert path.suffix == ".json"


def test_generate_filename_includes_domain():
    name = export_service.generate_filename("crawl_results", "example.com", "csv")
    assert "example_com" in name
    assert name.endswith(".csv")
    assert name.startswith("crawl_results_")