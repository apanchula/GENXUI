"""Read-only "what will this run solve" preview for the Runner page (GENXUI-4).

`build_run_preview(case_path)` reads a case's input files — the same folder
`stream_process()` runs Julia in — and predicts the run's shape: timestep count
(mirroring GenX's own time-domain-reduction decision), zones, resources,
policies, solver settings, and warnings for silent defaults / setting conflicts.

Pure: no Streamlit, `yaml.safe_load` only, never writes. See
docs/design/proposal_run_preview.md.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import yaml

from src.fleet_view import RESOURCE_FILES

# GenX default_settings() — keep in sync with
# GenX.jl/src/configure_settings/configure_settings.jl
_GENX_DEFAULTS: dict[str, object] = {
    "TimeDomainReduction": 0,
    "TimeDomainReductionFolder": "TDR_results",
    "SystemFolder": "system",
    "PoliciesFolder": "policies",
    "ResourcesFolder": "resources",
    "NetworkExpansion": 0,
    "UCommit": 0,
    "CO2Cap": 0,
    "MultiStage": 0,
    "DC_OPF": 0,
    "ParameterScale": 0,
    "MinCapReq": 0,
    "MaxCapReq": 0,
    "CapacityReserveMargin": 0,
    "EnergyShareRequirement": 0,
    "Trans_Loss_Segments": 1,
}

_CO2_MODES = {
    1: "mass-based",
    2: "rate-based (demand)",
    3: "rate-based (generation)",
}
_UCOMMIT = {0: "off", 1: "integer clustering", 2: "linearized clustering"}


@dataclass(frozen=True)
class PreviewRow:
    label: str
    value: str
    hint: str | None = None


@dataclass(frozen=True)
class RunPreview:
    timesteps: int | None          # None => "will cluster", see timesteps_basis
    timesteps_basis: str
    rows: list[PreviewRow] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None


# ── low-level readers ───────────────────────────────────────────────────────

def _load_yaml(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, yaml.YAMLError):
        return {}


def _as_int(value: object, default: int = 0) -> int:
    try:
        return int(float(value))  # tolerates "2", 2, 2.0
    except (TypeError, ValueError):
        return default


def _demand_file(folder: Path) -> Path | None:
    for name in ("Demand_data.csv", "Load_data.csv"):
        if (folder / name).is_file():
            return folder / name
    return None


def _read_csv(path: Path) -> pd.DataFrame | None:
    try:
        return pd.read_csv(path)
    except (OSError, pd.errors.ParserError, pd.errors.EmptyDataError):
        return None


def _count_time_index(demand_csv: Path) -> int | None:
    df = _read_csv(demand_csv)
    if df is None or "Time_Index" not in df.columns:
        return None
    return int(pd.to_numeric(df["Time_Index"], errors="coerce").notna().sum())


def _first_val(demand_csv: Path, col: str) -> float | None:
    df = _read_csv(demand_csv)
    if df is None or col not in df.columns:
        return None
    s = pd.to_numeric(df[col], errors="coerce").dropna()
    return float(s.iloc[0]) if not s.empty else None


def _tdr_complete(tdr_dir: Path) -> bool:
    """GenX's own reuse check (case_runner.jl: time_domain_reduced_files_exist)."""
    return (
        _demand_file(tdr_dir) is not None
        and (tdr_dir / "Generators_variability.csv").is_file()
        and (tdr_dir / "Fuels_data.csv").is_file()
    )


def _network(sys_dir: Path, demand_csv: Path | None) -> tuple[int, int]:
    """(zones, transmission lines)."""
    net = sys_dir / "Network.csv"
    df = _read_csv(net) if net.is_file() else None
    if df is not None:
        zones = int(pd.to_numeric(df.get("Network_zones", pd.Series(dtype=str)),
                                  errors="coerce").notna().sum()) or len(df)
        if "Network_Lines" in df.columns:
            lines = int(pd.to_numeric(df["Network_Lines"], errors="coerce").notna().sum())
        elif {"Start_Zone", "End_Zone"} <= set(df.columns):
            lines = int(df[["Start_Zone", "End_Zone"]].notna().all(axis=1).sum())
        else:
            lines = 0
        return max(zones, 1), lines
    # single-zone: infer zone count from Demand_MW_z* columns
    zones = 1
    if demand_csv is not None:
        dd = _read_csv(demand_csv)
        if dd is not None:
            zcols = [c for c in dd.columns if re.fullmatch(r"Demand_MW_z\d+", str(c))]
            zones = max(len(zcols), 1)
    return zones, 0


# ── main entry point ───────────────────────────────────────────────────────

def build_run_preview(case_path: Path) -> RunPreview:
    """Predict what a GenX run on `case_path` will solve. Never raises."""
    try:
        return _build(case_path)
    except Exception as exc:                      # never break the Runner page
        return RunPreview(None, "", error=f"could not read case inputs: {exc}")


def _build(case_path: Path) -> RunPreview:
    settings_dir = case_path / "settings"
    genx_raw = _load_yaml(settings_dir / "genx_settings.yml")
    setup = {**_GENX_DEFAULTS, **genx_raw}

    sys_name = str(setup["SystemFolder"])
    multi_stage = _as_int(setup["MultiStage"]) == 1

    # Multi-stage cases keep per-stage inputs under inputs/inputs_p1/… — describe
    # stage 1.
    input_root = case_path
    if not (case_path / sys_name).exists():
        p1 = case_path / "inputs" / "inputs_p1"
        if (p1 / sys_name).exists():
            input_root = p1
            multi_stage = True

    sys_dir = input_root / sys_name
    pol_dir = input_root / str(setup["PoliciesFolder"])
    res_dir = input_root / str(setup["ResourcesFolder"])
    tdr_name = str(setup["TimeDomainReductionFolder"])
    tdr_dir = input_root / tdr_name

    sys_demand = _demand_file(sys_dir)
    if sys_demand is None:
        return RunPreview(None, "", error=f"no Demand_data.csv under `{sys_dir.name}/`")

    warnings: list[str] = []
    if multi_stage and input_root != case_path:
        warnings.append("Multi-stage case — this preview describes stage 1 only.")
    tdr_on = _as_int(setup["TimeDomainReduction"]) == 1

    # ── timesteps ──────────────────────────────────────────────────────────
    if not tdr_on:
        t = _count_time_index(sys_demand)
        timesteps = t
        timesteps_basis = (
            f"full time series, no reduction"
            + (f" — {t:,} timesteps" if t else "")
        )
        if "TimeDomainReduction" not in genx_raw:
            warnings.append(
                "TimeDomainReduction isn't set — it defaults to off, so the "
                "full time series will be solved."
            )
        if _tdr_complete(tdr_dir):
            warnings.append(
                f"{tdr_name}/ holds clustered data but TimeDomainReduction is "
                "off — it will be ignored."
            )
    elif _tdr_complete(tdr_dir):
        tdr_demand = _demand_file(tdr_dir)
        timesteps = _count_time_index(tdr_demand)
        rep = _first_val(tdr_demand, "Rep_Periods")
        h = _first_val(tdr_demand, "Timesteps_per_Rep_Period")
        basis = f"reusing `{tdr_name}/`"
        if rep and h:
            basis += f" — {int(rep)} representative periods × {int(h)} h"
        timesteps_basis = basis
    else:
        tdr_yml = _load_yaml(settings_dir / "time_domain_reduction_settings.yml")
        h = _as_int(tdr_yml.get("TimestepsPerRepPeriod")
                    or tdr_yml.get("Timesteps_per_period"), 0)
        lo = _as_int(tdr_yml.get("MinPeriods"), 0)
        hi = _as_int(tdr_yml.get("MaxPeriods"), 0)
        timesteps = None
        if lo and hi and h and lo == hi:
            basis = f"will cluster on run — {lo} periods × {h} h = {lo * h:,} timesteps"
        elif lo and hi and h:
            basis = (f"will cluster on run — {lo}–{hi} periods × {h} h "
                     f"= {lo * h:,}–{hi * h:,} timesteps")
            if _as_int(tdr_yml.get("IterativelyAddPeriods")) == 1 and tdr_yml.get("Threshold"):
                try:
                    basis += f", stopping within {float(tdr_yml['Threshold']) * 100:g}% error"
                except (TypeError, ValueError):
                    pass
        else:
            basis = "will cluster on run — period count not set in time_domain_reduction_settings.yml"
        timesteps_basis = basis

        if tdr_dir.exists() and _demand_file(tdr_dir) is not None:
            warnings.append(
                f"{tdr_name}/ is incomplete (missing one of Demand / "
                "Generators_variability / Fuels_data) — GenX will re-cluster from scratch."
            )
        rep_sys = _first_val(sys_demand, "Rep_Periods")
        if rep_sys not in (None, 1.0):
            warnings.append(
                "system/Demand_data.csv already looks clustered (Rep_Periods ≠ 1) — "
                "GenX will stop with a prevent_doubled_timedomainreduction error."
            )

    # ── rows ───────────────────────────────────────────────────────────────
    rows: list[PreviewRow] = []
    zones, lines = _network(sys_dir, sys_demand)
    rows.append(PreviewRow("Zones", str(zones),
                           f"{lines} transmission line(s)" if zones > 1 else "single zone"))

    by_type: dict[str, int] = {}
    for fname, label in RESOURCE_FILES.items():
        df = _read_csv(res_dir / fname)
        if df is not None and not df.empty:
            n = int(df["Resource"].notna().sum()) if "Resource" in df.columns else len(df)
            if n:
                by_type[label] = by_type.get(label, 0) + n
    total_res = sum(by_type.values())
    rows.append(PreviewRow(
        "Resources", str(total_res),
        " · ".join(f"{lbl}: {n}" for lbl, n in by_type.items()) or None,
    ))

    co2 = _as_int(setup["CO2Cap"])
    if co2 == 0:
        rows.append(PreviewRow("CO₂ cap", "off"))
    else:
        cdf = _read_csv(pol_dir / "CO2_cap.csv")
        ncap = 0
        if cdf is not None:
            ncap = len([c for c in cdf.columns if re.fullmatch(r"CO_?2_Cap_Zone_\d+", str(c))])
        rows.append(PreviewRow(
            "CO₂ cap", _CO2_MODES.get(co2, f"mode {co2}"),
            f"{ncap} zonal cap(s)" if ncap else None,
        ))

    rows.append(PreviewRow("Unit commitment", _UCOMMIT.get(_as_int(setup["UCommit"]),
                                                           str(setup["UCommit"]))))
    rows.append(PreviewRow("Network expansion",
                           "on" if _as_int(setup["NetworkExpansion"]) == 1 else "off"))

    if multi_stage:
        ms = _load_yaml(settings_dir / "multi_stage_settings.yml")
        n = _as_int(ms.get("NumStages"), 0)
        rows.append(PreviewRow("Multi-stage", "on", f"{n} stages" if n else "preview describes stage 1"))
    else:
        rows.append(PreviewRow("Multi-stage", "off"))

    if _as_int(setup["DC_OPF"]) == 1:
        rows.append(PreviewRow("DC-OPF", "on"))
    rows.append(PreviewRow(
        "Parameter scaling",
        "on — GW units" if _as_int(setup["ParameterScale"]) == 1 else "off — MW units",
    ))

    pol_bits = []
    for key, fname, name in (
        ("MinCapReq", "Minimum_capacity_requirement.csv", "min-capacity"),
        ("MaxCapReq", "Maximum_capacity_requirement.csv", "max-capacity"),
        ("CapacityReserveMargin", "Capacity_reserve_margin.csv", "reserve-margin"),
        ("EnergyShareRequirement", "Energy_share_requirement.csv", "energy-share"),
    ):
        if _as_int(setup[key]) != 0:
            df = _read_csv(pol_dir / fname)
            cnt = len(df) if df is not None else None
            pol_bits.append(f"{name}" + (f" ({cnt})" if cnt else ""))
    rows.append(PreviewRow("Other policies", " · ".join(pol_bits) if pol_bits else "none"))

    rows.append(_solver_row(settings_dir, setup))

    return RunPreview(timesteps, timesteps_basis, rows, warnings)


def _solver_row(settings_dir: Path, setup: dict) -> PreviewRow:
    solver = str(setup.get("Solver") or "HiGHS").strip()
    yml = _load_yaml(settings_dir / f"{solver.lower()}_settings.yml")
    method = yml.get("Method")
    tl = yml.get("TimeLimit")
    cross = yml.get("run_crossover", yml.get("Crossover"))
    bits = []
    if method not in (None, ""):
        bits.append(f"method {method}")
    if str(cross).lower() in ("off", "0", "-1"):
        bits.append("no crossover")
    if tl not in (None, "") and _as_int(tl, 0) > 0 and float(_as_int(tl)) < 1e20:
        bits.append(f"time limit {tl}s")
    return PreviewRow("Solver", solver, " · ".join(bits) or None)
