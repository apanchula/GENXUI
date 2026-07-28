import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from pathlib import Path

st.set_page_config(page_title="GenX – Results", layout="wide")

GENX_ROOT = Path(__file__).parent.parent.parent / "GenX.jl"

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("GenX Results")

    cases = sorted([
        d.name for d in GENX_ROOT.iterdir()
        if d.is_dir() and (d / "Run.jl").exists()
    ])
    case_name = st.selectbox("Case", cases)
    case_path = GENX_ROOT / case_name
    results_dir = case_path / "results"

    st.divider()
    demand_mw = st.number_input(
        "Peak demand (MW)",
        value=100.0,
        step=10.0,
        help="Used to compute storage duration (MWh ÷ MW)",
    )

    st.link_button(
        "📖 GenX Output Docs",
        "https://genxproject.github.io/GenX.jl/stable/User_Guide/model_output/",
        width="stretch",
    )

# ── Guard: no results yet ─────────────────────────────────────────────────────
if not results_dir.exists():
    st.title("Results")
    st.info(
        f"No results found for **{case_name}**.  \n"
        "Run the model first from the **Runner** page."
    )
    st.stop()

# ── Data helpers ──────────────────────────────────────────────────────────────
@st.cache_data
def _read_csv(path_str: str, mtime: float) -> pd.DataFrame:
    return pd.read_csv(path_str)


def load(name: str) -> pd.DataFrame | None:
    p = results_dir / name
    if not p.exists():
        return None
    return _read_csv(str(p), p.stat().st_mtime)


costs_df      = load("costs.csv")
cap_df        = load("capacity.csv")
pb_df         = load("power_balance.csv")
rev_df        = load("NetRevenue.csv")
power_df      = load("power.csv")
charge_df     = load("charge.csv")
curtail_df    = load("curtailment.csv")
nse_df        = load("nse.csv")

st.title(f"Results — {case_name}")
st.caption(f"`{results_dir}`")

# ── Section 1: Key Metrics ────────────────────────────────────────────────────
st.subheader("Key Metrics")

# Pre-compute NSE and demand totals (shared by the LCOE table and the cost metrics)
_nse_total_mwh = 0.0
if nse_df is not None:
    _fc = nse_df.columns[0]
    if "Total" in nse_df.columns:
        _r = nse_df[nse_df[_fc].astype(str) == "AnnualSum"]
        if not _r.empty:
            _v = pd.to_numeric(_r["Total"].iloc[0], errors="coerce")
            if pd.notna(_v):
                _nse_total_mwh = float(_v)
    elif "AnnualSum" in nse_df.columns:
        _r = nse_df[nse_df[_fc].astype(str) == "Total"]
        if not _r.empty:
            _v = pd.to_numeric(_r["AnnualSum"].iloc[0], errors="coerce")
            if pd.notna(_v):
                _nse_total_mwh = float(_v)
nse_gwh_total = _nse_total_mwh / 1e3

_demand_total_mwh = 0.0
if pb_df is not None:
    _fc = pb_df.columns[0]
    _demand_cols = [c for c in pb_df.columns if c.split(".")[0] == "Demand"]
    if _demand_cols:
        _r = pb_df[pb_df[_fc].astype(str) == "AnnualSum"]
        if not _r.empty:
            _v = pd.to_numeric(_r[_demand_cols].iloc[0], errors="coerce").fillna(0)
            _demand_total_mwh = abs(float(_v.sum()))
    elif "AnnualSum" in pb_df.columns:
        _rows = pb_df[pb_df[_fc].astype(str) == "Demand"]
        if not _rows.empty:
            _demand_total_mwh = abs(float(pd.to_numeric(_rows["AnnualSum"], errors="coerce").fillna(0).sum()))
demand_gwh_total = _demand_total_mwh / 1e3

lcoe_df: pd.DataFrame | None = None

# Levelized Cost of Energy per resource
if rev_df is not None and power_df is not None:
    rev  = rev_df[rev_df["Resource"].astype(str) != "Total"].copy()

    # power.csv is wide: rows are Zone/AnnualSum/timesteps, resource names are columns
    annual_row = power_df[power_df["Resource"] == "AnnualSum"]
    pwr = (
        annual_row
        .drop(columns=["Resource", "Total"], errors="ignore")
        .T
        .reset_index()
    )
    pwr.columns = ["Resource", "AnnualSum"]
    pwr["AnnualSum"] = pd.to_numeric(pwr["AnnualSum"], errors="coerce")

    # Identify storage/FLEX resources from charge.csv to exclude their charging from VRE gen-to-load
    storage_resources: set[str] = set()
    charge_by_resource: dict[str, float] = {}
    if charge_df is not None:
        charge_row = charge_df[charge_df["Resource"] == "AnnualSum"]
        if not charge_row.empty:
            for col in charge_df.columns:
                if col not in ("Resource", "Total"):
                    val = float(charge_row.iloc[0][col])
                    charge_by_resource[col] = val
                    if val > 0:
                        storage_resources.add(col)

    total_charge = sum(charge_by_resource.values())

    def _is_vre(name: str) -> bool:
        n = name.lower()
        return any(k in n for k in ("pv", "solar", "wind"))

    vre_resources = pwr[
        ~pwr["Resource"].isin(storage_resources) & pwr["Resource"].apply(_is_vre)
    ]["Resource"].tolist()
    vre_total_gen = pwr[pwr["Resource"].isin(vre_resources)]["AnnualSum"].sum()

    def _gen_to_load(resource: str, annual_sum: float) -> float:
        if resource in storage_resources:
            return annual_sum                          # discharge → load
        if _is_vre(resource):
            vre_share = annual_sum / vre_total_gen if vre_total_gen > 0 else 0.0
            return max(0.0, annual_sum - total_charge * vre_share)  # subtract charging share
        return annual_sum

    pwr["_gen_to_load"] = pwr.apply(
        lambda r: _gen_to_load(r["Resource"], r["AnnualSum"]), axis=1
    )

    # Curtailment per resource (same wide format as power.csv)
    curtail_by_resource: dict[str, float] = {}
    if curtail_df is not None:
        curtail_row = curtail_df[curtail_df["Resource"] == "AnnualSum"]
        if not curtail_row.empty:
            for col in curtail_df.columns:
                if col not in ("Resource", "Total"):
                    curtail_by_resource[col] = float(curtail_row.iloc[0][col])

    # _total_cost (used for LCOE) includes charging cost; Hardware Cost breaks out
    # the non-charging portion so charging cost isn't double-counted between the two.
    rev["_total_cost"] = rev["Cost"]
    if "Charge_cost" in rev.columns:
        _charge_cost_by_resource = dict(zip(rev["Resource"], rev["Charge_cost"]))
    else:
        _charge_cost_by_resource = {}
    lcoe_df = rev[["Resource", "_total_cost"]].merge(pwr, on="Resource", how="left")
    lcoe_df["Hardware Cost ($M/yr)"] = (
        lcoe_df["_total_cost"] - lcoe_df["Resource"].map(_charge_cost_by_resource).fillna(0)
    ) / 1e6
    lcoe_df["Charging Cost ($M/yr)"] = lcoe_df["Resource"].map(
        lambda r: _charge_cost_by_resource.get(r, 0.0) / 1e6 if _charge_cost_by_resource.get(r, 0.0) > 0 else None
    )
    lcoe_df["Curtailment (GWh/yr)"] = lcoe_df["Resource"].map(
        lambda r: curtail_by_resource.get(r, 0.0) / 1e3
    )
    # Annual Gen = dispatch + curtailment  (total potential generation)
    # Gen to Load = dispatch - charging share  (excludes what went to charge storage)
    # Identity: Annual Gen = Gen to Load + Curtailment + Battery Charging
    lcoe_df["Gen to Load (GWh/yr)"] = lcoe_df["_gen_to_load"] / 1e3
    lcoe_df["Annual Gen (GWh/yr)"]  = lcoe_df["AnnualSum"] / 1e3 + lcoe_df["Curtailment (GWh/yr)"]
    lcoe_df["Curtail %"] = lcoe_df.apply(
        lambda r: 100 * r["Curtailment (GWh/yr)"] / r["Annual Gen (GWh/yr)"]
        if r["Annual Gen (GWh/yr)"] > 0 else None,
        axis=1,
    )
    lcoe_df["LCOE ($/MWh)"] = lcoe_df.apply(
        lambda r: r["_total_cost"] / r["AnnualSum"] if r["AnnualSum"] > 0 else None,
        axis=1,
    )
    lcoe_df = lcoe_df[[
        "Resource", "LCOE ($/MWh)", "Hardware Cost ($M/yr)", "Charging Cost ($M/yr)",
        "Annual Gen (GWh/yr)", "Gen to Load (GWh/yr)",
        "Curtailment (GWh/yr)", "Curtail %",
    ]]

    # ── Aggregate rows ─────────────────────────────────────────────────────────
    # DR Gen to Load: Demand_Response summed across all zones
    _dr_gen_gwh = 0.0
    if pb_df is not None:
        _fc = pb_df.columns[0]
        _ann = pb_df[pb_df[_fc].astype(str) == "AnnualSum"]
        if not _ann.empty:
            _dr_cols = [c for c in pb_df.columns if "Demand_Response" in str(c)]
            if _dr_cols:
                _v = pd.to_numeric(_ann[_dr_cols].iloc[0], errors="coerce").fillna(0)
                _dr_gen_gwh = abs(float(_v.sum())) / 1e3

    # DR Annual Cost: resources with "flex" in name (case-insensitive)
    _dr_cost_m = 0.0
    if rev_df is not None:
        _flex_rows = rev_df[
            rev_df["Resource"].astype(str).str.lower().str.contains("flex", na=False) &
            (rev_df["Resource"].astype(str) != "Total")
        ]
        if not _flex_rows.empty:
            _dr_cost_m = float(pd.to_numeric(_flex_rows["Cost"], errors="coerce").fillna(0).sum()) / 1e6

    _dr_lcoe = _dr_cost_m * 1e6 / (_dr_gen_gwh * 1e3) if _dr_gen_gwh > 0 else None

    # Nonserved Energy Gen to Load: Nonserved_Energy summed across all zones
    _nse_gen_gwh = 0.0
    if pb_df is not None:
        _fc = pb_df.columns[0]
        _ann = pb_df[pb_df[_fc].astype(str) == "AnnualSum"]
        if not _ann.empty:
            _nse_cols = [c for c in pb_df.columns if "Nonserved_Energy" in str(c)]
            if _nse_cols:
                _v = pd.to_numeric(_ann[_nse_cols].iloc[0], errors="coerce").fillna(0)
                _nse_gen_gwh = abs(float(_v.sum())) / 1e3

    # Unserved Energy annual cost = cNSE from costs.csv (matches the Key Metrics tile)
    _nse_cost_m = 0.0
    if costs_df is not None:
        _costs_series = costs_df.set_index("Costs")["Total"]
        _nse_cost_m = float(_costs_series.get("cNSE", 0)) / 1e6
    _nse_lcoe = _nse_cost_m * 1e6 / (_nse_gen_gwh * 1e3) if _nse_gen_gwh > 0 else None

    extra_rows = pd.DataFrame([
        {
            "Resource":               "Demand Response",
            "LCOE ($/MWh)":           _dr_lcoe,
            "Hardware Cost ($M/yr)":  _dr_cost_m if _dr_cost_m > 0 else None,
            "Charging Cost ($M/yr)":  None,
            "Annual Gen (GWh/yr)":    None,
            "Gen to Load (GWh/yr)":   _dr_gen_gwh,
            "Curtailment (GWh/yr)":   None,
            "Curtail %":              None,
        },
        {
            "Resource":               "Unserved Energy",
            "LCOE ($/MWh)":           _nse_lcoe,
            "Hardware Cost ($M/yr)":  _nse_cost_m if _nse_cost_m > 0 else None,
            "Charging Cost ($M/yr)":  None,
            "Annual Gen (GWh/yr)":    None,
            "Gen to Load (GWh/yr)":   _nse_gen_gwh,
            "Curtailment (GWh/yr)":   None,
            "Curtail %":              None,
        },
    ])
    lcoe_df = pd.concat([lcoe_df, extra_rows], ignore_index=True)

    # ── Total row ────────────────────────────────────────────────────────────
    _total_hw           = lcoe_df["Hardware Cost ($M/yr)"].sum(skipna=True)
    _total_charge_cost  = lcoe_df["Charging Cost ($M/yr)"].sum(skipna=True)
    _total_gen_to_load  = lcoe_df["Gen to Load (GWh/yr)"].sum(skipna=True)
    _total_lcoe = (
        (_total_hw + _total_charge_cost) * 1e6 / (_total_gen_to_load * 1e3)
        if _total_gen_to_load > 0 else None
    )
    total_row = pd.DataFrame([{
        "Resource":               "Total",
        "LCOE ($/MWh)":           _total_lcoe,
        "Hardware Cost ($M/yr)":  _total_hw,
        "Charging Cost ($M/yr)":  _total_charge_cost if _total_charge_cost > 0 else None,
        "Annual Gen (GWh/yr)":    None,
        "Gen to Load (GWh/yr)":   _total_gen_to_load,
        "Curtailment (GWh/yr)":   None,
        "Curtail %":              None,
    }])
    lcoe_df = pd.concat([lcoe_df, total_row], ignore_index=True)

    def _bold_total_row(row):
        style = "font-weight: bold" if row["Resource"] == "Total" else ""
        return [style] * len(row)

    st.dataframe(
        lcoe_df.style.apply(_bold_total_row, axis=1),
        hide_index=True,
        width="stretch",
        column_config={
            "LCOE ($/MWh)":           st.column_config.NumberColumn(format="$%.2f"),
            "Hardware Cost ($M/yr)":  st.column_config.NumberColumn(format="$%.3f"),
            "Charging Cost ($M/yr)":  st.column_config.NumberColumn(format="$%.3f"),
            "Annual Gen (GWh/yr)":    st.column_config.NumberColumn(format="%.1f"),
            "Gen to Load (GWh/yr)":   st.column_config.NumberColumn(format="%.1f"),
            "Curtailment (GWh/yr)":   st.column_config.NumberColumn(format="%.1f"),
            "Curtail %":              st.column_config.NumberColumn(format="%.1f%%"),
        },
    )
    st.divider()

# Redundant with the LCOE table's Total row above (Hardware Cost + Charging Cost
# covers cFix/cVar/cFuel, and the Unserved Energy row covers cNSE).
# if costs_df is not None:
#     costs = costs_df.set_index("Costs")["Total"]
#     c_fix   = float(costs.get("cFix",   0)) / 1e6
#     c_var   = float(costs.get("cVar",   0)) / 1e6
#     c_fuel  = float(costs.get("cFuel",  0)) / 1e6
#     c_nse   = float(costs.get("cNSE",   0)) / 1e6
#     # Unserved energy cost is broken out in its own metric below, so exclude it
#     # here to avoid double-counting it in the headline total.
#     c_total = float(costs.get("cTotal", 0)) / 1e6 - c_nse
#
#     def pct(val):
#         return f"{100 * val / c_total:.1f}% of total" if c_total else ""
#
#     nse_pct = 100.0 * nse_gwh_total / demand_gwh_total if demand_gwh_total > 0 else 0.0
#     nse_delta = f"{nse_gwh_total:.2f} GWh  ({nse_pct:.3f}% of load)"
#
#     col1, col2, col3, col4 = st.columns(4)
#     col1.metric("Total System Cost",  f"${c_total:.2f}M/yr")
#     col2.metric("Fixed Cost",         f"${c_fix:.2f}M/yr",         pct(c_fix))
#     col3.metric("Variable + Fuel",    f"${c_var + c_fuel:.2f}M/yr", pct(c_var + c_fuel))
#     col4.metric("Unserved Energy",    f"${c_nse:.4f}M/yr",          nse_delta, delta_color="off")
# else:
#     st.warning("`costs.csv` not found in results.")
#
# st.divider()

# ── Section 2: Capacity + Power Balance ──────────────────────────────────────
col_cap, col_pb = st.columns(2)

COLORS = {
    "thermal":  "#4682b4",
    "solar":    "#ff8c00",
    "wind":     "#27ae60",
    "storage":  "#2ecc71",
    "other":    "#888888",
}


def resource_color(name: str) -> str:
    n = name.lower()
    if any(k in n for k in ("gas", "ngcc", "natural_gas", "coal", "nuclear", "thermal")):
        return COLORS["thermal"]
    if any(k in n for k in ("pv", "solar")):
        return COLORS["solar"]
    if "wind" in n:
        return COLORS["wind"]
    if any(k in n for k in ("battery", "stor", "storage")):
        return COLORS["storage"]
    return COLORS["other"]


with col_cap:
    st.subheader("Capacity Built")
    if cap_df is not None:
        cap = cap_df[cap_df["Resource"].astype(str) != "Total"].copy()
        colors = [resource_color(r) for r in cap["Resource"]]

        fig = go.Figure()
        fig.add_trace(go.Bar(
            name="Power (MW)",
            x=cap["Resource"],
            y=cap["EndCap"],
            marker_color=colors,
        ))

        stor = cap[cap["EndEnergyCap"] > 0]
        if not stor.empty:
            fig.add_trace(go.Bar(
                name="Energy (MWh)",
                x=stor["Resource"],
                y=stor["EndEnergyCap"],
                marker_color="#1a7a4a",
                opacity=0.65,
            ))

        fig.update_layout(
            barmode="group",
            yaxis_title="Capacity",
            xaxis_tickangle=-20,
            height=340,
            margin=dict(t=5, b=5, l=0, r=0),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        st.plotly_chart(fig, width="stretch")

        # Storage metrics: demand, power, energy, duration
        if not stor.empty:
            def _small_metric(col, label, value):
                col.markdown(
                    f"<div style='font-size:0.75rem;color:grey;margin-bottom:2px'>{label}</div>"
                    f"<div style='font-size:0.95rem;font-weight:600'>{value}</div>",
                    unsafe_allow_html=True,
                )

            for _, row in stor.iterrows():
                st.caption(row["Resource"])
                m1, m2, m3, m4 = st.columns(4)
                bat_power  = row["EndCap"]
                bat_energy = row["EndEnergyCap"]
                bat_dur    = bat_energy / bat_power if bat_power > 0 else 0
                _small_metric(m1, "Demand Power",    f"{demand_mw:.0f} MW")
                _small_metric(m2, "Battery Power",   f"{bat_power:.1f} MW")
                _small_metric(m3, "Battery Energy",  f"{bat_energy:.1f} MWh")
                _small_metric(m4, "Battery Duration",f"{bat_dur:.1f} h")
    else:
        st.warning("`capacity.csv` not found.")


with col_pb:
    st.subheader("Supply to Load Mix")
    if lcoe_df is not None:
        pie_rows = lcoe_df[
            (lcoe_df["Gen to Load (GWh/yr)"] > 0) & (lcoe_df["Resource"] != "Total")
        ].copy()
        labels     = pie_rows["Resource"].tolist()
        values     = pie_rows["Gen to Load (GWh/yr)"].tolist()
        pie_colors = [resource_color(r) for r in labels]

        fig = go.Figure(go.Pie(
            labels=labels,
            values=values,
            hole=0.38,
            marker_colors=pie_colors,
            textinfo="label+percent",
            textposition="outside",
        ))
        fig.update_layout(
            height=340,
            margin=dict(t=5, b=5, l=0, r=100),
            showlegend=False,
        )
        st.plotly_chart(fig, width="stretch")
        total_to_load = sum(values)
        st.caption(f"Total supply to load: {total_to_load / 1e3:.3f} TWh/yr")
    else:
        st.warning("Run the model to see generation mix.")

st.divider()

# ── Section 3: Unserved Energy Timing ─────────────────────────────────────────
st.subheader("Unserved Energy by Time of Year")

if nse_df is not None:
    _fc = nse_df.columns[0]
    ts = nse_df[nse_df[_fc].astype(str).str.match(r"^t\d+$")]
    if "Total" in ts.columns:
        nse_series = pd.to_numeric(ts["Total"], errors="coerce").fillna(0).reset_index(drop=True)
    else:
        nse_series = pd.Series(dtype=float)

    n_hours = len(nse_series)
    if n_hours == 8760 and nse_series.sum() > 0:
        # Reshape into a 365-day x 24-hour grid (assumes a non-leap hourly year starting Jan 1)
        grid = nse_series.values.reshape(365, 24).T

        month_starts = [1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335]
        month_labels = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                         "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

        fig = go.Figure(go.Heatmap(
            z=grid,
            x=list(range(1, 366)),
            y=list(range(24)),
            colorscale="Reds",
            colorbar=dict(title="MW"),
        ))
        fig.update_layout(
            xaxis=dict(title="Month", tickvals=month_starts, ticktext=month_labels),
            yaxis=dict(title="Hour of Day", dtick=4),
            height=320,
            margin=dict(t=5, b=5, l=0, r=0),
        )
        st.plotly_chart(fig, width="stretch")
    elif n_hours > 0 and nse_series.sum() > 0:
        fig = px.area(
            x=range(1, n_hours + 1), y=nse_series.values,
            labels={"x": "Timestep", "y": "MW"},
        )
        fig.update_layout(height=280, margin=dict(t=5, b=5, l=0, r=0))
        st.plotly_chart(fig, width="stretch")
        st.caption(
            f"{n_hours} timesteps found (not a full 8760-hour year), "
            "showing unserved energy over the modeled period instead of a calendar heatmap."
        )
    else:
        st.caption("No unserved energy in this case.")
else:
    st.caption("`nse.csv` not found.")

st.divider()

# ── Section 4: Cost Breakdown ─────────────────────────────────────────────────
st.subheader("Cost Breakdown by Resource")

if rev_df is not None:
    rev = rev_df[rev_df["Resource"].astype(str) != "Total"].copy()
    M = 1e6

    inv_cols  = [c for c in ["Inv_cost_MW", "Inv_cost_MWh", "Inv_cost_charge_MW"] if c in rev.columns]
    fom_cols  = [c for c in ["Fixed_OM_cost_MW", "Fixed_OM_cost_MWh", "Fixed_OM_cost_charge_MW"] if c in rev.columns]
    vom_cols  = [c for c in ["Var_OM_cost_out", "Var_OM_cost_in"] if c in rev.columns]
    fuel_cols = [c for c in ["Fuel_cost"] if c in rev.columns]
    start_cols = [c for c in ["StartCost"] if c in rev.columns]
    other_cols = [c for c in ["CO2SequestrationCost", "EmissionsCost"] if c in rev.columns]

    rev = rev.copy()
    rev["Investment"]  = rev[inv_cols].sum(axis=1)   / M if inv_cols   else 0.0
    rev["Fixed O&M"]   = rev[fom_cols].sum(axis=1)   / M if fom_cols   else 0.0
    rev["Variable O&M"]= rev[vom_cols].sum(axis=1)   / M if vom_cols   else 0.0
    rev["Fuel"]        = rev[fuel_cols].sum(axis=1)  / M if fuel_cols  else 0.0
    rev["Startup"]     = rev[start_cols].sum(axis=1) / M if start_cols else 0.0
    rev["Other"]       = rev[other_cols].sum(axis=1) / M if other_cols else 0.0

    breakdown_cols = ["Investment", "Fixed O&M", "Variable O&M", "Fuel", "Startup", "Other"]
    melted = rev[["Resource"] + breakdown_cols].melt(
        id_vars="Resource", var_name="Cost Type", value_name="$M/yr"
    )
    melted = melted[melted["$M/yr"].abs() > 0]

    color_seq = ["#4682b4", "#87ceeb", "#ff8c00", "#b22222", "#9b59b6", "#888888"]
    fig = px.bar(
        melted,
        x="Resource",
        y="$M/yr",
        color="Cost Type",
        color_discrete_sequence=color_seq,
        barmode="stack",
    )
    fig.update_layout(
        yaxis_title="$M / yr",
        xaxis_tickangle=-20,
        height=360,
        margin=dict(t=5, b=5, l=0, r=0),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    st.plotly_chart(fig, width="stretch")
else:
    st.warning("`NetRevenue.csv` not found.")

st.divider()

# ── Section 5: Raw Data ───────────────────────────────────────────────────────
st.subheader("Raw Data")

raw_files = {
    "costs.csv":          costs_df,
    "capacity.csv":       cap_df,
    "power.csv":          power_df,
    "curtailment.csv":    curtail_df,
    "power_balance.csv":  pb_df,
    "NetRevenue.csv":     rev_df,
}

for fname, df in raw_files.items():
    with st.expander(f"📄 {fname}"):
        if df is not None:
            st.dataframe(df, width="stretch")
        else:
            st.caption("File not found.")
