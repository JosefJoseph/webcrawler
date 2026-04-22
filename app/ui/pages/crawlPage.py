import streamlit as st
import pandas as pd
import os
import re
from collections import Counter
from urllib.parse import urlparse

from app.crawler.crawler import crawl_domain
from app.parser.parser import build_page_result
from app.services.keyword_filter import filter_results_by_keywords, parse_keywords
from app.services.export_service import (
    build_food_csv_rows,
    build_food_json_records,
    export_to_json,
    export_to_csv,
    export_to_pdf,
    export_to_markdown,
)

if 'file_format' not in st.session_state:
    st.session_state.file_format = 'CSV'
if 'crawling' not in st.session_state:
    st.session_state.crawling = False
if 'crawling_completed' not in st.session_state:
    st.session_state.crawling_completed = False
if 'crawl_result_rows' not in st.session_state:
    st.session_state.crawl_result_rows = []
if 'crawl_result_rows_all' not in st.session_state:
    st.session_state.crawl_result_rows_all = []
if 'original_crawl_result_rows' not in st.session_state:
    st.session_state.original_crawl_result_rows = []
if 'crawl_debug_logs' not in st.session_state:
    st.session_state.crawl_debug_logs = []
if 'crawl_error' not in st.session_state:
    st.session_state.crawl_error = ''
if 'last_crawl_signature' not in st.session_state:
    st.session_state.last_crawl_signature = None
if 'path_filter_value' not in st.session_state:
    st.session_state.path_filter_value = ''
if 'path_filter_reset_requested' not in st.session_state:
    st.session_state.path_filter_reset_requested = False
if 'path_filter_suggestions' not in st.session_state:
    st.session_state.path_filter_suggestions = []
if 'last_filter_signature' not in st.session_state:
    st.session_state.last_filter_signature = None
if 'last_export_signature' not in st.session_state:
    st.session_state.last_export_signature = None
if 'keep_raw_text_json' not in st.session_state:
    st.session_state.keep_raw_text_json = False
if 'removed_result_urls' not in st.session_state:
    st.session_state.removed_result_urls = []
if 'last_export_ui_signature' not in st.session_state:
    st.session_state.last_export_ui_signature = None


def add_debug_log(level: str, message: str):
    if 'crawl_debug_logs' not in st.session_state:
        st.session_state.crawl_debug_logs = []
    st.session_state.crawl_debug_logs.append(f'[{level}] {message}')


def clear_debug_logs():
    st.session_state.crawl_debug_logs = []


def parse_path_filters(raw_filter: str) -> list[str]:
    return [item.strip() for item in raw_filter.split(',') if item.strip()]


def _compile_path_filter_pattern(path_filter: str) -> re.Pattern:
    escaped = re.escape(path_filter)
    wildcard_pattern = escaped.replace(r'\.\.\.', '.*')
    return re.compile(wildcard_pattern, re.IGNORECASE)


def _matches_any_path_filter(path: str, path_filters: list[str]) -> tuple[bool, str]:
    for path_filter in path_filters:
        if _compile_path_filter_pattern(path_filter).search(path):
            return True, path_filter
    return False, ''


def apply_post_crawl_path_filter(rows: list[dict], path_filters: list[str], log_details: bool = False) -> list[dict]:
    if not path_filters:
        return rows

    filtered_rows: list[dict] = []
    for row in rows:
        url = row.get('url', '')
        parsed_path = urlparse(url).path or '/'

        if log_details:
            add_debug_log('DEBUG', f'URL (roh): {url}')
            add_debug_log('DEBUG', f'Geparster Pfad: {parsed_path}')
            add_debug_log('DEBUG', f'Aktive Pfadfilter: {path_filters}')

        is_match, matched_filter = _matches_any_path_filter(parsed_path, path_filters)
        if is_match:
            filtered_rows.append(row)
            if log_details:
                add_debug_log('DEBUG', f'Filter-Treffer: {matched_filter} für {url}')

    return filtered_rows


def build_common_path_suggestions(rows: list[dict], limit: int = 8) -> list[str]:
    path_counter = Counter()

    for row in rows:
        path = urlparse(row.get('url', '')).path.strip('/')
        if not path:
            continue
        segments = [segment for segment in path.split('/') if segment]
        for depth in range(1, min(3, len(segments)) + 1):
            suggestion = '/' + '/'.join(segments[:depth])
            path_counter[suggestion] += 1

    suggestions = [path for path, _count in path_counter.most_common(limit)]
    return suggestions

if st.button('⬅ Back'):
    st.switch_page("pages/mainPage.py")

st.title('Webcrawler - Ergebnisse')
st.divider()

st.subheader('Crawl-Status')
statusText_placeholder = st.empty()

website = st.session_state.get('website', '').strip()
raw_keywords = st.session_state.get('infotosearch', '').strip()
max_pages = int(st.session_state.get('max_pages', 20))
max_depth = int(st.session_state.get('max_depth', 2))
use_playwright = bool(st.session_state.get('use_playwright', False))
keywords = parse_keywords(raw_keywords)

crawl_signature = (website, raw_keywords, max_pages, max_depth, use_playwright)

if not website:
    statusText_placeholder.info('Keine Website gesetzt. Gehe zurück zur Suche.')
elif st.session_state.crawling and st.session_state.last_crawl_signature != crawl_signature:
    statusText_placeholder.info('Crawling läuft...')
    clear_debug_logs()
    add_debug_log('INFO', f'Starte Crawl für Website: {website}')
    add_debug_log('INFO', f'Keywords: {", ".join(keywords) if keywords else "(keine)"}')
    add_debug_log('INFO', f'max_pages={max_pages}, max_depth={max_depth}, use_playwright={use_playwright}')

    try:
        with st.spinner('Seiten werden gecrawlt und ausgewertet...'):
            crawled_pages = crawl_domain(
                start_url=website,
                max_pages=max_pages,
                max_depth=max_depth,
                use_playwright=use_playwright,
            )

            add_debug_log('DEBUG', f'Gecrawlte Seiten: {len(crawled_pages)}')

            page_results = []
            for page in crawled_pages:
                page_result = build_page_result(page)
                page_results.append(page_result)
                add_debug_log(
                    'DEBUG',
                    (
                        f'Parser-Extraktion für {page_result.get("url", "")}: '
                        f'Titel="{page_result.get("title", "")}", '
                        f'text_blocks={len(page_result.get("text_blocks", []))}, '
                        f'attribute_texts={len(page_result.get("attribute_texts", []))}'
                    ),
                )

            add_debug_log('DEBUG', f'Ergebnisanzahl vor Keyword-Filter: {len(page_results)}')
            matched_results, unmatched_results = filter_results_by_keywords(page_results, keywords)
            add_debug_log('DEBUG', f'Ergebnisanzahl nach Keyword-Filter: {len(matched_results)}')

        st.session_state.original_crawl_result_rows = matched_results
        st.session_state.crawl_result_rows_all = matched_results
        st.session_state.crawl_result_rows = matched_results
        st.session_state.path_filter_suggestions = build_common_path_suggestions(matched_results)
        st.session_state.path_filter_value = ''
        st.session_state.removed_result_urls = []
        st.session_state.keep_raw_text_json = False
        st.session_state.crawl_error = ''
        st.session_state.crawling_completed = True
        st.session_state.crawling = False
        st.session_state.last_crawl_signature = crawl_signature
        st.session_state.last_filter_signature = None
        st.session_state.last_export_signature = None
        st.session_state.last_export_ui_signature = None

        add_debug_log('INFO', f'Seiten mit Keyword-Treffern: {len(matched_results)}')
        add_debug_log('INFO', f'Seiten ohne Treffer: {len(unmatched_results)}')
        add_debug_log('DEBUG', f'Häufige Pfad-Vorschläge: {st.session_state.path_filter_suggestions}')
        add_debug_log('INFO', 'Crawling erfolgreich abgeschlossen')

    except Exception as exc:
        st.session_state.crawl_result_rows = []
        st.session_state.crawl_result_rows_all = []
        st.session_state.crawling_completed = False
        st.session_state.crawling = False
        st.session_state.crawl_error = str(exc)
        st.session_state.last_crawl_signature = None
        add_debug_log('ERROR', f'Crawling fehlgeschlagen: {exc}')

if st.session_state.crawl_error:
    statusText_placeholder.error(f'Crawling fehlgeschlagen: {st.session_state.crawl_error}')
elif st.session_state.crawling_completed:
    statusText_placeholder.success('Crawling abgeschlossen!')
else:
    statusText_placeholder.info('Kein Crawling aktiv. Gehe zurück zur Suche.')
st.divider()

st.subheader('Pfadfilter')
if st.session_state.get('path_filter_reset_requested', False):
    st.session_state.path_filter_value = ''
    st.session_state.path_filter_reset_requested = False

st.text_input(
    'Pfadfilter',
    key='path_filter_value',
    placeholder='z.B. /food-details/.../nutrients, /food-details/.../ingredients',
)
st.caption('Mit Komma können mehrere Filter angegeben werden. Verwenden Sie "..." als Platzhalter.')

all_rows = st.session_state.get('crawl_result_rows_all', [])
raw_path_filter = st.session_state.get('path_filter_value', '').strip()
active_path_filters = parse_path_filters(raw_path_filter)

filter_signature = (
    tuple(row.get('url', '') for row in all_rows),
    raw_path_filter,
)

excluded_rows = []
filtered_rows = all_rows

if st.session_state.get('last_filter_signature') != filter_signature:
    add_debug_log('DEBUG', f'Aktiver Pfadfilter: {raw_path_filter or "(leer)"}')
    add_debug_log('DEBUG', f'Gesamtergebnisse in aktueller Arbeitsmenge: {len(all_rows)}')
    if active_path_filters:
        add_debug_log('INFO', f'Wende Pfadfilter an: {active_path_filters}')
        filtered_rows = apply_post_crawl_path_filter(all_rows, active_path_filters, log_details=True)
        excluded_urls = {row.get('url', '') for row in filtered_rows}
        excluded_rows = [row for row in all_rows if row.get('url', '') not in excluded_urls]
        add_debug_log('DEBUG', f'Sichtbare Ergebnisse nach Filter: {len(filtered_rows)}')
        add_debug_log('DEBUG', f'Ausgefilterte Ergebnisse: {len(excluded_rows)}')
    else:
        filtered_rows = all_rows
        add_debug_log('INFO', 'Pfadfilter leer: alle Ergebnisse sichtbar')
        add_debug_log('DEBUG', f'Sichtbare Ergebnisse nach Filter: {len(filtered_rows)}')

    st.session_state.crawl_result_rows = filtered_rows
    st.session_state.last_filter_signature = filter_signature
else:
    if active_path_filters:
        filtered_rows = apply_post_crawl_path_filter(all_rows, active_path_filters, log_details=False)
        filtered_urls = {row.get('url', '') for row in filtered_rows}
        excluded_rows = [row for row in all_rows if row.get('url', '') not in filtered_urls]

path_suggestions = st.session_state.get('path_filter_suggestions', [])
if path_suggestions:
    st.write('Häufige Pfad-Vorschläge: ' + ', '.join(path_suggestions))

st.info('Hinweis: Entfernt alle Ergebnisse aus der aktuellen Liste, die nicht zum aktiven Pfadfilter passen.')

action_col1, action_col2 = st.columns(2)

with action_col1:
    disable_remove_filtered = not active_path_filters or len(excluded_rows) == 0
    if st.button(
        f'Ausgefilterte Ergebnisse entfernen ({len(excluded_rows)})',
        disabled=disable_remove_filtered,
        help='Entfernt alle aktuell ausgefilterten Ergebnisse dauerhaft aus der aktuellen Arbeitsmenge.',
    ):
        filtered_urls = {row.get('url', '') for row in filtered_rows}
        removed_now = [row for row in all_rows if row.get('url', '') not in filtered_urls]
        st.session_state.crawl_result_rows_all = filtered_rows
        st.session_state.crawl_result_rows = filtered_rows
        st.session_state.removed_result_urls = list(
            dict.fromkeys(st.session_state.get('removed_result_urls', []) + [row.get('url', '') for row in removed_now])
        )
        st.session_state.last_filter_signature = None
        st.session_state.last_export_signature = None
        add_debug_log('INFO', f'Ausgefilterte Ergebnisse entfernt: {len(removed_now)}')
        add_debug_log('INFO', f'Aktuell sichtbare Ergebnisse: {len(filtered_rows)}')
        st.rerun()

with action_col2:
    can_reset = len(st.session_state.get('original_crawl_result_rows', [])) > 0
    if st.button(
        'Standardzustand wiederherstellen',
        disabled=not can_reset,
        help='Stellt die ursprünglichen Crawl-Ergebnisse wieder her und setzt manuelle Änderungen zurück.',
    ):
        restored_rows = st.session_state.get('original_crawl_result_rows', [])
        st.session_state.crawl_result_rows_all = restored_rows
        st.session_state.crawl_result_rows = restored_rows
        st.session_state.path_filter_reset_requested = True
        st.session_state.removed_result_urls = []
        st.session_state.last_filter_signature = None
        st.session_state.last_export_signature = None
        add_debug_log('INFO', 'Standardzustand wurde wiederhergestellt')
        add_debug_log('INFO', f'Aktuell sichtbare Ergebnisse: {len(restored_rows)}')
        st.rerun()

st.subheader('Debug-Bereich')
with st.expander('Debug Logs'):
    debug_log_lines = st.session_state.get('crawl_debug_logs', [])
    if not debug_log_lines:
        debug_log_lines = ['[INFO] Noch kein Crawl durchgeführt.']
    st.code('\n'.join(debug_log_lines), language='text')
st.divider()

st.subheader('Ergebnisliste')
rows = st.session_state.get('crawl_result_rows', [])
total_rows = st.session_state.get('crawl_result_rows_all', [])
original_rows = st.session_state.get('original_crawl_result_rows', [])
removed_count = max(0, len(original_rows) - len(total_rows))
st.write(f'Gesamt (Original): {len(original_rows)} | Aktuelle Arbeitsmenge: {len(total_rows)} | Sichtbar: {len(rows)} | Entfernt: {removed_count}')
st.caption('Hinweis: "Ergebnis entfernen" wirkt nur auf die aktuelle Ergebnisliste in dieser Session.')

if not rows:
    st.info('Keine Treffer vorhanden.')
else:
    with st.expander(f'📋 **Alle Treffer** ({len(rows)} URLs)', expanded=True):
        st.write(f'**Gefundene URLs mit Treffern:** {len(rows)}')
        st.divider()
        
        for idx, row in enumerate(rows, 1):
            url = row.get('url', '')
            title = row.get('title', '')
            matched_blocks = row.get('matched_blocks', [])

            st.markdown(
                (
                    f"<div style='font-size:0.78rem; color:#6b7280; margin:0.2rem 0 0.35rem 0;'>"
                    f"{url}"
                    f"</div>"
                ),
                unsafe_allow_html=True,
            )
            
            with st.expander(f"**{idx}. {title}** ({len(matched_blocks)} Trefferblöcke)"):
                if st.button('Ergebnis entfernen', key=f'remove_result_{idx}_{url}', help='Entfernt dieses Ergebnis aus Anzeige und Export der aktuellen Session.'):
                    new_all_rows = [item for item in st.session_state.get('crawl_result_rows_all', []) if item.get('url', '') != url]
                    st.session_state.crawl_result_rows_all = new_all_rows
                    st.session_state.removed_result_urls = list(
                        dict.fromkeys(st.session_state.get('removed_result_urls', []) + [url])
                    )
                    st.session_state.last_filter_signature = None
                    st.session_state.last_export_signature = None
                    add_debug_log('INFO', f'Ergebnis manuell entfernt: {url}')
                    add_debug_log('INFO', f'Aktuell sichtbare Ergebnisse: {len(new_all_rows)}')
                    st.rerun()

                st.markdown(f"**URL:** `{url}`")
                st.markdown(f"**Tiefe:** {row.get('depth', 0)} | **Status:** {row.get('status', '')}")
                st.markdown(f"**Keywords gefunden:** {', '.join(row.get('keyword_matches', []))}")
                
                st.divider()
                
                if not matched_blocks:
                    st.info('Keine Trefferblöcke gefunden.')
                else:
                    for block_idx, block in enumerate(matched_blocks, 1):
                        st.markdown(f"**Block {block_idx}:**")
                        st.markdown(f"- **Quelle:** `{block.get('source_type', '')}` | **Tag:** `{block.get('tag', '')}`")
                        st.markdown(f"- **Keywords in diesem Block:** {', '.join(block.get('keywords', []))}")
                        st.markdown(f"- **Vorkommen:** {block.get('match_count', 0)}")
                        
                        block_text = block.get('text', '')
                        st.markdown(f"**Textblock:**")
                        st.markdown(f'> {block_text}')
                        
                        if block_idx < len(matched_blocks):
                            st.divider()
st.divider()

st.subheader('Exportsektion')

def download_format():
    st.session_state.file_format = st.radio(
        "Download-Format",
        ["CSV", "JSON", "PDF", "MD"],
        key='format_radio',
        help='Wählen Sie das gewünschte Exportformat für die aktuell sichtbaren Ergebnisse.',
    )

download_format()

if st.session_state.file_format == 'JSON':
    st.checkbox(
        'Rohtext im JSON behalten',
        key='keep_raw_text_json',
        help='Falls aktiviert, wird zusätzlicher Rohtext mit exportiert. Die Datei kann dadurch deutlich größer werden.',
    )

export_ui_signature = (st.session_state.file_format, st.session_state.keep_raw_text_json)
if st.session_state.get('last_export_ui_signature') != export_ui_signature:
    add_debug_log('INFO', f'Exportformat gewählt: {st.session_state.file_format}')
    if st.session_state.file_format == 'JSON':
        add_debug_log('DEBUG', f'JSON raw_text aktiviert: {st.session_state.keep_raw_text_json}')
    st.session_state.last_export_ui_signature = export_ui_signature

rows = st.session_state.get('crawl_result_rows', [])
json_records = []
if rows:
    export_log_signature = (
        tuple(row.get('url', '') for row in rows),
        len(rows),
        st.session_state.file_format,
        st.session_state.keep_raw_text_json,
    )
    log_export_details = st.session_state.get('last_export_signature') != export_log_signature

    if st.session_state.file_format == 'JSON':
        if log_export_details:
            add_debug_log('INFO', 'Erzeuge strukturierte JSON-Dokumente')
        json_records, export_stats = build_food_json_records(
            rows,
            include_raw_text=st.session_state.get('keep_raw_text_json', False),
            debug_logger=add_debug_log if log_export_details else None,
        )
        results = pd.DataFrame([{'source_url': item.get('source_url', '')} for item in json_records])

        if log_export_details:
            add_debug_log('DEBUG', f'Food-Seiten für JSON erkannt: {export_stats.get("food_page_count", 0)}')
            add_debug_log('DEBUG', f'Gemappte Standard-Nährstoffe: {export_stats.get("mapped_nutrient_keys", [])}')
            add_debug_log('DEBUG', f'Finale JSON-Dokumentanzahl: {export_stats.get("total_output_records", 0)}')
            st.session_state.last_export_signature = export_log_signature
    else:
        if log_export_details:
            add_debug_log('INFO', 'Erzeuge strukturierte CSV-Exportzeilen (Wide)')
        results, export_stats = build_food_csv_rows(
            rows,
            debug_logger=add_debug_log if log_export_details else None,
        )

        if log_export_details:
            add_debug_log('DEBUG', f'Befüllte Standardspalten (CSV): {list(results.columns)}')
            add_debug_log('DEBUG', f'Erkannte Food-Zeilen: {export_stats.get("food_row_count", 0)} / {export_stats.get("total_input_rows", 0)}')
            add_debug_log('DEBUG', f'Finale CSV-Zeilenanzahl: {export_stats.get("total_output_rows", 0)}')
            st.session_state.last_export_signature = export_log_signature
else:
    results = pd.DataFrame()

if st.session_state.file_format and not results.empty:
    parsed_domain = urlparse(st.session_state.get('website', '')).netloc
    domain = parsed_domain or 'unknown'
    try:
        add_debug_log('INFO', f'Starte Export im Format: {st.session_state.file_format}')
        if st.session_state.file_format == 'CSV':
            filepath = export_to_csv(results, domain)
        elif st.session_state.file_format == 'JSON':
            filepath = export_to_json(json_records, domain)
        elif st.session_state.file_format == 'PDF':
            filepath = export_to_pdf(results, domain)
        elif st.session_state.file_format == 'MD':
            filepath = export_to_markdown(results, domain)
        
        with open(filepath, 'rb') as f:
            data = f.read()
        add_debug_log('INFO', f'Export erfolgreich: {filepath}')
        st.download_button(
            label=f"Datei herunterladen ({st.session_state.file_format.upper()})",
            data=data,
            file_name=os.path.basename(filepath),
            mime=f"application/{st.session_state.file_format}" if st.session_state.file_format in ['JSON', 'PDF'] else f"text/{st.session_state.file_format}",
        )
    except Exception as e:
        add_debug_log('ERROR', f'Export fehlgeschlagen: {e}')
        st.error(f"Fehler beim Export: {e}")
elif results.empty:
    if st.session_state.get('last_export_signature') != ('empty', st.session_state.file_format):
        add_debug_log('WARN', 'Keine Ergebnisse zum Exportieren vorhanden.')
        st.session_state.last_export_signature = ('empty', st.session_state.file_format)
    st.info("Keine Ergebnisse zum Exportieren vorhanden.")

# Versionnummer
st.caption("Webcrawler-UI 1.2")
