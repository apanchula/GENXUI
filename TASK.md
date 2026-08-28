<!-- meta: ticket=GENXUI-2 night=1 generated=2026-08-28T18:39:09Z base_commit=fd43663dce6d7b0c9dd748fbec81c26ef2534ab7 -->

# GENXUI-2: GenX.jl Example Runner & Path Switching

**Window:** 11:00 PM – 2:00 AM (run ad hoc, outside the scheduled window at user's request) · **Branch:** `feature/v2-refresh` · **Active Ticket:** GENXUI-2 · **Night 1 of 1**

## Instructions for Worker Agent

> **Blocked / Ambiguous Work Clause:** If a step is ambiguous, or a blocker prevents meeting an Acceptance Criterion, stop that item immediately. Do not guess, do not improvise scope, and do not mark the criterion done. Log it under "Blockers / Notes → Blocked" with enough detail for Nightly Review to act on it, then continue only with unblocked remaining scope items.
>
> **Plan Issue Clause:** If the ticket's Acceptance Criteria conflict with the actual codebase, are no longer accurate, or can't be satisfied as written regardless of implementation approach, do not silently reinterpret the ticket. Stop, log it under "Blockers / Notes → Plan Issue," and continue only with unaffected scope items. This is distinct from being blocked — it signals the ticket itself needs revision, not just another attempt.
>
> **Scope Boundary Clause:** Only modify files listed under Key Files to Modify/Create. Files listed under Do-Not-Touch may only receive minimal, additive changes required to integrate with them — no restructuring. Any change outside the allow-list must be logged under Blockers/Notes even if it seemed necessary.
>
> **Timeout Clause:** If fewer than 15 minutes remain in the window and the Definition of Done is unmet, stop making changes. Commit whatever is in a working, compiling state. Do not rush an uncommitted or partially-tested change through to try to finish. Log remaining scope under Blockers/Notes.
>
> **Idempotency Clause:** Before creating a file or directory, check whether it already exists from a prior partial run of this same ticket. Do not duplicate work or overwrite prior progress blindly — inspect and extend it if it's consistent with the current Scope of Work, or flag the conflict under Blockers/Notes if it isn't.
>
> **Commit Convention:** Prefix every commit message with the ticket ID, e.g. `git commit -m "GENXUI-2: add src/examples.py"`, so `git log` on the branch is a readable audit trail without cross-referencing the task archive.

## Scope of Work

**Scope note:** GENXUI-1 built the user-configurable `/data` + `/archive` workspace and an "Import case from GenX.jl checkout" action, but that action only scans the *top level* of the GenX.jl checkout — it does not see the 11 canonical example cases nested under `example_systems/<name>/`. This ticket adds a dedicated example-case picker for that directory, and closes out the open question GENXUI-1 deferred: whether running a case from *outside* the original GenX.jl tree (i.e. copied into the user's workspace `data/`) actually resolves the `GenX` Julia package correctly.

### Acceptance Criteria
- `src/examples.py` exists and exports `list_example_cases() -> list[ExampleCase]`, scanning `workspace.legacy_genx_root() / "example_systems"` for subdirectories containing `Run.jl`; each `ExampleCase` carries `name` and a short `description` parsed from that example's `README.md` (first non-heading line of text). Returns `[]` if `example_systems/` doesn't exist. Sorted by name.
- `src/examples.py` exports `import_example_case(name: str) -> Path` that copies `example_systems/<name>` into the active workspace's `data_dir()` — raises `FileNotFoundError` if no such example exists, `FileExistsError` if a case with that name is already present in `data_dir()` (same not-silently-overwriting contract as GENXUI-1's `import_case_from_legacy`).
- `app.py` sidebar gains a "🧪 Load GenX.jl example" expander, alongside the existing "📥 Import case from GenX.jl checkout" expander, listing examples from `src/examples.py` with their description and an import button that reruns the app on success.
- **Execution verification (the deferred risk):** using a real `example_systems` case imported into the workspace `data/`, run it end-to-end through the existing `stream_process()` / Run button. Record the outcome in this ticket's Blockers/Notes:
  - If it completes successfully and results appear under `<case>/results/`, mark the GENXUI-1-flagged Project.toml risk resolved/non-issue in this environment, with the reasoning.
  - If it fails due to Julia package resolution, log it as a **Blocked** item with the exact error, rather than silently working around it.
- `stream_process()` in `app.py` additionally recognizes a Julia package-resolution failure in the subprocess output (e.g. stderr containing `ArgumentError` together with `not found`) and appends one clear banner line to the output (distinct from the raw Julia stacktrace) so the failure is legible in the terminal pane. This is additive only — the underlying `["julia", "--project=.", "Run.jl"]` invocation and its `cwd` argument are unchanged.
- `grep -rn "example_systems" src/*.py app.py` returns matches (sanity check the discovery code actually landed, not just a UI stub).

### Key Files to Modify/Create
- `src/examples.py` (new)
- `app.py` (sidebar addition + `stream_process` error-surfacing only)

### Do-Not-Touch Files
- `src/workspace.py` — GENXUI-1's workspace mechanics are working and out of scope; `src/examples.py` may call into it but must not modify it.
- `archive_lib.py`, `pages/2_Inputs.py`, `pages/3_Results.py`, `pages/4_Archives.py`, `report_lib.py` — unrelated to example loading/execution, do not touch.
- The `["julia", "--project=.", "Run.jl"]` subprocess command line and its `cwd` — do not change the invocation itself, only how its output is interpreted.

## Definition of Done
- All Acceptance Criteria above are met.
- `streamlit run app.py` launches cleanly with no regression to the GENXUI-1 workspace flow.
- The "Load GenX.jl example" picker lists all `example_systems/*` cases with descriptions.
- Importing one and running it via the existing Run button either completes with results visible/archivable, or produces a clearly logged Blocked note with the real error — not a silent failure.
- `grep -rn "GenX.jl\"\|parent.parent / \"archives\"" *.py pages/*.py archive_lib.py` (GENXUI-1's check) still returns no matches.

## Blockers / Notes

### Blocked
_(none)_

### Plan Issue
_(none)_

### Informational

**Execution verification (the deferred GENXUI-1 risk) — RESOLVED / non-issue.**
Imported `example_systems/1_three_zones` into the active workspace
(`C:\Users\alexp\genxui-workspace\data\1_three_zones`) via
`examples.import_example_case()` and ran it with the exact invocation
`stream_process()` uses — `["julia", "--project=.", "Run.jl"]`, cwd = the case
dir under `data/`.

- `using GenX` resolved fine from the workspace copy. `--project=.` points at
  the case dir (no Project.toml there), so Julia falls back to the shared
  default env `~/.julia/environments/v1.12`, which has `GenX v0.4.5`
  installed. The GENXUI-1-flagged Project.toml risk (that a case copied out of
  the GenX.jl tree wouldn't resolve the `GenX` package) **does not occur in
  this environment** — resolution does not depend on the case's location, only
  on GenX being in the user's default Julia env (or the case's own project).
- Model built and the solve returned `OPTIMAL` (objval 9208.45, 204 simplex
  iterations); full `results/` written (`status.csv`, `costs.csv`, `power.csv`,
  … 40+ files). End-to-end path — discovery → import → Run → results — works.

Caveat (environmental, not a code/plan issue): this 16 GB host is RAM-starved.
With the stock `highs_settings.yml` `Method: ipm`, HiGHS aborts with
`std::bad_alloc` / SIGABRT before its first interior-point iteration (seen at
both ~0.7 GB and ~2.8 GB free). Switching the imported copy's
`settings/highs_settings.yml` to `Method: simplex` + `run_crossover: "off"`
let it solve to optimality. This is a solver-memory limitation of the machine,
**not** Julia package resolution and not a GenXUI defect — the `data/` copy of
the case runs GenX correctly. `1_three_zones` is left in the workspace with
that one settings tweak and its `results/` as evidence.

**`_is_package_resolution_failure()`** (app.py) unit-checked against
representative lines: matches `ArgumentError: Package X not found in ...`,
does not match unrelated `MethodError` / stacktrace lines.

### Acceptance Criteria status
- [x] `src/examples.py` — `list_example_cases()` / `import_example_case()` as specified; discovery returns all 11 `example_systems/*` cases, sorted, with README-derived descriptions; `[]` when the dir is absent.
- [x] `app.py` sidebar "🧪 Load GenX.jl example" expander alongside the existing import expander, with description + import button + rerun on success.
- [x] Execution verification performed and recorded (above).
- [x] `stream_process()` recognizes a Julia package-resolution failure (`ArgumentError` + `not found`) and appends one distinct banner line; underlying invocation and cwd unchanged (additive only).
- [x] `grep -rn "example_systems" src/*.py app.py` returns matches.
- [x] GENXUI-1 check `grep -rn 'GenX.jl"|parent.parent / "archives"' *.py pages/*.py archive_lib.py` still returns nothing.
- [x] `app.py` / `src/examples.py` parse cleanly; `streamlit` imports.
