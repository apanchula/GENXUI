import pandas as pd
import streamlit as st
import yaml
from pathlib import Path

st.set_page_config(page_title="GenX – Inputs", layout="wide")

GENX_ROOT = Path(__file__).parent.parent.parent / "GenX.jl"
TREE_DIRS  = ["resources", "system", "policies", "settings"]

# ── Session state ─────────────────────────────────────────────────────────────
if "inputs_selected" not in st.session_state:
    st.session_state.inputs_selected = None


# ── Sidebar: case selector + file tree ───────────────────────────────────────
with st.sidebar:
    st.title("GenX Inputs")

    cases = sorted([
        d.name for d in GENX_ROOT.iterdir()
        if d.is_dir() and (d / "Run.jl").exists()
    ])
    case_name = st.selectbox("Case", cases)
    case_path = GENX_ROOT / case_name

    st.divider()

    # Inject CSS: make sidebar buttons look like tree items
    st.markdown("""
    <style>
    section[data-testid="stSidebar"] div.stButton > button {
        text-align: left;
        background: transparent;
        border: none;
        padding: 2px 6px;
        font-size: 0.85rem;
        width: 100%;
        color: inherit;
    }
    section[data-testid="stSidebar"] div.stButton > button:hover {
        background: rgba(255,255,255,0.08);
        border: none;
    }
    </style>
    """, unsafe_allow_html=True)

    st.link_button(
        "📖 GenX Input Docs",
        "https://genxproject.github.io/GenX.jl/stable/User_Guide/model_input/",
        use_container_width=True,
    )
    st.divider()

    for dir_name in TREE_DIRS:
        dir_path = case_path / dir_name
        if not dir_path.exists():
            continue
        files = sorted(dir_path.glob("*.csv")) + sorted(dir_path.glob("*.yml"))
        if not files:
            continue

        with st.expander(f"📁  {dir_name}", expanded=True):
            for fp in files:
                is_active = st.session_state.inputs_selected == str(fp)
                label = f"{'▶ ' if is_active else '    '}📄 {fp.name}"
                if st.button(label, key=f"tree_{fp}"):
                    st.session_state.inputs_selected = str(fp)
                    st.rerun()


# ── Helpers ───────────────────────────────────────────────────────────────────
@st.cache_data
def _read_csv(path_str: str, mtime: float) -> pd.DataFrame:
    return pd.read_csv(path_str)


def load_csv(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        st.warning(f"`{path.name}` not found.")
        return None
    return _read_csv(str(path), path.stat().st_mtime)


def save_df(df: pd.DataFrame, path: Path, key: str):
    if st.button("💾 Save", key=key, type="primary"):
        df.to_csv(path, index=False)
        st.cache_data.clear()
        st.success(f"Saved `{path.name}`")


# ── Main content ──────────────────────────────────────────────────────────────
selected = st.session_state.inputs_selected

if not selected:
    st.title("Inputs")
    st.info("Select a file from the directory tree on the left.")
    st.stop()

sel_path = Path(selected)

# If case switched, deselect stale path
if not sel_path.exists():
    st.session_state.inputs_selected = None
    st.rerun()

col_title, col_reload = st.columns([5, 1])
with col_title:
    st.title(sel_path.name)
    st.caption(f"`{sel_path}`")
with col_reload:
    st.write("")
    if st.button("🔄 Reload", help="Discard unsaved edits and reload from disk"):
        st.cache_data.clear()
        st.rerun()
st.divider()

folder = sel_path.parent.name

# ── YAML files ────────────────────────────────────────────────────────────────
if sel_path.suffix == ".yml":
    raw = yaml.safe_load(sel_path.read_text()) or {}
    kv_df = pd.DataFrame(
        [(k, v) for k, v in raw.items()],
        columns=["Setting", "Value"],
    )
    edited_kv = st.data_editor(
        kv_df,
        disabled=["Setting"],
        width="stretch",
        key=f"yml_{sel_path.name}",
    )
    if st.button("💾 Save", type="primary", key=f"save_yml_{sel_path.name}"):
        updated = dict(zip(edited_kv["Setting"], edited_kv["Value"]))
        sel_path.write_text(yaml.dump(updated, default_flow_style=False, sort_keys=False))
        st.cache_data.clear()
        st.success(f"Saved `{sel_path.name}`")
    st.stop()

df = load_csv(sel_path)
if df is None:
    st.stop()


# ── Resources: small editable table ──────────────────────────────────────────
if folder in ("resources", "policies"):
    if df.empty:
        st.info("No data rows — file contains only a header.")
        st.code(sel_path.read_text().splitlines()[0])
    else:
        edited = st.data_editor(
            df,
            num_rows="dynamic",
            width="stretch",
            key=f"editor_{sel_path.name}",
        )
        save_df(edited, sel_path, key=f"save_{sel_path.name}")

# ── System / Demand_data: editable NSE segments + demand chart ────────────────
elif sel_path.name == "Demand_data.csv":
    segment_cols = [
        "Voll", "Demand_Segment",
        "Cost_of_Demand_Curtailment_per_MW",
        "Max_Demand_Curtailment", "$/MWh",
    ]

    seg_df = df.dropna(subset=["Demand_Segment"]).copy()
    seg_df = seg_df[[c for c in segment_cols if c in seg_df.columns]]

    st.markdown("**NSE segments**")
    edited_seg = st.data_editor(seg_df, width="stretch", key="seg_editor")

    demand_cols = [c for c in df.columns if c.startswith("Demand_MW")]
    if demand_cols and "Time_Index" in df.columns:
        st.markdown("**Demand profile (MW)**")
        plot_df = df[["Time_Index"] + demand_cols].dropna()
        st.line_chart(plot_df.set_index("Time_Index"), height=250)

    if st.button("💾 Save NSE segments", type="primary"):
        for col in edited_seg.columns:
            df.loc[df["Demand_Segment"].notna(), col] = edited_seg[col].values
        df.to_csv(sel_path, index=False)
        st.cache_data.clear()
        st.success(f"Saved `{sel_path.name}`")

# ── System / time-series: summary + chart + upload ────────────────────────────
else:
    numeric_cols = df.select_dtypes("number").columns.tolist()
    time_col     = "Time_Index" if "Time_Index" in df.columns else None
    series_cols  = [c for c in numeric_cols if c != "Time_Index"]

    st.markdown(f"**{len(df):,} rows · {len(series_cols)} series column(s)**")

    st.dataframe(
        df[series_cols].describe().T[["min", "mean", "max"]].round(4),
        width="stretch",
    )

    if series_cols:
        st.markdown("**Profile preview**")
        plot_df = df[[time_col] + series_cols].dropna() if time_col else df[series_cols].dropna()
        step = max(1, len(plot_df) // 500)
        sampled = plot_df.iloc[::step]
        if time_col:
            sampled = sampled.set_index(time_col)
        st.line_chart(sampled, height=250)

    st.divider()
    st.markdown("**Replace file**")
    upload = st.file_uploader(
        f"Upload new `{sel_path.name}` (must match column structure)",
        type="csv",
        key=f"upload_{sel_path.name}",
    )
    if upload:
        new_df = pd.read_csv(upload)
        st.dataframe(new_df.head(5), width="stretch")
        if st.button("💾 Save uploaded file", type="primary"):
            new_df.to_csv(sel_path, index=False)
            st.cache_data.clear()
            st.success(f"Saved `{sel_path.name}` ({len(new_df):,} rows)")
