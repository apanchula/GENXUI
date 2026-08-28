"""Shared UI chrome. Call `compact_layout()` right after `st.set_page_config`
on every page."""
import streamlit as st

_CSS = """
<style>
/* Pull the main content up under the toolbar — Streamlit ships ~6rem here. */
.block-container,
[data-testid="stMainBlockContainer"] {
    padding-top: 2.2rem;
    padding-bottom: 2rem;
}
/* Sidebar too. */
[data-testid="stSidebar"] > div:first-child { padding-top: 2rem; }
/* Slightly tighter default spacing between stacked elements. */
[data-testid="stMainBlockContainer"] [data-testid="stVerticalBlock"] { gap: 0.75rem; }
</style>
"""


def compact_layout() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def sidebar_brand() -> None:
    """The 'GenXUI' header at the top of every page's sidebar. Same size as the
    sidebar section subheaders (st.subheader)."""
    st.sidebar.subheader("GenXUI")
