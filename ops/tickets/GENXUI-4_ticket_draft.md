## GENXUI-4: Run Preview panel on the Runner

**Target Execution Window:** 11:00 PM – 2:00 AM · **Priority:** Medium (self-contained, additive; makes the Runner honest about what a case will actually solve before the user commits minutes/hours to a run)

**Scope note:** the Refresh roadmap's Phase 4 ("Main Modeling Page & Visualization Refresh") is deliberately **narrowed for this ticket to one deliverable: the Run Preview panel** specified in [`docs/proposal_run_preview.md`](proposal_run_preview.md). A broader Runner/Inputs layout-and-charts overhaul is *not* in scope here — if that's still wanted it gets its own ticket later.

Today nothing tells the user what a run will do before they start it. `TimeDomainReduction` defaults to `0` (a missing key ⇒ full-year solve); when it's on, the timestep count depends on whether `TDR_results/` already exists; and `CO2Cap`, `UCommit`, `NetworkExpansion`, `MultiStage`, `DC_OPF`, the policy flags and solver method are all invisible. A user recently had to reverse-engineer "why is this 1,848 timesteps?" from the raw CSVs. This ticket adds a compact, **read-only** preview directly below the ▶ Run GenX button. It writes nothing.

The full design — timestep-prediction algorithm (mirroring GenX's `load_demand_data.jl` / `case_runner.jl`), field-source table, warning catalog, `RunPreview` data model, caching, and test plan — is in `proposal_run_preview.md` and is the spec. This ticket's criteria are the checkable subset.

### Scope & Acceptance Criteria

- **`src/run_preview.py` exists** (pure — no Streamlit import; `yaml.safe_load` only, read-only) and exports `build_run_preview(case_path: Path) -> RunPreview`. `case_path` is `workspace.data_dir() / case_name` — the exact folder `stream_process()` runs Julia in. On any unreadable/malformed input it returns `RunPreview(error=…)`, never raises.
- **`RunPreview`** carries at least: `timesteps: int | None`, `timesteps_basis: str`, `rows: list[PreviewRow]` (label / value / optional hint), `warnings: list[str]`, `error: str | None`.
- **Timestep prediction** matches GenX's own logic:
  - `TimeDomainReduction` off (default, or `0`) → `timesteps` = count of `Time_Index` rows in `system/Demand_data.csv`; basis says "full time series — no reduction".
  - on **and** `TDR_results/` (or the configured `TimeDomainReductionFolder`) has `Demand_data.csv`/`Load_data.csv` **+** `Generators_variability.csv` **+** `Fuels_data.csv` → `timesteps` = `Time_Index` rows in the clustered `Demand_data.csv`; basis reports `Rep_Periods × Timesteps_per_Rep_Period` and that it's "reusing" the folder.
  - on **and** that folder is absent/partial → `timesteps is None`; basis gives the `MinPeriods–MaxPeriods × TimestepsPerRepPeriod` range from `time_domain_reduction_settings.yml`.
- **Warnings** include at least: `TimeDomainReduction` key absent ("defaults to off — full series"); flag off but `TDR_results/` populated ("exists but will be ignored"); flag on, no TDR folder, and `system/Demand_data.csv` already has `Rep_Periods ≠ 1` ("looks already-clustered — GenX will error"); flag on with a **partial** TDR folder ("incomplete — GenX will re-cluster").
- **Rows** cover, reading the merged `default_settings()` + `genx_settings.yml`: zones + transmission lines (from `system/Network.csv`), resources by type (row counts of the `resources/*.csv` that exist), `CO2Cap` (mode label + zonal-cap count from `policies/CO2_cap.csv`), `UCommit`, `NetworkExpansion`, `MultiStage` (+ `NumStages`), `DC_OPF`, `ParameterScale`, the min/max-capacity / capacity-reserve-margin / energy-share-requirement policy flags (active + constraint counts), and solver method / crossover / time limit from the `*_settings.yml` in use.
- The GenX-defaults subset baked into `run_preview.py` carries a comment pointing at `GenX.jl/src/configure_settings/configure_settings.jl` as the source of truth to keep in sync.
- **`app.py` renders it** in `col_controls`, immediately after the `st.caption("Runs overwrite this case's results/…")` line and before the `_rc` result block, as a `st.expander("🔎 Run preview")`. When `pv.error` is set, show a single caption; otherwise show the timesteps + basis, the rows, and each warning via `st.warning`. The expander recomputes when the selected case changes.
- **Caching:** `build_run_preview` (or a cached inner function) is keyed on the mtimes of `settings/`, `resources/`, `policies/`, `system/Demand_data.csv`, and the TDR folder's `Demand_data.csv` — not recomputed on every rerun.
- **No writes:** `grep -n "open(.*w\|write_text\|to_csv\|mkdir\|yaml.dump" src/run_preview.py` returns nothing. The `["julia", "--project=.", "Run.jl"]` invocation, its `cwd`, and `stream_process()` are untouched.
- `grep -rn "GenX.jl\"\|parent.parent / \"archives\"" *.py pages/*.py archive_lib.py` (GENXUI-1's check) still returns nothing.

### Key Files to Modify/Create
- `src/run_preview.py` (new)
- `app.py` (the preview expander in `col_controls` only — additive)
- `tests/test_run_preview.py` (new)

### Do-Not-Touch Files
- `src/workspace.py`, `src/examples.py`, `src/run_diagnosis.py`, `src/run_settings.py`, `src/help_docs.py`, `src/fleet_view.py`, `src/resource_style.py`, `src/metrics.py` — complete/other tickets; `run_preview.py` may import `workspace` but must not modify any of these.
- `stream_process()` and the Julia subprocess command line + `cwd` in `app.py`.
- `pages/*.py`, `archive_lib.py`, `report_lib.py`.
- Any case input file — this feature is strictly read-only.
- The broader Phase-4 layout/chart overhaul — explicitly out of scope.

### Verification Steps
- `streamlit run app.py` launches cleanly; select `1_three_zones` (TDR on, `TDR_results/` present) → the preview reads **1,848 timesteps**, "reusing TDR_results/ — 11 rep periods × 168 h", and lists CO₂ cap = rate-based/3 zonal, UCommit = linearized clustering, 3 zones / 2 lines.
- Select a single-zone case → preview reflects a single-zone case; select a case with no `TimeDomainReduction` key → the "defaults to off" warning shows and timesteps = the raw `Demand_data.csv` length.
- Delete a case's `TDR_results/` (in a scratch copy) with `TimeDomainReduction: 1` → preview shows the timestep *range*, not a number.
- `python tests/test_run_preview.py` passes (synthetic cases per the proposal's test plan: TDR off / reusing / will-cluster / ignored folder / partial folder / CO₂ cap / empty settings / missing Demand_data.csv). Plus: `build_run_preview` on each real `example_systems/*` copy returns `error is None`.
- `streamlit` `AppTest` on `app.py` runs without exception with the preview expander present.

### Est. Nights: 1–2
*(One pure module with a fair amount of GenX-specific branching to get right, one additive expander, and a test suite that has to cover the TDR decision tree.)*

---

## Implementation status — done 2026-08-28

All acceptance criteria met. Shipped:

- `src/run_preview.py` — `build_run_preview(case_path) -> RunPreview` (`PreviewRow` / `RunPreview` as specified). `_GENX_DEFAULTS` carries the sync-with-`configure_settings.jl` comment. TDR decision tree (off / reusing complete `TDR_results/` / partial-or-absent → range) mirrors `case_runner.jl`'s `time_domain_reduced_files_exist`. Warnings: TDR-not-set, folder-ignored, incomplete-folder, already-clustered-system-input. Rows: zones+lines, resources by type (via `fleet_view.RESOURCE_FILES`), CO₂ cap mode + zonal count, UCommit, NetworkExpansion, MultiStage (+NumStages), DC-OPF, ParameterScale, other policies, solver method/crossover/time-limit.
- `app.py` — `_render_run_preview()` + a `@st.cache_data` wrapper keyed on the input-dir mtimes; the `🔎 Run preview` expander sits between the "Runs overwrite…" caption and the result block.
- `tests/test_run_preview.py` — 12 cases + a check that every real `example_systems/*` returns `error is None`. All pass; `streamlit` AppTest clean on all four pages.

**Deviations (both minor):** multi-stage cases (no top-level `system/`) read `inputs/inputs_p1/` and add a "this preview describes stage 1 only" warning — not spelled out in the criteria but the honest behaviour. The optional "rough model-size hint" from the proposal was not built.

**Verified output** — `1_three_zones`: 1,848 timesteps, "reusing `TDR_results/` — 11 representative periods × 168 h", CO₂ = rate-based (demand) / 3 zonal, UCommit = linearized clustering, 3 zones / 2 lines, min-capacity policy (3), HiGHS simplex / no crossover. A raw single-zone case with no `TimeDomainReduction` key: 8,760 timesteps + the "TimeDomainReduction isn't set" warning.
