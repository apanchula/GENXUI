## GENXUI-6: Case management (rename · new-from-example · duplicate · delete)

**Target Execution Window:** 11:00 PM – 2:00 AM · **Priority:** Medium (rounds out the workspace model — everything else assumes cases already exist and are named sensibly)

**Scope note:** GENXUI-1 gave us a user-chosen workspace with `data/` (cases) and `archive/` (runs). GENXUI-2 added "Load GenX.jl example" → copies `example_systems/<name>` into `data/` under the **example's own name**, once. That's the *only* way to get a case in, and there's no way to:

1. **Rename** a case (`data/1_three_zones` → `data/base_case`),
2. **Create a new case from an example under a name you choose** (so you can keep `example_1` pristine and work on `scenario_A`),
3. **Duplicate** a case already in the workspace (fork `base_case` → `base_case_high_CO2` to tweak and re-run).

Delete is in the same gap and is included here so the workspace doesn't just accumulate. This ticket adds a **Cases** page that owns all of it; the Runner's "🧪 Load GenX.jl example" expander is retired (one door, not two).

Assume a fresh install with the default workspace already configured (GENXUI-1 handles that gate).

### Scope & Acceptance Criteria

- **`src/workspace.py` gains** (pure, no Streamlit):
  - `case_dir(name: str) -> Path` — `data_dir() / name` (no validation, just the join).
  - `valid_case_name(name: str) -> str | None` — returns a cleaned name, or `None` if it can't be made into a safe single-segment directory name: rejects empty / whitespace-only, path separators and the `<>:"/\|?*` set and control chars, `.`/`..`, leading-or-trailing dot or space, and names that are Windows-reserved (`CON`, `COM1`, …). Does **not** reject a name that collides with an existing case — callers check that and raise `FileExistsError` (same "never silently overwrite" contract as GENXUI-1/2).
  - `rename_case(old: str, new: str) -> Path` — `data/old` → `data/new`. `FileNotFoundError` if `old` isn't a case, `ValueError` if `new` fails `valid_case_name`, `FileExistsError` if `new` already exists. Moves the whole folder (results/, TDR_results/, etc. ride along — `Run.jl` is location-independent).
  - `duplicate_case(src: str, new: str, *, inputs_only: bool = False) -> Path` — copies `data/src` → `data/new`. `inputs_only=True` copies only `Run.jl` + `resources/` `system/` `policies/` `settings/` (drops `results*/`, `TDR_results/`, `Full_TimeSeries/`) so the copy is a clean starting point. Same error contract as `rename_case`.
  - `delete_case(name: str) -> None` — `shutil.rmtree(data/name)`. `FileNotFoundError` if absent. Does not touch `archive/`.
  - The `<>:"/\|?*` + reserved-names definitions currently living in `archive_lib.py` move to `src/workspace.py` (or a tiny shared module); `archive_lib` imports them so there's one source of truth.
- **`src/examples.py`:** `import_example_case(name: str, dest_name: str | None = None) -> Path` — `dest_name` (validated via `workspace.valid_case_name`) overrides the destination folder name; default keeps today's behaviour (dest = example name). `FileExistsError` unchanged.
- **New page `pages/1_Cases.py` — "Cases":**
  - Lists every case in `data/` with: an active-case marker (`selected_case`), the short path, whether it has results (and whether they look stale — `results/` older than an input), and a rough on-disk size.
  - Per case: **Set active**, **Rename** (text field + confirm), **Duplicate** (new-name field + "inputs only" checkbox), **Delete** — the delete button stays disabled until the user types the exact word **`Delete`** into a confirmation text box next to it; only then does the click `rmtree` the folder.
  - A **"New case from example"** section: the `examples.list_example_cases()` picker (with descriptions) + a name field (prefilled with the example name) + Create.
  - Renders the GENXUI-1 setup gate when no workspace is configured; a friendly empty state when `data/` has no cases.
- **Session-state upkeep:** when the active case (`st.session_state["selected_case"]`) is **renamed**, update it to the new name; when it's **deleted**, clear it. A case open on the Inputs page whose folder was renamed/deleted is already handled by that page's stale-selection guard — no change needed there.
- **Runner cleanup:** remove the "🧪 Load GenX.jl example" expander from `app.py`'s sidebar (superseded by the Cases page). The "No cases found …" message points at the **Cases** page.
- **Tests** (`tests/test_workspace_cases.py`, pure — tmp workspace): `valid_case_name` accept/reject table; `rename_case` moves the folder incl. a `results/` subdir and errors on missing/duplicate/bad-name; `duplicate_case` full vs `inputs_only`; `delete_case` removes only the data folder; `import_example_case(dest_name=…)` lands under the chosen name.
- `grep -rn "GenX.jl\"\|parent.parent / \"archives\"" *.py pages/*.py archive_lib.py` (GENXUI-1's check) still returns nothing.

### Key Files to Modify/Create
- `src/workspace.py` (new case-management functions + the moved name constants)
- `src/examples.py` (`dest_name` parameter)
- `pages/1_Cases.py` (new)
- `app.py` (drop the example-loader expander; update the no-cases hint)
- `archive_lib.py` (import the name constants from their new home — no behaviour change)
- `tests/test_workspace_cases.py` (new)

### Do-Not-Touch Files
- `src/run_diagnosis.py`, `src/run_preview.py`, `src/run_settings.py`, `src/help_docs.py`, `src/fleet_view.py`, `src/metrics.py`, `src/resource_style.py`, `src/ui.py` — unrelated; may be imported, not modified.
- `archive_lib.create_archive` / `list_archives` / `restore_archive_to_new_case` and the archive manifest schema — the only allowed change to `archive_lib.py` is importing the name constants from `workspace`.
- `pages/2_Inputs.py`, `pages/3_Results.py`, `pages/4_Archives.py`, `pages/5_Help.py` — the Inputs stale-selection guard already covers renamed/deleted cases; don't rework it.
- The Julia subprocess invocation and `stream_process()`.

### Verification Steps
- `streamlit run app.py` launches cleanly; the **Cases** page appears first in the page nav after the Runner.
- Create a new case from `1_three_zones` as `base_case` → it appears in `data/`, `1_three_zones` is not touched, and it's selectable as the active case on every page.
- Rename `base_case` → `base_v2` while it's the active case → the Runner / Inputs / Results all now show `base_v2` as active; `data/base_case` is gone.
- Duplicate `base_v2` → `base_v2_copy` with "inputs only" → the copy has `settings/`, `resources/`, `system/`, `policies/`, `Run.jl` and **no** `results*/` or `TDR_results/`; running it from the Runner produces fresh results.
- The Delete button for `base_v2_copy` is disabled; typing `Delete` into its confirmation box enables it; clicking it removes `data/base_v2_copy` and nothing in `archive/`; if it was active, the active-case marker clears. (Typing anything other than `Delete` leaves the button disabled.)
- Rename to `CON`, to `a/b`, to `  ` → each is rejected with a clear message, nothing moved.
- `python tests/test_workspace_cases.py` passes.

### Est. Nights: 1–2
*(Five small workspace functions + a name validator + one new page with a table and four guarded actions + moving the shared name constants. The page is the bulk of it.)*

---

## Interaction detail — Delete confirmation

The delete affordance for each case is a `st.text_input` + a `st.button("Delete case", type="primary", disabled=<typed != "Delete">)`. The button does nothing until the box holds the exact string `Delete`. On a successful delete the page reruns and the row disappears; there is no undo (the case's archived runs, if any, are untouched under `archive/`).

---

## Implementation status — done 2026-08-31

All acceptance criteria met.

- `src/workspace.py`: `case_dir`, `valid_case_name` (rejects illegal chars /
  reserved stems / `.`·`..` outright; collapses whitespace, trims outer
  dots/spaces), `rename_case`, `duplicate_case(inputs_only=)`, `delete_case`.
  The `<>:"…` char class + reserved-name set now live here as
  `ILLEGAL_NAME_CHARS` / `RESERVED_NAMES`; `archive_lib` imports them.
- `src/examples.py`: `import_example_case(name, dest_name=None)`.
- `pages/1_Cases.py` (new): "New case from example" row + one bordered card per
  case (active marker · path · size · results status) with **Set active** and
  **✏️ Rename / 📑 Duplicate / 🗑 Delete** popovers. Delete button is disabled
  until `Delete` is typed. Active-case session key follows a rename, clears on
  a delete.
- `app.py`: the "🧪 Load GenX.jl example" sidebar expander is gone, replaced by
  a `🗂 Manage cases` page link; the no-cases message points at the Cases page.
- `tests/test_workspace_cases.py`: 9 cases. 109 tests total pass; AppTest clean
  on all six pages; end-to-end create→duplicate→rename→delete verified against
  the real workspace.

**Deviation:** the per-case size/stale-check (`_case_stat`) walks the tree with
`rglob` behind an `@st.cache_data` keyed on the dir mtime — fine for normal
cases, could be slow for one with a huge `Full_TimeSeries/`. Acceptable; revisit
if it bites.
