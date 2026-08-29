from datetime import datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from pathlib import Path

import archive_lib
import report_lib
from src import metrics, ui, workspace
from src.resource_style import resource_color, type_color

st.set_page_config(page_title="GenX – Results", layout="wide")
ui.compact_layout()

if workspace.get_workspace_root() is None:
    st.title("Results")
    st.info("No workspace configured yet. Set one up from the **Runner** page first.")
    st.stop()

GENX_ROOT = workspace.legacy_genx_root()  # GenX.jl solver checkout, used only for git-commit tracking

# ── Sidebar ───────────────────────────────────────────────────────────────────
_archives = archive_lib.list_archives()
_pending_archive = st.session_state.pop("archive_to_view", None)

with st.sidebar:
    st.subheader("Source")

    source_options = ["Live case", "Archived run"]
    default_source = "Archived run" if _pending_archive else "Live case"
    source = st.radio("Data source", source_options, index=source_options.index(default_source))

    is_archived = source == "Archived run"
    archive_manifest: dict | None = None

    if is_archived:
        if not _archives:
            st.info("No archived runs yet. Archive a live run below to see it here.")
            st.stop()
        archive_labels = [
            f"{m['case_name']} — {m.get('label') or 'unlabeled'} — {m['archived_at'][:19]}"
            for m in _archives
        ]
        default_idx = 0
        if _pending_archive:
            for i, m in enumerate(_archives):
                if m.get("archive_dir_name") == _pending_archive:
                    default_idx = i
                    break
        sel_idx = st.selectbox(
            "Archived run", range(len(_archives)),
            format_func=lambda i: archive_labels[i], index=default_idx,
        )
        archive_manifest = _archives[sel_idx]
        case_name = archive_manifest["case_name"]
        results_dir = Path(archive_manifest["path"]) / "results"
        inputs_dir = Path(archive_manifest["path"]) / "inputs"
    else:
        cases = workspace.discover_cases()
        if not cases:
            st.info(f"No cases in `{workspace.data_dir()}`. Import one from the **Runner** page.")
            st.stop()
        _default_case = st.session_state.get("selected_case")
        _default_idx = cases.index(_default_case) if _default_case in cases else 0
        case_name = st.selectbox("Case", cases, index=_default_idx)
        case_path = workspace.data_dir() / case_name
        # GenX may have written results/, or results_1/, results_2/… — show the latest.
        results_dir = workspace.resolve_results_dir(case_path)
        inputs_dir = case_path

    if not is_archived and results_dir is not None:
        st.divider()
        st.markdown("**Archive this run**")
        if st.session_state.get("running"):
            st.caption("⚠ A run may be in progress — results shown could be stale.")
        archive_label = st.text_input("Label (optional)", key="archive_label_input")
        if st.button("📦 Archive this run", width="stretch"):
            try:
                archive_dir = archive_lib.create_archive(case_path, GENX_ROOT, label=archive_label)
                st.success(f"Archived to `{archive_dir.name}`")
            except archive_lib.ArchiveError as e:
                st.error(str(e))

    st.link_button(
        "📖 GenX Output Docs",
        "https://genxproject.github.io/GenX.jl/stable/User_Guide/model_output/",
        width="stretch",
    )

# ── Load results ─────────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def _load(results_dir_str: str, sig: float):
    del sig
    return metrics.load_results(Path(results_dir_str))


def _dir_sig(d: Path) -> float:
    try:
        return max((p.stat().st_mtime for p in d.glob("*.csv")), default=0.0)
    except OSError:
        return 0.0


rs = None if results_dir is None else _load(str(results_dir), _dir_sig(results_dir))

if rs is None:
    st.title("Results")
    st.info(
        f"No results found for **{case_name}**.  \n"
        "Run the model first from the **Runner** page."
    )
    st.stop()

st.title(f"Results — {case_name}")
if is_archived and archive_manifest is not None:
    st.caption(
        f"Archived run — {archive_manifest.get('label') or 'unlabeled'} — "
        f"{archive_manifest['archived_at'][:19]} — "
        f"`{archive_lib.short_path(results_dir, workspace.archive_dir())}`"
    )
else:
    st.caption(f"Live case — `{archive_lib.short_path(results_dir, workspace.data_dir())}`")

if rs.dropped_resources:
    st.caption(
        f"{len(rs.dropped_resources)} resource(s) with zero capacity and zero "
        f"generation are hidden: {', '.join(rs.dropped_resources)}"
    )

# ── Section 1: Key Metrics (zone-aware) ──────────────────────────────────────
st.subheader("Key Metrics")

_zs = metrics.zone_summary(rs)
_comp = metrics.costs_components(rs)
_total_row = _zs[_zs["is_total"]]
_total_cap = float(_total_row["Capacity_MW"].iloc[0]) if not _total_row.empty else 0.0
_total_gen = float(_total_row["Generation_MWh"].iloc[0]) if not _total_row.empty else 0.0
_total_curt = float(_total_row["Curtailment_MWh"].iloc[0]) if not _total_row.empty else 0.0
_nse_mwh = metrics.nse_total_mwh(rs)

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("System cost", f"${_comp.get('cTotal', 0.0) / 1e9:,.2f} B/yr" if _comp else "—")
m2.metric("Built capacity", f"{_total_cap:,.0f} MW")
m3.metric("Annual generation", f"{_total_gen / 1e6:,.1f} TWh")
m4.metric("Curtailment", f"{_total_curt / 1e6:,.1f} TWh",
          f"{100 * _total_curt / _total_gen:.1f}%" if _total_gen > 0 else None,
          delta_color="off")
m5.metric("Unserved energy", f"{_nse_mwh / 1e3:,.1f} GWh")

# ── Levelized cost per asset ────────────────────────────────────────────────
_lcoe = metrics.lcoe_by_resource(rs)
lcoe_styler = None
if _lcoe.empty:
    st.caption("`NetRevenue.csv` / `power.csv` needed for levelized cost.")
else:
    _lv = _lcoe.rename(columns={
        "LCOE_$MWh": "LCOE ($/MWh)", "HardwareCost_$M": "Hardware Cost ($M/yr)",
        "ChargeCost_$M": "Charging Cost ($M/yr)", "AnnualGen_GWh": "Annual Gen (GWh/yr)",
        "GenToLoad_GWh": "Gen to Load (GWh/yr)", "Curtail_GWh": "Curtailment (GWh/yr)",
        "CurtailPct": "Curtail %",
    })
    _lv["Zone"] = _lv["Zone"].map(lambda z: "" if z == "" else f"Zone {z}")
    _cols = ["Resource", "Type", "Zone", "LCOE ($/MWh)", "Hardware Cost ($M/yr)",
             "Charging Cost ($M/yr)", "Annual Gen (GWh/yr)", "Gen to Load (GWh/yr)",
             "Curtailment (GWh/yr)", "Curtail %"]
    _is_total = _lcoe["is_total"].tolist()

    def _bold_total(_row):
        return ["font-weight: bold" if _is_total[_row.name] else ""] * len(_row)

    lcoe_styler = _lv[_cols].style.apply(_bold_total, axis=1).format({
        "LCOE ($/MWh)": "${:.2f}", "Hardware Cost ($M/yr)": "${:.1f}",
        "Charging Cost ($M/yr)": "${:.1f}", "Annual Gen (GWh/yr)": "{:,.0f}",
        "Gen to Load (GWh/yr)": "{:,.0f}", "Curtailment (GWh/yr)": "{:,.0f}",
        "Curtail %": "{:.1f}%",
    }, na_rep="—")
    st.dataframe(lcoe_styler, hide_index=True, width="stretch")
    st.download_button(
        "⬇ Levelized cost (CSV)", _lcoe.drop(columns="is_total").to_csv(index=False).encode(),
        file_name=f"lcoe_{case_name}.csv", mime="text/csv",
    )

# ── Capacity & generation by zone ──────────────────────────────────────────
_flags = list(zip(_zs["is_subtotal"], _zs["is_total"])) if not _zs.empty else []


def _bold(_row):
    sub, tot = _flags[_row.name]
    return ["font-weight: bold" if (sub or tot) else ""] * len(_row)


if not _zs.empty:
    with st.expander("Capacity & generation by zone", expanded=rs.multi_zone):
        _disp = _zs.copy()
        _disp["Capacity (MW)"] = _disp["Capacity_MW"].map(lambda v: f"{v:,.0f}")
        _disp["Generation (GWh)"] = _disp["Generation_MWh"].map(lambda v: f"{v / 1e3:,.0f}")
        _disp["Curtailment (GWh)"] = _disp["Curtailment_MWh"].map(
            lambda v: f"{v / 1e3:,.0f}" if v > 0 else "")
        _disp["Zone"] = _disp["Zone"].map(lambda z: "" if z == "" else f"Zone {z}")
        _view = _disp[["Zone", "Type", "Capacity (MW)", "Generation (GWh)", "Curtailment (GWh)"]]
        st.dataframe(_view.style.apply(_bold, axis=1), hide_index=True, width="stretch")
        st.download_button(
            "⬇ Zone summary (CSV)",
            _zs[["Zone", "Type", "Capacity_MW", "Generation_MWh", "Curtailment_MWh"]]
            .to_csv(index=False).encode(),
            file_name=f"zone_summary_{case_name}.csv", mime="text/csv",
        )

st.divider()

# ── Section 2: Capacity + Supply-to-Load Mix ─────────────────────────────────
cap_fig = None
pie_fig = None

_cap = metrics.capacity_by_resource(rs)
_stl = metrics.supply_to_load(rs)

col_cap, col_pb = st.columns(2)

with col_cap:
    st.subheader("Capacity Built")
    if _cap.empty:
        st.warning("`capacity.csv` has no built resources.")
    else:
        colors = [resource_color(r) for r in _cap["Resource"]]
        cap_fig = go.Figure()
        cap_fig.add_trace(go.Bar(
            name="Power (MW)", x=_cap["Resource"], y=_cap["EndCap_MW"], marker_color=colors,
        ))
        _stor = _cap[_cap["EndEnergy_MWh"] > 0]
        if not _stor.empty:
            cap_fig.add_trace(go.Bar(
                name="Energy (MWh)", x=_stor["Resource"], y=_stor["EndEnergy_MWh"],
                marker_color="#1a7a4a", opacity=0.65,
            ))
        cap_fig.update_layout(
            barmode="group", yaxis_title="Capacity", xaxis_tickangle=-20, height=340,
            margin=dict(t=5, b=5, l=0, r=0),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        st.plotly_chart(cap_fig, width="stretch")

        if not _stor.empty:
            def _small_metric(col, label, value):
                col.markdown(
                    f"<div style='font-size:0.75rem;color:grey;margin-bottom:1px'>{label}</div>"
                    f"<div style='font-size:0.95rem;font-weight:600'>{value}</div>",
                    unsafe_allow_html=True,
                )

            for _, row in _stor.iterrows():
                st.markdown(
                    f"<div style='font-weight:600;font-size:0.9rem;"
                    f"margin:1.0rem 0 0.1rem'>{row['Resource']}</div>",
                    unsafe_allow_html=True,
                )
                c1, c2, c3, c4, c5 = st.columns(5)
                dis_p = row["EndCap_MW"]
                chg_cap = row["EndCharge_MW"] or 0.0
                # Symmetric storage has no separate charge investment (EndChargeCap == 0),
                # so its charge power equals its discharge power rating.
                chg_p = chg_cap if chg_cap > 0 else dis_p
                energy = row["EndEnergy_MWh"]
                _small_metric(c1, "Discharge Power", f"{dis_p:.1f} MW")
                _small_metric(c2, "Charge Power", f"{chg_p:.1f} MW")
                _small_metric(c3, "Battery Energy", f"{energy:.1f} MWh")
                _small_metric(c4, "Battery Duration",
                              f"{energy / dis_p:.1f} h" if dis_p > 0 else "—")
                _small_metric(c5, "Min Charge Time",
                              f"{energy / chg_p:.1f} h" if chg_p > 0 else "—")

with col_pb:
    st.subheader("Supply to Load Mix")
    if _stl.empty:
        st.warning("Run the model to see generation mix.")
    else:
        _zone_order = (["System"] + [f"{z}" for z in rs.zones]) if rs.multi_zone \
            else [f"{z}" for z in rs.zones]

        def _donut(sub: pd.DataFrame, title: str) -> go.Figure:
            fig = go.Figure(go.Pie(
                labels=sub["Type"], values=sub["GenToLoad_MWh"], hole=0.4,
                marker_colors=[type_color(t) for t in sub["Type"]],
                textinfo="label+percent", textposition="inside",
            ))
            fig.update_layout(height=300, margin=dict(t=28, b=10, l=0, r=0),
                              showlegend=False, title=dict(text=title, font=dict(size=13)))
            return fig

        for _z in _zone_order:
            _key = "System" if _z == "System" else int(_z)
            _sub = _stl[_stl["Zone"] == _key]
            if _sub.empty:
                continue
            _fig = _donut(_sub, "System" if _z == "System" else f"Zone {_z}")
            if pie_fig is None:
                pie_fig = _fig
            st.plotly_chart(_fig, width="stretch", key=f"mix_{_z}")

        _stl_csv = _stl.copy()
        st.download_button(
            "⬇ Supply mix (CSV)", _stl_csv.to_csv(index=False).encode(),
            file_name=f"supply_mix_{case_name}.csv", mime="text/csv",
        )

st.divider()

# ── Section 3: Unserved Energy Timing ────────────────────────────────────────
st.subheader("Unserved Energy by Time of Year")

nse_fig = None
_nse_series = metrics.nse_timeseries(rs)
_n_hours = len(_nse_series)

if _n_hours == 0 or _nse_series.sum() <= 0:
    st.caption("No unserved energy in this case." if _n_hours else "`nse.csv` not found.")
elif _n_hours == 8760:
    grid = _nse_series.values.reshape(365, 24).T
    month_starts = [1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335]
    month_labels = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    nse_fig = go.Figure(go.Heatmap(
        z=grid, x=list(range(1, 366)), y=list(range(24)),
        colorscale=[[0, "#1a7a4a"], [1, "#ffffff"]], colorbar=dict(title="MW"),
    ))
    nse_fig.update_layout(
        xaxis=dict(title="Month", tickvals=month_starts, ticktext=month_labels),
        yaxis=dict(title="Hour of Day", dtick=4), height=320,
        margin=dict(t=5, b=5, l=0, r=0),
    )
    st.plotly_chart(nse_fig, width="stretch")
else:
    nse_fig = px.area(x=range(1, _n_hours + 1), y=_nse_series.values,
                      labels={"x": "Timestep", "y": "MW"})
    nse_fig.update_layout(height=280, margin=dict(t=5, b=5, l=0, r=0))
    st.plotly_chart(nse_fig, width="stretch")
    st.caption(
        f"{_n_hours} timesteps (not a full 8760-hour year), showing unserved "
        "energy over the modeled period instead of a calendar heatmap."
    )

st.divider()

# ── Section 4: Cost Breakdown ────────────────────────────────────────────────
st.subheader("Cost Breakdown by Resource")

cost_fig = None
_cb = metrics.cost_breakdown(rs)
if _cb.empty:
    st.warning("`NetRevenue.csv` not found.")
else:
    _breakdown_cols = ["Investment", "Fixed O&M", "Variable O&M", "Fuel", "Startup", "Other"]
    _melted = _cb[["Resource"] + _breakdown_cols].melt(
        id_vars="Resource", var_name="Cost Type", value_name="$M/yr")
    _melted = _melted[_melted["$M/yr"].abs() > 0]
    cost_fig = px.bar(
        _melted, x="Resource", y="$M/yr", color="Cost Type", barmode="stack",
        color_discrete_sequence=["#4682b4", "#87ceeb", "#ff8c00", "#b22222", "#9b59b6", "#888888"],
    )
    cost_fig.update_layout(
        yaxis_title="$M / yr", xaxis_tickangle=-20, height=360,
        margin=dict(t=5, b=5, l=0, r=0),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    st.plotly_chart(cost_fig, width="stretch")

st.divider()

# ── Section 4b: Hourly Curtailment ──────────────────────────────────────────
st.subheader("Hourly Curtailment")

_curt_ts = metrics.curtailment_timeseries(rs)
_pv_cols = [c for c in _curt_ts.columns if "pv" in str(c).lower()]
if not _curt_ts.empty and _pv_cols:
    _plot = _curt_ts[_pv_cols].reset_index()
    _step = max(1, len(_plot) // 500)
    curt_fig = px.line(_plot.iloc[::_step], x="hour", y=_pv_cols, labels={"value": "MW", "hour": "Hour"})
    curt_fig.update_layout(
        height=250, margin=dict(t=5, b=5, l=0, r=0),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, title=None),
    )
    st.plotly_chart(curt_fig, width="stretch")
else:
    st.caption("No hourly PV curtailment data found.")

st.divider()

# ── Section 4c: Hourly Power by Resource ────────────────────────────────────
st.subheader("Hourly Power by Resource")

_pwr_ts = metrics.power_timeseries(rs)
if not _pwr_ts.empty:
    _sel = st.selectbox("Resource", list(_pwr_ts.columns), key="power_resource_select")
    _plot = _pwr_ts[[_sel]].reset_index().dropna()
    _step = max(1, len(_plot) // 500)
    power_fig = px.line(_plot.iloc[::_step], x="hour", y=_sel, labels={_sel: "MW", "hour": "Hour"})
    power_fig.update_layout(height=280, margin=dict(t=5, b=5, l=0, r=0))
    st.plotly_chart(power_fig, width="stretch")
else:
    st.caption("No hourly power data found.")

st.divider()

# ── Section 4d: Storage Charging Source ─────────────────────────────────────
st.subheader("Storage Charging Source")
st.caption(
    "GenX doesn't track which generator's energy charges storage — it's a single "
    "zonal energy balance. This infers a likely source per hour by matching the "
    "zonal shadow price against each resource's known marginal cost. Treat this as "
    "a derived economic interpretation, not a physically tracked flow."
)


@st.cache_data(show_spinner=False)
def _charging(results_dir_str: str, inputs_dir_str: str, sig: float):
    del sig
    _rs = metrics.load_results(Path(results_dir_str))
    return metrics.charging_source(_rs, Path(inputs_dir_str)) if _rs else pd.DataFrame()


_src_mtimes = [_dir_sig(results_dir)]
for _rel in ("resources/Thermal.csv", "resources/Vre.csv", "resources/Storage.csv",
             "system/Fuels_data.csv"):
    _p = inputs_dir / _rel
    if _p.exists():
        _src_mtimes.append(_p.stat().st_mtime)

charge_source_df = _charging(str(results_dir), str(inputs_dir), max(_src_mtimes))

if charge_source_df.empty:
    st.caption(
        "Need `prices.csv`, `charge.csv`, and case inputs (Thermal.csv, Storage.csv, "
        "Fuels_data.csv) to derive charging source."
    )
else:
    _summary = charge_source_df.groupby(["Storage", "Bucket"])["MWh"].sum().reset_index()
    _pivot = _summary.pivot(index="Bucket", columns="Storage", values="MWh").fillna(0.0)
    _pct = _pivot.div(_pivot.sum(axis=0), axis=1) * 100
    _pivot_with_total = pd.concat([_pivot, _pivot.sum(axis=0).to_frame("Total").T])

    col_src_tab, col_src_chart = st.columns([1, 1.4])
    with col_src_tab:
        st.caption("Annual charging by inferred source (MWh)")
        st.dataframe(_pivot_with_total.style.format("{:,.0f}"), width="stretch")
        st.caption("Share of each resource's total charging (%)")
        st.dataframe(_pct.style.format("{:,.1f}%"), width="stretch")

    with col_src_chart:
        _stor_options = sorted(charge_source_df["Storage"].unique())
        _sel_stor = st.selectbox("Storage resource", _stor_options, key="charge_source_resource")
        _sub = charge_source_df[charge_source_df["Storage"] == _sel_stor].copy()
        _sub["Day"] = ((_sub["Hour"] - 1) // 24) + 1
        _daily = _sub.groupby(["Day", "Bucket"], as_index=False)["MWh"].sum()
        _bucket_colors = {
            "Curtailed VRE": "#27ae60",
            "Reliability shortfall": "#b22222",
            "Unclassified": "#888888",
        }
        _color_map = {b: _bucket_colors.get(b, resource_color(b)) for b in _daily["Bucket"].unique()}
        source_fig = px.bar(_daily, x="Day", y="MWh", color="Bucket", color_discrete_map=_color_map)
        source_fig.update_layout(
            barmode="stack", yaxis_title="MWh/day", height=320,
            margin=dict(t=5, b=5, l=0, r=0),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, title=None),
        )
        st.plotly_chart(source_fig, width="stretch")

    st.caption(
        "Classification matches each hour's zonal shadow price to a resource's "
        "marginal cost (±2% or $0.50 tolerance). 'Unclassified' hours had a price "
        "that didn't clearly match any candidate — often solver-tolerance noise or "
        "degenerate unit-commitment pricing."
    )

st.divider()

# ── Export ──────────────────────────────────────────────────────────────────
st.subheader("Export")

_report_html = report_lib.build_results_html(
    case_label=case_name,
    generated_at=datetime.now(),
    lcoe_styler=lcoe_styler,
    cap_fig=cap_fig,
    pie_fig=pie_fig,
    nse_fig=nse_fig,
    cost_fig=cost_fig,
)
st.download_button(
    "⬇ Export report (HTML)",
    data=_report_html,
    file_name=f"genx_results_{case_name}_{datetime.now():%Y%m%d-%H%M%S}.html",
    mime="text/html",
)

st.divider()

# ── Section 5: Raw Data ─────────────────────────────────────────────────────
st.subheader("Raw Data")

for fname, df in {
    "costs.csv":          rs.costs,
    "capacity.csv":       rs.capacity,
    "power.csv":          rs.power,
    "curtailment.csv":    rs.curtailment,
    "power_balance.csv":  rs.power_balance,
    "NetRevenue.csv":     rs.net_revenue,
    "nse.csv":            rs.nse,
}.items():
    with st.expander(f"📄 {fname}"):
        if df is not None:
            st.dataframe(df, width="stretch")
        else:
            st.caption("File not found.")
