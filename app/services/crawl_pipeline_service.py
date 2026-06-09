from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.crawler.crawler import crawl_domain, normalize_url as _normalize_url
from app.parser.parser import build_page_result
from app.services.keyword_filter import filter_results_by_keywords


@dataclass
class CrawlPipelineResult:
    matched_results: list[dict[str, Any]] = field(default_factory=list)
    unmatched_results: list[dict[str, Any]] = field(default_factory=list)
    pipeline_stats: dict[str, Any] = field(default_factory=dict)
    semantic_stats: dict[str, Any] = field(default_factory=dict)
    semantic_matcher: Any = None   # befüllter SemanticMatcher oder None
    error: str = ""


def run_crawl_pipeline(
    website: str,
    keywords: list[str],
    max_pages: int,
    max_depth: int,
    use_playwright: bool,
    semantic_enabled: bool,
    semantic_threshold: float,
    semantic_matcher=None,
    on_progress=None,
    on_event=None,
    debug_logger=None,
) -> CrawlPipelineResult:
    """Führt die vollständige Crawl-Pipeline aus: Crawlen, Parsen, Semantic-Init, Filtern, Stats.

    Kein Streamlit-Import. debug_logger ist ein optionales Callable (level: str, message: str) -> None.
    """

    def _log(level: str, message: str) -> None:
        if callable(debug_logger):
            debug_logger(level, message)

    try:
        _normalized_start = _normalize_url(website)

        _log(
            "CONFIG",
            f"start_url={website} normalized={_normalized_start} "
            f"max_pages={max_pages} max_depth={max_depth} "
            f"semantic_enabled={semantic_enabled} "
            f"semantic_threshold={semantic_threshold:.2f} ",
        )
        _log(
            "INFO",
            f"Crawl started with semantic matching {'enabled' if semantic_enabled else 'disabled'}, "
            f"threshold={semantic_threshold:.2f}",
        )

        # --- Crawl stage ---
        crawled_pages = crawl_domain(
            start_url=website,
            max_pages=max_pages,
            max_depth=max_depth,
            use_playwright=use_playwright,
            on_progress=on_progress,
            on_event=on_event,
        )

        # --- Crawl result classification ---
        ok_pages = [p for p in crawled_pages if p.get("status") == "ok"]
        skipped_pages = [p for p in crawled_pages if p.get("status") == "skipped"]
        error_pages = [p for p in crawled_pages if p.get("status") == "error"]

        _log("DEBUG", f"Gecrawlte Seiten: {len(crawled_pages)}")
        _log(
            "CRAWL",
            f"attempted={len(crawled_pages)} ok={len(ok_pages)} "
            f"skipped={len(skipped_pages)} failed={len(error_pages)}",
        )

        skipped_reasons = {}
        for p in skipped_pages:
            reason = p.get("error", "skipped")
            skipped_reasons[reason] = skipped_reasons.get(reason, 0) + 1
            _log("SKIP", f"url={p['url']} reason={reason}")
            _log("FETCH", f"success=false url={p['url']} status=skipped reason={reason}")
        for p in error_pages:
            _log("FETCH", f"success=false url={p['url']} error={p.get('error', '')}")
        for p in ok_pages:
            html_chars = len(p.get("html", ""))
            links = len(p.get("links", []))
            _log(
                "FETCH",
                f"success=true url={p['url']} final_url={p.get('final_url', p.get('url', ''))} "
                f"status_code={p.get('status_code', 'n/a') or 'n/a'} "
                f"content_type={p.get('content_type', 'n/a') or 'n/a'} "
                f"html_chars={html_chars} links={links} method={p.get('fetch_method', '')}",
            )

        if skipped_reasons:
            _log("DEBUG", f"Übersprungene Seiten nach Grund: {skipped_reasons}")

        # --- Parse stage ---
        page_results = []
        total_text_chars = 0
        pages_with_text_count = 0

        for page in crawled_pages:
            page_result = build_page_result(page)
            page_results.append(page_result)

            text_len = len(page_result.get("text", "") or "")
            blocks = len(page_result.get("text_blocks", []))
            passages = len(page_result.get("passage_blocks", []))
            snippet = (page_result.get("text", "") or "")[:80].replace("\n", " ")
            total_text_chars += text_len
            if text_len > 0 or blocks > 0:
                pages_with_text_count += 1

            _log(
                "PARSE",
                f"url={page_result.get('url', '')} text_chars={text_len} "
                f"text_blocks={blocks} passage_blocks={passages} "
                f'snippet="{snippet}"',
            )
            _log(
                "DEBUG",
                (
                    f'Parser-Extraktion für {page_result.get("url", "")}: '
                    f'Titel="{page_result.get("title", "")}", '
                    f'text_blocks={blocks}, '
                    f'attribute_texts={len(page_result.get("attribute_texts", []))}'
                ),
            )

        _log(
            "DEBUG",
            f"Ergebnisanzahl vor Keyword-Filter: {len(page_results)} | "
            f"Seiten mit Text: {pages_with_text_count} | "
            f"Gesamtzeichen: {total_text_chars}",
        )

        pipeline_stats = {
            "attempted": len(crawled_pages),
            "ok": len(ok_pages),
            "skipped": len(skipped_pages),
            "failed": len(error_pages),
            "parsed": len(page_results),
            "pages_with_text": pages_with_text_count,
            "total_chars": total_text_chars,
        }

        # --- Keyword match stage ---
        _log("MATCH", f"input_pages={len(page_results)} keywords={keywords}")

        # --- Semantic stage ---
        semantic_matcher_instance = semantic_matcher
        model_ready = False
        model_error = None

        if semantic_enabled:
            from app.services.semantic_matcher import SemanticMatcher

            _log("INFO", f"Semantische Suche aktiviert, Schwellenwert={semantic_threshold}")

            if semantic_matcher_instance is not None and getattr(semantic_matcher_instance, "ready", False):
                model_ready = True
                _log(
                    "SEMANTIC",
                    f"ready=true device={semantic_matcher_instance.device or 'cpu'} "
                    f"threshold={semantic_matcher_instance.threshold:.2f} source=cache",
                )
            else:
                _log("INFO", "Lade Semantic-Modell...")
                _log(
                    "DEBUG",
                    f"[Threshold] SemanticMatcher wird mit threshold={semantic_threshold:.2f} erstellt",
                )
                matcher = SemanticMatcher(threshold=semantic_threshold)
                success, msg = matcher.initialize()
                if success:
                    semantic_matcher_instance = matcher
                    model_ready = True
                    _log("INFO", f"Semantic-Backend bereit: {msg}")
                    _log(
                        "INFO",
                        f"Semantic backend using device: "
                        f"{semantic_matcher_instance.device or 'cpu'}, "
                        f"threshold={matcher.threshold:.2f}",
                    )
                    _log(
                        "SEMANTIC",
                        f"ready=true device={semantic_matcher_instance.device or 'cpu'} "
                        f"threshold={matcher.threshold:.2f}",
                    )
                else:
                    model_error = msg
                    semantic_matcher_instance = None
                    _log(
                        "WARNING",
                        f"Semantic model unavailable, falling back to keyword filtering: {msg}",
                    )
                    _log("SEMANTIC", f'ready=false error="{msg}"')
        else:
            _log("SEMANTIC", "ready=false enabled=false")

        matched_results, unmatched_results = filter_results_by_keywords(
            page_results,
            keywords,
            semantic_matcher=semantic_matcher_instance,
            debug_logger=debug_logger,
        )
        _log("DEBUG", f"Ergebnisanzahl nach Keyword-Filter: {len(matched_results)}")

        # --- RESULT log ---
        _log(
            "RESULT",
            f"matched={len(matched_results)} unmatched={len(unmatched_results)} "
            f"skipped={len(skipped_pages)} failed={len(error_pages)}",
        )

        # --- Semantic stats ---
        all_score_items = matched_results + unmatched_results
        all_scores = [
            r["semantic_score"]
            for r in all_score_items
            if r.get("semantic_score") is not None
        ]
        semantic_stats = {
            "max_score": max(all_scores) if all_scores else None,
            "avg_score": sum(all_scores) / len(all_scores) if all_scores else None,
            "min_score": min(all_scores) if all_scores else None,
            "score_count": len(all_scores),
            "total_crawled": len(page_results),
            "keyword_count": sum(
                1 for r in matched_results if r.get("matched_by") == "keyword"
            ),
            "semantic_count": sum(
                1 for r in matched_results if r.get("matched_by") == "semantic"
            ),
            "both_count": sum(
                1 for r in matched_results if r.get("matched_by") == "keyword+semantic"
            ),
            "unmatched_count": len(unmatched_results),
            "threshold": semantic_threshold,
            "semantic_enabled": semantic_enabled,
            "model_ready": model_ready if semantic_enabled else None,
            "model_error": model_error,
        }

        # --- SUMMARY log ---
        if len(matched_results) == 0:
            if len(crawled_pages) == 0:
                _no_results_reason = "No pages were crawled"
                _next_action = "Check if the start URL is valid and reachable"
            elif len(ok_pages) == 0 and len(skipped_pages) > 0:
                _no_results_reason = "All attempted URLs were skipped"
                _next_action = "Check the skip reason in the debug log, or test another URL"
            elif len(ok_pages) == 0 and len(error_pages) > 0:
                _no_results_reason = "All pages failed to fetch"
                _next_action = "Check network connectivity and the URL, then try again"
            elif pages_with_text_count == 0:
                _no_results_reason = (
                    "Pages were fetched but no text was extracted (JS rendering issue?)"
                )
                _next_action = "Try a different URL or disable JS rendering"
            else:
                _no_results_reason = "Keywords did not match any extracted text"
                _next_action = "Try different keywords or lower the semantic threshold"

            _log(
                "SUMMARY",
                f"attempted={len(crawled_pages)} fetched_ok={len(ok_pages)} "
                f"skipped={len(skipped_pages)} failed={len(error_pages)} "
                f"parsed={len(page_results)} matched=0 "
                f"unmatched={len(unmatched_results)}",
            )
            _log("SUMMARY", f'no_results_reason="{_no_results_reason}"')
            _log("SUMMARY", f'next_action="{_next_action}"')
        else:
            _log(
                "SUMMARY",
                f"attempted={len(crawled_pages)} fetched_ok={len(ok_pages)} "
                f"skipped={len(skipped_pages)} failed={len(error_pages)} "
                f"parsed={len(page_results)} matched={len(matched_results)} "
                f"unmatched={len(unmatched_results)}",
            )

        # Timestamp auf alle matched results stempeln
        crawl_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for result in matched_results:
            result["crawl_timestamp"] = crawl_timestamp

        # Der neue SemanticMatcher wird nur zurückgegeben wenn er frisch erstellt wurde
        new_matcher = (
            semantic_matcher_instance
            if semantic_enabled and semantic_matcher_instance is not None and semantic_matcher_instance is not semantic_matcher
            else None
        )

        return CrawlPipelineResult(
            matched_results=matched_results,
            unmatched_results=unmatched_results,
            pipeline_stats=pipeline_stats,
            semantic_stats=semantic_stats,
            semantic_matcher=new_matcher,
            error="",
        )

    except Exception as exc:
        _log("ERROR", f"Crawling fehlgeschlagen: {type(exc).__name__}: {exc}")
        return CrawlPipelineResult(error=str(exc))
