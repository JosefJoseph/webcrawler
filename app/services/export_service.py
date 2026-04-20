from __future__ import annotations

import csv
import json
from pathlib import Path


EXPORT_DIR = Path("exports")
EXPORT_DIR.mkdir(exist_ok=True)


def export_json(data: list[dict], filename: str = "results.json") -> str:
    path = EXPORT_DIR / filename
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)
    return str(path)


def export_csv(data: list[dict], filename: str = "results.csv") -> str:
    path = EXPORT_DIR / filename
    rows = []

    for item in data:
        for block in item.get("matched_blocks", []):
            rows.append(
                {
                    "url": item.get("url", ""),
                    "depth": item.get("depth", 0),
                    "status": item.get("status", ""),
                    "fetch_method": item.get("fetch_method", ""),
                    "title": item.get("title", ""),
                    "match_summary": item.get("match_summary", ""),
                    "keywords": ", ".join(block.get("keywords", [])),
                    "source_type": block.get("source_type", ""),
                    "tag": block.get("tag", ""),
                    "match_count": block.get("match_count", 0),
                    "text_block": block.get("text", ""),
                }
            )

    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "url",
                "depth",
                "status",
                "fetch_method",
                "title",
                "match_summary",
                "keywords",
                "source_type",
                "tag",
                "match_count",
                "text_block",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    return str(path)


def export_markdown(data: list[dict], filename: str = "results.md") -> str:
    path = EXPORT_DIR / filename
    lines = ["# Web Research Tool Export", ""]

    for index, item in enumerate(data, start=1):
        lines.append(f"## Ergebnis {index}")
        lines.append("")
        lines.append(f"**URL:** {item.get('url', '')}")
        lines.append(f"**Tiefe:** {item.get('depth', 0)}")
        lines.append(f"**Status:** {item.get('status', '')}")
        lines.append(f"**Fetch-Methode:** {item.get('fetch_method', '')}")
        lines.append(f"**Titel:** {item.get('title', '')}")
        lines.append(f"**Trefferblöcke:** {item.get('matched_block_count', item.get('match_count', 0))}")
        lines.append(f"**Keyword-Vorkommen:** {item.get('match_occurrence_count', 0)}")
        if item.get("match_summary"):
            lines.append(f"**Zusammenfassung:** {item.get('match_summary', '')}")
        lines.append("")

        for block in item.get("matched_blocks", []):
            lines.append(f"- Keywords: **{', '.join(block.get('keywords', []))}**")
            lines.append(f"  - Quelle: `{block.get('source_type', '')}`")
            lines.append(f"  - Tag: `{block.get('tag', '')}`")
            lines.append(f"  - Vorkommen im Block: {block.get('match_count', 0)}")
            lines.append(f"  - Textblock: {block.get('text', '')}")
            lines.append("")

        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)
