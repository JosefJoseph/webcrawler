import streamlit as st
import re
from datetime import datetime
from urllib.parse import urlparse

from app.crawler.crawler import crawl_domain
from app.services.crawl_request_service import should_run_crawl
from app.parser.parser import build_page_result
from app.services.keyword_filter import filter_results_by_keywords, parse_keywords
from app.services.path_filter_service import (
    build_common_path_suggestions,
    parse_path_filters,
    split_rows_by_path_filter,
)
from app.services.export_service import (
    build_research_export_frame,
    build_food_csv_rows,
    build_food_json_records,
    build_csv_bytes,
    build_json_bytes,
    build_markdown_bytes,
    build_pdf_bytes,
)
from app.services.result_state_service import (
    compute_removed_count,
    remove_excluded_results,
    remove_result_by_url,
    restore_original_results,
)

# --- Session state initialization ---
_SESSION_DEFAULTS = {
    "file_format": "CSV",
    "crawling": False,
    "crawling_completed": False,
    "crawl_result_rows": [],
    "crawl_result_rows_all": [],
    "original_crawl_result_rows": [],
    "crawl_debug_logs": [],
    "crawl_error": "",
    "last_crawl_signature": None,
    "crawl_requested": False,
    "crawl_request_id": None,
    "last_processed_crawl_request_id": None,
    "crawl_payload": None,
    "path_filter_value": "",
    "path_filter_reset_requested": False,
    "path_filter_suggestions": [],
    "last_filter_signature": None,
    "last_export_signature": None,
    "keep_raw_text_json": False,
    "removed_result_urls": [],
    "last_export_ui_signature": None,
    "exporting": False,
    "prepared_export_payload": None,
    "crawl_semantic_stats": None,
    "crawl_pipeline_stats": None,
}
for _k, _v in _SESSION_DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v


def add_debug_log(level: str, message: str, **fields) -> None:
    """Append a structured log line to the debug console.

    Format: [HH:MM:SS.mmm] [LEVEL] message key=value ...
    Supports optional **fields for machine-readable key=value pairs appended
    after the message, enabling copy-paste-friendly structured output.
    """
    if "crawl_debug_logs" not in st.session_state:
        st.session_state.crawl_debug_logs = []
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    field_str = (" " + " ".join(f"{k}={v}" for k, v in fields.items())) if fields else ""
    st.session_state.crawl_debug_logs.append(
        f"[{timestamp}] [{level}] {message}{field_str}"
    )


def clear_debug_logs() -> None:
    st.session_state.crawl_debug_logs = []


def _render_debug_console() -> None:
    """Render the debug console as a copy-friendly text area with controls."""
    st.subheader("Debug-Konsole")

    debug_log_lines = st.session_state.get("crawl_debug_logs", [])
    log_count = len(debug_log_lines)

    ctrl_col1, ctrl_col2 = st.columns([3, 1])
    with ctrl_col1:
        st.caption(f"{log_count} Log-Einträge")
    with ctrl_col2:
        if st.button(
            "🗑️ Logs leeren", disabled=log_count == 0, key="clear_debug_logs_btn"
        ):
            clear_debug_logs()
            add_debug_log("INFO", "Debug-Logs wurden geleert.")
            st.rerun()

    with st.expander("Debug Logs", expanded=False):
        if not debug_log_lines:
            st.info("Noch keine Logs vorhanden.")
        else:
            st.text_area(
                "Logs (kopierbar)",
                value="\n".join(debug_log_lines),
                height=400,
                label_visibility="collapsed",
                key="debug_log_text_area",
            )


def _highlight_terms(text: str, terms: list[str]) -> str:
    if not text:
        return ""
    highlighted = text
    for term in sorted({term for term in terms if term}, key=len, reverse=True):
        pattern = re.compile(re.escape(term), re.IGNORECASE)
        highlighted = pattern.sub(lambda match: f"<mark>{match.group(0)}</mark>", highlighted)
    return highlighted


# --- Page layout ---
if st.button("⬅ Back"):
    st.switch_page("pages/mainPage.py")

st.title("Webcrawler - Ergebnisse")
st.divider()

st.subheader("Crawl-Status")
statusText_placeholder = st.empty()


def handle_crawl_progress(
    message: str, visited_count: int = 0, total_pages: int = 0, current_url: str = ""
) -> None:
    statusText_placeholder.info(
        f"{visited_count}/{total_pages} Seiten gecrawled. Aktuelle Seite: {current_url}"
    )
    if current_url:
        add_debug_log(
            "CRAWL",
            f"attempt url={current_url} visited={visited_count}/{total_pages}",
        )


def handle_crawl_event(stage: str, message: str = "", **fields) -> None:
    add_debug_log(stage, message, **fields)


# --- Read crawl parameters from payload (snapshot), fall back to session_state ---
payload: dict = st.session_state.get("crawl_payload") or {}
request_id = payload.get("request_id")
last_processed_id = st.session_state.get("last_processed_crawl_request_id")

website = str(payload.get("website") or st.session_state.get("website", "")).strip()
raw_keywords = str(payload.get("keywords") or st.session_state.get("infotosearch", "")).strip()
max_pages = int(payload.get("max_pages") or st.session_state.get("max_pages", 20))
max_depth = int(payload.get("max_depth") or st.session_state.get("max_depth", 2))
semantic_search_enabled = bool(payload.get("semantic_search", st.session_state.get("semantic_search", False)))
semantic_threshold = float(payload.get("semantic_threshold", st.session_state.get("semantic_threshold", 0.30)))
semantic_threshold = max(0.0, min(1.0, semantic_threshold))
keywords = parse_keywords(raw_keywords)

_run_crawl = should_run_crawl(payload, last_processed_id)

# --- State diagnostics (always logged) ---
add_debug_log(
    "STATE",
    "crawl_page_loaded",
    request_id=request_id or "(none)",
    already_processed=(request_id is not None and request_id == last_processed_id),
    crawling=st.session_state.get("crawling"),
    crawling_completed=st.session_state.get("crawling_completed"),
    website=website or "(empty)",
)

_no_run_status_message = ""

if not website:
    _no_run_status_message = "Keine Website gesetzt. Gehe zurück zur Suche."
    add_debug_log("STATE", "No website in crawl payload/session state.")
elif _run_crawl:
    statusText_placeholder.info(f"0/{max_pages} Seiten gecrawled. Aktuelle Seite: ...")
    clear_debug_logs()
    add_debug_log("INFO", "━━━ Neuer Crawl gestartet ━━━")
    add_debug_log("STATE", f"request_id={request_id}")
    add_debug_log("INFO", f"Ziel-URL: {website}")
    add_debug_log("INFO", f'Keywords: {", ".join(keywords) if keywords else "(keine)"}')
    add_debug_log(
        "STATE",
        f"semantic payload_enabled={semantic_search_enabled} "
        f"payload_threshold={semantic_threshold:.2f} "
        f"session_enabled={st.session_state.get('semantic_search', '(nicht gesetzt)')} "
        f"session_threshold={st.session_state.get('semantic_threshold', '(nicht gesetzt)')}",
    )

    from app.crawler.crawler import normalize_url as _normalize_url
    _normalized_start = _normalize_url(website)

    add_debug_log(
        "CONFIG",
        f"start_url={website} normalized={_normalized_start} "
        f"max_pages={max_pages} max_depth={max_depth} "
        f"semantic_enabled={semantic_search_enabled} "
        f"semantic_threshold={semantic_threshold:.2f} "
    )
    add_debug_log(
        "INFO",
        f"Crawl started with semantic matching {'enabled' if semantic_search_enabled else 'disabled'}, "
        f"threshold={semantic_threshold:.2f}",
    )

    try:
        with st.spinner("Seiten werden gecrawlt und ausgewertet..."):
            crawled_pages = crawl_domain(
                start_url=website,
                max_pages=max_pages,
                max_depth=max_depth,
                use_playwright=True,
                on_progress=handle_crawl_progress,
                on_event=handle_crawl_event,
            )

            # --- Crawl result classification ---
            ok_pages = [p for p in crawled_pages if p.get("status") == "ok"]
            skipped_pages = [p for p in crawled_pages if p.get("status") == "skipped"]
            error_pages = [p for p in crawled_pages if p.get("status") == "error"]

            add_debug_log("DEBUG", f"Gecrawlte Seiten: {len(crawled_pages)}")
            add_debug_log(
                "CRAWL",
                f"attempted={len(crawled_pages)} ok={len(ok_pages)} "
                f"skipped={len(skipped_pages)} failed={len(error_pages)}",
            )

            skipped_reasons = {}
            for p in skipped_pages:
                reason = p.get("error", "skipped")
                skipped_reasons[reason] = skipped_reasons.get(reason, 0) + 1
                add_debug_log(
                    "SKIP",
                    f"url={p['url']} reason={reason}",
                )
                add_debug_log(
                    "FETCH",
                    f"success=false url={p['url']} status=skipped reason={reason}",
                )
            for p in error_pages:
                add_debug_log(
                    "FETCH",
                    f"success=false url={p['url']} error={p.get('error', '')}",
                )
            for p in ok_pages:
                html_chars = len(p.get("html", ""))
                links = len(p.get("links", []))
                add_debug_log(
                    "FETCH",
                    f"success=true url={p['url']} final_url={p.get('final_url', p.get('url', ''))} "
                    f"status_code={p.get('status_code', 'n/a') or 'n/a'} "
                    f"content_type={p.get('content_type', 'n/a') or 'n/a'} "
                    f"html_chars={html_chars} links={links} method={p.get('fetch_method', '')}",
                )

            if skipped_reasons:
                add_debug_log(
                    "DEBUG",
                    f"Übersprungene Seiten nach Grund: {skipped_reasons}",
                )

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

                add_debug_log(
                    "PARSE",
                    f"url={page_result.get('url', '')} text_chars={text_len} "
                    f"text_blocks={blocks} passage_blocks={passages} "
                    f'snippet="{snippet}"',
                )
                add_debug_log(
                    "DEBUG",
                    (
                        f'Parser-Extraktion für {page_result.get("url", "")}: '
                        f'Titel="{page_result.get("title", "")}", '
                        f'text_blocks={blocks}, '
                        f'attribute_texts={len(page_result.get("attribute_texts", []))}'
                    ),
                )

            add_debug_log(
                "DEBUG",
                f"Ergebnisanzahl vor Keyword-Filter: {len(page_results)} | "
                f"Seiten mit Text: {pages_with_text_count} | "
                f"Gesamtzeichen: {total_text_chars}",
            )

            # --- Store pipeline stats ---
            st.session_state.crawl_pipeline_stats = {
                "attempted": len(crawled_pages),
                "ok": len(ok_pages),
                "skipped": len(skipped_pages),
                "failed": len(error_pages),
                "parsed": len(page_results),
                "pages_with_text": pages_with_text_count,
                "total_chars": total_text_chars,
            }

            # --- Keyword match stage ---
            add_debug_log(
                "MATCH",
                f"input_pages={len(page_results)} keywords={keywords}",
            )

            # --- Semantic stage ---
            semantic_matcher_instance = None
            model_ready = False
            model_error = None

            if semantic_search_enabled:
                from app.services.semantic_matcher import SemanticMatcher
                add_debug_log(
                    "INFO",
                    f"Semantische Suche aktiviert, Schwellenwert={semantic_threshold}",
                )
                add_debug_log("INFO", "Lade Semantic-Modell...")
                with st.spinner("Semantic matching (Beta): Modell wird geladen..."):
                    add_debug_log(
                        "DEBUG",
                        f"[Threshold] SemanticMatcher wird mit threshold={semantic_threshold:.2f} erstellt",
                    )
                    matcher = SemanticMatcher(threshold=semantic_threshold)
                    success, msg = matcher.initialize()
                    if success:
                        semantic_matcher_instance = matcher
                        st.session_state["semantic_matcher_instance"] = matcher
                        model_ready = True
                        add_debug_log("INFO", f"Semantic-Backend bereit: {msg}")
                        add_debug_log(
                            "INFO",
                            f"Semantic backend using device: "
                            f"{semantic_matcher_instance.device or 'cpu'}, "
                            f"threshold={matcher.threshold:.2f}",
                        )
                        add_debug_log(
                            "SEMANTIC",
                            f"ready=true device={semantic_matcher_instance.device or 'cpu'} "
                            f"threshold={matcher.threshold:.2f}",
                        )
                    else:
                        model_error = msg
                        add_debug_log(
                            "WARNING",
                            f"Semantic model unavailable, falling back to keyword filtering: {msg}",
                        )
                        add_debug_log("SEMANTIC", f'ready=false error="{msg}"')
            else:
                st.session_state.pop("semantic_matcher_instance", None)
                add_debug_log("SEMANTIC", "ready=false enabled=false")

            matched_results, unmatched_results = filter_results_by_keywords(
                page_results,
                keywords,
                semantic_matcher=semantic_matcher_instance,
                debug_logger=add_debug_log,
            )
            add_debug_log(
                "DEBUG", f"Ergebnisanzahl nach Keyword-Filter: {len(matched_results)}"
            )

            # --- RESULT log ---
            add_debug_log(
                "RESULT",
                f"matched={len(matched_results)} unmatched={len(unmatched_results)} "
                f"skipped={len(skipped_pages)} failed={len(error_pages)}",
            )

            # Compute semantic stats for zero-results diagnostic
            all_score_items = matched_results + unmatched_results
            all_scores = [
                r["semantic_score"]
                for r in all_score_items
                if r.get("semantic_score") is not None
            ]
            st.session_state.crawl_semantic_stats = {
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
                "semantic_enabled": semantic_search_enabled,
                "model_ready": model_ready if semantic_search_enabled else None,
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
                else:
                    _no_results_reason = "Keywords did not match any extracted text"
                    _next_action = "Try different keywords or lower the semantic threshold"

                add_debug_log(
                    "SUMMARY",
                    f"attempted={len(crawled_pages)} fetched_ok={len(ok_pages)} "
                    f"skipped={len(skipped_pages)} failed={len(error_pages)} "
                    f"parsed={len(page_results)} matched=0 "
                    f"unmatched={len(unmatched_results)}",
                )
                add_debug_log("SUMMARY", f'no_results_reason="{_no_results_reason}"')
                add_debug_log("SUMMARY", f'next_action="{_next_action}"')
            else:
                add_debug_log(
                    "SUMMARY",
                    f"attempted={len(crawled_pages)} fetched_ok={len(ok_pages)} "
                    f"skipped={len(skipped_pages)} failed={len(error_pages)} "
                    f"parsed={len(page_results)} matched={len(matched_results)} "
                    f"unmatched={len(unmatched_results)}",
                )

            crawl_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for result in matched_results:
                result["crawl_timestamp"] = crawl_timestamp

        st.session_state.original_crawl_result_rows = matched_results
        st.session_state.crawl_result_rows_all = matched_results
        st.session_state.crawl_result_rows = matched_results
        st.session_state.path_filter_suggestions = build_common_path_suggestions(
            matched_results
        )
        st.session_state.path_filter_value = ""
        st.session_state.removed_result_urls = []
        st.session_state.keep_raw_text_json = False
        st.session_state.crawl_error = ""
        st.session_state.crawling_completed = True
        st.session_state.crawling = False
        st.session_state.last_processed_crawl_request_id = request_id
        st.session_state.crawl_requested = False
        st.session_state.last_filter_signature = None
        st.session_state.last_export_signature = None
        st.session_state.last_export_ui_signature = None
        st.session_state.prepared_export_payload = None

        add_debug_log("INFO", f"Seiten mit Keyword-Treffern: {len(matched_results)}")
        add_debug_log("INFO", f"Seiten ohne Treffer: {len(unmatched_results)}")
        add_debug_log(
            "DEBUG",
            f"Häufige Pfad-Vorschläge: {st.session_state.path_filter_suggestions}",
        )
        for mr in matched_results:
            kw_list = mr.get("keyword_matches", [])
            matched_by = mr.get("matched_by") or "-"
            semantic_score = mr.get("semantic_score")
            semantic_score_text = (
                f"{semantic_score:.2f}"
                if isinstance(semantic_score, (float, int))
                else "-"
            )
            add_debug_log(
                "DEBUG",
                (
                    f'Treffer: {mr.get("url", "")} — matched_by={matched_by}, '
                    f'keywords={", ".join(kw_list) if kw_list else "(keine)"}, '
                    f"semantic_score={semantic_score_text}, "
                    f'blocks={mr.get("matched_block_count", 0)}'
                ),
            )
        add_debug_log("INFO", "━━━ Crawling erfolgreich abgeschlossen ━━━")

    except Exception as exc:
        st.session_state.crawl_result_rows = []
        st.session_state.crawl_result_rows_all = []
        st.session_state.crawling_completed = False
        st.session_state.crawling = False
        st.session_state.crawl_error = str(exc)
        st.session_state.last_crawl_signature = None
        st.session_state.crawl_semantic_stats = None
        st.session_state.crawl_pipeline_stats = None
        if request_id:
            st.session_state.last_processed_crawl_request_id = request_id
        st.session_state.crawl_requested = False
        add_debug_log("ERROR", f"Crawling fehlgeschlagen: {type(exc).__name__}: {exc}")
else:
    already_processed = bool(request_id and request_id == last_processed_id)
    if st.session_state.get("crawling_completed"):
        _no_run_status_message = "Crawl bereits abgeschlossen. Zeige gespeicherte Ergebnisse."
        _no_run_reason = "Crawl request already processed; showing cached results."
    elif not request_id:
        _no_run_status_message = "Kein neuer Crawl-Request vorhanden. Bitte auf der Suchseite Crawling starten."
        _no_run_reason = "No crawl request found. Return to MainPage and press Crawling starten."
    elif already_processed:
        _no_run_status_message = "Dieser Crawl-Request wurde bereits verarbeitet. Zeige gespeicherte Ergebnisse."
        _no_run_reason = "Crawl request already processed; showing cached results."
    else:
        _no_run_status_message = "Kein Crawling aktiv. Bitte auf der Suchseite Crawling starten."
        _no_run_reason = "No active crawl branch matched."

    _diag_sig = (request_id or "", last_processed_id or "", _no_run_status_message)
    if st.session_state.get("last_crawl_state_diag_signature") != _diag_sig:
        add_debug_log("STATE", _no_run_reason)
        st.session_state.last_crawl_state_diag_signature = _diag_sig

if st.session_state.crawl_error:
    statusText_placeholder.error(
        f"Crawling fehlgeschlagen: {st.session_state.crawl_error}"
    )
elif st.session_state.crawling_completed:
    statusText_placeholder.success("Crawling abgeschlossen!")
elif _no_run_status_message:
    statusText_placeholder.info(_no_run_status_message)
else:
    statusText_placeholder.info("Kein Crawling aktiv. Bitte auf der Suchseite Crawling starten.")
st.divider()

st.subheader("Pfadfilter")
if st.session_state.get("path_filter_reset_requested", False):
    st.session_state.path_filter_value = ""
    st.session_state.path_filter_reset_requested = False

st.text_input(
    "Pfadfilter",
    key="path_filter_value",
    placeholder="z.B. /food-details/.../nutrients, /food-details/.../ingredients",
)
st.caption(
    'Mit Komma können mehrere Filter angegeben werden. Verwenden Sie "..." als Platzhalter.'
)

all_rows = st.session_state.get("crawl_result_rows_all", [])
raw_path_filter = st.session_state.get("path_filter_value", "").strip()
active_path_filters = parse_path_filters(raw_path_filter)

filter_signature = (
    tuple(row.get("url", "") for row in all_rows),
    raw_path_filter,
)

excluded_rows = []
filtered_rows = all_rows

if st.session_state.get("last_filter_signature") != filter_signature:
    add_debug_log("DEBUG", f'Aktiver Pfadfilter: {raw_path_filter or "(leer)"}')
    add_debug_log(
        "DEBUG", f"Gesamtergebnisse in aktueller Arbeitsmenge: {len(all_rows)}"
    )
    if active_path_filters:
        add_debug_log("INFO", f"Wende Pfadfilter an: {active_path_filters}")
        filtered_rows, excluded_rows = split_rows_by_path_filter(
            all_rows,
            active_path_filters,
        )
        add_debug_log(
            "DEBUG", f"Sichtbare Ergebnisse nach Filter: {len(filtered_rows)}"
        )
        add_debug_log("DEBUG", f"Ausgefilterte Ergebnisse: {len(excluded_rows)}")
        add_debug_log(
            "INFO",
            f'Pfadfilter angewendet: {", ".join(active_path_filters)}, '
            f"{len(filtered_rows)} Einträge sichtbar",
        )
    else:
        filtered_rows = all_rows
        add_debug_log("INFO", "Pfadfilter leer: alle Ergebnisse sichtbar")
        add_debug_log(
            "DEBUG", f"Sichtbare Ergebnisse nach Filter: {len(filtered_rows)}"
        )

    st.session_state.crawl_result_rows = filtered_rows
    st.session_state.last_filter_signature = filter_signature
else:
    if active_path_filters:
        filtered_rows, excluded_rows = split_rows_by_path_filter(
            all_rows,
            active_path_filters,
        )

path_suggestions = st.session_state.get("path_filter_suggestions", [])
if path_suggestions:
    st.write("Häufige Pfad-Vorschläge: " + ", ".join(path_suggestions))

st.info(
    "Hinweis: Entfernt alle Ergebnisse aus der aktuellen Liste, die nicht zum aktiven Pfadfilter passen."
)

action_col1, action_col2, action_col3 = st.columns(3)

with action_col1:
    disable_remove_filtered = not active_path_filters or len(excluded_rows) == 0
    if st.button(
        f"Ausgefilterte Ergebnisse entfernen ({len(excluded_rows)})",
        disabled=disable_remove_filtered,
        help="Entfernt alle aktuell ausgefilterten Ergebnisse dauerhaft aus der aktuellen Arbeitsmenge.",
    ):
        new_rows, removed_count_now = remove_excluded_results(all_rows, filtered_rows)
        kept_urls = {r.get("url", "") for r in new_rows}
        removed_urls_now = [
            row.get("url", "") for row in all_rows if row.get("url", "") not in kept_urls
        ]
        st.session_state.crawl_result_rows_all = new_rows
        st.session_state.crawl_result_rows = new_rows
        st.session_state.removed_result_urls = list(
            dict.fromkeys(
                st.session_state.get("removed_result_urls", []) + removed_urls_now
            )
        )
        st.session_state.last_filter_signature = None
        st.session_state.last_export_signature = None
        st.session_state.prepared_export_payload = None
        add_debug_log("INFO", f"Ausgefilterte Ergebnisse entfernt: {removed_count_now}")
        add_debug_log("DEBUG", f"Entfernte URLs: {removed_urls_now}")
        add_debug_log("INFO", f"Aktuell sichtbare Ergebnisse: {len(new_rows)}")
        st.rerun()

with action_col2:
    can_reset = len(st.session_state.get("original_crawl_result_rows", [])) > 0
    if st.button(
        "Standardzustand wiederherstellen",
        disabled=not can_reset,
        help="Stellt die ursprünglichen Crawl-Ergebnisse wieder her und setzt manuelle Änderungen zurück.",
    ):
        restored_rows = restore_original_results(
            st.session_state.get("original_crawl_result_rows", [])
        )
        st.session_state.crawl_result_rows_all = restored_rows
        st.session_state.crawl_result_rows = restored_rows
        st.session_state.path_filter_reset_requested = True
        st.session_state.removed_result_urls = []
        st.session_state.last_filter_signature = None
        st.session_state.last_export_signature = None
        st.session_state.prepared_export_payload = None
        add_debug_log("INFO", f"Ergebnisse zurückgesetzt auf {len(restored_rows)} Einträge")
        add_debug_log("DEBUG", "Pfadfilter zurückgesetzt, entfernte URLs-Liste geleert")
        st.rerun()

_render_debug_console()
st.divider()

st.subheader("Ergebnisliste")
rows = st.session_state.get("crawl_result_rows", [])
total_rows = st.session_state.get("crawl_result_rows_all", [])
original_rows = st.session_state.get("original_crawl_result_rows", [])
removed_count = compute_removed_count(original_rows, total_rows)
st.write(
    f"Gesamt (Original): {len(original_rows)} | Aktuelle Arbeitsmenge: {len(total_rows)} "
    f"| Sichtbar: {len(rows)} | Entfernt: {removed_count}"
)
_sem_stats = st.session_state.get("crawl_semantic_stats")
if _sem_stats:
    kw_n = _sem_stats.get("keyword_count", 0)
    sem_n = _sem_stats.get("semantic_count", 0)
    both_n = _sem_stats.get("both_count", 0)
    max_s = _sem_stats.get("max_score")
    score_parts = []
    if kw_n:
        score_parts.append(f"Keyword: {kw_n}")
    if sem_n:
        score_parts.append(f"Semantic: {sem_n}")
    if both_n:
        score_parts.append(f"Beide: {both_n}")
    if max_s is not None:
        score_parts.append(f"Höchster Score: {max_s:.2f}")
    if score_parts:
        st.caption(" | ".join(score_parts))
st.caption(
    'Hinweis: "Entfernen" wirkt nur auf die aktuelle Ergebnisliste in dieser Session.'
)


def _render_matched_by_badge(row: dict, threshold: float | None = None) -> None:
    """Render match type badge plus separate keyword and semantic detail lines."""
    from app.services.result_formatting_service import (
        format_match_type,
        format_keyword_matches,
        format_semantic_line,
    )

    matched_by = row.get("matched_by") or ""
    label = format_match_type(matched_by)

    if matched_by == "semantic":
        badge_css = (
            "border:1px solid #facc15;background:rgba(250,204,21,0.12);color:#b45309;"
        )
    elif matched_by == "keyword+semantic":
        badge_css = (
            "border:1px solid #60a5fa;background:rgba(96,165,250,0.10);color:#1d4ed8;"
        )
    else:
        badge_css = (
            "border:1px solid #4ade80;background:rgba(74,222,128,0.10);color:#15803d;"
        )

    st.markdown(
        f"<span style='display:inline-block;{badge_css}border-radius:6px;"
        f"padding:0.15rem 0.55rem;font-size:0.82rem;font-weight:600;'>{label}</span>",
        unsafe_allow_html=True,
    )
    st.caption(f"Keyword-Treffer: {format_keyword_matches(row)}")
    st.caption(format_semantic_line(row, threshold))


def _render_zero_results_diagnostic(
    semantic_stats, pipeline_stats, keywords, semantic_enabled, semantic_threshold
):
    """Render a helpful diagnostic panel when no results were found."""
    st.warning("Keine Treffer gefunden.")
    if not st.session_state.get("crawling_completed"):
        return
    with st.expander("Diagnose: Warum keine Ergebnisse?", expanded=True):
        kw_str = ", ".join(keywords) if keywords else "(keine)"
        st.markdown(f"**Aktive Keywords:** `{kw_str}`")

        # --- Pipeline stats ---
        if pipeline_stats:
            attempted = pipeline_stats.get("attempted", 0)
            ok = pipeline_stats.get("ok", 0)
            skipped = pipeline_stats.get("skipped", 0)
            failed = pipeline_stats.get("failed", 0)
            pages_with_text = pipeline_stats.get("pages_with_text", 0)
            total_chars = pipeline_stats.get("total_chars", 0)

            st.markdown("**Crawl-Pipeline:**")
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Versucht", attempted)
                st.metric("Erfolgreich abgerufen", ok)
            with col2:
                st.metric("Übersprungen", skipped)
                st.metric("Fehlgeschlagen", failed)
            with col3:
                st.metric("Seiten mit extrahiertem Text", pages_with_text)
                st.metric("Extrahierte Zeichen gesamt", total_chars)

            if skipped > 0 and ok == 0:
                st.error(
                    f"⚠️ Alle {skipped} URL(s) wurden übersprungen. "
                    "Details stehen in der Debug-Konsole."
                )
            elif ok > 0 and pages_with_text > 0:
                st.info(
                    f"Seiten wurden abgerufen und Text wurde extrahiert "
                    f"({total_chars} Zeichen gesamt). "
                    "Die Keywords haben jedoch keinen passenden Textblock gefunden."
                )

        # --- Semantic model status ---
        if semantic_enabled and semantic_stats:
            model_ready = semantic_stats.get("model_ready")
            model_error = semantic_stats.get("model_error")
            threshold = semantic_stats.get("threshold", semantic_threshold)
            st.markdown(f"**Semantic Threshold:** `{threshold:.2f}`")

            if model_ready is False and model_error:
                st.error(f"Semantic model not ready: {model_error}")
            elif model_ready:
                max_s = semantic_stats.get("max_score")
                if max_s is not None:
                    st.markdown(
                        f"**Höchster Semantic Score (über alle Seiten):** `{max_s:.2f}`"
                    )
                    if max_s < threshold:
                        st.markdown(
                            f"Der beste gefundene Score (`{max_s:.2f}`) liegt **unter** "
                            f"dem Threshold (`{threshold:.2f}`). "
                            "Kein Ergebnis konnte aufgenommen werden."
                        )
                        if max_s < 0.25:
                            st.error(
                                "Alle Scores sind ungewöhnlich niedrig (< 0.25). "
                                "Mögliche Ursache: Das Modell ist multilingual, aber die Seite verwendet "
                                "eine andere Sprache/Fachsprache als der Suchbegriff, "
                                "oder der Text enthält hauptsächlich Navigation/UI-Elemente."
                            )
                        else:
                            st.info(
                                f"Probiere den Threshold auf "
                                f"`{max(0.0, max_s - 0.05):.2f}` zu senken, "
                                "um mindestens die beste Übereinstimmung zu sehen."
                            )
                else:
                    st.info(
                        "Kein Semantic Score berechnet. "
                        "Keine Seiten wurden semantisch ausgewertet."
                    )
            else:
                st.info(
                    "Kein Semantic Score berechnet. "
                    "Entweder wurde kein Keyword angegeben oder das Modell ist nicht bereit."
                )
        elif not semantic_enabled:
            st.info(
                "Semantic Matching ist deaktiviert. "
                "Nur exakte Keyword-Treffer werden gefunden."
            )

        # --- Suggestions ---
        st.markdown("**Vorschläge:**")
        suggestions = []
        _pl = pipeline_stats or {}
        suggestions += [
            "Keyword ändern oder andere Schreibweise versuchen",
            "Threshold senken (z.B. auf 0.20–0.30 für breitere Treffer)",
            "max_pages oder max_depth erhöhen",
        ]
        if semantic_enabled:
            suggestions.append(
                "Für englische Keywords auf deutschen Seiten: Das Modell "
                "'paraphrase-multilingual-MiniLM-L12-v2' "
                "unterstützt Cross-Language-Matching, aber Scores sind oft niedriger "
                "als bei einsprachigen Suchen"
            )
        for s in suggestions:
            st.markdown(f"- {s}")


if not rows:
    _render_zero_results_diagnostic(
        st.session_state.get("crawl_semantic_stats"),
        st.session_state.get("crawl_pipeline_stats"),
        keywords,
        semantic_search_enabled,
        semantic_threshold,
    )
else:
    with st.expander(f"Alle Treffer ({len(rows)} URLs)", expanded=True):
        st.write(f"**Gefundene URLs mit Treffern:** {len(rows)}")
        st.divider()

        for idx, row in enumerate(rows, 1):
            url = row.get("url", "")
            title = row.get("title", "") or url
            matched_blocks = row.get("matched_blocks", [])
            matched_by = row.get("matched_by")
            semantic_score = row.get("semantic_score")

            st.markdown(
                f"<div style='font-size:0.78rem; color:#6b7280; margin:0.2rem 0 0.35rem 0;'>"
                f"{url}</div>",
                unsafe_allow_html=True,
            )

            with st.expander(
                f"**{idx}. {title}** ({len(matched_blocks)} Trefferblöcke)"
            ):
                _render_matched_by_badge(row, semantic_threshold)

                act_col1, act_col2 = st.columns([1, 3])
                with act_col1:
                    if st.button(
                        "Entfernen",
                        key=f"remove_result_{idx}_{url}",
                        help="Entfernt dieses Ergebnis aus Anzeige und Export der aktuellen Session.",
                    ):
                        new_all_rows = remove_result_by_url(
                            st.session_state.get("crawl_result_rows_all", []),
                            url,
                        )
                        st.session_state.crawl_result_rows_all = new_all_rows
                        st.session_state.removed_result_urls = list(
                            dict.fromkeys(
                                st.session_state.get("removed_result_urls", []) + [url]
                            )
                        )
                        st.session_state.last_filter_signature = None
                        st.session_state.last_export_signature = None
                        st.session_state.prepared_export_payload = None
                        add_debug_log("INFO", f"Ergebnis entfernt: {url}")
                        add_debug_log(
                            "DEBUG",
                            f"Verbleibende Ergebnisse in Arbeitsmenge: {len(new_all_rows)}",
                        )
                        add_debug_log(
                            "DEBUG",
                            f"Bisher entfernte URLs gesamt: "
                            f"{len(st.session_state.removed_result_urls)}",
                        )
                        st.rerun()

                st.markdown(f"**URL:** `{url}`")
                st.markdown(
                    f"**Tiefe:** {row.get('depth', 0)} | **Status:** {row.get('status', '')}"
                )

                st.divider()

                if not matched_blocks:
                    st.info("Keine Trefferblöcke gefunden.")
                else:
                    for block_idx, block in enumerate(matched_blocks, 1):
                        st.markdown(f"**Block {block_idx}:**")
                        st.markdown(
                            f"- **Quelle:** `{block.get('source_type', '')}` "
                            f"| **Tag:** `{block.get('tag', '')}`"
                        )
                        st.markdown(
                            f"- **Keywords:** {', '.join(block.get('keywords', []))}"
                        )
                        st.markdown(f"- **Vorkommen:** {block.get('match_count', 0)}")

                        block_text = block.get("text", "")
                        highlighted_text = _highlight_terms(
                            block_text,
                            block.get("keywords", []) + row.get("keyword_matches", []),
                        )
                        st.markdown("**Textblock:**")
                        if matched_by in {"semantic", "keyword+semantic"}:
                            st.caption("Semantik-Beta: Trefferkontext hervorgehoben")
                        st.markdown(
                            f"> {highlighted_text or block_text}",
                            unsafe_allow_html=True,
                        )

                        if block_idx < len(matched_blocks):
                            st.divider()
st.divider()

st.subheader("Exportsektion")


def download_format():
    st.session_state.file_format = st.radio(
        "Download-Format",
        ["CSV", "JSON", "PDF", "MD"],
        key="format_radio",
        help="Wählen Sie das gewünschte Exportformat für die aktuell sichtbaren Ergebnisse.",
    )


download_format()

if st.session_state.file_format == "JSON":
    st.checkbox(
        "Rohtext im JSON behalten",
        key="keep_raw_text_json",
        help="Falls aktiviert, wird zusätzlicher Rohtext mit exportiert. Die Datei kann dadurch deutlich größer werden.",
    )

export_ui_signature = (
    st.session_state.file_format,
    st.session_state.keep_raw_text_json,
)
if st.session_state.get("last_export_ui_signature") != export_ui_signature:
    add_debug_log("INFO", f"Exportformat gewählt: {st.session_state.file_format}")
    if st.session_state.file_format == "JSON":
        add_debug_log(
            "DEBUG", f"JSON raw_text aktiviert: {st.session_state.keep_raw_text_json}"
        )
    st.session_state.last_export_ui_signature = export_ui_signature

rows = st.session_state.get("crawl_result_rows", [])
current_export_signature = (
    tuple(row.get("url", "") for row in rows),
    st.session_state.file_format,
    st.session_state.keep_raw_text_json,
)
prepared_payload = st.session_state.get("prepared_export_payload")
if prepared_payload and prepared_payload.get("signature") != current_export_signature:
    st.session_state.prepared_export_payload = None
    prepared_payload = None
    add_debug_log(
        "INFO", "Export-Cache invalidiert: Ergebnisse oder Format wurden geändert"
    )

if not rows:
    if st.session_state.get("last_export_signature") != (
        "empty",
        st.session_state.file_format,
    ):
        add_debug_log("WARNING", "Keine Ergebnisse zum Exportieren vorhanden.")
        st.session_state.last_export_signature = (
            "empty",
            st.session_state.file_format,
        )
    st.session_state.prepared_export_payload = None
    st.info("Keine Ergebnisse zum Exportieren vorhanden.")
else:
    parsed_domain = urlparse(st.session_state.get("website", "")).netloc
    domain = parsed_domain or "unknown"
    fmt = st.session_state.file_format

    prepare_col, download_col = st.columns([1, 2])
    with prepare_col:
        if st.button(
            "Export vorbereiten",
            disabled=st.session_state.get("exporting", False),
            help="Erzeugt den Export aus den aktuell sichtbaren Ergebnissen.",
        ):
            st.session_state.exporting = True
            try:
                add_debug_log(
                    "INFO",
                    f"Export started: format={fmt}, visible_results={len(rows)}",
                )
                with st.spinner("Export wird vorbereitet..."):
                    export_progress = st.progress(0, text="Normalisiere Ergebnisse...")
                    structured_df, _ = build_food_csv_rows(rows, debug_logger=add_debug_log)
                    research_df = build_research_export_frame(rows)
                    crawl_settings = {
                        "Semantic matching": (
                            "enabled" if semantic_search_enabled else "disabled"
                        ),
                        "Semantic threshold": f"{semantic_threshold:.2f}",
                        "Path filter": raw_path_filter or "(none)",
                        "Visible results": len(rows),
                    }

                    export_progress.progress(35, text="Erzeuge Ausgabeformat...")
                    if fmt == "CSV":
                        file_bytes = build_csv_bytes(structured_df)
                        mime = "text/csv"
                        suggested_ext = "csv"
                    elif fmt == "JSON":
                        json_records, _ = build_food_json_records(
                            rows,
                            include_raw_text=st.session_state.get(
                                "keep_raw_text_json", False
                            ),
                            debug_logger=add_debug_log,
                        )
                        file_bytes = build_json_bytes(json_records)
                        mime = "application/json"
                        suggested_ext = "json"
                    elif fmt == "PDF":
                        file_bytes = build_pdf_bytes(research_df, domain)
                        mime = "application/pdf"
                        suggested_ext = "pdf"
                    else:
                        file_bytes = build_markdown_bytes(
                            research_df, domain, crawl_settings
                        )
                        mime = "text/markdown"
                        suggested_ext = "md"

                    export_progress.progress(100, text="Export bereit")
                    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                    safe_domain = (
                        domain.replace("https://", "")
                        .replace("http://", "")
                        .replace("/", "_")
                        .replace(".", "_")
                    )
                    file_name = (
                        f"crawl_results_{safe_domain}_{timestamp}.{suggested_ext}"
                    )

                    st.session_state.prepared_export_payload = {
                        "signature": current_export_signature,
                        "fmt": fmt,
                        "file_bytes": file_bytes,
                        "mime": mime,
                        "file_name": file_name,
                    }
                    st.session_state.last_export_signature = current_export_signature
                    add_debug_log(
                        "INFO",
                        f"Export completed: format={fmt}, "
                        f"size_kb={len(file_bytes) / 1024:.1f}",
                    )
            except Exception as e:
                st.session_state.prepared_export_payload = None
                add_debug_log("ERROR", f"Export failed: {type(e).__name__}: {e}")
                st.error(f"Fehler beim Export: {e}")
            finally:
                st.session_state.exporting = False

    with download_col:
        prepared_payload = st.session_state.get("prepared_export_payload")
        if prepared_payload:
            st.download_button(
                label=f"Datei herunterladen ({prepared_payload.get('fmt', fmt).upper()})",
                data=prepared_payload.get("file_bytes", b""),
                file_name=prepared_payload.get(
                    "file_name", f"crawl_results.{fmt.lower()}"
                ),
                mime=prepared_payload.get("mime", "application/octet-stream"),
            )
        else:
            st.caption(
                "Klicken Sie auf „Export vorbereiten“, dann erscheint der Download-Button."
            )

# Versionnummer
st.caption("Webcrawler-UI 2.0")
