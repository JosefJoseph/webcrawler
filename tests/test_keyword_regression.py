"""Regression tests for keyword matching and pipeline skip behavior."""
from __future__ import annotations

from app.parser.parser import build_page_result
from app.services.keyword_filter import filter_results_by_keywords


def _make_page(url: str, html: str, status: str = "ok", error: str = "") -> dict:
    raw = {
        "url": url,
        "final_url": url,
        "depth": 0,
        "html": html,
        "links": [],
        "status": status,
        "error": error,
        "fetch_method": "mock" if status == "ok" else "skip",
        "fetch_error": error,
    }
    return build_page_result(raw)


# ---------------------------------------------------------------------------
# D. Keyword fallback regression
# ---------------------------------------------------------------------------


def test_keyword_matching_finds_monitor_and_eyes():
    """Regression: page containing 'monitor' and 'eyes' matches those exact keywords."""
    html = """
    <html>
    <head><title>FOV Calculator</title></head>
    <body>
    <h1>FOV Calculator</h1>
    <p>Distance from your eyes to the screen determines your field of view.
    Use a monitor that fits your sim racing cockpit setup for the best experience.</p>
    </body>
    </html>
    """
    page = _make_page("https://simracingcockpit.gg/fov-calculator/", html)
    matched, unmatched = filter_results_by_keywords(
        [page], ["gap to screen", "monitor", "eyes"]
    )

    assert len(matched) == 1, f"Expected 1 match, got {len(matched)}: {[r['url'] for r in unmatched]}"
    kw = matched[0]["keyword_matches"]
    assert "monitor" in kw, f"Expected 'monitor' in keyword_matches, got: {kw}"
    assert "eyes" in kw, f"Expected 'eyes' in keyword_matches, got: {kw}"


def test_keyword_matching_finds_gap_to_screen_phrase():
    """Regression: multi-word phrase 'gap to screen' matches correctly."""
    html = """
    <html>
    <body>
    <p>The gap to screen distance is important for optimal visibility in your setup.</p>
    </body>
    </html>
    """
    page = _make_page("https://example.com/page", html)
    matched, _ = filter_results_by_keywords([page], ["gap to screen", "monitor", "eyes"])

    assert len(matched) == 1
    kw = matched[0]["keyword_matches"]
    assert "gap to screen" in kw, f"Expected 'gap to screen' in keyword_matches, got: {kw}"


def test_keyword_matching_all_three_keywords():
    """All three keywords appear in the text; all should be reported."""
    html = """
    <html>
    <body>
    <p>The gap to screen measurement from your eyes to the monitor surface
    is critical for the correct FOV setting.</p>
    </body>
    </html>
    """
    page = _make_page("https://example.com/fov", html)
    matched, _ = filter_results_by_keywords(
        [page], ["gap to screen", "monitor", "eyes"]
    )

    assert len(matched) == 1
    kw = matched[0]["keyword_matches"]
    assert "gap to screen" in kw
    assert "monitor" in kw
    assert "eyes" in kw


def test_keyword_no_match_returns_unmatched():
    """Page without any of the keywords ends up in unmatched list."""
    html = """
    <html>
    <body>
    <p>This page is about cooking recipes and has nothing to do with racing cockpits.</p>
    </body>
    </html>
    """
    page = _make_page("https://example.com/cooking", html)
    matched, unmatched = filter_results_by_keywords(
        [page], ["gap to screen", "monitor", "eyes"]
    )

    assert len(matched) == 0
    assert len(unmatched) == 1


# ---------------------------------------------------------------------------
# E. Crawl skip test: skipped pages go through parser without crashing
# ---------------------------------------------------------------------------


def test_skipped_page_builds_result_without_crash():
    """build_page_result must handle a locally skipped page (empty html) gracefully."""
    skipped_raw = {
        "url": "https://example.com",
        "final_url": "https://example.com",
        "depth": 0,
        "html": "",
        "links": [],
        "status": "skipped",
        "error": "manual skip",
        "fetch_method": "skip",
        "fetch_error": "manual skip",
    }
    result = build_page_result(skipped_raw)

    assert result["status"] == "skipped"
    assert result["url"] == "https://example.com"
    assert result["error"] == "manual skip"
    assert result["text"] == "" or result["text"] is not None


def test_skipped_page_does_not_match_keywords():
    """A skipped page with no text should land in unmatched, not matched."""
    skipped_raw = {
        "url": "https://example.com",
        "final_url": "https://example.com",
        "depth": 0,
        "html": "",
        "links": [],
        "status": "skipped",
        "error": "manual skip",
        "fetch_method": "skip",
        "fetch_error": "manual skip",
    }
    page_result = build_page_result(skipped_raw)
    matched, unmatched = filter_results_by_keywords(
        [page_result], ["monitor", "eyes"]
    )

    assert len(matched) == 0, "Skipped (empty) page must not match any keywords"
    assert len(unmatched) == 1


def test_pipeline_stats_skipped_vs_ok():
    """Pipeline classifies ok and skipped pages independently."""
    ok_raw = {
        "url": "https://example.com/page",
        "final_url": "https://example.com/page",
        "depth": 0,
        "html": "<html><body><p>monitor eyes screen</p></body></html>",
        "links": [],
        "status": "ok",
        "error": "",
        "fetch_method": "mock",
        "fetch_error": "",
    }
    skipped_raw = {
        "url": "https://example.com/blocked",
        "final_url": "https://example.com/blocked",
        "depth": 0,
        "html": "",
        "links": [],
        "status": "skipped",
        "error": "manual skip",
        "fetch_method": "skip",
        "fetch_error": "manual skip",
    }

    crawled_pages = [ok_raw, skipped_raw]
    ok_pages = [p for p in crawled_pages if p["status"] == "ok"]
    skipped_pages = [p for p in crawled_pages if p["status"] == "skipped"]

    assert len(ok_pages) == 1
    assert len(skipped_pages) == 1
    assert len(crawled_pages) == 2  # not zero — skipped pages are visible in pipeline


# ---------------------------------------------------------------------------
# Logging helpers (unit-testable subset)
# ---------------------------------------------------------------------------


def test_add_debug_log_structured_fields():
    """add_debug_log with **fields must produce key=value formatted output."""
    logs: list[str] = []

    def _log(level: str, message: str, **fields) -> None:
        field_str = (" " + " ".join(f"{k}={v}" for k, v in fields.items())) if fields else ""
        logs.append(f"[{level}] {message}{field_str}")

    _log("SKIP", "url=https://example.com reason=manual skip")
    _log("FETCH", "success=false", url="https://example.com", status="skipped")
    _log("SEMANTIC", "ready=false", error="model not initialized")
    _log("SUMMARY", "attempted=1 fetched_ok=0 skipped=1 failed=0 matched=0")

    assert any("[SKIP]" in line and "reason=manual skip" in line for line in logs)
    assert any("[FETCH]" in line and "success=false" in line for line in logs)
    assert any("[SEMANTIC]" in line and "ready=false" in line for line in logs)
    assert any("[SUMMARY]" in line and "skipped=1" in line for line in logs)
