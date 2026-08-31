## GENXUI-1: User-Defined Workspace (`/data` + `/archive`)

**Target Execution Window:** 11:00 PM – 2:00 AM · **Priority:** High (GENXUI-2's example loader and GENXUI-4/5's dashboards all assume this directory model exists)

**Scope note:** this replaces the current model outright — case discovery today scans *inside* `../GenX.jl/` for `Run.jl` folders, and archives live in a fixed sibling path next to GenXUI. Neither is user-configurable today. This ticket introduces one user-chosen workspace root containing `data/` (active cases) and `archive/` (archived runs), fully decoupled from where GenX.jl or GenXUI happen to sit on disk.

### Scope & Acceptance Criteria
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

### Verification Steps
- `streamlit run App.py` with no workspace root configured shows the setup prompt, not a crash.
- After setting a root, `data/` and `archive/` appear under it.
- Importing an existing GenX.jl case into `data/` and running it either behaves identically to today, or produces a clearly logged Blocked/Plan Issue note (expected and acceptable — not a failure of this ticket) if Julia project-path resolution breaks.
- Archiving a run writes into the new `/archive` and is visible on the Archives page.
- Restarting the Streamlit server preserves the configured workspace root.

### Est. Nights: 2+
*(Flagging up front — this touches case discovery, archiving, and execution wiring across five files plus a persisted config, which is more than the original one-line summary implied.)*
