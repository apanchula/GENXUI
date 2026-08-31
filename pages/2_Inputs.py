import math

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import yaml
from pathlib import Path

import archive_lib
from src import fleet_view, help_docs, ui, workspace

st.set_page_config(page_title="GenX – Inputs", layout="wide")
ui.compact_layout()

if workspace.get_workspace_root() is None:
    st.title("Inputs")
    st.info("No workspace configured yet. Set one up from the **Runner** page first.")
    st.stop()

TREE_DIRS = ["resources", "system", "policies", "settings"]
ALL_RESOURCES = "::all_resources"   # sentinel for the cross-file resources view

# ── Session state ─────────────────────────────────────────────────────────────
if "inputs_selected" not in st.session_state:
    st.session_state.inputs_selected = None


# ── Sidebar: case selector + file tree ───────────────────────────────────────
with st.sidebar:
    st.subheader("Case")

    cases = workspace.discover_cases()
    if not cases:
        st.info(f"No cases in `{workspace.data_dir()}`. Import one from the **Runner** page.")
        st.stop()

    _default_case = st.session_state.get("selected_case")
    _default_idx = cases.index(_default_case) if _default_case in cases else 0
    case_name = st.selectbox("Case", cases, index=_default_idx, label_visibility="collapsed")
    case_path = workspace.data_dir() / case_name

    # Switching Case leaves inputs_selected pointing at the previous case's file
    # (which still exists on disk, so the "stale path" guard below never fires).
    # Carry the selection over to the same file in the new case if it exists,
    # otherwise drop it so the user gets the "pick a file" prompt.
    _sel = st.session_state.inputs_selected
    if _sel and _sel != ALL_RESOURCES and not Path(_sel).is_relative_to(case_path):
        for _root in (workspace.data_dir() / c for c in cases):
            if Path(_sel).is_relative_to(_root):
                _rel = Path(_sel).relative_to(_root)
                _new = case_path / _rel
                st.session_state.inputs_selected = str(_new) if _new.exists() else None
                break
        else:
            st.session_state.inputs_selected = None

    # Inject CSS: make the sidebar file buttons read as a compact, flat tree.
    # Streamlit's default button paints a filled "secondary" background and a
    # focus/active box-shadow — both are forced off here so the row is just text
    # that tints on hover, with the highlight covering the whole row.
    st.markdown("""
    <style>
    section[data-testid="stSidebar"] div.stButton > button,
    section[data-testid="stSidebar"] div.stButton > button:hover,
    section[data-testid="stSidebar"] div.stButton > button:active,
    section[data-testid="stSidebar"] div.stButton > button:focus,
    section[data-testid="stSidebar"] div.stButton > button:focus-visible {
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        outline: none !important;
        color: inherit !important;
        text-align: left;
        width: 100%;
        min-height: 0;
        height: 1.55rem;
        line-height: 1.55rem;
        padding: 0 6px;
        font-size: 0.82rem;
        border-radius: 4px;
        overflow: hidden;
        white-space: nowrap;
    }
    section[data-testid="stSidebar"] div.stButton > button p {
        line-height: 1.55rem;
        margin: 0;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        max-width: 100%;
    }
    section[data-testid="stSidebar"] div.stButton > button:hover {
        background: rgba(128,128,128,0.18) !important;
    }
    /* tighten the vertical gap between consecutive tree rows */
    section[data-testid="stSidebar"] [data-testid="stExpanderDetails"] [data-testid="stVerticalBlock"] {
        gap: 0.1rem;
    }
    section[data-testid="stSidebar"] [data-testid="stExpanderDetails"] { padding-top: 0.25rem; }
    </style>
    """, unsafe_allow_html=True)

    _has_resource_files = any(
        (case_path / "resources" / f).exists() for f in fleet_view.RESOURCE_FILES
    )
    if _has_resource_files:
        st.subheader("Graph")
        _all_active = st.session_state.inputs_selected == ALL_RESOURCES
        if st.button(f"{'▶' if _all_active else '▷'} ★ All Resources Graph", key="tree_all_resources"):
            st.session_state.inputs_selected = ALL_RESOURCES
            st.rerun()

    st.subheader("Files")
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
                # ▶/▷ are a same-width pair; a leading run of spaces would be
                # parsed by markdown as an indented code block (taller, boxed),
                # which is what made the selected row jump out of line.
                label = f"{'▶' if is_active else '▷'} 📄 {fp.name}"
                if st.button(label, key=f"tree_{fp}"):
                    st.session_state.inputs_selected = str(fp)
                    st.rerun()

    st.divider()
    st.link_button(
        "📖 GenX Input Docs",
        "https://genxproject.github.io/GenX.jl/stable/User_Guide/model_input/",
        width="stretch",
    )


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


def replace_file_uploader(path: Path):
    st.divider()
    st.markdown("**Replace file**")
    upload = st.file_uploader(
        f"Upload new `{path.name}` (must match column structure)",
        type="csv",
        key=f"upload_{path.name}",
    )
    if upload:
        new_df = pd.read_csv(upload)
        st.dataframe(new_df.head(5), width="stretch")
        if st.button("💾 Save uploaded file", type="primary"):
            new_df.to_csv(path, index=False)
            st.cache_data.clear()
            st.success(f"Saved `{path.name}` ({len(new_df):,} rows)")


# ── Inline GenX reference (GENXUI-3) ─────────────────────────────────────────
def render_settings_help(keys) -> None:
    """A collapsed reference block for the genx_settings.yml keys in this file."""
    entries = [(k, help_docs.settings_help(str(k))) for k in keys]
    entries = [(k, h) for k, h in entries if h]
    if not entries:
        return
    with st.expander("ℹ️ Settings reference", expanded=False):
        for k, h in entries:
            st.markdown(f"**`{k}`** — {h.as_markdown()}")
        st.caption("Source: GenX.jl docs · see the **Help** page for the full reference.")


def render_column_help(file_stem: str, columns) -> None:
    """A collapsed reference block for the documented columns present in this CSV."""
    docs = help_docs.documented_columns(file_stem, [str(c) for c in columns])
    if not docs:
        return
    with st.expander("ℹ️ Column reference", expanded=False):
        for col, desc in docs:
            st.markdown(f"**`{col}`** — {desc}")
        st.caption("Source: GenX.jl docs · see the **Help** page for the full reference.")


# ── Fleet view (resource Overview) ───────────────────────────────────────────
def _type_color_map(resources) -> dict[str, str]:
    m: dict[str, str] = {}
    for r in resources:
        m.setdefault(r.type, r.color)
    return m


def _bus_figure(layout: dict, uniform: bool) -> go.Figure:
    fig = go.Figure()
    # tie lines between zone hubs
    for x0, y0, x1, y1 in layout["ties"]:
        fig.add_trace(go.Scatter(
            x=[x0, x1], y=[y0, y1], mode="lines",
            line=dict(color="rgba(128,128,128,0.55)", width=4),
            hoverinfo="skip", showlegend=False,
        ))
    # resource -> hub spokes
    for x0, y0, x1, y1 in layout["spokes"]:
        fig.add_trace(go.Scatter(
            x=[x0, x1], y=[y0, y1], mode="lines",
            line=dict(color="rgba(128,128,128,0.30)", width=1),
            hoverinfo="skip", showlegend=False,
        ))
    # hub -> load stubs
    for x0, y0, x1, y1 in layout.get("load_edges", []):
        fig.add_trace(go.Scatter(
            x=[x0, x1], y=[y0, y1], mode="lines",
            line=dict(color="rgba(192,57,43,0.55)", width=2, dash="dot"),
            hoverinfo="skip", showlegend=False,
        ))
    # load nodes (demand centres)
    loads = layout.get("loads", [])
    if loads:
        mx = max((ld["mw"] for ld in loads), default=1.0) or 1.0
        fig.add_trace(go.Scatter(
            x=[ld["x"] for ld in loads], y=[ld["y"] for ld in loads],
            mode="markers",
            marker=dict(symbol="triangle-down", line=dict(width=1, color="white"),
                        color="#c0392b",
                        size=[14 + 22 * math.sqrt(ld["mw"] / mx) for ld in loads]),
            customdata=[[ld["zone"], ld["mw"]] for ld in loads],
            hovertemplate="load · zone %{customdata[0]}<br>peak %{customdata[1]:,.0f} MW<extra></extra>",
            showlegend=False,
        ))
    # hub nodes
    if layout["hubs"]:
        fig.add_trace(go.Scatter(
            x=[h["x"] for h in layout["hubs"]],
            y=[h["y"] for h in layout["hubs"]],
            mode="markers+text",
            marker=dict(symbol="square", size=22, color="rgba(128,128,128,0.85)"),
            text=[h["label"] for h in layout["hubs"]],
            textposition="bottom center", textfont=dict(size=11),
            hovertemplate="bus %{text}<extra></extra>", showlegend=False,
        ))
    # resource nodes
    nodes = layout["nodes"]
    if nodes:
        if uniform:
            marker_size = [16] * len(nodes)
        else:
            mx = max((n["size"] for n in nodes), default=1.0) or 1.0
            marker_size = [12 + 26 * math.sqrt(max(0.0, n["size"]) / mx) for n in nodes]
        fig.add_trace(go.Scatter(
            x=[n["x"] for n in nodes], y=[n["y"] for n in nodes],
            mode="markers",
            marker=dict(size=marker_size, color=[n["color"] for n in nodes],
                        line=dict(width=1, color="white")),
            text=[n["name"] for n in nodes],
            customdata=[[n["type"], n["zone"]] for n in nodes],
            hovertemplate="<b>%{text}</b><br>%{customdata[0]} · zone %{customdata[1]}<extra></extra>",
            showlegend=False,
        ))
    fig.update_layout(
        height=420, margin=dict(t=10, l=0, r=0, b=0),
        xaxis=dict(visible=False), yaxis=dict(visible=False, scaleanchor="x", scaleratio=1),
        plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def render_fleet_overview(case_path: Path, key: str = "all") -> None:
    """Combined graphical view over every resource file in the case."""
    loaded = fleet_view.load_fleet(case_path, include_absent=True)
    resources = [r for r in loaded if r.exists]
    hidden = len(loaded) - len(resources)

    if not resources:
        msg = "No resources to visualize in this case."
        if hidden:
            msg = (f"All {hidden} resource row(s) here are non-existent "
                   "(no existing capacity, and neither buildable nor retireable).")
        st.info(msg)
        return

    m = fleet_view.fleet_metrics(resources)
    demand = fleet_view.read_zone_demand(case_path)
    metric_label = st.radio("Size by", list(fleet_view.SIZE_METRICS),
                            horizontal=True, key=f"fv_size_{key}")
    sizes, uniform, note = fleet_view.size_series(resources, fleet_view.SIZE_METRICS[metric_label])

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Resources", m["count"])
    c2.metric("Zones", m["n_zones"])
    c3.metric("Built capacity", f"{m['existing_total_mw']:,.0f} MW")
    c4.metric("New-build candidates", m["candidate_count"])
    c5.metric("Peak demand", f"{sum(demand.values()):,.0f} MW" if demand else "—")
    st.caption(" · ".join(f"{t}: {n}" for t, n in m["by_type"].items()))
    if hidden:
        st.caption(f"{hidden} non-existent row(s) hidden — no existing capacity, "
                   "not buildable, not retireable.")
    if note:
        st.caption(f"⚠ {note}")

    frame = fleet_view.fleet_frame(resources, sizes)
    tree = px.treemap(
        frame, path=[px.Constant("fleet"), "Zone", "Type", "Resource"], values="Size",
        color="Type", color_discrete_map=_type_color_map(resources),
        custom_data=["Existing_MW", "Max_MW", "New_Build"],
    )
    tree.update_traces(
        root_color="rgba(0,0,0,0)",
        hovertemplate="<b>%{label}</b><br>existing %{customdata[0]:,.0f} MW · "
                      "max %{customdata[1]} · new build %{customdata[2]}<extra></extra>",
    )
    tree.update_layout(height=340, margin=dict(t=10, l=0, r=0, b=0))
    st.markdown("**Composition**")
    st.plotly_chart(tree, width="stretch", key=f"fv_tree_{key}")

    st.markdown("**Zone / bus topology**")
    ties = fleet_view.read_network_lines(case_path)
    layout = fleet_view.bus_layout(resources, sizes, ties, demand)
    st.plotly_chart(_bus_figure(layout, uniform), width="stretch", key=f"fv_bus_{key}")

    _notes = ["🔻 red = per-zone demand centre (peak MW)"] if demand else \
             ["no `system/Demand_data.csv` — demand centres not shown"]
    if not ties and m["n_zones"] > 1:
        _notes.append("no `system/Network.csv` — hubs shown without tie-lines")
    st.caption(" · ".join(_notes))


# ── Main content ──────────────────────────────────────────────────────────────
selected = st.session_state.inputs_selected

if not selected:
    st.title("Inputs")
    st.info("Select a file from the directory tree on the left.")
    st.stop()

if selected == ALL_RESOURCES:
    st.title("All Resources Graph")
    st.caption(f"`{case_name}` · every resource file combined")
    st.divider()
    render_fleet_overview(case_path)
    st.stop()

sel_path = Path(selected)

# If case switched, deselect stale path
if not sel_path.exists():
    st.session_state.inputs_selected = None
    st.rerun()

col_title, col_reload = st.columns([5, 1])
with col_title:
    st.title(sel_path.name)
    st.caption(f"`{archive_lib.short_path(sel_path, workspace.data_dir())}`")
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
    render_settings_help(raw.keys())
    st.stop()

df = load_csv(sel_path)
if df is None:
    st.stop()

render_column_help(sel_path.stem, df.columns)


# ── Resources: editable table + graphical Overview ──────────────────────────
def _resource_editor(frame: pd.DataFrame) -> None:
    if frame.empty:
        st.info("No data rows — file contains only a header.")
        st.code(sel_path.read_text().splitlines()[0])
        return
    edited = st.data_editor(
        frame, num_rows="dynamic", width="stretch", key=f"editor_{sel_path.name}",
    )
    save_df(edited, sel_path, key=f"save_{sel_path.name}")


if folder in ("resources", "policies"):
    _resource_editor(df)

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

# ── System / Network: full table of line parameters (not a time series) ───────
elif sel_path.name == "Network.csv":
    show = df.copy()
    if show.columns[0].startswith("Unnamed:"):
        show = show.rename(columns={show.columns[0]: "Zone"}).set_index("Zone")

    st.markdown(f"**{len(show):,} row(s) · {show.shape[1]} column(s)**")
    st.dataframe(show, width="stretch")

    replace_file_uploader(sel_path)

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

    replace_file_uploader(sel_path)
