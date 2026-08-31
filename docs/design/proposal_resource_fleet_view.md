# Proposal: Graphical Fleet View for the Resources Tab

**Status:** core implemented 2026-08-28 (see "Implementation status" below)
**Location:** `pages/2_Inputs.py`, resource files only (`folder == "resources"`)

## Problem

The Resources tab (`Thermal.csv`, `Vre.csv`, `Storage.csv`, `Vre_stor.csv`) currently
renders only as a raw, editable `st.data_editor` grid. There's no at-a-glance visual
read of the fleet: how much capacity of what type, how it's distributed across zones,
or which resources share a common zone bus. The number of resources in a case is
variable (today's cases have 2-3 per file; nothing stops a case from having 50+), so
any graphical view has to degrade gracefully at both ends of that range.

## Where it fits in the UI

Add a view toggle (`st.segmented_control` or `st.tabs`) above the existing
`st.data_editor`: `Table | Overview`. Keep the editable grid as-is — editing needs
cell-level granularity. The graphical view is read-only and additive, answering a
different question ("what does this fleet look like") than the table does ("edit this
value").

## Two complementary charts, not one

A single chart type can't answer both "how much capacity of what type" and "what's
electrically connected to what" — those are different relationships and need different
chart families.

### 1. Treemap — composition (capacity by type/zone)

`px.treemap`, area = `Existing_Cap_MW` (or `Max_Cap_MW` for new-build candidates),
colored by type, optionally nested `Zone > Type > Resource`.

- Area encoding scales to any resource count without layout breakage — 2 resources
  render as two big rectangles, 80 resources render as a legible mosaic with hover
  detail instead of a scrollbar.
- Nesting under a `Zone` parent groups resources visually by zone, but this is
  **containment, not topology** — it does not represent a shared bus/node the way a
  network diagram does. Don't oversell this chart as answering the "common bus"
  question.
- Guard against negative sentinel values (`-1` = unbounded, used in this project's
  `Storage.csv` for uncapped fields) before feeding capacity into the size encoding —
  treemap will error or misrender on negative sizes.

### 2. Bus / network diagram — topology (shared zone bus)

A hub-and-spoke node-link diagram, one hub per zone bus, with resources as spokes
converging on it. This is the standard representation power-system tools use for this
relationship (it's what PyPSA's own network plots do).

- **Single-zone case (what every case in this repo is today — confirmed no case has a
  `Network.csv`):** one bus node at the center, each resource placed on a circle around
  it, edge from resource → bus. Edge width or resource-node size = capacity, color =
  type (reuse the `resource_color()` scheme already in `pages/3_Results.py` for visual
  consistency between Inputs and Results).
- **Multi-zone (future-proofing):** each zone gets its own hub; hubs connect to each
  other via tie-line edges read from `Network.csv` once that file exists in a case.
  Resources still radiate off their own zone's hub — this generalizes the single-zone
  layout rather than replacing it.
- **Implementation:** `go.Scatter` (nodes) + `go.Scatter` (line traces for edges) with
  a manually computed circular layout — bus at origin, resources at evenly-spaced
  angles (trivial trig for a star topology, no layout engine needed). Keeps it
  dependency-free and consistent with the rest of the app (already all-Plotly).
  - Alternative considered: `st.graphviz_chart`. Hands off layout for free but pulls in
    a new dependency (`graphviz` Python package + system binary). Only worth it if the
    multi-zone topology becomes a real mesh rather than a star/tree, where manual
    positioning stops being trivial.

## Supporting pieces

- **Sorted horizontal bar** (capacity per resource) as an alternative small-fleet view
  — fine up to ~25-30 resources, then either needs a "top N" cutoff via `st.slider` or
  should defer to the treemap.
- **Card grid** — one card per resource (name, type, zone, capacity, cost), built with
  a wrap-into-rows helper (`for i in range(0, len(df), n_cols): cols = st.columns(n_cols)`)
  since Streamlit has no native grid primitive. Pair with a zone/type multiselect
  filter so large fleets stay browsable instead of scrolling.
- **Scatter (screening-curve style)**: cost (`Inv_Cost_per_MWyr` or `Var_OM`) vs
  capacity, size = capacity, color = New_Build vs existing. Same size/color encoding
  pattern used in the PyPSA/fneum energy-system-modelling Streamlit+Plotly workshop
  for generator fleets.
- **Metric row**: resource count, total existing capacity, total candidate (new-build)
  capacity — cheap, always renders regardless of N.

## Cross-file rollup (stretch goal)

Resources are split across four files (Thermal/Vre/Storage/Vre_stor.csv) that the
sidebar already treats as one logical "resources" folder. A second-level "All
Resources" overview that concatenates a normalized
`{Resource, Type, Zone, Capacity, Build status}` frame across all four and feeds it
into the treemap + bus diagram would answer "what's in this case" without clicking
through each file individually — probably the highest-value piece given how the
sidebar is already structured.

## Open decision

Scope for a first pass: treemap + metric row only, or the full set (treemap + bus
diagram + cards + scatter)? The bus diagram is likely the more novel/useful piece
since nothing else in the app currently shows zone-level connectivity — worth
prioritizing over the card grid/scatter if scope needs to be cut.

---

## Implementation status — done 2026-08-28

Scope decisions (from the user): **core set** (metrics + treemap + bus diagram),
**cross-file "All resources" rollup included**, **resource files only** (policy
files stay table-only), **sizing-metric selector with graceful fallback**.

- `src/resource_style.py` (new): `COLORS` + `resource_color()` extracted from
  `pages/3_Results.py` so Inputs and Results share one scheme. `3_Results.py`
  now imports from it (only change to that file).
- `src/fleet_view.py` (new): `load_fleet()`, `fleet_metrics()`, `size_series()`
  (uniform fallback + caption when the metric is all-zero/all-sentinel),
  `fleet_frame()`, `read_network_lines()` (list **and** matrix interfaces),
  `read_zone_demand()` (peak MW per zone from `system/Demand_data.csv`),
  `bus_layout()` (single-zone → central hub; multi-zone → hub ring + tie-lines;
  per-zone demand centre as a red load node hanging off each hub).
- `pages/2_Inputs.py`:
  - "★ All Resources Graph" entry at the top of the sidebar tree → the combined
    graphical view. (An earlier build also put a `Table | Overview` toggle on
    each individual resource file; that was dropped — the combined graph is the
    only graphical view, individual files stay table-only.)
  - The graph = sizing radio + 5-metric row + by-type caption + `px.treemap`
    (`fleet > Zone > Type > Resource`) + hub-and-spoke `go.Figure` bus diagram
    with per-zone demand nodes. Rows failing `FleetResource.exists` are hidden.
- `tests/test_fleet_view.py`: 16 cases (parsing, sentinel handling, greenfield
  vs fixed-fleet metrics, both network interfaces, single/multi-zone layout).
  All pass; `streamlit` AppTest clean on all four pages.

**Not done** (deferred per the scope decision): card grid, screening-curve
scatter, sorted capacity bar, and any policy-file Overview.
