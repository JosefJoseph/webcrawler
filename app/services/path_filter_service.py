from __future__ import annotations

import re
from collections import Counter
from functools import lru_cache
from typing import Any
from urllib.parse import urlparse


def parse_path_filters(raw_filter: str) -> list[str]:
    """Parst ein kommagetrenntes Pfadfilter-Input in bereinigte Filter.

    Args:
        raw_filter: Eingabetext aus der UI (z. B. "/faq, /food-details/.../nutrients").

    Returns:
        Liste bereinigter, nicht-leerer Filterwerte.
    """
    return [item.strip() for item in raw_filter.split(",") if item.strip()]


@lru_cache(maxsize=256)
def compile_path_filter_pattern(path_filter: str) -> re.Pattern[str]:
    """Kompiliert einen Pfadfilter mit `...`-Wildcard in ein Regex-Pattern.

    Args:
        path_filter: Ein einzelner Pfadfilter.

    Returns:
        Kompiliertes Regex-Pattern (case-insensitive).
    """
    # Replace the "..." wildcard token with regex ".*" for flexible path matching
    escaped = re.escape(path_filter)
    wildcard_pattern = escaped.replace(r"\.\.\.", ".*")
    return re.compile(wildcard_pattern, re.IGNORECASE)


def matches_any_path_filter(path: str, path_filters: list[str]) -> tuple[bool, str]:
    """Prüft, ob ein URL-Pfad zu mindestens einem Filter passt.

    Args:
        path: URL-Pfad (z. B. "/food-details/123/nutrients").
        path_filters: Liste aktiver Filter.

    Returns:
        Tuple aus Treffer-Flag und dem ersten passenden Filter.
    """
    for path_filter in path_filters:
        if compile_path_filter_pattern(path_filter).search(path):
            return True, path_filter
    return False, ""


def split_rows_by_path_filter(
    rows: list[dict[str, Any]],
    path_filters: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Teilt Ergebnisse in sichtbare und ausgeschlossene Treffer auf.

    Args:
        rows: Aktuelle Ergebnisliste.
        path_filters: Liste aktiver Pfadfilter.

    Returns:
        Tuple mit (sichtbare Ergebnisse, ausgeschlossene Ergebnisse).
    """
    if not path_filters:
        return rows, []

    visible_rows: list[dict[str, Any]] = []
    excluded_rows: list[dict[str, Any]] = []

    for row in rows:
        url = str(row.get("url", ""))
        parsed_path = urlparse(url).path or "/"
        is_match, _ = matches_any_path_filter(parsed_path, path_filters)
        if is_match:
            visible_rows.append(row)
        else:
            excluded_rows.append(row)

    return visible_rows, excluded_rows


def build_common_path_suggestions(rows: list[dict[str, Any]], limit: int = 8) -> list[str]:
    """Erzeugt häufige Pfadvorschläge aus vorhandenen URLs.

    Args:
        rows: Ergebnisliste mit URL-Feldern.
        limit: Maximale Anzahl von Vorschlägen.

    Returns:
        Liste häufiger Pfadpräfixe.
    """
    path_counter: Counter[str] = Counter()

    for row in rows:
        path = urlparse(str(row.get("url", ""))).path.strip("/")
        if not path:
            continue

        # Generate prefix suggestions at depth 1–2 (e.g. /food-details, /food-details/123)
        segments = [segment for segment in path.split("/") if segment]
        for depth in range(1, min(3, len(segments)) + 1):
            suggestion = "/" + "/".join(segments[:depth])
            path_counter[suggestion] += 1

    return [path for path, _count in path_counter.most_common(limit)]
