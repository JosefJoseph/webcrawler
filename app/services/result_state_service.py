from __future__ import annotations

from typing import Any


def remove_result_by_url(rows: list[dict[str, Any]], url: str) -> list[dict[str, Any]]:
    """Entfernt ein Ergebnis anhand seiner URL aus einer Ergebnisliste.

    Args:
        rows: Aktuelle Ergebnisliste.
        url: Ziel-URL, die entfernt werden soll.

    Returns:
        Neue Ergebnisliste ohne den entsprechenden Eintrag.
    """
    return [row for row in rows if str(row.get("url", "")) != url]


def remove_excluded_results(
    current_rows: list[dict[str, Any]],
    visible_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Behält nur sichtbare Treffer und gibt Anzahl entfernter Treffer zurück.

    Args:
        current_rows: Aktuelle Arbeitsmenge.
        visible_rows: Ergebnisliste nach aktivem Filter.

    Returns:
        Tuple aus (bereinigter Liste, entfernte Anzahl).
    """
    visible_urls = {str(row.get("url", "")) for row in visible_rows}
    removed_count = sum(1 for row in current_rows if str(row.get("url", "")) not in visible_urls)
    return visible_rows, removed_count


def restore_original_results(original_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Stellt den ursprünglichen Crawl-Zustand wieder her.

    Args:
        original_rows: Unveränderte Ergebnisliste nach dem Crawl.

    Returns:
        Kopie der ursprünglichen Ergebnisliste.
    """
    return list(original_rows)


def compute_removed_count(original_rows: list[dict[str, Any]], current_rows: list[dict[str, Any]]) -> int:
    """Berechnet wie viele Ergebnisse gegenüber dem Originalzustand entfernt wurden.

    Args:
        original_rows: Ergebnisliste direkt nach dem Crawl.
        current_rows: Aktuelle Arbeitsmenge.

    Returns:
        Nicht-negative Anzahl entfernter Ergebnisse.
    """
    return max(0, len(original_rows) - len(current_rows))
