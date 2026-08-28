"""Shared UI chrome. Call `compact_layout()` right after `st.set_page_config`
on every page."""
import streamlit as st

_CSS = """
<style>
/* Pull the main content up under the toolbar — Streamlit ships ~6rem here. */
.block-container,
[data-testid="stMainBlockContainer"] {
    padding-top: 2rem;
    padding-bottom: 2rem;
}
/* Smaller page titles (st.title renders a chunky h1). */
[data-testid="stMainBlockContainer"] h1 {
    font-size: 1.6rem;
    padding-top: 0;
    padding-bottom: 0.4rem;
}
/* Slightly tighter default spacing between stacked elements. */
[data-testid="stMainBlockContainer"] [data-testid="stVerticalBlock"] { gap: 0.75rem; }

/* Sidebar: pull everything up toward the toolbar. */
[data-testid="stSidebar"] > div:first-child { padding-top: 0.5rem; }
[data-testid="stSidebarHeader"] { padding-top: 0.25rem; padding-bottom: 0.25rem; }
[data-testid="stSidebarNav"] { padding-top: 0; margin-top: 0; }
[data-testid="stSidebarUserContent"] { padding-top: 0.5rem; }

/* "GenXUI" brand — sits above the auto-generated page nav. */
[data-testid="stSidebarNav"]::before {
    content: "GenXUI";
    display: block;
    font-size: 1.7rem;
    font-weight: 700;
    line-height: 1.2;
    padding: 0 0 0.5rem 1.4rem;
}
</style>
"""


def compact_layout() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)
