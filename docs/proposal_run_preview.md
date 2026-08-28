<!-- status: proposal · owner: GenXUI · created 2026-08-28 -->

# Proposal: "Run preview" panel — what this run will actually solve

## Problem

Nothing in GenXUI tells the user what a case is going to do before they run it.
The settings that matter most for runtime and results are spread across four
files, some are silent defaults, and a few interact in non-obvious ways:

- **`TimeDomainReduction` is `0` by default** (missing key ⇒ off). A user who
  assumes clustering is on can kick off a full 8,760-hour solve by accident —
  or the reverse: a populated `TDR_results/` folder is silently ignored when
  the flag isn't `1`.
- When clustering *is* on, the number of timesteps depends on whether
  `TDR_results/` already exists (reused as-is) or not (re-clustered on the
  spot, count not known until it runs).
- `CO2Cap`, `UCommit`, `NetworkExpansion`, `MultiStage`, `DC_OPF`,
  `ParameterScale`, the min/max-capacity and reserve-margin policies — all
  change the model materially and none are surfaced.

A user recently had to reverse-engineer "why is this 1,848 timesteps?" from the
raw CSVs. That should be one glance.

## Goal

A compact, read-only **Run preview** on the Runner page, directly below the
**▶ Run GenX** button, that reads the case inputs and reports what the run will
solve:

- **Timesteps** — the predicted `T`, with the basis for the number.
- **Time domain reduction** — off / reusing `TDR_results/` / will re-cluster.
- **Zones**, **resources** (by type), **transmission lines**.
- **CO₂ cap** — mode + how many zonal caps.
- **Unit commitment**, **network expansion**, **multi-stage**, **DC-OPF**,
  **parameter scaling**.
- **Other policies** — min/max capacity requirement, capacity reserve margin,
  energy share requirement (active + constraint counts).
- **Solver** — method, crossover, time limit (from `highs_settings.yml`).
- **Warnings** — silent defaults and setting conflicts that change the output.

It updates when the selected case changes. It never writes anything.

---

## Predicting the timestep count

This mirrors GenX exactly — see
[`load_demand_data.jl:41`](../../GenX.jl/src/load_inputs/load_demand_data.jl#L41)
(`T = length(:Time_Index)` of the *active* `Demand_data.csv`) and
[`case_runner.jl:44-64`](../../GenX.jl/src/case_runners/case_runner.jl#L44)
(which `Demand_data.csv` is active).

```
setup      = merge(GenX default_settings(), yaml(settings/genx_settings.yml))
tdr_on     = setup["TimeDomainReduction"] == 1           # default 0
tdr_folder = setup["TimeDomainReductionFolder"]          # default "TDR_results"

if not tdr_on:
    T     = count_time_index(system/Demand_data.csv)     # e.g. 8760
    basis = "full time series — no reduction"

elif tdr_files_exist(<case>/<tdr_folder>):               # Demand_data.csv (or
    # GenX prints "Time Series Data Already Clustered." and reuses these files
    #  Load_data.csv) + Generators_variability.csv + Fuels_data.csv all present
    dd    = <case>/<tdr_folder>/Demand_data.csv
    T     = count_time_index(dd)                          # e.g. 1848
    rep   = int(dd[:Rep_Periods][0])                      # e.g. 11
    H     = int(dd[:Timesteps_per_Rep_Period][0])         # e.g. 168
    basis = f"reusing {tdr_folder}/ — {rep} rep periods × {H} h"

else:
    # GenX will cluster on run; the exact count isn't known until it does
    tdr   = yaml(settings/time_domain_reduction_settings.yml)
    H     = tdr["TimestepsPerRepPeriod"]                  # e.g. 168
    lo    = tdr["MinPeriods"]; hi = tdr["MaxPeriods"]     # e.g. 8, 11
    T     = None
    basis = (f"will cluster on run — {lo}–{hi} periods × {H} h "
             f"= {lo*H}–{hi*H} timesteps"
             + ("" if not tdr["IterativelyAddPeriods"]
                   else f", stopping at {tdr['Threshold']:.0%} error"))
```

`tdr_files_exist()` is GenX's own check
([`case_runner.jl:44`](../../GenX.jl/src/case_runners/case_runner.jl#L44)):
`Demand_data.csv`/`Load_data.csv` **and** `Generators_variability.csv` **and**
`Fuels_data.csv` all present in the TDR folder.

`count_time_index(path)` = number of non-blank cells in the `Time_Index`
column.

### Timestep-related warnings

| condition | warning |
|---|---|
| `TimeDomainReduction` key absent | "TimeDomainReduction not set → defaults to **off**; the full 8,760 h will be solved." |
| flag ≠ 1 **and** `TDR_results/` exists and is populated | "`TDR_results/` exists but TimeDomainReduction is off — it will be **ignored**." |
| flag = 1, no TDR folder, **and** `system/Demand_data.csv` already has `Rep_Periods ≠ 1` | "Input `Demand_data.csv` looks already-clustered; GenX will error (`prevent_doubled_timedomainreduction`)." |
| flag = 1, TDR folder present but **partial** (missing one of the three files) | "`TDR_results/` is incomplete — GenX will re-cluster from scratch." |

---

## Other fields — where each comes from

| Field | Source | Notes |
|---|---|---|
| Zones | `system/Network.csv` `Network_zones` rows, or `Demand_MW_z*` columns | |
| Transmission lines | `system/Network.csv` `Network_Lines` non-blank | |
| Network expansion | `setup["NetworkExpansion"]` (default 0) | |
| Resources by type | row counts of `resources/{Thermal,Vre,Storage,Vre_stor,Hydro,Must_run,Flex_demand,Electrolyzer}.csv` | only files that exist |
| Unit commitment | `setup["UCommit"]` | 0 none · 1 integer clustered · 2 linearized clustered |
| CO₂ cap | `setup["CO2Cap"]` + `policies/CO2_cap.csv` | 0 off · 1 mass · 2 demand rate-based · 3 gen rate-based; count `CO_2_Cap_Zone_*` columns set to 1 and report the caps |
| Min capacity req | `setup["MinCapReq"]` + `policies/Minimum_capacity_requirement.csv` row count | |
| Max capacity req | `setup["MaxCapReq"]` + `policies/Maximum_capacity_requirement.csv` | |
| Capacity reserve margin | `setup["CapacityReserveMargin"]` + `policies/Capacity_reserve_margin.csv` | |
| Energy share req | `setup["EnergyShareRequirement"]` + `policies/Energy_share_requirement.csv` | |
| Multi-stage | `setup["MultiStage"]` + `settings/multi_stage_settings.yml` `NumStages` | preview is for stage 1 unless noted |
| DC-OPF | `setup["DC_OPF"]` (default 0) | |
| Parameter scaling | `setup["ParameterScale"]` (default 0) | affects units in results, not model size |
| Solver | `settings/highs_settings.yml` (`Method`, `run_crossover`, `TimeLimit`) | detect Gurobi/CPLEX settings files too |

### Rough model-size hint (optional)

A single deliberately-fuzzy line, not a promise:

> ≈ `T × (resources + zones)` core dispatch variables — **~{n:,}** (before UC,
> storage, transmission, and policy variables)

Skip it if it proves misleading in practice.

---

## Data model + entry point

New module `src/run_preview.py` — pure, no Streamlit, uses `yaml.safe_load`
(read-only; comment preservation isn't a concern here, unlike
[`run_settings.py`](../src/run_settings.py)).

```python
from dataclasses import dataclass, field

@dataclass(frozen=True)
class PreviewRow:
    label: str
    value: str
    hint: str | None = None       # small caption under the value

@dataclass(frozen=True)
class RunPreview:
    timesteps: int | None         # None => "will cluster", show the range in `timesteps_basis`
    timesteps_basis: str
    rows: list[PreviewRow]        # zones, resources, CO2 cap, UC, …
    warnings: list[str] = field(default_factory=list)
    error: str | None = None      # inputs unreadable / case malformed


# GenX default_settings() subset we rely on — keep in sync with
# GenX.jl/src/configure_settings/configure_settings.jl
_GENX_DEFAULTS = {
    "TimeDomainReduction": 0, "TimeDomainReductionFolder": "TDR_results",
    "NetworkExpansion": 0, "UCommit": 0, "CO2Cap": 0, "MultiStage": 0,
    "DC_OPF": 0, "ParameterScale": 0, "MinCapReq": 0, "MaxCapReq": 0,
    "CapacityReserveMargin": 0, "EnergyShareRequirement": 0,
    "Trans_Loss_Segments": 1, "SystemFolder": "system",
}

def build_run_preview(case_path: Path) -> RunPreview:
    """Read a case's inputs and predict what the run will solve. Never writes.
    On any unreadable/malformed input, returns RunPreview(error=...) rather
    than raising."""
    ...
```

`case_path` is `workspace.data_dir() / case_name` — the same folder
`stream_process()` runs Julia in, so the preview reflects exactly what will
execute.

---

## UI placement

`col_controls` in [`app.py`](../app.py), between the "Runs overwrite …"
caption and the `_rc` result block:

```python
    with st.expander("🔎 Run preview", expanded=False):
        pv = run_preview.build_run_preview(case_path)
        if pv.error:
            st.caption(f"Preview unavailable — {pv.error}")
        else:
            if pv.timesteps is not None:
                st.metric("Timesteps", f"{pv.timesteps:,}")
            st.caption(pv.timesteps_basis)
            for row in pv.rows:
                st.markdown(f"**{row.label}** · {row.value}"
                            + (f"  \n<small>{row.hint}</small>" if row.hint else ""),
                            unsafe_allow_html=True)
            for w in pv.warnings:
                st.warning(w, icon="⚠️")
```

Rendering details (metric vs. plain list, exact wording, whether it starts
expanded) are for implementation — the data model is the contract.

### Caching

`build_run_preview` is cheap (a few small CSV reads + two YAML loads). Wrap a
cached inner function keyed on the mtimes of `settings/`, `resources/`,
`policies/`, `system/Demand_data.csv`, and `TDR_results/Demand_data.csv` so it
recomputes when inputs change but not on every rerun.

---

## Testing

`tests/test_run_preview.py`, using small synthetic case folders in a tmpdir:

- **Timesteps — TDR off:** `system/Demand_data.csv` with 48 `Time_Index` rows,
  no `TimeDomainReduction` key ⇒ `timesteps == 48`, basis mentions "no
  reduction", warning about the default.
- **Timesteps — reusing TDR:** `TimeDomainReduction: 1` + a populated
  `TDR_results/` (`Rep_Periods=11`, `H=168`, 1848 `Time_Index` rows) ⇒
  `timesteps == 1848`, basis says "reusing".
- **Timesteps — will cluster:** `TimeDomainReduction: 1`, no `TDR_results/`,
  `MinPeriods=8 MaxPeriods=11 TimestepsPerRepPeriod=168` ⇒ `timesteps is None`,
  basis contains "1344–1848".
- **Ignored TDR folder:** flag absent but `TDR_results/` populated ⇒ warning.
- **Partial TDR folder:** only `Demand_data.csv` present ⇒ "will re-cluster"
  path + warning.
- **CO₂ cap:** `CO2Cap: 2` + a `CO2_cap.csv` with 3 zonal columns ⇒ row reads
  "Rate-based (demand), 3 zonal caps".
- **Defaults:** empty `genx_settings.yml` ⇒ UC "off", CO₂ "off", DC-OPF "off",
  no crash.
- **Malformed:** missing `system/Demand_data.csv` ⇒ `RunPreview(error=…)`, no
  exception.

Plus a check against the real bundled examples: `build_run_preview` on each
`example_systems/*` copy returns no `error`.

---

## Out of scope

- **Exact post-clustering timestep count** when GenX will re-cluster — it's
  genuinely not knowable without running the clustering. The range + threshold
  is the honest answer.
- **Multi-stage** beyond reporting stage count and that the preview describes
  stage 1.
- **Predicting solve time / memory** — too environment-dependent; the
  [error-diagnosis layer](proposal_run_error_diagnosis.md) already handles the
  out-of-memory case after the fact.
- Any write to case inputs.

---

## Relationship to other proposals

- [`proposal_run_error_diagnosis.md`](proposal_run_error_diagnosis.md) — after
  the run; this is before.
- [`proposal_results_dir_resolution.md`](proposal_results_dir_resolution.md) —
  the preview could also note "a previous `results/` exists — this run will
  overwrite it" once `OverwriteResults` handling is in.
