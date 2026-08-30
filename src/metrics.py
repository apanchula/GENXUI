"""GenX results-CSV parsing engine (GENXUI-5).

`load_results(results_dir)` reads a GenX output directory (live or archived) into
a `ResultSet`; the accessor functions turn that into tidy, zone-aware frames the
Results page renders. Pure — no Streamlit.

GenX output CSVs come in two shapes:

* **long**   — one row per resource: capacity.csv, NetRevenue.csv
* **wide**   — first column is a row label, remaining columns are resources (or
               balance components); special rows `Zone`, `AnnualSum`, then
               `t1, t2, …`: power.csv, charge.csv, curtailment.csv,
               power_balance.csv, nse.csv

`_wide_parts()` splits a wide CSV into (zone-of-column, annual-of-column,
timeseries). Everything else builds on that.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from src.resource_style import resource_type

_TS_RE = re.compile(r"^t\d+$")


def _f(x, default: float = 0.0) -> float:
    try:
        v = float(x)
        return v if pd.notna(v) else default
    except (TypeError, ValueError):
        return default


def _read(results_dir: Path, name: str) -> pd.DataFrame | None:
    fp = results_dir / name
    try:
        return pd.read_csv(fp) if fp.is_file() else None
    except (OSError, pd.errors.ParserError, pd.errors.EmptyDataError):
        return None


def _wide_parts(df: pd.DataFrame | None):
    """(zone_of_col, annual_of_col, timeseries_df) for a wide GenX CSV.

    timeseries_df is indexed by integer hour, columns are the data columns
    (numeric-coerced).
    """
    if df is None or df.shape[1] < 2:
        return {}, {}, pd.DataFrame()
    fc = df.columns[0]
    key = df[fc].astype(str)
    data_cols = list(df.columns[1:])

    zone_of: dict[str, int] = {}
    zr = df[key == "Zone"]
    if not zr.empty:
        for c in data_cols:
            try:
                zone_of[c] = int(float(zr.iloc[0][c]))
            except (TypeError, ValueError):
                pass

    annual_of: dict[str, float] = {}
    ar = df[key == "AnnualSum"]
    if not ar.empty:
        for c in data_cols:
            annual_of[c] = _f(ar.iloc[0][c])

    ts_rows = df[key.str.match(_TS_RE)]
    if ts_rows.empty:
        ts = pd.DataFrame(columns=data_cols)
        ts.index.name = "hour"
    else:
        ts = ts_rows[data_cols].apply(pd.to_numeric, errors="coerce")
        ts.index = pd.Index(ts_rows[fc].astype(str).str[1:].astype(int), name="hour")
    return zone_of, annual_of, ts


# ── ResultSet ───────────────────────────────────────────────────────────────

@dataclass
class ResultSet:
    results_dir: Path
    capacity: pd.DataFrame | None
    power: pd.DataFrame | None
    charge: pd.DataFrame | None
    curtailment: pd.DataFrame | None
    power_balance: pd.DataFrame | None
    nse: pd.DataFrame | None
    net_revenue: pd.DataFrame | None
    costs: pd.DataFrame | None
    prices: pd.DataFrame | None
    zones: list[int] = field(default_factory=list)
    dropped_resources: list[str] = field(default_factory=list)

    @property
    def multi_zone(self) -> bool:
        return len(self.zones) > 1


def load_results(results_dir: Path) -> ResultSet | None:
    """Parse a GenX results directory. None if it has no capacity.csv."""
    cap = _read(results_dir, "capacity.csv")
    if cap is None:
        return None

    rs = ResultSet(
        results_dir=results_dir,
        capacity=cap,
        power=_read(results_dir, "power.csv"),
        charge=_read(results_dir, "charge.csv"),
        curtailment=_read(results_dir, "curtailment.csv"),
        power_balance=_read(results_dir, "power_balance.csv"),
        nse=_read(results_dir, "nse.csv"),
        net_revenue=_read(results_dir, "NetRevenue.csv"),
        costs=_read(results_dir, "costs.csv"),
        prices=_read(results_dir, "prices.csv"),
    )

    # zones: prefer capacity.csv's Zone column, fall back to power.csv's Zone row
    zones: set[int] = set()
    if "Zone" in cap.columns:
        for z in pd.to_numeric(cap["Zone"], errors="coerce").dropna():
            zones.add(int(z))
    if not zones:
        zone_of, _, _ = _wide_parts(rs.power)
        zones.update(zone_of.values())
    rs.zones = sorted(z for z in zones if z > 0) or [1]

    master = _resource_master(rs)
    rs.dropped_resources = sorted(
        master.loc[~master["exists"], "Resource"].tolist()
    )
    return rs


# ── resource-level frames ───────────────────────────────────────────────────

def _resource_master(rs: ResultSet) -> pd.DataFrame:
    """One row per resource: Resource, Type, Zone, EndCap_MW, NewCap_MW,
    RetCap_MW, EndEnergy_MWh, EndCharge_MW, AnnualGen_MWh, Curtail_MWh, exists.

    `exists` is False for a resource with zero capacity AND zero generation —
    it contributed nothing to the solve (mirrors fleet_view.FleetResource.exists).
    """
    cap = rs.capacity
    rows = []
    if cap is not None:
        for _, r in cap.iterrows():
            name = str(r.get("Resource", "")).strip()
            if not name or name.lower() == "total":
                continue
            rows.append({
                "Resource": name,
                "Zone": int(_f(r.get("Zone"), 1)),
                "EndCap_MW": _f(r.get("EndCap")),
                "NewCap_MW": _f(r.get("NewCap")),
                "RetCap_MW": _f(r.get("RetCap")),
                "EndEnergy_MWh": _f(r.get("EndEnergyCap")),
                "EndCharge_MW": _f(r.get("EndChargeCap")),
            })
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=[
            "Resource", "Type", "Zone", "EndCap_MW", "NewCap_MW", "RetCap_MW",
            "EndEnergy_MWh", "EndCharge_MW", "AnnualGen_MWh", "Curtail_MWh", "exists",
        ])

    zone_of, gen_of, _ = _wide_parts(rs.power)
    _, curt_of, _ = _wide_parts(rs.curtailment)
    df["AnnualGen_MWh"] = df["Resource"].map(lambda n: max(0.0, gen_of.get(n, 0.0)))
    df["Curtail_MWh"] = df["Resource"].map(lambda n: max(0.0, curt_of.get(n, 0.0)))
    # power.csv's Zone row is authoritative when capacity.csv lacks one
    df["Zone"] = df.apply(
        lambda r: zone_of.get(r["Resource"], r["Zone"]), axis=1
    ).astype(int)
    df["Type"] = df["Resource"].map(resource_type)
    df["exists"] = (df["EndCap_MW"] > 0) | (df["AnnualGen_MWh"] > 0) | (df["EndEnergy_MWh"] > 0)
    return df


def capacity_by_resource(rs: ResultSet) -> pd.DataFrame:
    m = _resource_master(rs)
    m = m[m["exists"]]
    return m[["Resource", "Type", "Zone", "EndCap_MW", "NewCap_MW", "RetCap_MW",
             "EndEnergy_MWh", "EndCharge_MW"]].reset_index(drop=True)


def generation_by_resource(rs: ResultSet) -> pd.DataFrame:
    m = _resource_master(rs)
    m = m[m["exists"]]
    return m[["Resource", "Type", "Zone", "AnnualGen_MWh"]].reset_index(drop=True)


# ── zone summary (Key Metrics) ──────────────────────────────────────────────

def zone_summary(rs: ResultSet) -> pd.DataFrame:
    """Rows per (Zone, Type) with Capacity_MW / Generation_MWh / Curtailment_MWh,
    a bold-able subtotal per zone, and a system TOTAL row.

    For a single-zone case the per-zone subtotal rows are omitted (just the
    Type rows + TOTAL).
    """
    m = _resource_master(rs)
    m = m[m["exists"]]
    cols = ["Capacity_MW", "Generation_MWh", "Curtailment_MWh"]
    if m.empty:
        return pd.DataFrame(columns=["Zone", "Type", *cols, "is_subtotal", "is_total"])

    grp = (m.groupby(["Zone", "Type"], as_index=False)
             .agg(Capacity_MW=("EndCap_MW", "sum"),
                  Generation_MWh=("AnnualGen_MWh", "sum"),
                  Curtailment_MWh=("Curtail_MWh", "sum")))
    grp["is_subtotal"] = False
    grp["is_total"] = False

    out_rows = []
    for z in sorted(m["Zone"].unique()):
        zrows = grp[grp["Zone"] == z].sort_values("Type")
        out_rows.append(zrows)
        if rs.multi_zone:
            out_rows.append(pd.DataFrame([{
                "Zone": z, "Type": "— zone total —",
                "Capacity_MW": zrows["Capacity_MW"].sum(),
                "Generation_MWh": zrows["Generation_MWh"].sum(),
                "Curtailment_MWh": zrows["Curtailment_MWh"].sum(),
                "is_subtotal": True, "is_total": False,
            }]))
    out_rows.append(pd.DataFrame([{
        "Zone": "", "Type": "SYSTEM TOTAL",
        "Capacity_MW": grp["Capacity_MW"].sum(),
        "Generation_MWh": grp["Generation_MWh"].sum(),
        "Curtailment_MWh": grp["Curtailment_MWh"].sum(),
        "is_subtotal": False, "is_total": True,
    }]))
    return pd.concat(out_rows, ignore_index=True)


# ── gen-to-load / supply to load / LCOE ────────────────────────────────────

def _gen_to_load_map(rs: ResultSet) -> dict[str, float]:
    """{resource -> MWh that actually served load}. Storage discharge counts
    fully; each VRE resource has its zone-proportional share of storage charging
    netted out (mirrors the old `_gen_to_load`)."""
    m = _resource_master(rs)
    m = m[m["exists"]].copy()
    if m.empty:
        return {}
    _, charge_of, _ = _wide_parts(rs.charge)
    m["charge"] = m["Resource"].map(lambda n: max(0.0, charge_of.get(n, 0.0)))
    storage_names = set(m.loc[m["charge"] > 0, "Resource"])

    out: dict[str, float] = {}
    for z in m["Zone"].unique():
        zm = m[m["Zone"] == z]
        total_charge = zm["charge"].sum()
        vre_total = zm.loc[zm["Type"].isin(["Solar", "Wind"]), "AnnualGen_MWh"].sum()
        for _, r in zm.iterrows():
            g = r["AnnualGen_MWh"]
            if r["Resource"] in storage_names:
                out[r["Resource"]] = g
            elif r["Type"] in ("Solar", "Wind"):
                share = g / vre_total if vre_total > 0 else 0.0
                out[r["Resource"]] = max(0.0, g - total_charge * share)
            else:
                out[r["Resource"]] = g
    return out


def supply_to_load(rs: ResultSet) -> pd.DataFrame:
    """Zone, Type, GenToLoad_MWh — annual energy that served load, per zone.
    Includes an `Unserved` slice (non-served energy) so each zone's mix sums to
    that zone's demand. A `System` pseudo-zone is appended when the case has
    >1 zone.
    """
    m = _resource_master(rs)
    m = m[m["exists"]].copy()
    gtl = _gen_to_load_map(rs)
    if not m.empty:
        m["GenToLoad_MWh"] = m["Resource"].map(lambda n: gtl.get(n, 0.0))
        m = m[m["GenToLoad_MWh"] > 0]
    df = (m.groupby(["Zone", "Type"], as_index=False)["GenToLoad_MWh"].sum()
          if not m.empty else pd.DataFrame(columns=["Zone", "Type", "GenToLoad_MWh"]))

    nse_zone, nse_annual, _ = _wide_parts(rs.nse)
    nse_by_zone: dict[int, float] = {}
    for col, mwh in nse_annual.items():
        if str(col).lower() == "total":
            continue
        z = nse_zone.get(col)
        if z:
            nse_by_zone[z] = nse_by_zone.get(z, 0.0) + max(0.0, _f(mwh))
    nse_rows = [{"Zone": z, "Type": "Unserved", "GenToLoad_MWh": v}
                for z, v in sorted(nse_by_zone.items()) if v > 0]
    if nse_rows:
        df = pd.concat([df, pd.DataFrame(nse_rows)], ignore_index=True)

    if df.empty:
        return df
    if rs.multi_zone:
        sys_df = df.groupby("Type", as_index=False)["GenToLoad_MWh"].sum()
        sys_df.insert(0, "Zone", "System")
        df = pd.concat([df, sys_df], ignore_index=True)
    return df


# NetRevenue.csv cost columns, grouped. Their sum is the `Cost` column, and
# `LCOE × dispatch == CapExPower + CapExEnergy + OpEx + Emissions + ChargeCost`.
_CAPEX_POWER = ("Inv_cost_MW", "Inv_cost_charge_MW")
_CAPEX_ENERGY = ("Inv_cost_MWh",)
_OPEX = ("Fixed_OM_cost_MW", "Fixed_OM_cost_MWh", "Fixed_OM_cost_charge_MW",
         "Var_OM_cost_out", "Var_OM_cost_in", "Fuel_cost", "StartCost",
         "CO2SequestrationCost")
_EMISSIONS = ("EmissionsCost",)
_CHARGECOST = ("Charge_cost",)


def asset_metrics(rs: ResultSet) -> pd.DataFrame:
    """One row per asset (+ a TOTAL row) with the energy and cost accounting the
    Results page splits into its two tables.

    Energy columns (MWh/yr): AnnualGen (dispatch), EnergyToLoad, Curtail,
    EnergyToCharge.
    Cost columns ($/yr): CapExPower, CapExEnergy, OpEx, Emissions, ChargeCost —
    their sum is NetRevenue.csv's `Cost`.

    LCOE_$MWh: per asset = Cost / generation (dispatch — the standard LCOE
    definition; curtailed energy is not in the denominator). The summary row
    ("System") is a different basis: Σcost / Σ energy-served-to-load, so
    storage round-trips aren't double-counted.
    """
    cols = ["Resource", "Type", "Zone", "AnnualGen_MWh", "EnergyToLoad_MWh",
            "Curtail_MWh", "EnergyToCharge_MWh", "LCOE_$MWh", "CapExPower_$",
            "CapExEnergy_$", "OpEx_$", "Emissions_$", "ChargeCost_$", "is_total"]
    m = _resource_master(rs)
    m = m[m["exists"]].copy()
    if m.empty:
        return pd.DataFrame(columns=cols)

    rev = rs.net_revenue
    rev_of: dict[str, pd.Series] = {}
    if rev is not None and "Resource" in rev.columns:
        for _, r in rev.iterrows():
            n = str(r["Resource"]).strip()
            if n.lower() != "total":
                rev_of[n] = r

    def _grp(row, names):
        return sum(_f(row.get(c)) for c in names) if row is not None else 0.0

    _, charge_of, _ = _wide_parts(rs.charge)
    gtl = _gen_to_load_map(rs)

    rows = []
    for _, r in m.iterrows():
        n = r["Resource"]
        rr = rev_of.get(n)
        gen = r["AnnualGen_MWh"]
        cost = _f(rr.get("Cost")) if rr is not None else (
            _grp(rr, _CAPEX_POWER) + _grp(rr, _CAPEX_ENERGY) + _grp(rr, _OPEX)
            + _grp(rr, _EMISSIONS) + _grp(rr, _CHARGECOST))
        rows.append({
            "Resource": n, "Type": r["Type"], "Zone": int(r["Zone"]),
            "AnnualGen_MWh": gen,
            "EnergyToLoad_MWh": gtl.get(n, gen),
            "Curtail_MWh": r["Curtail_MWh"],
            "EnergyToCharge_MWh": max(0.0, charge_of.get(n, 0.0)),
            "LCOE_$MWh": (cost / gen) if gen > 0 else None,
            "CapExPower_$": _grp(rr, _CAPEX_POWER),
            "CapExEnergy_$": _grp(rr, _CAPEX_ENERGY),
            "OpEx_$": _grp(rr, _OPEX),
            "Emissions_$": _grp(rr, _EMISSIONS),
            "ChargeCost_$": _grp(rr, _CHARGECOST),
            "is_total": False,
        })
    df = pd.DataFrame(rows)

    _cost_cols = ["CapExPower_$", "CapExEnergy_$", "OpEx_$", "Emissions_$", "ChargeCost_$"]
    tot_cost = df[_cost_cols].sum().sum()
    tot_e2l = df["EnergyToLoad_MWh"].sum()
    total = {"Resource": "System", "Type": "", "Zone": "", "is_total": True,
             "LCOE_$MWh": (tot_cost / tot_e2l) if tot_e2l > 0 else None}
    for c in ["AnnualGen_MWh", "EnergyToLoad_MWh", "Curtail_MWh",
              "EnergyToCharge_MWh", *_cost_cols]:
        total[c] = df[c].sum()
    df = pd.concat([df, pd.DataFrame([total])], ignore_index=True)
    return df[cols]


# ── costs / NSE ────────────────────────────────────────────────────────────

def costs_components(rs: ResultSet) -> dict[str, float]:
    """{component -> total $} from costs.csv (cTotal, cFix, cVar, cNSE, …)."""
    if rs.costs is None or "Total" not in rs.costs.columns:
        return {}
    fc = rs.costs.columns[0]
    return {str(k): _f(v) for k, v in zip(rs.costs[fc], rs.costs["Total"])}


def cost_breakdown(rs: ResultSet) -> pd.DataFrame:
    """Per-resource cost breakdown ($M/yr): Resource, Type, Investment, Fixed O&M,
    Variable O&M, Fuel, Startup, Other."""
    rev = rs.net_revenue
    if rev is None or "Resource" not in rev.columns:
        return pd.DataFrame(columns=["Resource", "Type", "Investment", "Fixed O&M",
                                     "Variable O&M", "Fuel", "Startup", "Other"])
    rev = rev[rev["Resource"].astype(str) != "Total"].copy()
    M = 1e6

    def _grp(cands):
        present = [c for c in cands if c in rev.columns]
        return rev[present].apply(pd.to_numeric, errors="coerce").sum(axis=1) / M if present else 0.0

    out = pd.DataFrame({
        "Resource": rev["Resource"].astype(str),
        "Investment":  _grp(["Inv_cost_MW", "Inv_cost_MWh", "Inv_cost_charge_MW"]),
        "Fixed O&M":   _grp(["Fixed_OM_cost_MW", "Fixed_OM_cost_MWh", "Fixed_OM_cost_charge_MW"]),
        "Variable O&M": _grp(["Var_OM_cost_out", "Var_OM_cost_in"]),
        "Fuel":        _grp(["Fuel_cost"]),
        "Startup":     _grp(["StartCost"]),
        "Other":      _grp(["CO2SequestrationCost", "EmissionsCost"]),
    })
    out.insert(1, "Type", out["Resource"].map(resource_type))
    return out.reset_index(drop=True)


def nse_summary(rs: ResultSet) -> pd.DataFrame:
    """Zone, NSE_MWh — annual non-served energy per zone (+ a System row when
    multi-zone)."""
    zone_of, annual_of, _ = _wide_parts(rs.nse)
    per_zone: dict[int, float] = {}
    for col, mwh in annual_of.items():
        if str(col).lower() == "total":
            continue
        z = zone_of.get(col)
        if z:
            per_zone[z] = per_zone.get(z, 0.0) + _f(mwh)
    rows = [{"Zone": z, "NSE_MWh": v} for z, v in sorted(per_zone.items())]
    if rs.multi_zone and rows:
        rows.append({"Zone": "System", "NSE_MWh": sum(per_zone.values())})
    return pd.DataFrame(rows, columns=["Zone", "NSE_MWh"])


def nse_total_mwh(rs: ResultSet) -> float:
    _, annual_of, _ = _wide_parts(rs.nse)
    if "Total" in annual_of:
        return _f(annual_of["Total"])
    return sum(_f(v) for k, v in annual_of.items() if str(k).lower() != "total")


def demand_total_mwh(rs: ResultSet) -> float:
    zone_of, annual_of, _ = _wide_parts(rs.power_balance)
    total = 0.0
    for col, v in annual_of.items():
        if str(col).split(".")[0] == "Demand":
            total += abs(_f(v))
    return total


# ── timeseries accessors (chart sections) ──────────────────────────────────

def nse_timeseries(rs: ResultSet) -> pd.Series:
    """Total non-served energy (MW) per hour."""
    _, _, ts = _wide_parts(rs.nse)
    if ts.empty:
        return pd.Series(dtype=float)
    if "Total" in ts.columns:
        return pd.to_numeric(ts["Total"], errors="coerce").fillna(0.0)
    return ts.apply(pd.to_numeric, errors="coerce").fillna(0.0).sum(axis=1)


def curtailment_timeseries(rs: ResultSet) -> pd.DataFrame:
    """Hour-indexed curtailment (MW), columns = resources (Total dropped)."""
    _, _, ts = _wide_parts(rs.curtailment)
    return ts.drop(columns=[c for c in ts.columns if str(c).lower() == "total"], errors="ignore")


def power_timeseries(rs: ResultSet) -> pd.DataFrame:
    """Hour-indexed power (MW), columns = resources (Total dropped)."""
    _, _, ts = _wide_parts(rs.power)
    return ts.drop(columns=[c for c in ts.columns if str(c).lower() == "total"], errors="ignore")


# ── storage charging-source inference (ported from 3_Results) ───────────────

def charging_source(rs: ResultSet, inputs_dir: Path) -> pd.DataFrame:
    """(Storage, Hour, Bucket, MWh) — for each hour a storage resource charges,
    infer the marginal source by matching the zonal shadow price to each
    candidate's marginal cost. Derived economic interpretation, not a tracked flow.
    """
    empty = pd.DataFrame(columns=["Storage", "Hour", "Bucket", "MWh"])

    def _r(p: Path):
        try:
            return pd.read_csv(p) if p.exists() else None
        except (OSError, pd.errors.ParserError, pd.errors.EmptyDataError):
            return None

    thermal_df = _r(inputs_dir / "resources" / "Thermal.csv")
    vre_df = _r(inputs_dir / "resources" / "Vre.csv")
    storage_df = _r(inputs_dir / "resources" / "Storage.csv")
    fuels_df = _r(inputs_dir / "system" / "Fuels_data.csv")
    prices_in = rs.prices
    charge_in = rs.charge
    pb_in = rs.power_balance
    cap_in = rs.capacity

    if any(d is None for d in (thermal_df, storage_df, fuels_df, prices_in, charge_in)):
        return empty

    _pc = prices_in.columns[0]
    price_ts = prices_in[prices_in[_pc].astype(str).str.match(_TS_RE)].reset_index(drop=True)
    T = len(price_ts)
    if T == 0:
        return empty
    hours = list(range(1, T + 1))
    price_ts.index = hours

    fuels_indexed = fuels_df.set_index("Time_Index")

    def _fuel_price_series(fuel_name):
        if fuel_name not in fuels_indexed.columns:
            return pd.Series(0.0, index=hours)
        s = fuels_indexed[fuel_name]
        return pd.Series([_f(s.get(h, 0.0)) for h in hours], index=hours)

    thermal_cost = {}
    for _, row in thermal_df.iterrows():
        thermal_cost[row["Resource"]] = {
            "zone": int(_f(row["Zone"], 1)),
            "cost": _f(row.get("Var_OM_Cost_per_MWh"))
                    + _f(row.get("Heat_Rate_MMBTU_per_MWh")) * _fuel_price_series(row.get("Fuel")),
        }

    vre_zone = {}
    if vre_df is not None:
        vre_zone = {row["Resource"]: int(_f(row["Zone"], 1)) for _, row in vre_df.iterrows()}
    vre_zones_present = set(vre_zone.values())

    nse_by_zone = {}
    if pb_in is not None:
        zone_of, _, ts = _wide_parts(pb_in)
        ts.index = hours[:len(ts)] if len(ts) <= len(hours) else ts.index
        nse_cols = [c for c in pb_in.columns if "Nonserved_Energy" in str(c)]
        for zone in {zone_of.get(c) for c in nse_cols if zone_of.get(c)}:
            cols = [c for c in nse_cols if zone_of.get(c) == zone]
            nse_by_zone[zone] = pd.to_numeric(ts[cols].sum(axis=1), errors="coerce").fillna(0.0)

    storage_zone = {row["Resource"]: int(_f(row["Zone"], 1)) for _, row in storage_df.iterrows()}
    if cap_in is not None and "EndEnergyCap" in cap_in.columns:
        built = set(cap_in[pd.to_numeric(cap_in["EndEnergyCap"], errors="coerce").fillna(0.0) > 0]["Resource"])
        storage_zone = {n: z for n, z in storage_zone.items() if n in built}

    _chc = charge_in.columns[0]
    charge_ts = charge_in[charge_in[_chc].astype(str).str.match(_TS_RE)].reset_index(drop=True)
    charge_ts.index = hours

    TOL_REL, TOL_ABS = 0.02, 0.5

    def _classify(price, candidates, nse):
        if nse > 1e-3:
            return "Reliability shortfall"
        best_name, best_diff = None, None
        for name, cost in candidates.items():
            diff = abs(price - cost)
            tol = max(TOL_ABS, TOL_REL * max(price, cost, 1))
            if diff <= tol and (best_diff is None or diff < best_diff):
                best_name, best_diff = name, diff
        return best_name or "Unclassified"

    records = []
    for stor_name, zone in storage_zone.items():
        if stor_name not in charge_ts.columns or str(zone) not in price_ts.columns:
            continue
        price_s = pd.to_numeric(price_ts[str(zone)], errors="coerce").fillna(0.0)
        nse_s = nse_by_zone.get(zone)
        candidates = {n: i["cost"] for n, i in thermal_cost.items() if i["zone"] == zone}
        has_vre = zone in vre_zones_present
        charge_s = pd.to_numeric(charge_ts[stor_name], errors="coerce").fillna(0.0)
        for h in hours:
            c = charge_s[h]
            if c <= 1e-6:
                continue
            cand_at_h = {n: s[h] for n, s in candidates.items()}
            if has_vre:
                cand_at_h["Curtailed VRE"] = 0.0
            bucket = _classify(price_s[h], cand_at_h, nse_s[h] if nse_s is not None else 0.0)
            records.append({"Storage": stor_name, "Hour": h, "Bucket": bucket, "MWh": c})
    return pd.DataFrame(records, columns=["Storage", "Hour", "Bucket", "MWh"])
