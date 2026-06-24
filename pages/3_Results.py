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


costs_df = load("costs.csv")
cap_df   = load("capacity.csv")
pb_df    = load("power_balance.csv")
rev_df   = load("NetRevenue.csv")

st.title(f"Results — {case_name}")
st.caption(f"`{results_dir}`")

# ── Section 1: Key Metrics ────────────────────────────────────────────────────
st.subheader("Key Metrics")

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

        # Storage duration info
        if not stor.empty:
            dur_cols = st.columns(len(stor))
            for col_d, (_, row) in zip(dur_cols, stor.iterrows()):
                dur = row["EndEnergyCap"] / demand_mw if demand_mw > 0 else 0
                col_d.metric(f"{row['Resource']}\nduration", f"{dur:.1f} hrs")
    else:
        st.warning("`capacity.csv` not found.")


with col_pb:
    st.subheader("Annual Generation Mix")
    if pb_df is not None:
        if "BalanceComponent" in pb_df.columns:
            annual_rows = pb_df[pb_df["BalanceComponent"] == "AnnualSum"]
            annual = annual_rows.iloc[0] if not annual_rows.empty else pb_df.iloc[0]
        else:
            annual = pb_df.iloc[0]

        supply_cols = {
            "Generation":            "Generation",
            "VRE_Storage_Discharge": "VRE+Storage Discharge",
            "Storage_Discharge":     "Storage Discharge",
            "Nonserved_Energy":      "Unserved Energy",
        }

        labels, values, pie_colors = [], [], []
        color_map = [COLORS["thermal"], COLORS["solar"], COLORS["storage"], "#e74c3c"]
        for i, (col, label) in enumerate(supply_cols.items()):
            if col in annual.index:
                val = abs(float(annual[col]))
                if val > 0:
                    labels.append(label)
                    values.append(val)
                    pie_colors.append(color_map[i])

        if labels:
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
            total_gen = sum(values)
            st.caption(f"Total annual generation: {total_gen / 1e6:.2f} TWh")
        else:
            st.info("No supply data found in `power_balance.csv`.")
    else:
        st.warning("`power_balance.csv` not found.")

st.divider()

# ── Section 3: Cost Breakdown ─────────────────────────────────────────────────
st.subheader("Cost Breakdown by Resource")

if rev_df is not None:
    rev = rev_df[rev_df["Resource"].astype(str) != "Total"].copy()
    M = 1e6

    inv_cols  = [c for c in ["Inv_cost_MW", "Inv_cost_MWh", "Inv_cost_charge_MW"] if c in rev.columns]
    fom_cols  = [c for c in ["Fixed_OM_cost_MW", "Fixed_OM_cost_MWh", "Fixed_OM_cost_charge_MW"] if c in rev.columns]
    vom_cols  = [c for c in ["Var_OM_cost_out"] if c in rev.columns]
    fuel_cols = [c for c in ["Fuel_cost"] if c in rev.columns]

    rev = rev.copy()
    rev["Investment"]  = rev[inv_cols].sum(axis=1)  / M if inv_cols  else 0.0
    rev["Fixed O&M"]   = rev[fom_cols].sum(axis=1)  / M if fom_cols  else 0.0
    rev["Variable O&M"]= rev[vom_cols].sum(axis=1)  / M if vom_cols  else 0.0
    rev["Fuel"]        = rev[fuel_cols].sum(axis=1) / M if fuel_cols else 0.0

    melted = rev[["Resource", "Investment", "Fixed O&M", "Variable O&M", "Fuel"]].melt(
        id_vars="Resource", var_name="Cost Type", value_name="$M/yr"
    )
    melted = melted[melted["$M/yr"].abs() > 0]

    color_seq = ["#4682b4", "#87ceeb", "#ff8c00", "#b22222"]
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
    "costs.csv":       costs_df,
    "capacity.csv":    cap_df,
    "power_balance.csv": pb_df,
    "NetRevenue.csv":  rev_df,
}

for fname, df in raw_files.items():
    with st.expander(f"📄 {fname}"):
        if df is not None:
            st.dataframe(df, width="stretch")
        else:
            st.caption("File not found.")
