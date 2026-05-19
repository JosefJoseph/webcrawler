import sys
from pathlib import Path
import streamlit as st

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

if 'submitted' not in st.session_state:
    st.session_state.submitted = False

# Callbacks definieren
def update_website():
    st.session_state.website = st.session_state.website_input

def update_infotosearch():
    st.session_state.infotosearch = st.session_state.infotosearch_input

pages = [
    st.Page("pages/mainPage.py", title="Search"),
    st.Page("pages/crawlPage.py", title="Crawler")
]

pg = st.navigation(pages)
pg.run()