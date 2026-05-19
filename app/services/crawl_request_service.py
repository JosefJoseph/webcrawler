from __future__ import annotations


def should_run_crawl(payload: dict | None, last_processed_request_id: str | None) -> bool:
    """Return True if payload represents a new, unprocessed crawl request."""
    if not payload:
        return False
    request_id = payload.get("request_id")
    if not request_id:
        return False
    return str(request_id) != str(last_processed_request_id or "")
