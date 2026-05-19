"""
Export formatting utilities for human-readable Markdown and PDF output.

Design decisions:
- Markdown: Structured sections with headings, compact per-page blocks.
- PDF: Styled sections via fpdf2 with consistent typography, page breaks between pages, headers/footers.
- Raw data is preserved but moved out of the main reading flow.
- Cookie/boilerplate text is stripped from summaries.
"""

import re
from datetime import datetime

import pandas as pd

from app.services.result_formatting_service import (
    format_match_type,
    format_keyword_matches,
    format_semantic_line,
)

# ─── Text Cleaning ────────────────────────────────────────────────────────────

_BOILERPLATE_PATTERNS = [
    r'Cookie[s]?\s*(Policy|Settings|Details|List)',
    r'Privacy Preference Center',
    r'Powered by OneTrust',
    r'Necessary Cookies\s*(Always Active)?',
    r'Analytics Cookies',
    r'Advertising\s*(Advertising)?',
    r'Personalization\s*(Personalization)?',
    r'Reject All\s*Confirm My Choices',
    r'checkbox label label',
    r'Opens in a new Tab',
    r'onetrust-text-resize',
    r'Close preference center',
    r'Filter Cookie List',
    r'Back Button Cookie List Search Icon',
    r'Consent Leg\.Interest',
    r'Apply Cancel',
    r'Clear checkbox label',
]

_BOILERPLATE_RE = re.compile('|'.join(_BOILERPLATE_PATTERNS), re.IGNORECASE)


def clean_text_for_summary(text: str, max_length: int = 500) -> str:
    """Remove boilerplate noise and truncate for display."""
    if not text:
        return ''
    # Remove boilerplate segments
    cleaned = _BOILERPLATE_RE.sub('', text)
    # Collapse whitespace
    cleaned = re.sub(r'\s{2,}', ' ', cleaned).strip()
    # Remove common UI artifacts
    cleaned = re.sub(r'(Read More|Learn More|Explore|LEARN MORE)\s*-?\s*', '', cleaned)
    cleaned = re.sub(r'\s{2,}', ' ', cleaned).strip()
    if len(cleaned) > max_length:
        return cleaned[:max_length].rsplit(' ', 1)[0] + '...'
    return cleaned


def extract_meaningful_snippet(text: str, keywords: list[str], max_length: int = 300) -> str:
    """Extract the most relevant snippet around matched keywords."""
    if not text or not keywords:
        return clean_text_for_summary(text, max_length)

    text_lower = text.lower()
    best_pos = -1
    for kw in keywords:
        pos = text_lower.find(kw.lower())
        if pos != -1:
            best_pos = pos
            break

    if best_pos == -1:
        return clean_text_for_summary(text, max_length)

    start = max(0, best_pos - 100)
    end = min(len(text), best_pos + max_length - 100)
    snippet = text[start:end].strip()
    snippet = _BOILERPLATE_RE.sub('', snippet)
    snippet = re.sub(r'\s{2,}', ' ', snippet).strip()

    if start > 0:
        snippet = '...' + snippet
    if end < len(text):
        snippet = snippet + '...'
    return snippet


# ─── Keyword Highlighting ─────────────────────────────────────────────────────

def _highlight_keywords_md(text: str, keywords: list[str]) -> str:
    """Wrap keyword occurrences in bold markdown markers."""
    if not keywords or not text:
        return text
    pattern = re.compile('|'.join(re.escape(kw) for kw in keywords), re.IGNORECASE)
    return pattern.sub(lambda m: f'**{m.group()}**', text)


def _pdf_write_inline(pdf, text: str, h: int = 4) -> None:
    """Write inline text without line break (fpdf2 / pyfpdf compat)."""
    safe_text = _safe(text)
    try:
        pdf.write(h=h, text=safe_text)
    except TypeError:
        pdf.write(h=h, txt=safe_text)


def _pdf_write_with_highlights(pdf, text: str, keywords: list[str], h: int = 4) -> None:
    """Write a text block inline, bolding each keyword occurrence."""
    truncated = text[:600]
    if not keywords:
        _pdf_write_multi(pdf, 0, h, truncated)
        return
    pattern = re.compile('|'.join(re.escape(kw) for kw in keywords), re.IGNORECASE)
    pos = 0
    for m in pattern.finditer(truncated):
        before = truncated[pos:m.start()]
        if before:
            pdf.set_font('Helvetica', '', 9)
            _pdf_write_inline(pdf, before, h)
        pdf.set_font('Helvetica', 'B', 9)
        _pdf_write_inline(pdf, m.group(), h)
        pos = m.end()
    remaining = truncated[pos:]
    if remaining:
        pdf.set_font('Helvetica', '', 9)
        _pdf_write_inline(pdf, remaining, h)
    pdf.ln()
    pdf.set_font('Helvetica', '', 9)


# ─── Markdown Formatting ──────────────────────────────────────────────────────

def format_markdown_report(df: pd.DataFrame, domain: str) -> str:
    """Generate a structured, readable Markdown report from crawl results."""
    lines = []
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # ── Title & Metadata ──
    lines.append(f'# Crawl Report: {domain}')
    lines.append('')
    lines.append(f'**Generated:** {timestamp}  ')
    lines.append(f'**Domain:** {domain}  ')
    lines.append(f'**Pages crawled:** {_count_unique_pages(df)}  ')
    lines.append(f'**Total result rows:** {len(df)}')
    lines.append('')
    lines.append('---')
    lines.append('')

    # ── Executive Summary ──
    lines.append('## Executive Summary')
    lines.append('')
    summary_stats = _build_summary_stats(df)
    for stat in summary_stats:
        lines.append(f'- {stat}')
    lines.append('')

    # ── Keyword Summary ──
    keyword_data = _build_keyword_summary(df)
    if keyword_data:
        lines.append('## Keyword Matches')
        lines.append('')
        lines.append('| Keyword | Occurrences | Pages |')
        lines.append('|---------|-------------|-------|')
        for kw, count, pages in keyword_data:
            lines.append(f'| {kw} | {count} | {pages} |')
        lines.append('')

    # ── Per-Page Results ──
    lines.append('## Page Results')
    lines.append('')

    page_rows = _get_primary_page_rows(df)
    for i, (_, row) in enumerate(page_rows.iterrows(), 1):
        lines.extend(_format_page_section(row, i))

    # Add truncated raw data for reference
    for _, row in page_rows.iterrows():
        url = str(row.get('source_url', ''))
        if not url:
            continue
        raw = str(row.get('raw_text', ''))
        if raw and len(raw) > 50:
            lines.append(f'### {url}')
            lines.append('')
            truncated = raw[:1000].replace('\n', ' ')
            truncated = re.sub(r'\s{2,}', ' ', truncated)
            lines.append(f'```')
            lines.append(truncated + ('...' if len(raw) > 1000 else ''))
            lines.append(f'```')
            lines.append('')

    return '\n'.join(lines)


def _count_unique_pages(df: pd.DataFrame) -> int:
    """Count unique pages (rows with a source_url)."""
    url_column = 'source_url' if 'source_url' in df.columns else ('url' if 'url' in df.columns else None)
    if url_column:
        return df[url_column].replace('', pd.NA).dropna().nunique()
    return len(df)


def _build_summary_stats(df: pd.DataFrame) -> list[str]:
    """Build executive summary bullet points."""
    stats = []
    num_pages = _count_unique_pages(df)
    stats.append(f'{num_pages} unique pages with content')

    if 'keyword_matches' in df.columns:
        pages_with_matches = df[df['keyword_matches'].astype(str).str.strip().ne('')].shape[0]
        if pages_with_matches:
            stats.append(f'{pages_with_matches} rows contain keyword matches')

    if 'matched_block_count' in df.columns:
        total_blocks = pd.to_numeric(df['matched_block_count'], errors='coerce').sum()
        if total_blocks > 0:
            stats.append(f'{int(total_blocks)} total matched content blocks')

    if 'match_occurrence_count' in df.columns:
        total_occ = pd.to_numeric(df['match_occurrence_count'], errors='coerce').sum()
        if total_occ > 0:
            stats.append(f'{int(total_occ)} total keyword occurrences')

    # Check for food/nutrition data
    if 'fdc_id' in df.columns:
        food_pages = df[df['fdc_id'].astype(str).str.strip().ne('')].shape[0]
        if food_pages > 0:
            stats.append(f'{food_pages} pages with food/nutrition data (FDC)')

    return stats


def _build_keyword_summary(df: pd.DataFrame) -> list[tuple[str, int, int]]:
    """Build keyword frequency table: (keyword, total_occurrences, page_count)."""
    keyword_column = None
    if 'keyword_matches' in df.columns:
        keyword_column = 'keyword_matches'
    elif 'matched_terms' in df.columns:
        keyword_column = 'matched_terms'

    if keyword_column is None:
        return []

    keyword_counts: dict[str, int] = {}
    keyword_pages: dict[str, int] = {}

    for _, row in df.iterrows():
        kw_str = str(row.get(keyword_column, ''))
        if not kw_str.strip():
            continue
        keywords = [k.strip() for k in kw_str.split(',') if k.strip()]
        seen_this_row = set()
        for kw in keywords:
            keyword_counts[kw] = keyword_counts.get(kw, 0) + 1
            if kw not in seen_this_row:
                keyword_pages[kw] = keyword_pages.get(kw, 0) + 1
                seen_this_row.add(kw)

    # Sort by frequency
    sorted_kws = sorted(keyword_counts.items(), key=lambda x: x[1], reverse=True)
    return [(kw, count, keyword_pages.get(kw, 0)) for kw, count in sorted_kws[:20]]


def _get_primary_page_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Get only the primary page rows (with a source_url), deduplicated."""
    url_column = 'source_url' if 'source_url' in df.columns else ('url' if 'url' in df.columns else None)
    if url_column is None:
        return df

    mask = df[url_column].astype(str).str.strip().ne('')
    primary = df[mask].drop_duplicates(subset=[url_column], keep='first')
    return primary


def _format_page_section(row: pd.Series, index: int) -> list[str]:
    """Format a single page result as a readable section."""
    lines = []
    url = str(row.get('source_url', '') or row.get('url', 'N/A'))
    title = _normalize_title(str(row.get('page_title', '') or row.get('title', '')) or 'Untitled')
    path = str(row.get('path', ''))

    lines.append(f'### {index}. {title}')
    lines.append('')
    lines.append(f'- **URL:** {url}')
    lines.append(f'- **Path:** {path}')

    # Match info — clear separation of keyword and semantic
    matched_by = str(row.get('matched_by', '')).strip()
    if matched_by:
        lines.append(f'- **Match-Typ:** {format_match_type(matched_by)}')
    lines.append(f'- **Keyword-Treffer:** {format_keyword_matches(row)}')
    lines.append(f'- **{format_semantic_line(row)}**')
    block_count = row.get('matched_block_count', 0)
    occ_count = row.get('match_occurrence_count', 0)
    if block_count or occ_count:
        lines.append(f'- **Match stats:** {block_count} blocks, {occ_count} occurrences')

    # Structured data (food, nutrition, etc.)
    structured_fields = []
    for field in ['brand', 'manufacturer', 'category', 'food_name', 'ingredients',
                  'calories', 'protein', 'fat', 'carbohydrates']:
        val = str(row.get(field, ''))
        if val.strip():
            structured_fields.append((field.replace('_', ' ').title(), val))

    if structured_fields:
        lines.append('')
        lines.append('**Extracted Data:**')
        lines.append('')
        lines.append('| Field | Value |')
        lines.append('|-------|-------|')
        for field_name, value in structured_fields:
            lines.append(f'| {field_name} | {value[:100]} |')

    # Content snippet
    raw_text = str(row.get('raw_text', '') or row.get('snippet', ''))
    _kw_raw = row.get('keyword_matches') or row.get('matched_terms') or ''
    if isinstance(_kw_raw, list):
        kw_list = [str(k).strip() for k in _kw_raw if str(k).strip()]
    else:
        kw_list = [k.strip() for k in str(_kw_raw).split(',') if k.strip()]
    if raw_text.strip():
        snippet = extract_meaningful_snippet(raw_text, kw_list, max_length=400)
        if snippet:
            lines.append('')
            lines.append('**Content preview:**')
            lines.append(f'> {snippet}')

    # Matched blocks with keyword highlighting
    matched_blocks = row.get('matched_blocks', [])
    if not isinstance(matched_blocks, list):
        matched_blocks = []
    if matched_blocks:
        lines.append('')
        lines.append(f'**Matched Blocks ({len(matched_blocks)}):**')
        lines.append('')
        for bi, block in enumerate(matched_blocks, 1):
            source = block.get('source_type') or block.get('source', '')
            tag = block.get('tag', '')
            block_keywords = block.get('keywords', []) or kw_list
            match_count = block.get('match_count', block.get('occurrences', len(block_keywords)))
            occ_word = 'occurrence' if match_count == 1 else 'occurrences'
            kw_display = ', '.join(f'**{k}**' for k in block_keywords)
            lines.append(f'**Block {bi}** — `{source}` · `<{tag}>` | Keywords: {kw_display} | {match_count} {occ_word}')
            lines.append('')
            block_text = block.get('text', '').strip()
            if block_text:
                highlighted = _highlight_keywords_md(block_text[:600], block_keywords)
                for text_line in highlighted.split('\n'):
                    lines.append(f'> {text_line}')
            lines.append('')

    lines.append('---')
    lines.append('')
    return lines


# ─── PDF Formatting ───────────────────────────────────────────────────────────


def _pdf_write_cell(pdf, w, h, text, **kwargs):
    """Write a cell across both pyfpdf and fpdf2 APIs."""
    safe_text = _safe(text)
    align = kwargs.get('align', '')
    fill = kwargs.get('fill', False)
    ln = 1 if kwargs.get('ln', True) else 0
    try:
        pdf.cell(w=w, h=h, text=safe_text, align=align, fill=fill, ln=ln)
    except Exception:
        pdf.cell(w=w, h=h, txt=safe_text, align=align, fill=fill, ln=1 if ln else 0)


def _pdf_write_multi(pdf, w, h, text):
    """Write a multi_cell across both pyfpdf and fpdf2 APIs.

    When w=0 is requested, the effective width is computed from page margins
    to avoid layout issues in fpdf2 where w=0 changed semantics.
    """
    safe_text = _safe(text)
    effective_w = w
    if effective_w == 0:
        try:
            effective_w = pdf.w - pdf.l_margin - pdf.r_margin
        except Exception:
            effective_w = 0
    try:
        pdf.multi_cell(w=effective_w, h=h, text=safe_text)
    except TypeError:
        pdf.multi_cell(w=effective_w, h=h, txt=safe_text)


def format_pdf_report(pdf, df: pd.DataFrame, domain: str) -> None:
    """Populate an FPDF instance with a structured report.

    Args:
        pdf: An FPDF instance (already created with add_page).
        df: The crawl results DataFrame.
        domain: The crawled domain name.
    """
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # ── Title Page ──
    pdf.set_font('Helvetica', 'B', 20)
    _pdf_write_cell(pdf, 0, 15, 'Crawl Report', align='C')
    pdf.set_font('Helvetica', '', 14)
    _pdf_write_cell(pdf, 0, 10, domain, align='C')
    pdf.ln(8)
    pdf.set_font('Helvetica', '', 10)
    _pdf_write_cell(pdf, 0, 6, f'Generated: {timestamp}', align='C')
    _pdf_write_cell(pdf, 0, 6, f'Pages: {_count_unique_pages(df)} | Rows: {len(df)}', align='C')
    pdf.ln(12)

    # ── Executive Summary ──
    _pdf_section_header(pdf, 'Executive Summary')
    summary_stats = _build_summary_stats(df)
    for stat in summary_stats:
        pdf.set_font('Helvetica', '', 10)
        _pdf_write_multi(pdf, 0, 5, f'  * {stat}')
    pdf.ln(6)

    # ── Keyword Summary Table ──
    keyword_data = _build_keyword_summary(df)
    if keyword_data:
        _pdf_section_header(pdf, 'Keyword Matches')
        _pdf_table(pdf, ['Keyword', 'Occurrences', 'Pages'],
                   [[kw, str(count), str(pages)] for kw, count, pages in keyword_data[:15]])
        pdf.ln(6)

    # ── Per-Page Results ──
    _pdf_section_header(pdf, 'Page Results')
    pdf.ln(4)

    page_rows = _get_primary_page_rows(df)
    for i, (_, row) in enumerate(page_rows.iterrows(), 1):
        _format_pdf_page_section(pdf, row, i)


def _pdf_section_header(pdf, title: str) -> None:
    """Render a styled section header."""
    pdf.ln(4)
    pdf.set_font('Helvetica', 'B', 13)
    pdf.set_fill_color(240, 240, 240)
    _pdf_write_cell(pdf, 0, 8, f'  {title}', fill=True)
    pdf.ln(3)


def _pdf_table(pdf, headers: list[str], rows: list[list[str]]) -> None:
    """Render a simple table in PDF."""
    col_widths = _calc_col_widths(pdf, headers, rows)
    # Header
    pdf.set_font('Helvetica', 'B', 9)
    for i, header in enumerate(headers):
        is_last = (i == len(headers) - 1)
        try:
            pdf.cell(w=col_widths[i], h=6, text=_safe(header), border=1, align='C', ln=1 if is_last else 0)
        except Exception:
            pdf.cell(w=col_widths[i], h=6, txt=_safe(header), border=1, align='C', ln=1 if is_last else 0)
    # Rows
    pdf.set_font('Helvetica', '', 9)
    for row in rows:
        for i, cell_val in enumerate(row):
            is_last = (i == len(row) - 1)
            try:
                pdf.cell(w=col_widths[i], h=5, text=_safe(cell_val[:50]), border=1, ln=1 if is_last else 0)
            except Exception:
                pdf.cell(w=col_widths[i], h=5, txt=_safe(cell_val[:50]), border=1, ln=1 if is_last else 0)


def _calc_col_widths(pdf, headers: list[str], rows: list[list[str]]) -> list[float]:
    """Calculate proportional column widths."""
    page_width = pdf.w - pdf.l_margin - pdf.r_margin
    num_cols = len(headers)
    # First column gets more space
    if num_cols == 3:
        return [page_width * 0.5, page_width * 0.25, page_width * 0.25]
    return [page_width / num_cols] * num_cols


def _format_pdf_page_section(pdf, row: pd.Series, index: int) -> None:
    """Render a single page result in PDF format."""
    url = str(row.get('source_url', '') or row.get('url', 'N/A'))
    title = _normalize_title(str(row.get('page_title', '') or row.get('title', '')) or 'Untitled')
    path = str(row.get('path', ''))
    matched_by = str(row.get('matched_by', '')).strip()

    # Check if we need a new page (leave space)
    if pdf.get_y() > pdf.h - 60:
        pdf.add_page()

    # Page title
    pdf.set_font('Helvetica', 'B', 11)
    _pdf_write_multi(pdf, 0, 6, f'{index}. {title}')

    # Metadata — clear separation of match type, keywords, semantic
    pdf.set_font('Helvetica', '', 9)
    pdf.set_text_color(80, 80, 80)
    display_url = url if len(url) <= 80 else url[:77] + '...'
    _pdf_write_multi(pdf, 0, 4, f'URL: {display_url}')
    _pdf_write_cell(pdf, 0, 4, f'Path: {path}')
    if matched_by:
        _pdf_write_cell(pdf, 0, 4, f'Match-Typ: {format_match_type(matched_by)}')
    _pdf_write_cell(pdf, 0, 4, f'Keyword-Treffer: {format_keyword_matches(row)}')
    _pdf_write_cell(pdf, 0, 4, format_semantic_line(row))
    block_count = row.get('matched_block_count', 0)
    occ_count = row.get('match_occurrence_count', 0)
    if block_count or occ_count:
        _pdf_write_cell(pdf, 0, 4, f'Matches: {block_count} blocks, {occ_count} occurrences')
    pdf.set_text_color(0, 0, 0)

    # Structured data
    structured_fields = []
    for field in ['brand', 'manufacturer', 'category', 'food_name', 'ingredients',
                  'calories', 'protein', 'fat', 'carbohydrates']:
        val = str(row.get(field, ''))
        if val.strip():
            structured_fields.append((field.replace('_', ' ').title(), val[:80]))

    if structured_fields:
        pdf.ln(2)
        pdf.set_font('Helvetica', 'B', 9)
        _pdf_write_cell(pdf, 0, 5, 'Extracted Data:')
        pdf.set_font('Helvetica', '', 9)
        for field_name, value in structured_fields:
            _pdf_write_cell(pdf, 0, 4, f'  {field_name}: {value}')

    _kw_raw = row.get('keyword_matches') or row.get('matched_terms') or ''
    if isinstance(_kw_raw, list):
        kw_list = [str(k).strip() for k in _kw_raw if str(k).strip()]
    else:
        kw_list = [k.strip() for k in str(_kw_raw).split(',') if k.strip()]

    # Content snippet
    raw_text = str(row.get('raw_text', '') or row.get('snippet', ''))
    if raw_text.strip():
        snippet = extract_meaningful_snippet(raw_text, kw_list, max_length=300)
        if snippet:
            pdf.ln(2)
            pdf.set_font('Helvetica', 'I', 9)
            _pdf_write_multi(pdf, 0, 4, snippet[:500])

    # Matched blocks with keyword highlighting
    matched_blocks = row.get('matched_blocks', [])
    if not isinstance(matched_blocks, list):
        matched_blocks = []
    if matched_blocks:
        pdf.ln(3)
        pdf.set_font('Helvetica', 'B', 9)
        _pdf_write_cell(pdf, 0, 5, f'Matched Blocks ({len(matched_blocks)}):')
        for bi, block in enumerate(matched_blocks, 1):
            if pdf.get_y() > pdf.h - 45:
                pdf.add_page()
            source = block.get('source_type') or block.get('source', '')
            tag = block.get('tag', '')
            block_keywords = block.get('keywords', []) or kw_list
            match_count = block.get('match_count', block.get('occurrences', len(block_keywords)))
            kw_display = ', '.join(block_keywords[:6])
            # Block header line
            pdf.set_font('Helvetica', 'B', 8)
            pdf.set_text_color(60, 60, 60)
            _pdf_write_multi(pdf, 0, 4,
                f'Block {bi} — {source} / <{tag}> | Keywords: {kw_display} | {match_count} occurrence(s)')
            pdf.set_text_color(0, 0, 0)
            # Block text with inline keyword highlighting
            block_text = block.get('text', '').strip()
            if block_text:
                _pdf_write_with_highlights(pdf, block_text, block_keywords)
            pdf.ln(1)

    # Separator
    pdf.ln(4)
    pdf.set_draw_color(200, 200, 200)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(4)


def _safe(text: str) -> str:
    """Make text safe for PDF rendering (Latin-1 compatible)."""
    return text.encode('latin-1', 'replace').decode('latin-1')


def _normalize_title(title: str) -> str:
    """Normalize title separators for export readability."""
    if not title:
        return title
    normalized = title.replace(' – ', ' | ')
    normalized = normalized.replace(' — ', ' | ')
    normalized = normalized.replace(' ? ', ' | ')
    return normalized
