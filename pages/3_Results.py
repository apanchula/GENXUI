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

st.title(f"Results — {case_name}")
st.caption(f"`{results_dir}`")

# ── Section 1: Key Metrics ────────────────────────────────────────────────────
st.subheader("Key Metrics")

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

    # Identify storage resources from charge.csv (wide format, same as power.csv)
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

    # VRE resources (solar/wind) exclusively charge storage, so all charging
    # is subtracted from VRE generation; thermal generation is unaffected.
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
        return annual_sum                              # thermal: no adjustment

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

    rev["_total_cost"] = rev["Cost"]
    lcoe_df = rev[["Resource", "_total_cost"]].merge(pwr, on="Resource", how="left")
    lcoe_df["Annual Cost ($M/yr)"]  = lcoe_df["_total_cost"] / 1e6
    lcoe_df["Annual Gen (GWh/yr)"]  = lcoe_df["AnnualSum"]   / 1e3
    lcoe_df["Gen to Load (GWh/yr)"] = lcoe_df["_gen_to_load"] / 1e3
    lcoe_df["Curtailment (GWh/yr)"] = lcoe_df["Resource"].map(
        lambda r: curtail_by_resource.get(r, 0.0) / 1e3
    )
    lcoe_df["Curtail %"] = lcoe_df.apply(
        lambda r: 100 * r["Curtailment (GWh/yr)"] / (r["Annual Gen (GWh/yr)"] + r["Curtailment (GWh/yr)"])
        if (r["Annual Gen (GWh/yr)"] + r["Curtailment (GWh/yr)"]) > 0 else None,
        axis=1,
    )
    lcoe_df["LCOE ($/MWh)"] = lcoe_df.apply(
        lambda r: r["_total_cost"] / r["AnnualSum"] if r["AnnualSum"] > 0 else None,
        axis=1,
    )
    lcoe_df = lcoe_df[[
        "Resource", "LCOE ($/MWh)", "Annual Cost ($M/yr)",
        "Annual Gen (GWh/yr)", "Gen to Load (GWh/yr)",
        "Curtailment (GWh/yr)", "Curtail %",
    ]]

    st.dataframe(
        lcoe_df,
        hide_index=True,
        width="stretch",
        column_config={
            "LCOE ($/MWh)":           st.column_config.NumberColumn(format="$%.2f"),
            "Annual Cost ($M/yr)":    st.column_config.NumberColumn(format="$%.3f"),
            "Annual Gen (GWh/yr)":    st.column_config.NumberColumn(format="%.1f"),
            "Gen to Load (GWh/yr)":   st.column_config.NumberColumn(format="%.1f"),
            "Curtailment (GWh/yr)":   st.column_config.NumberColumn(format="%.1f"),
            "Curtail %":              st.column_config.NumberColumn(format="%.1f%%"),
        },
    )
    st.divider()

if costs_df is not None:
    costs = costs_df.set_index("Costs")["Total"]
    c_total = float(costs.get("cTotal", 0)) / 1e6
    c_fix   = float(costs.get("cFix",   0)) / 1e6
    c_var   = float(costs.get("cVar",   0)) / 1e6
    c_fuel  = float(costs.get("cFuel",  0)) / 1e6
    c_nse   = float(costs.get("cNSE",   0)) / 1e6

    def pct(val):
        return f"{100 * val / c_total:.1f}% of total" if c_total else ""

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total System Cost",  f"${c_total:.2f}M/yr")
    col2.metric("Fixed Cost",         f"${c_fix:.2f}M/yr",         pct(c_fix))
    col3.metric("Variable + Fuel",    f"${c_var + c_fuel:.2f}M/yr", pct(c_var + c_fuel))
    col4.metric("Unserved Energy",    f"${c_nse:.4f}M/yr")
else:
    st.warning("`costs.csv` not found in results.")

st.divider()

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
        pie_rows = lcoe_df[lcoe_df["Gen to Load (GWh/yr)"] > 0].copy()
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

# ── Section 3: Cost Breakdown ─────────────────────────────────────────────────
st.subheader("Cost Breakdown by Resource")

if rev_df is not None:
    rev = rev_df[rev_df["Resource"].astype(str) != "Total"].copy()
    M = 1e6

    inv_cols  = [c for c in ["Inv_cost_MW", "Inv_cost_MWh", "Inv_cost_charge_MW"] if c in rev.columns]
    fom_cols  = [c for c in ["Fixed_OM_cost_MW", "Fixed_OM_cost_MWh", "Fixed_OM_cost_charge_MW"] if c in rev.columns]
    vom_cols  = [c for c in ["Var_OM_cost_out", "Var_OM_cost_in", "Charge_cost"] if c in rev.columns]
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

# ── Section 4: Raw Data ───────────────────────────────────────────────────────
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
