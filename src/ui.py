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
[data-testid="stSidebar"] > div:first-child { padding-top: 1.5rem; }
/* Slightly tighter default spacing between stacked elements. */
[data-testid="stMainBlockContainer"] [data-testid="stVerticalBlock"] { gap: 0.75rem; }

/* "GenXUI" brand — sits above the auto-generated page nav. */
[data-testid="stSidebarNav"]::before {
    content: "GenXUI";
    display: block;
    font-size: 1.75rem;
    font-weight: 700;
    line-height: 1.2;
    padding: 0 0 0.6rem 1.4rem;
}
</style>
"""


def compact_layout() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)
