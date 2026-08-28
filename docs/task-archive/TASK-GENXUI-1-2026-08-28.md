<!-- meta: ticket=GENXUI-1 night=1 generated=2026-08-28T06:10:16Z base_commit=1b39e44bfd722a4c9d3f95730f00e014f7e15fa6 -->

# GENXUI-1: User-Defined Workspace (`/data` + `/archive`)

**Window:** 11:00 PM – 2:00 AM · **Branch:** `feature/v2-refresh` · **Active Ticket:** GENXUI-1 · **Night 1 of 2+**

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
> **Commit Convention:** Prefix every commit message with the ticket ID, e.g. `git commit -m "GENXUI-1: add data_manager.py"`, so `git log` on the branch is a readable audit trail without cross-referencing the task archive.

## Scope of Work

**Scope note:** this replaces the current model outright — case discovery today scans *inside* `../GenX.jl/` for `Run.jl` folders, and archives live in a fixed sibling path next to GenXUI. Neither is user-configurable today. This ticket introduces one user-chosen workspace root containing `data/` (active cases) and `archive/` (archived runs), fully decoupled from where GenX.jl or GenXUI happen to sit on disk.

### Acceptance Criteria
- `src/workspace.py` exists and exports `get_workspace_root() -> Path | None`, `set_workspace_root(path: Path) -> None`, `data_dir() -> Path`, `archive_dir() -> Path`, and `discover_cases() -> list[str]` (scans `data_dir()` for subdirectories containing `Run.jl`, replacing the current `GenX.jl`-scanning logic).
- The workspace root is **unset by default** on first run. If unset, `app.py` shows a setup prompt requiring the user to choose a directory before any case list loads — the app must not crash and must not silently fall back to scanning `../GenX.jl`.
- Choosing a root (or reopening the app with one already set) creates `data/` and `archive/` under it if they don't exist (`mkdir(parents=True, exist_ok=True)`) — idempotent per the Idempotency Clause, no error on a second run against the same root.
- The chosen root is persisted to a real config file (e.g. `~/.genxui/config.json`), not just `st.session_state` — it must survive a full server restart, not just a page rerun.
- `app.py`, `pages/2_Inputs.py`, `pages/3_Results.py`, and `pages/4_Archives.py` all read case/archive locations through `src/workspace.py` — `grep -rn "GenX.jl\"\|parent.parent / \"archives\"" *.py pages/*.py archive_lib.py` returns no remaining hardcoded references.
- `archive_lib.ARCHIVE_ROOT` (module-level constant) is replaced with a call into `workspace.archive_dir()`, so `create_archive` / `list_archives` / `restore_archive_to_new_case` all operate against the user-configured `/archive`.
- A "Change workspace" control (sidebar or settings section) shows the current root and lets the user pick a different one; changing it re-runs case/archive discovery against the new root without requiring a manual restart.
- **Import utility:** an "Import case from GenX.jl" action copies an existing case folder from the GenX.jl directory into the workspace's `data/`, so users with pre-existing cases aren't stranded by the directory-model change.
- **Legacy archive notice:** if archives exist at the old default location (the current sibling-of-GenXUI `archives/` folder) and differ from the newly configured `/archive`, show a one-time informational notice — not a silent auto-migration — so the user knows those runs aren't lost, just not currently visible.

### Key Files to Modify/Create
- `src/workspace.py` (new)
- `app.py`
- `archive_lib.py`
- `pages/2_Inputs.py`
- `pages/3_Results.py`
- `pages/4_Archives.py`

### Do-Not-Touch Files
- `report_lib.py` — unrelated, do not touch.
- The Julia subprocess invocation itself (`stream_process()` in `app.py`) — `cwd` should now point at the case's location inside the new `data/`, but the `julia --project=. Run.jl` command line stays as-is.
- **Known risk, not this ticket's job to solve:** each GenX.jl case typically carries its own `Project.toml` that may reference GenX.jl via a path relative to its *original* location inside the GenX.jl tree. If importing a case into the new `data/` breaks that relative reference, log it under Blockers/Notes as a **Plan Issue** for GENXUI-2 (which owns execution/path-switching) rather than attempting to rewrite Julia project resolution here.

## Definition of Done
- All Acceptance Criteria above are met.
- `streamlit run app.py` with no workspace root configured shows the setup prompt, not a crash.
- After setting a root, `data/` and `archive/` appear under it.
- Importing an existing GenX.jl case into `data/` and running it either behaves identically to today, or produces a clearly logged Blocked/Plan Issue note (expected and acceptable — not a failure of this ticket) if Julia project-path resolution breaks.
- Archiving a run writes into the new `/archive` and is visible on the Archives page.
- Restarting the Streamlit server preserves the configured workspace root.
- `grep -rn "GenX.jl\"\|parent.parent / \"archives\"" *.py pages/*.py archive_lib.py` returns no matches.

## Blockers / Notes

### Blocked
_(none)_

### Plan Issue
_(none — the Acceptance Criteria were satisfiable as written)_

### Informational (not blocking this ticket's DoD)
- Actual Julia execution against an imported case was **not verified in this environment** — no Julia runtime or real GenX.jl checkout is available in the execution sandbox. All directory-routing, persistence, import, archive, and restore behavior was verified end-to-end using a synthetic fake case (`Run.jl` + `resources/Thermal.csv` + fabricated `results/*.csv`) and a headless-browser smoke test of all four pages. The known risk flagged above (case-relative `Project.toml` GenX.jl path resolution breaking after an import into `data/`) is real and unverified either way — GENXUI-2 (which owns the execution pipeline) should verify this against an actual GenX.jl checkout before relying on the import flow for real runs.
