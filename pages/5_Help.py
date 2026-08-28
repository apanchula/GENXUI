"""Help & GenX.jl Reference (GENXUI-3).

Pure reference — renders without a configured workspace. Content comes from
`src/help_docs.py` (a bundled GenX docs snapshot, or a live GenX.jl checkout).
"""
import streamlit as st

from src import help_docs, ui

st.set_page_config(page_title="GenX – Help", layout="wide")
ui.compact_layout()

st.title("Help & GenX.jl Reference")
st.caption(
    "Reference material from the GenX.jl documentation. "
    "Inline versions of this appear next to the settings and input tables on the **Inputs** page."
)

_topics = help_docs.topics()
_slug_to_title = {t.slug: t.title for t in _topics}

with st.sidebar:
    st.title("GenX Help")
    st.link_button("📖 Full GenX.jl docs", help_docs.hosted_docs_url(), width="stretch")
    if any(not t.available for t in _topics):
        st.caption("⚠ Some reference sections could not be loaded.")

# ── Search ───────────────────────────────────────────────────────────────────
query = st.text_input("Search the reference", placeholder="e.g. time domain, CO2 cap, unit commitment")

if query.strip():
    hits = help_docs.search(query)
    if not hits:
        st.info(f"No matches for **{query}**.")
    else:
        st.caption(f"{len(hits)} match(es)")
        for i, hit in enumerate(hits):
            with st.container(border=True):
                st.markdown(f"**{hit.section}**  \n<small>{hit.topic_title}</small>",
                            unsafe_allow_html=True)
                st.write(hit.snippet)
                if st.button("Open section ↴", key=f"jump_{i}"):
                    st.session_state["help_open_topic"] = hit.topic_slug
                    st.rerun()
    st.divider()

# ── Topics ───────────────────────────────────────────────────────────────────
_open = st.session_state.pop("help_open_topic", None)

for topic in _topics:
    with st.expander(topic.title, expanded=(topic.slug == _open)):
        if not topic.available:
            st.warning("This reference section is not available in the current install.")
        else:
            st.markdown(help_docs.topic_body(topic.slug))
