## GENXUI-2: GenX.jl Example Runner & Path Switching

**Target Execution Window:** 11:00 PM – 2:00 AM · **Priority:** High (owns resolving the case-relative execution risk GENXUI-1 flagged and deferred)

**Scope note:** GENXUI-1 built the user-configurable `/data` + `/archive` workspace and an "Import case from GenX.jl checkout" action, but that action only scans the *top level* of the GenX.jl checkout (`a-single-zone-case/`, `a-single-zone-case/`, etc.) — it does not see the 11 canonical example cases nested under `example_systems/<name>/`, which is what GenX.jl's own docs point users to as "the" example systems. This ticket adds a dedicated example-case picker for that directory, and closes out the open question GENXUI-1 deferred: whether running a case from *outside* the original GenX.jl tree (i.e. copied into the user's workspace `data/`) actually resolves the `GenX` Julia package correctly.

### Scope & Acceptance Criteria
- `src/examples.py` exists and exports `list_example_cases() -> list[ExampleCase]`, scanning `workspace.legacy_genx_root() / "example_systems"` for subdirectories containing `Run.jl`; each `ExampleCase` carries `name` and a short `description` parsed from that example's `README.md` (first non-heading line of text). Returns `[]` if `example_systems/` doesn't exist. Sorted by name.
- `src/examples.py` exports `import_example_case(name: str) -> Path` that copies `example_systems/<name>` into the active workspace's `data_dir()` — raises `FileNotFoundError` if no such example exists, `FileExistsError` if a case with that name is already present in `data_dir()` (same not-silently-overwriting contract as GENXUI-1's `import_case_from_legacy`).
- `app.py` sidebar gains a "🧪 Load GenX.jl example" expander, alongside the existing "📥 Import case from GenX.jl checkout" expander, listing examples from `src/examples.py` with their description and an import button that reruns the app on success.
- **Execution verification (the deferred risk):** using a real `example_systems` case imported into the workspace `data/`, run it end-to-end through the existing `stream_process()` / Run button. Record the outcome in this ticket's Blockers/Notes:
  - If it completes successfully and results appear under `<case>/results/`, mark the GENXUI-1-flagged Project.toml risk resolved/non-issue in this environment, with the reasoning (e.g. package resolves via the default Julia depot environment, independent of cwd).
  - If it fails due to Julia package resolution, log it as a **Blocked** item with the exact error, rather than silently working around it.
- `stream_process()` in `app.py` additionally recognizes a Julia package-resolution failure in the subprocess output (e.g. stderr containing `ArgumentError` together with `not found`) and appends one clear banner line to the output (distinct from the raw Julia stacktrace) so the failure is legible in the terminal pane. This is additive only — the underlying `["julia", "--project=.", "Run.jl"]` invocation and its `cwd` argument are unchanged.
- `grep -rn "example_systems" src/*.py app.py` returns matches (sanity check the discovery code actually landed, not just a UI stub).

### Key Files to Modify/Create
- `src/examples.py` (new)
- `app.py` (sidebar addition + `stream_process` error-surfacing only)

### Do-Not-Touch Files
- `src/workspace.py` — GENXUI-1's workspace mechanics (`get_workspace_root`, `data_dir`, `archive_dir`, `discover_cases`, the existing `legacy_*` / `import_case_from_legacy` helpers) are working and out of scope; `src/examples.py` may call into it but must not modify it.
- `archive_lib.py`, `pages/2_Inputs.py`, `pages/3_Results.py`, `pages/4_Archives.py`, `report_lib.py` — unrelated to example loading/execution, do not touch.
- The `["julia", "--project=.", "Run.jl"]` subprocess command line and its `cwd` — do not change the invocation itself, only how its output is interpreted.

### Verification Steps
- `streamlit run app.py` launches cleanly with no regression to the GENXUI-1 workspace flow.
- The "Load GenX.jl example" picker lists all `example_systems/*` cases with descriptions.
- Importing one and running it via the existing Run button either completes with results visible/archivable, or produces a clearly logged Blocked note with the real error — not a silent failure.
- `grep -rn "GenX.jl\"\|parent.parent / \"archives\"" *.py pages/*.py archive_lib.py` (GENXUI-1's check) still returns no matches — confirms this ticket didn't reintroduce a hardcoded path.

### Est. Nights: 1
