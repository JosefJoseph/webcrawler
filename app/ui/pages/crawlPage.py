import streamlit as st
import pandas as pd
import os
from urllib.parse import urlparse

from app.crawler.crawler import crawl_domain
from app.parser.parser import build_page_result
from app.services.keyword_filter import filter_results_by_keywords, parse_keywords
from app.ui.export_service import export_to_json, export_to_csv, export_to_pdf, export_to_markdown

if 'file_format' not in st.session_state:
    st.session_state.file_format = 'csv'
if 'crawling' not in st.session_state:
    st.session_state.crawling = False
if 'crawling_completed' not in st.session_state:
    st.session_state.crawling_completed = False
if 'crawl_result_rows' not in st.session_state:
    st.session_state.crawl_result_rows = []
if 'crawl_debug_logs' not in st.session_state:
    st.session_state.crawl_debug_logs = []
if 'crawl_error' not in st.session_state:
    st.session_state.crawl_error = ''
if 'last_crawl_signature' not in st.session_state:
    st.session_state.last_crawl_signature = None

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
    debug_logs = [
        f'[INFO] Starting crawl for website: {website}',
        f'[INFO] Keywords: {", ".join(keywords) if keywords else "(keine)"}',
        f'[INFO] max_pages={max_pages}, max_depth={max_depth}, use_playwright={use_playwright}',
    ]

    try:
        with st.spinner('Seiten werden gecrawlt und ausgewertet...'):
            crawled_pages = crawl_domain(
                start_url=website,
                max_pages=max_pages,
                max_depth=max_depth,
                use_playwright=use_playwright,
            )

            page_results = [build_page_result(page) for page in crawled_pages]
            matched_results, unmatched_results = filter_results_by_keywords(page_results, keywords)

        st.session_state.crawl_result_rows = matched_results
        st.session_state.crawl_error = ''
        st.session_state.crawling_completed = True
        st.session_state.crawling = False
        st.session_state.last_crawl_signature = crawl_signature

        debug_logs.append(f'[INFO] Pages crawled: {len(crawled_pages)}')
        debug_logs.append(f'[INFO] Pages with keyword matches: {len(matched_results)}')
        debug_logs.append(f'[INFO] Pages without matches: {len(unmatched_results)}')
        debug_logs.append('[INFO] Crawling completed successfully')

    except Exception as exc:
        st.session_state.crawl_result_rows = []
        st.session_state.crawling_completed = False
        st.session_state.crawling = False
        st.session_state.crawl_error = str(exc)
        st.session_state.last_crawl_signature = None
        debug_logs.append(f'[ERROR] Crawling failed: {exc}')

    st.session_state.crawl_debug_logs = debug_logs

if st.session_state.crawl_error:
    statusText_placeholder.error(f'Crawling fehlgeschlagen: {st.session_state.crawl_error}')
elif st.session_state.crawling_completed:
    statusText_placeholder.success('Crawling abgeschlossen!')
else:
    statusText_placeholder.info('Kein Crawling aktiv. Gehe zurück zur Suche.')
st.divider()

st.subheader('Debug-Bereich')
with st.expander('Debug Logs'):
    debug_log_lines = st.session_state.get('crawl_debug_logs', [])
    if not debug_log_lines:
        debug_log_lines = ['[INFO] Noch kein Crawl durchgeführt.']
    st.code('\n'.join(debug_log_lines), language='text')
st.divider()

st.subheader('Ergebnisliste')
rows = st.session_state.get('crawl_result_rows', [])

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
            
            with st.expander(f"**{idx}. {title}** ({len(matched_blocks)} Trefferblöcke)"):
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
        "Wählen Sie das Download-Format",
        ["csv", "json", "pdf", "md"],
        key='format_radio'
    )

download_format()

rows = st.session_state.get('crawl_result_rows', [])
if rows:
    table_rows = []
    for row in rows:
        for block in row.get('matched_blocks', []):
            table_rows.append(
                {
                    'URL': row.get('url', ''),
                    'Title': row.get('title', ''),
                    'Depth': row.get('depth', 0),
                    'Status': row.get('status', ''),
                    'Fetch': row.get('fetch_method', ''),
                    'Keywords': ', '.join(row.get('keyword_matches', [])),
                    'Trefferblöcke': row.get('matched_block_count', 0),
                    'Keyword-Vorkommen': row.get('match_occurrence_count', 0),
                    'Zusammenfassung': row.get('match_summary', ''),
                }
            )
    
    results = pd.DataFrame(table_rows)
else:
    results = pd.DataFrame()

if st.session_state.file_format and not results.empty:
    parsed_domain = urlparse(st.session_state.get('website', '')).netloc
    domain = parsed_domain or 'unknown'
    try:
        if st.session_state.file_format == 'csv':
            filepath = export_to_csv(results, domain)
        elif st.session_state.file_format == 'json':
            filepath = export_to_json(results, domain)
        elif st.session_state.file_format == 'pdf':
            filepath = export_to_pdf(results, domain)
        elif st.session_state.file_format == 'md':
            filepath = export_to_markdown(results, domain)
        
        with open(filepath, 'rb') as f:
            data = f.read()
        st.download_button(
            label=f"Download ({st.session_state.file_format.upper()})",
            data=data,
            file_name=os.path.basename(filepath),
            mime=f"application/{st.session_state.file_format}" if st.session_state.file_format in ['json', 'pdf'] else f"text/{st.session_state.file_format}",
        )
    except Exception as e:
        st.error(f"Fehler beim Export: {e}")
elif results.empty:
    st.info("Keine Ergebnisse zum Exportieren vorhanden.")

# Versionnummer
st.caption("Webcrawler-UI 1.1")
