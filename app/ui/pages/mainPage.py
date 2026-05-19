import uuid
from datetime import datetime

import streamlit as st
from urllib.parse import urlparse
import requests

from app.services.local_settings_service import (
    load_local_settings,
    save_local_settings,
    clear_local_settings,
    merge_with_defaults,
)

# ── Keyword presets ───────────────────────────────────────────────────────────
keywords_map = {
    "Inhaltsstoffe": ["nutrition facts", "calories", "protein", "fat", "carbohydrates", "sugar", "salt", "fiber", "vitamins", "minerals", "ingredients", "allergens", "additives", "preservatives", "E-numbers"],
    "Rohstoffe": ["raw materials", "sourcing", "origin", "country of origin", "supplier", "cocoa", "wheat", "milk", "eggs", "nuts", "natural ingredients", "non-GMO"],
    "Qualitätssiegel": ["organic", "fair-trade", "bio", "EU-Bio", "DIN", "ISO", "certification", "label", "certified", "quality standard", "rainforest alliance", "UTZ", "gluten-free", "vegan"],
    "Lieferkette": ["supply chain", "traceability", "transparency", "chain of custody", "batch number", "lot number", "producer", "manufacturer", "distributor", "audited", "logistics"],
    "Lieferwege": ["distribution", "logistics", "delivery", "warehouse", "cold chain", "temperature control", "storage", "distribution partners", "transportation"],
    "Transport": ["shipping", "freight", "transport method", "truck", "ship", "rail", "air freight", "carbon footprint", "packaging", "eco-friendly"],
    "Gewinne": ["revenue", "profit", "sales", "market share", "price", "cost", "margin", "financial results", "earnings"],
    "Steuern": ["taxes", "VAT", "customs", "duties", "tariff", "regulations", "compliance", "legal requirements", "certifications"],
}

CATEGORY_OPTIONS = list(keywords_map.keys())

# ── Defaults ──────────────────────────────────────────────────────────────────
DEFAULT_SETTINGS: dict = {
    "website": "",
    "infotosearch": "",
    "category_input": CATEGORY_OPTIONS[0],
    "keywords_selection": [],
    "max_pages": 3,
    "max_depth": 2,
    "semantic_search": False,
    "semantic_threshold": 0.30,
}

# ── Load + merge persisted settings ──────────────────────────────────────────
_saved = load_local_settings()
_settings = merge_with_defaults(_saved, DEFAULT_SETTINGS)

# ── Initialize session state (Pattern A: before any widget creation) ──────────
# Each key is only set if it is not already in session state (avoids overwriting
# values that Streamlit's widget machinery already committed for this rerun).
if "website" not in st.session_state:
    st.session_state["website"] = _settings["website"]

if "infotosearch" not in st.session_state:
    st.session_state["infotosearch"] = _settings["infotosearch"]
# infotosearch_input is the widget key for the text area; keep in sync.
if "infotosearch_input" not in st.session_state:
    st.session_state["infotosearch_input"] = _settings["infotosearch"]

_saved_cat = _settings["category_input"]
if _saved_cat not in CATEGORY_OPTIONS:
    _saved_cat = CATEGORY_OPTIONS[0]
if "category_input" not in st.session_state:
    st.session_state["category_input"] = _saved_cat

if "keywords_selection" not in st.session_state:
    _active_opts = keywords_map.get(st.session_state["category_input"], [])
    _saved_sel = _settings["keywords_selection"]
    if not isinstance(_saved_sel, list):
        _saved_sel = []
    st.session_state["keywords_selection"] = [k for k in _saved_sel if k in _active_opts]

if "max_pages" not in st.session_state:
    st.session_state["max_pages"] = int(max(1, min(500, int(_settings["max_pages"]))))

if "max_depth" not in st.session_state:
    st.session_state["max_depth"] = int(max(0, min(10, int(_settings["max_depth"]))))

if "semantic_search" not in st.session_state:
    st.session_state["semantic_search"] = bool(_settings["semantic_search"])

if "semantic_threshold" not in st.session_state:
    st.session_state["semantic_threshold"] = float(
        max(0.0, min(1.0, float(_settings["semantic_threshold"])))
    )

# ── on_change callbacks ───────────────────────────────────────────────────────
def _parse_keywords(text: str) -> list[str]:
    return [entry.strip() for entry in text.split(",") if entry.strip()]


def update_infotosearch() -> None:
    st.session_state["infotosearch"] = st.session_state["infotosearch_input"]
    active_options = keywords_map.get(st.session_state.get("category_input", ""), [])
    typed = _parse_keywords(st.session_state["infotosearch_input"])
    st.session_state["keywords_selection"] = [kw for kw in typed if kw in active_options]


def update_infotosearch_from_multiselect() -> None:
    active_options = set(keywords_map.get(st.session_state.get("category_input", ""), []))
    typed = _parse_keywords(st.session_state["infotosearch_input"])
    keep = [kw for kw in typed if kw not in active_options]
    merged = keep + list(st.session_state.get("keywords_selection", []))
    new_text = ", ".join(dict.fromkeys(merged))
    st.session_state["infotosearch_input"] = new_text
    st.session_state["infotosearch"] = new_text


def update_category() -> None:
    active_options = keywords_map.get(st.session_state.get("category_input", ""), [])
    typed = _parse_keywords(st.session_state.get("infotosearch_input", ""))
    st.session_state["keywords_selection"] = [kw for kw in typed if kw in active_options]


def checkUrlValid(url: str) -> bool:
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except ValueError:
        return False


def checkUrlReachable(url: str) -> bool:
    try:
        requests.get(url, timeout=5)
        return True
    except (
        requests.exceptions.HTTPError,
        requests.exceptions.ConnectionError,
        requests.exceptions.RequestException,
    ):
        return False


# ── Page layout ───────────────────────────────────────────────────────────────
_col_title, _col_reset = st.columns([3, 1])
with _col_title:
    st.title("Webcrawler")
with _col_reset:
    st.markdown("<div style='padding-top:1.5rem'>", unsafe_allow_html=True)
    # Reset button before widgets so session_state pops happen before widget rendering
    if st.button("Alle Eingaben zurücksetzen", type="secondary", use_container_width=True):
        clear_local_settings()
        for _key in [
            "website",
            "infotosearch",
            "infotosearch_input",
            "category_input",
            "keywords_selection",
            "max_pages",
            "max_depth",
            "semantic_search",
            "semantic_threshold",
            # crawl/result state
            "crawling",
            "crawling_completed",
            "crawl_result_rows",
            "crawl_result_rows_all",
            "original_crawl_result_rows",
            "last_crawl_signature",
            "crawl_pipeline_stats",
            "crawl_semantic_stats",
        ]:
            st.session_state.pop(_key, None)
        st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

st.markdown("### Filter")

# ── Clamp bounded values before widget creation ───────────────────────────────
st.session_state["max_pages"] = int(
    max(1, min(500, int(st.session_state.get("max_pages", DEFAULT_SETTINGS["max_pages"]))))
)
st.session_state["max_depth"] = int(
    max(0, min(10, int(st.session_state.get("max_depth", DEFAULT_SETTINGS["max_depth"]))))
)
st.session_state["semantic_threshold"] = float(
    max(0.0, min(1.0, float(st.session_state.get("semantic_threshold", DEFAULT_SETTINGS["semantic_threshold"]))))
)

# Validate category before selectbox
if st.session_state.get("category_input") not in CATEGORY_OPTIONS:
    st.session_state["category_input"] = CATEGORY_OPTIONS[0]

# Validate keywords_selection against active category options
_active_opts_now = keywords_map.get(st.session_state.get("category_input", ""), [])
_sel_now = st.session_state.get("keywords_selection", [])
if not isinstance(_sel_now, list):
    _sel_now = []
_valid_sel = [k for k in _sel_now if k in _active_opts_now]
if _valid_sel != _sel_now:
    st.session_state["keywords_selection"] = _valid_sel

# ── Widgets ───────────────────────────────────────────────────────────────────
st.text_input(
    "Start-URL",
    key="website",
    placeholder="z.B. https://world.openfoodfacts.org/, https://fdc.nal.usda.gov/",
    help="Die Webseite, bei der der Crawler startet. Alle verlinkten Unterseiten werden von dort aus systematisch durchsucht.",
)

st.text_area(
    "Keywords (kommagetrennt)",
    key="infotosearch_input",
    on_change=update_infotosearch,
    placeholder="z.B. nutrition facts, Food Category, ingredients, allergens",
    help="Kommagetrennte Suchbegriffe. Der Crawler markiert Seiten als Treffer, die mindestens einen dieser Begriffe enthalten. Groß-/Kleinschreibung wird ignoriert.",
)

col3, col4 = st.columns(2)
with col3:
    st.selectbox(
        "Kategorie",
        options=CATEGORY_OPTIONS,
        key="category_input",
        on_change=update_category,
        help="Wähle eine vordefinierte Themenkategorie. Die zugehörigen Keywords werden zur Schnellauswahl im Feld rechts angeboten.",
    )
with col4:
    st.multiselect(
        "Keywords",
        options=keywords_map.get(st.session_state.get("category_input", CATEGORY_OPTIONS[0]), []),
        key="keywords_selection",
        on_change=update_infotosearch_from_multiselect,
        help="Vordefinierte Keywords der gewählten Kategorie. Die Auswahl wird automatisch in das Keyword-Textfeld übernommen.",
    )

col1, col2 = st.columns(2)
with col1:
    st.number_input(
        "Maximale Seiten",
        min_value=1,
        max_value=500,
        step=1,
        key="max_pages",
        help="Maximale Anzahl an Seiten, die der Crawler insgesamt besucht. Höhere Werte erhöhen Vollständigkeit, aber auch Laufzeit.",
    )
with col2:
    st.number_input(
        "Maximale Tiefe",
        min_value=0,
        max_value=10,
        step=1,
        key="max_depth",
        help="Wie viele Verlinkungsebenen tief der Crawler folgt. Tiefe 0 = nur Startseite, Tiefe 1 = Startseite + direkt verlinkte Seiten, usw.",
    )

st.markdown("### AI-Optionen")
_cb_col, _lbl_col = st.columns([0.06, 0.94])
with _cb_col:
    st.markdown("<div style='padding-top:0.55rem'>", unsafe_allow_html=True)
    st.checkbox(
        "Semantisches Matching",
        key="semantic_search",
        label_visibility="collapsed",
        help="Aktiviert KI-gestützte semantische Ähnlichkeitssuche. Findet thematisch verwandte Seiten auch ohne exakte Keyword-Treffer. Läuft lokal mit Sentence Transformers.",
    )
    st.markdown("</div>", unsafe_allow_html=True)
with _lbl_col:
    st.markdown(
        """
        <div style="padding-top:0.25rem">
          <b>Semantisches Matching</b>
          <span style="background:#6366f1;color:#fff;border-radius:5px;
                       padding:2px 8px;font-size:0.7em;font-weight:700;
                       letter-spacing:0.07em;vertical-align:middle">BETA</span><br>
          <span style="font-size:0.82em;color:#888">
            Findet Seiten, die thematisch passen, auch ohne exakte Keyword-Treffer.
          </span>
        </div>
        """,
        unsafe_allow_html=True,
    )
if st.session_state.get("semantic_search"):
    st.slider(
        "Semantik-Schwellenwert",
        min_value=0.0,
        max_value=1.0,
        step=0.01,
        key="semantic_threshold",
        help="Mindestwert für die semantische Ähnlichkeit (0 = alles, 1 = exakte Übereinstimmung). Niedrigere Werte liefern mehr, aber ungenauere Treffer.",
    )
    st.caption(f"Aktiver Schwellenwert: {st.session_state['semantic_threshold']:.2f}")

# ── Auto-save settings after every rerun ─────────────────────────────────────
# Save from infotosearch_input (widget key) — infotosearch can be stale after navigation.
_current_keywords = st.session_state.get("infotosearch_input", "")
save_local_settings({
    "website": st.session_state.get("website", ""),
    "infotosearch": _current_keywords,
    "category_input": st.session_state.get("category_input", CATEGORY_OPTIONS[0]),
    "keywords_selection": st.session_state.get("keywords_selection", []),
    "max_pages": int(st.session_state.get("max_pages", DEFAULT_SETTINGS["max_pages"])),
    "max_depth": int(st.session_state.get("max_depth", DEFAULT_SETTINGS["max_depth"])),
    "semantic_search": bool(st.session_state.get("semantic_search", False)),
    "semantic_threshold": float(st.session_state.get("semantic_threshold", DEFAULT_SETTINGS["semantic_threshold"])),
})

# ── Start button ──────────────────────────────────────────────────────────────
if st.button(
    "Crawling starten",
    disabled=not st.session_state.get("website"),
):
    if not checkUrlValid(st.session_state["website"]):
        st.error("Ungültige Start-URL")
    elif not checkUrlReachable(st.session_state["website"]):
        st.error("Start-URL ist nicht erreichbar")
    else:
        # Sync widget → canonical keys before snapshot
        _kw_snapshot = st.session_state.get("infotosearch_input", "")
        st.session_state["infotosearch"] = _kw_snapshot
        _sem_enabled = bool(st.session_state.get("semantic_search", False))
        _sem_threshold = float(st.session_state.get("semantic_threshold", DEFAULT_SETTINGS["semantic_threshold"]))
        _request_id = str(uuid.uuid4())
        st.session_state["crawl_requested"] = True
        st.session_state["crawl_request_id"] = _request_id
        st.session_state["last_processed_crawl_request_id"] = None

        st.session_state["crawl_payload"] = {
            "request_id": _request_id,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "website": st.session_state.get("website", ""),
            "keywords": _kw_snapshot,
            "max_pages": int(st.session_state.get("max_pages", DEFAULT_SETTINGS["max_pages"])),
            "max_depth": int(st.session_state.get("max_depth", DEFAULT_SETTINGS["max_depth"])),
            "semantic_search": _sem_enabled,
            "semantic_threshold": _sem_threshold,
            "use_playwright": True,
        }

        # Clear old result state
        st.session_state["crawling"] = True
        st.session_state["crawling_completed"] = False
        st.session_state["crawl_error"] = ""
        st.session_state["crawl_result_rows"] = []
        st.session_state["crawl_result_rows_all"] = []
        st.session_state["original_crawl_result_rows"] = []
        st.session_state["crawl_debug_logs"] = []
        st.session_state["crawl_pipeline_stats"] = None
        st.session_state["crawl_semantic_stats"] = None

        st.switch_page("pages/crawlPage.py")

st.markdown("---")
st.caption("Webcrawler-UI 2.0")
