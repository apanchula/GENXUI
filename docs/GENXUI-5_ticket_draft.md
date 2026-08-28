## GENXUI-5: Scalable Metrics Engine & Zone-Aware Results

**Target Execution Window:** 11:00 PM – 2:00 AM · **Priority:** High (Phase 5 of the Refresh roadmap; the Results page is the app's main payoff and its parsing breaks on anything bigger than the original toy case)

**Scope note:** `pages/3_Results.py` is a 930-line monolith. Every GenX output CSV is parsed inline with fragile string matching — `df[df[col] == "AnnualSum"]`, `col.split(".")[0] == "Demand"`, `"Total"` column probing, VRE/storage classification by name keywords scattered across the file. It was written for one 3-resource single-zone test case; on the standard `example_systems` runs (10–30 resources, 3 zones) the Key Metrics table and Supply-to-Load donut either mislabel data or throw `KeyError`/reshape errors. This ticket extracts the parsing into a tested `src/metrics.py` engine, makes the summary views **zone-aware** (per-zone rows, per-zone subtotals, system totals), drops resources that don't exist in the solution, and adds per-table CSV export. The individual charts (capacity, unserved-energy timing, cost breakdown, hourly power/curtailment, storage charging source) are refactored to consume the engine but keep their current behaviour.

This is Phase 5 of `GENXUI-Refresh_Master.md` §5. GENXUI-1…4 modules are complete/out of scope. **`app.py`'s Run Preview (referenced in §5) belongs to the Phase-4 / `docs/proposal_run_preview.md` work, not this ticket — do not build it here.**

### Scope & Acceptance Criteria

- **`src/metrics.py` exists** (pure — no Streamlit) and is the single reader for GenX result CSVs. It takes a results directory (works for both a live `workspace.resolve_results_dir(case_path)` and an archived `<archive>/results`) and exports at minimum:
  - `load_results(results_dir: Path) -> ResultSet | None` — `None` when the directory has no `capacity.csv`. `ResultSet` carries the parsed frames plus `zones: list[int]`.
  - `capacity_by_resource(rs) -> pd.DataFrame` — long format, one row per resource: `Resource, Type, Zone, EndCap_MW, NewCap_MW, RetCap_MW` (+ energy/charge capacity where present). Type from a shared `resource_style.resource_type(name)` helper (see below).
  - `generation_by_resource(rs) -> pd.DataFrame` — `Resource, Type, Zone, AnnualGen_MWh` from the wide `power.csv` (`Zone` row → resource→zone, `AnnualSum` row → annual). Robust to the `-0.0` / scientific-notation values and to a missing `Total` column.
  - `zone_summary(rs) -> pd.DataFrame` — one row **per (Zone, Type)** with `Capacity_MW, Generation_MWh, Curtailment_MWh`; plus a per-zone subtotal row and a system `TOTAL` row. This is the frame behind the redesigned Key Metrics table.
  - `supply_to_load(rs) -> pd.DataFrame` — `Zone, Type, GenToLoad_MWh` (storage discharge and VRE-charging bookkeeping preserved from the current `_gen_to_load` logic, but computed per zone). Includes a `System` pseudo-zone row when `len(rs.zones) > 1`.
  - `cost_breakdown(rs) -> pd.DataFrame` and `nse_summary(rs) -> pd.DataFrame` covering what Sections 1 and 3 use today.
- **Non-existent assets are dropped.** A resource that appears in a result CSV with `EndCap_MW == 0` **and** `AnnualGen_MWh == 0` is excluded from every `metrics.py` frame (same "contributes nothing" rule as `fleet_view.FleetResource.exists`). `load_results` records how many were dropped so the page can caption it.
- **Shared type inference:** `src/resource_style.py` gains `resource_type(name: str) -> str` returning a stable label (`"Thermal" | "Solar" | "Wind" | "Storage" | "Hydro" | "Other"`) using the same keyword sets as `resource_color()`. `metrics.py` and the fleet view both use it; the ad-hoc `_is_vre()` in `3_Results.py` is removed.
- **Zone-aware Key Metrics (§5 "broken down by zone, sub-totaled by zone, and totals for entire simulation"):** the Key Metrics section renders `zone_summary(rs)` — resources grouped under their zone, a bold subtotal per zone, and a bold system-total row. For a single-zone case it collapses to just the resource rows + total (no redundant "Zone 1" grouping).
- **Zone-aware Supply to Load Mix (§5 "broken down by zone, and also show total if zone>1"):** one mix chart per zone (donut or stacked bar), plus a system-total chart shown only when `len(rs.zones) > 1`.
- **CSV export (§5 "download filtered summary tables as CSV"):** a `st.download_button` next to the Key Metrics table and the Supply-to-Load table, each exporting that table (as currently displayed/filtered) to `.csv`. The existing "Export report (HTML)" button stays.
- **No regression:** every existing Results section still renders for a real `example_systems` run and for an archived run — Capacity Built, Unserved Energy by Time of Year, Cost Breakdown by Resource, Hourly Curtailment, Hourly Power by Resource, Storage Charging Source, Raw Data.
- `pages/3_Results.py` no longer contains inline `== "AnnualSum"` / `== "Total"` result-shape probing — `grep -n 'AnnualSum\|"Total"' pages/3_Results.py` returns only display-side references (column labels, styler rows), not parsing.
- `grep -rn "GenX.jl\"\|parent.parent / \"archives\"" *.py pages/*.py archive_lib.py` (GENXUI-1's check) still returns nothing.

### Key Files to Modify/Create
- `src/metrics.py` (new)
- `src/resource_style.py` (add `resource_type()`)
- `pages/3_Results.py` (rewrite the parsing + Key Metrics + Supply-to-Load sections against `metrics.py`; refactor the other sections to consume its frames)
- `tests/test_metrics.py` (new)

### Do-Not-Touch Files
- `src/workspace.py`, `src/examples.py`, `src/run_diagnosis.py`, `src/run_settings.py`, `src/help_docs.py`, `src/fleet_view.py` — complete; `metrics.py` may import from them (and should reuse `resource_style`) but must not modify them.
- `app.py` — the Runner, including its Run Preview / diagnosis code. Out of scope for this ticket.
- `archive_lib.py` — `metrics.py` may be called from `compute_headline_metrics` as a **stretch** consolidation, but the archive **manifest schema** (`schema_version`, its metric keys) and `create_archive` / `list_archives` / `restore_archive_to_new_case` must not change. If aligning them is non-trivial, leave `compute_headline_metrics` as-is and log it under Informational.
- `report_lib.py` — the HTML report builder; the "Export report (HTML)" button must keep working, but don't restructure the report.
- `pages/2_Inputs.py`, `pages/4_Archives.py`, the Julia invocation.

### Verification Steps
- `streamlit run app.py` launches cleanly; open Results for a real 3-zone `example_systems` run (e.g. `1_three_zones` after a solve): Key Metrics shows per-zone groups + subtotals + a system total; Supply-to-Load shows one chart per zone plus a system chart.
- Switch the Results source to an **archived** run — the same views render from `<archive>/results`.
- A single-zone case (`a-single-zone-case`) renders Key Metrics as a flat resource list + total, with no empty "Zone" scaffolding.
- The two new CSV download buttons produce well-formed CSVs matching the on-screen tables.
- `python tests/test_metrics.py` passes (synthetic results dirs: multi-zone, single-zone, a resource with zero cap+gen that must be dropped, a missing optional CSV).
- `streamlit`-testing `AppTest` on `pages/3_Results.py` runs without exception for a live case, an archived case, and the no-results guard.

### Est. Nights: 2–3
*(New engine + a tested parser for ~6 CSV shapes + reworking the two summary sections and re-pointing five chart sections — and the current parsing has a lot of undocumented edge-case handling that has to be carried over deliberately, not dropped.)*
