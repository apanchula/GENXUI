"""Data prep for the Inputs page "fleet view" (resource Overview).

Pure — no Streamlit, no Plotly. The page (`pages/2_Inputs.py`) turns these
frames / layout dicts into a treemap and a hub-and-spoke bus diagram.

See docs/proposal_resource_fleet_view.md.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from src.resource_style import resource_color

# resource file -> short type label (order = legend / treemap order)
RESOURCE_FILES: dict[str, str] = {
    "Thermal.csv":         "Thermal",
    "Vre.csv":             "VRE",
    "Hydro.csv":           "Hydro",
    "Storage.csv":         "Storage",
    "Vre_stor.csv":        "VRE+Storage",
    "Flex_demand.csv":     "Flex demand",
    "Must_run.csv":        "Must-run",
    "Electrolyzer.csv":    "Electrolyzer",
    "Allam_Cycle_LOX.csv": "Allam Cycle",
}

# label shown in the sizing selector -> FleetResource attribute
SIZE_METRICS: dict[str, str] = {
    "Existing capacity (MW)":      "existing_mw",
    "Max capacity (MW)":           "max_mw",
    "Investment cost ($/MW-yr)":   "inv_cost",
}

_UNBOUNDED = -1.0


@dataclass(frozen=True)
class FleetResource:
    name: str
    type: str
    zone: int
    region: str
    existing_mw: float
    max_mw: float | None       # None == unbounded (-1) or unspecified
    min_mw: float
    inv_cost: float
    new_build: bool

    @property
    def color(self) -> str:
        return resource_color(self.name)


def _num(row: pd.Series, *keys: str, default: float = 0.0) -> float:
    for k in keys:
        if k in row.index and pd.notna(row[k]):
            try:
                return float(row[k])
            except (TypeError, ValueError):
                return default
    return default


def load_fleet(case_path: Path, filenames: list[str] | None = None) -> list[FleetResource]:
    """Read the resource CSVs under `case_path/resources/` into FleetResources.

    `filenames` restricts to specific files (e.g. ["Thermal.csv"]); default is
    every known resource file that exists. Unknown files are ignored.
    """
    res_dir = case_path / "resources"
    if not res_dir.exists():
        return []

    wanted = filenames or list(RESOURCE_FILES)
    out: list[FleetResource] = []
    for fname in wanted:
        rtype = RESOURCE_FILES.get(fname)
        fp = res_dir / fname
        if rtype is None or not fp.exists():
            continue
        try:
            df = pd.read_csv(fp)
        except (OSError, pd.errors.ParserError, pd.errors.EmptyDataError):
            continue
        for _, row in df.iterrows():
            if pd.isna(row.get("Resource")):
                continue
            max_raw = _num(row, "Max_Cap_MW", default=_UNBOUNDED)
            out.append(FleetResource(
                name=str(row["Resource"]).strip(),
                type=rtype,
                zone=int(_num(row, "Zone", default=1)),
                region=str(row.get("region") or "").strip(),
                existing_mw=max(0.0, _num(row, "Existing_Cap_MW")),
                max_mw=None if max_raw < 0 else max_raw,
                min_mw=max(0.0, _num(row, "Min_Cap_MW")),
                inv_cost=_num(row, "Inv_Cost_per_MWyr"),
                new_build=bool(_num(row, "New_Build", default=0.0)),
            ))
    return out


# ── metrics ─────────────────────────────────────────────────────────────────

def fleet_metrics(resources: list[FleetResource]) -> dict:
    zones = sorted({r.zone for r in resources})
    by_type: dict[str, int] = {}
    for r in resources:
        by_type[r.type] = by_type.get(r.type, 0) + 1
    existing_total = sum(r.existing_mw for r in resources)
    candidates = [r for r in resources if r.new_build and r.existing_mw == 0]
    candidate_cap = sum(r.max_mw for r in candidates if r.max_mw is not None)
    return {
        "count": len(resources),
        "zones": zones,
        "n_zones": len(zones),
        "existing_total_mw": existing_total,
        "candidate_count": len(candidates),
        "candidate_cap_mw": candidate_cap,          # 0 when candidates are uncapped
        "by_type": by_type,
        "greenfield": bool(resources) and existing_total == 0,
    }


# ── sizing ──────────────────────────────────────────────────────────────────

def size_series(resources: list[FleetResource], attr: str) -> tuple[list[float], bool, str | None]:
    """Values for the chosen sizing metric.

    Returns (values, is_uniform, note). When the metric is missing / all
    non-positive (e.g. a greenfield case sized by existing capacity, or
    Max_Cap_MW all unbounded), falls back to equal values and a note the page
    can show as a caption.
    """
    raw = [getattr(r, attr) for r in resources]
    vals = [float(v) if v is not None and v > 0 else 0.0 for v in raw]
    if not vals or sum(vals) == 0:
        note = {
            "existing_mw": "No built capacity in this case — tiles are equal-sized (greenfield).",
            "max_mw":      "Max capacity is unbounded/unset for every resource — tiles are equal-sized.",
            "inv_cost":    "No investment cost set — tiles are equal-sized.",
        }.get(attr, "Metric unavailable — tiles are equal-sized.")
        return [1.0] * len(resources), True, note
    return vals, False, None


# ── treemap frame ───────────────────────────────────────────────────────────

def fleet_frame(resources: list[FleetResource], sizes: list[float]) -> pd.DataFrame:
    """One row per resource, with the resolved `Size` column, for px.treemap."""
    return pd.DataFrame({
        "Resource": [r.name for r in resources],
        "Type":     [r.type for r in resources],
        "Zone":     [f"Zone {r.zone}" + (f" · {r.region}" if r.region else "") for r in resources],
        "Region":   [r.region for r in resources],
        "Existing_MW": [r.existing_mw for r in resources],
        "Max_MW":   [("∞" if r.max_mw is None else r.max_mw) for r in resources],
        "Inv_Cost": [r.inv_cost for r in resources],
        "New_Build": ["Yes" if r.new_build else "No" for r in resources],
        "Color":    [r.color for r in resources],
        "Size":     [max(0.0, s) for s in sizes],
    })


# ── network / bus layout ────────────────────────────────────────────────────

def read_network_lines(case_path: Path) -> list[tuple[int, int]]:
    """Inter-zone lines from system/Network.csv, as (start_zone, end_zone).

    Supports the list interface (Start_Zone/End_Zone columns) and the matrix
    interface (z1, z2, … columns with +1 / -1). [] if no Network.csv.
    """
    fp = case_path / "system" / "Network.csv"
    if not fp.exists():
        return []
    try:
        df = pd.read_csv(fp)
    except (OSError, pd.errors.ParserError, pd.errors.EmptyDataError):
        return []

    lines: list[tuple[int, int]] = []
    if {"Start_Zone", "End_Zone"} <= set(df.columns):
        for _, row in df.iterrows():
            s, e = row.get("Start_Zone"), row.get("End_Zone")
            if pd.notna(s) and pd.notna(e):
                lines.append((int(s), int(e)))
        return lines

    zcols = sorted((c for c in df.columns if _is_zcol(c)), key=_zcol_num)
    for _, row in df.iterrows():
        start = end = None
        for c in zcols:
            v = row.get(c)
            if pd.isna(v):
                continue
            if v == 1:
                start = _zcol_num(c)
            elif v == -1:
                end = _zcol_num(c)
        if start and end:
            lines.append((start, end))
    return lines


def read_zone_demand(case_path: Path) -> dict[int, float]:
    """Peak demand (MW) per zone from system/Demand_data.csv (or Load_data.csv).

    Returns {zone_number: peak_MW}; {} if the file or the Demand_MW_z* columns
    aren't there.
    """
    for name in ("Demand_data.csv", "Load_data.csv"):
        fp = case_path / "system" / name
        if fp.exists():
            break
    else:
        return {}
    try:
        df = pd.read_csv(fp)
    except (OSError, pd.errors.ParserError, pd.errors.EmptyDataError):
        return {}

    out: dict[int, float] = {}
    for col in df.columns:
        m = re.fullmatch(r"(?:Demand|Load)_MW_z(\d+)", str(col))
        if not m:
            continue
        peak = pd.to_numeric(df[col], errors="coerce").max()
        if pd.notna(peak):
            out[int(m.group(1))] = float(peak)
    return out


def _is_zcol(c: object) -> bool:
    s = str(c)
    return len(s) >= 2 and s[0] in "zZ" and s[1:].isdigit()


def _zcol_num(c: object) -> int:
    return int(str(c)[1:])


def bus_layout(resources: list[FleetResource], sizes: list[float] | None = None,
               tie_lines: list[tuple[int, int]] | None = None,
               demand: dict[int, float] | None = None) -> dict:
    """Hub-and-spoke coordinates for the bus diagram.

    One hub per zone; resources radiate off their zone's hub; hubs are linked
    by `tie_lines`; each zone's demand (from `demand`, {zone: peak_MW}) hangs
    off its hub as a load node pointing away from the grid centre. Single-zone
    collapses to one central hub. `sizes` (aligned to `resources`) passes
    straight through onto the node dicts for the page to scale.
    """
    sizes = sizes or [1.0] * len(resources)
    demand = demand or {}
    zones = sorted(
        {r.zone for r in resources}
        | {z for pair in (tie_lines or []) for z in pair}
        | set(demand)
    )
    if not zones:
        return {"hubs": [], "nodes": [], "spokes": [], "ties": [], "loads": [], "load_edges": []}

    hub_r = 0.0 if len(zones) == 1 else 3.2
    hub_xy: dict[int, tuple[float, float]] = {}
    hubs = []
    for i, z in enumerate(zones):
        ang = 2 * math.pi * i / len(zones) - math.pi / 2
        x, y = (hub_r * math.cos(ang), hub_r * math.sin(ang)) if hub_r else (0.0, 0.0)
        hub_xy[z] = (x, y)
        region = _common_region(resources, z)
        hubs.append({"zone": z, "label": region or f"Zone {z}", "x": x, "y": y})

    # Resources and the load share one evenly-spaced ring around each hub, so
    # the load stub never lands on top of (or behind) a resource spoke. Slot 0
    # is reserved for the load (pointing radially outward from the grid centre,
    # or straight down for a lone hub); resources take the remaining slots.
    spoke_r = 1.3
    load_r = 2.0
    nodes, spokes, loads, load_edges = [], [], [], []
    by_zone: dict[int, list[int]] = {}
    for idx, r in enumerate(resources):
        by_zone.setdefault(r.zone, []).append(idx)

    for z in zones:
        hx, hy = hub_xy[z]
        idxs = by_zone.get(z, [])
        has_load = z in demand
        total = len(idxs) + (1 if has_load else 0)
        if total == 0:
            continue
        base = -math.pi / 2 if len(zones) == 1 else math.atan2(hy, hx)

        slot = 0
        if has_load:
            lx, ly = hx + load_r * math.cos(base), hy + load_r * math.sin(base)
            loads.append({"zone": z, "x": lx, "y": ly, "mw": demand[z]})
            load_edges.append((hx, hy, lx, ly))
            slot = 1

        for k, idx in enumerate(idxs):
            ang = base + 2 * math.pi * (slot + k) / total
            nx, ny = hx + spoke_r * math.cos(ang), hy + spoke_r * math.sin(ang)
            r = resources[idx]
            nodes.append({
                "name": r.name, "type": r.type, "zone": z,
                "x": nx, "y": ny, "color": r.color, "size": max(0.0, sizes[idx]),
            })
            spokes.append((nx, ny, hx, hy))

    ties = []
    for a, b in (tie_lines or []):
        if a in hub_xy and b in hub_xy:
            ties.append((*hub_xy[a], *hub_xy[b]))

    return {"hubs": hubs, "nodes": nodes, "spokes": spokes, "ties": ties,
            "loads": loads, "load_edges": load_edges}


def _common_region(resources: list[FleetResource], zone: int) -> str:
    regions = [r.region for r in resources if r.zone == zone and r.region]
    return max(set(regions), key=regions.count) if regions else ""
