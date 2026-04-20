import streamlit as st

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