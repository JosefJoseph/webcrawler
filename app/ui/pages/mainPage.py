import streamlit as st

if 'website' not in st.session_state:
    st.session_state.website = ""
if 'infotosearch' not in st.session_state:
    st.session_state.infotosearch = ""
if 'max_pages' not in st.session_state:
    st.session_state.max_pages = 20
if 'max_depth' not in st.session_state:
    st.session_state.max_depth = 2
if 'use_playwright' not in st.session_state:
    st.session_state.use_playwright = True

def update_website():
    st.session_state.website = st.session_state.website_input

def update_infotosearch():
    st.session_state.infotosearch = st.session_state.infotosearch_input


def update_max_pages():
    st.session_state.max_pages = st.session_state.max_pages_input


def update_max_depth():
    st.session_state.max_depth = st.session_state.max_depth_input


def update_use_playwright():
    st.session_state.use_playwright = st.session_state.use_playwright_input

st.title('Webcrawler')

st.subheader("Crawl-Konfiguration")

st.text_input(
    'Start-URL', 
    value=st.session_state.website,
    key='website_input',
    on_change=update_website,
    placeholder='z.B. https://world.openfoodfacts.org/, https://fdc.nal.usda.gov/'
)
st.text_area(
    'Keywords (kommagetrennt)',
    value=st.session_state.infotosearch,
    key='infotosearch_input', 
    on_change=update_infotosearch,
    placeholder='z.B. nutrition facts, Food Category, ingredients, allergens'
)

col1, col2 = st.columns(2)

with col1:
    st.number_input(
        'Maximale Seiten',
        min_value=1,
        max_value=500,
        value=st.session_state.max_pages,
        step=1,
        key='max_pages_input',
        on_change=update_max_pages,
    )

with col2:
    st.number_input(
        'Maximale Tiefe',
        min_value=0,
        max_value=10,
        value=st.session_state.max_depth,
        step=1,
        key='max_depth_input',
        on_change=update_max_depth,
    )

st.toggle(
    'JavaScript-Seiten mit Playwright laden',
    value=st.session_state.use_playwright,
    key='use_playwright_input',
    on_change=update_use_playwright,
)

if st.button('Crawling starten', disabled=not st.session_state.website):
    st.session_state.crawling = True
    st.session_state.crawling_completed = False
    st.session_state.crawl_error = ""
    st.session_state.crawl_result_rows = []
    st.session_state.crawl_debug_logs = []
    st.session_state.last_crawl_signature = None
    st.switch_page("pages/crawlPage.py")

st.markdown("---")

# Versionnummer
st.caption("Webcrawler-UI 1.2")