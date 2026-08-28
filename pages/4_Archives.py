import pandas as pd
import streamlit as st
from pathlib import Path

import archive_lib
from src import ui, workspace

st.set_page_config(page_title="GenX – Archives", layout="wide")
ui.compact_layout()
ui.sidebar_brand()

if workspace.get_workspace_root() is None:
    st.title("Archives")
    st.info("No workspace configured yet. Set one up from the **Runner** page first.")
    st.stop()

GENX_ROOT = workspace.legacy_genx_root()  # GenX.jl solver checkout, used only for git-commit tracking

st.title("Archives")
st.caption(f"`{workspace.archive_dir()}`")

archives = archive_lib.list_archives()

if not archives:
    st.info(
        "No archived runs yet. Go to the **Results** page, select a live case, "
        "and click **Archive this run**."
    )
    st.stop()

# ── Browse table ──────────────────────────────────────────────────────────────
table_rows = []
for m in archives:
    metrics = m.get("metrics", {})
    table_rows.append({
        "Case":          m["case_name"],
        "Label":         m.get("label") or "",
        "Archived At":   m["archived_at"][:19],
        "Commit":        m.get("genx_commit") or "unknown",
        "Total Cost ($M/yr)": metrics.get("total_system_cost_musd_per_yr"),
        "NSE (% of load)":    metrics.get("nse_pct_of_demand"),
        "Capacity (MW)":      metrics.get("total_capacity_mw"),
    })

st.dataframe(
    pd.DataFrame(table_rows),
    hide_index=True,
    width="stretch",
    column_config={
        "Total Cost ($M/yr)": st.column_config.NumberColumn(format="$%.2f"),
        "NSE (% of load)":    st.column_config.NumberColumn(format="%.2f%%"),
        "Capacity (MW)":      st.column_config.NumberColumn(format="%.1f"),
    },
)

st.divider()

# ── Detail panel for one selected archive ────────────────────────────────────
st.subheader("Archive details")

labels = [
    f"{m['case_name']} — {m.get('label') or 'unlabeled'} — {m['archived_at'][:19]}"
    for m in archives
]
sel_idx = st.selectbox("Select an archive", range(len(archives)), format_func=lambda i: labels[i])
manifest = archives[sel_idx]
archive_dir = Path(manifest["path"])

col_info, col_actions = st.columns([2, 1])

with col_info:
    st.markdown(f"**Case:** {manifest['case_name']}")
    st.markdown(f"**Label:** {manifest.get('label') or '_none_'}")
    st.markdown(f"**Archived at:** {manifest['archived_at']}")
    st.markdown(f"**GenX.jl commit:** `{manifest.get('genx_commit') or 'unknown'}`")

    mismatch = archive_lib.check_commit_mismatch(manifest, GENX_ROOT)
    if mismatch:
        st.warning(mismatch)

    metrics = manifest.get("metrics", {})
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total System Cost", f"${metrics.get('total_system_cost_musd_per_yr') or 0:.2f}M/yr")
    m2.metric("Unserved Energy", f"{metrics.get('nse_pct_of_demand') or 0:.2f}% of load")
    m3.metric("Total Capacity", f"{metrics.get('total_capacity_mw') or 0:.1f} MW")
    m4.metric("Total Energy Cap", f"{metrics.get('total_energy_capacity_mwh') or 0:.1f} MWh")

with col_actions:
    if st.button("📊 View dashboard", width="stretch"):
        st.session_state["archive_to_view"] = manifest["archive_dir_name"]
        st.switch_page("pages/3_Results.py")

    st.download_button(
        "⬇ Download .zip",
        data=archive_lib.build_zip_bytes(archive_dir),
        file_name=f"{archive_dir.name}.zip",
        mime="application/zip",
        width="stretch",
    )

    if st.button("🔁 Recreate as new case", width="stretch"):
        try:
            new_case_dir = archive_lib.restore_archive_to_new_case(archive_dir)
            st.session_state["_restored_case"] = new_case_dir.name
            st.success(f"Restored inputs to `{new_case_dir.name}`")
        except archive_lib.ArchiveError as e:
            st.error(str(e))

    restored_case = st.session_state.get("_restored_case")
    if restored_case:
        st.caption(f"Ready to run: `{restored_case}`")
        go_disabled = bool(st.session_state.get("running"))
        if go_disabled:
            st.caption("⚠ A run is in progress on the Runner page — finish or clear it before switching cases.")
        if st.button("▶ Go to Runner", width="stretch", disabled=go_disabled):
            st.session_state["_preselect_case"] = restored_case
            del st.session_state["_restored_case"]
            st.switch_page("App.py")
