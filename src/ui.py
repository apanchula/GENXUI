"""Shared UI chrome. Call `compact_layout()` right after `st.set_page_config`
on every page."""
import streamlit as st

_CSS = """
<style>
/* Transparent toolbar so the page title can sit at the same height as the
   sidebar "GenXUI" without being hidden (the toolbar buttons stay on the far
   right, clear of the left-aligned title). */
[data-testid="stHeader"] { background: transparent; }

/* Main content pulled right up. */
.block-container,
[data-testid="stMainBlockContainer"] {
    padding-top: 1.1rem;
    padding-bottom: 2rem;
}
/* Smaller page titles (st.title renders a chunky h1). */
[data-testid="stMainBlockContainer"] h1 {
    font-size: 1.7rem;
    line-height: 1.3;
    padding-top: 0;
    padding-bottom: 0.4rem;
}
/* Slightly tighter default spacing between stacked elements. */
[data-testid="stMainBlockContainer"] [data-testid="stVerticalBlock"] { gap: 0.75rem; }

/* Sidebar: raise everything toward the top, but keep room for the collapse
   chevron that lives in stSidebarHeader. */
[data-testid="stSidebar"] > div:first-child { padding-top: 0; }
[data-testid="stSidebarHeader"] { padding-top: 0.4rem; padding-bottom: 0; }
[data-testid="stSidebarNav"] { padding-top: 0; margin-top: 0; }
[data-testid="stSidebarNav"] ul { padding-top: 0.15rem; padding-bottom: 0.25rem; }
[data-testid="stSidebarUserContent"] { padding-top: 0.5rem; }

/* "GenXUI" brand — pulled up onto the header row, sharing it with the
   collapse chevron (chevron is right-aligned, this is left-aligned with the
   nav links, so they don't collide). */
[data-testid="stSidebarNav"]::before {
    content: "GenXUI";
    display: block;
    font-size: 1.7rem;
    font-weight: 700;
    line-height: 1.3;
    margin-top: -1.9rem;
    padding: 0 0 0.35rem 0.5rem;
}
</style>
"""


def compact_layout() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)
