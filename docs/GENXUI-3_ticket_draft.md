## GENXUI-3: Contextual Documentation & GenX.jl Reference

**Target Execution Window:** 11:00 PM – 2:00 AM · **Priority:** Medium (Phase 3 of the Refresh roadmap; makes the input surface legible ahead of GENXUI-4's modeling-page overhaul, but nothing else is blocked on it)

**Scope note:** the Inputs page today is a raw file-tree editor — `settings/*.yml` render as an untitled key/value `st.data_editor` grid, and `resources/` / `policies/` CSVs as bare tables. A user editing `UCommit`, `CO2Cap`, `TimeDomainReduction`, or a `Min_Cap_MW` column has no in-app indication of what the values mean or which are valid; the answer lives only in the GenX.jl docs website. This ticket adds a documentation helper that sources GenX's own reference material, injects per-parameter help inline on the Inputs page, and adds a dedicated searchable "Help & GenX.jl Reference" page. It is **additive** — no existing editor, save path, or parser is restructured.

This is Phase 3 of `GENXUI-Refresh_Master.md` (§3 "Dynamic Contextual Documentation & Help"). GENXUI-1 (workspace) and GENXUI-2 (example runner) are complete and their modules are out of scope here.

### Scope & Acceptance Criteria

- **`src/help_docs.py` exists** and is the single source of reference content for the app. It exports:
  - `settings_help(key: str) -> ParamHelp | None` — for a `genx_settings.yml` key (e.g. `"UCommit"`), returns a short description plus the enumerated allowed values / meanings. `None` for unknown keys.
  - `column_help(file_stem: str, column: str) -> str | None` — for an input CSV column (e.g. `("Thermal", "Min_Cap_MW")`, `("CO2_cap", "CO_2_Max_Mtons_1")`), a one-line description. `None` when not documented.
  - `topics() -> list[Topic]` and `topic_body(slug: str) -> str` — the curated reference sections for the Help page (rendered markdown).
  - `search(query: str) -> list[DocHit]` — case-insensitive substring/keyword search across topic titles and bodies, returning `(topic_slug, title, snippet)` ranked by match count.
- **Reference material sourcing** is resilient to GenX.jl not being on disk (GENXUI-1 decoupled the workspace from the GenX.jl checkout location):
  - A curated snapshot of the relevant GenX docs is **bundled in the repo** under `reference/genx/` (at minimum: the settings-parameter tables from `User_Guide/model_configuration.md`, input-column references from `User_Guide/model_input.md`, output references from `User_Guide/model_output.md`, plus `Model_Reference/TDR.md` and `Model_Reference/policies.md`). A `reference/genx/SOURCE.md` records the upstream GenX version/commit the snapshot was taken from.
  - If `workspace.legacy_genx_root() / "docs" / "src"` exists, `help_docs` prefers the live copy over the bundled snapshot (fresher), falling back cleanly when it doesn't.
- **`src/help_docs.py` parses the settings-parameter tables** from `model_configuration.md` into the `{key: ParamHelp}` map used by `settings_help()` — verified by `settings_help("UCommit")` returning text that mentions all three of "no unit commitment", "integer clustering", "linearized clustering", and `settings_help("TimeDomainReduction")` mentioning the folder-reuse behaviour and the `0` = "do not perform clustering" default.
- **Inline help on `pages/2_Inputs.py`:**
  - When a `settings/*.yml` file is selected, each key present in the file is shown with its `settings_help()` description — via a `st.popover` / `st.expander` / `help=` tooltip adjacent to the editor, not inside the editable grid. Keys with no documentation are simply shown without help (no error, no empty popover).
  - When a `resources/` or `policies/` CSV is selected, a collapsed "ℹ️ Column reference" `st.expander` lists the documented columns present in that file with their `column_help()` text.
  - The existing `st.data_editor` widgets, their `key=`s, and the YAML/CSV save logic are unchanged.
- **New page `pages/5_Help.py` — "Help & GenX.jl Reference":**
  - A search box (`st.text_input`) driving `help_docs.search()`; results link to the matching topic.
  - Topics from `help_docs.topics()` rendered as collapsible `st.expander` sections (`topic_body()` via `st.markdown`).
  - A link-out button to the hosted docs (`https://genxproject.github.io/GenX.jl/stable/`).
  - Loads without a workspace configured (it's pure reference — no case/results dependency); if `get_workspace_root()` is `None` it still renders.
- **No network calls.** All content is from bundled files or the local GenX.jl checkout. `grep -rn "requests\|urllib\|httpx\|urlopen" src/help_docs.py pages/5_Help.py` returns nothing.
- `grep -rn "help_docs" pages/2_Inputs.py pages/5_Help.py` returns matches (the helper is actually wired in, not just created).

### Key Files to Modify/Create
- `src/help_docs.py` (new)
- `reference/genx/` (new — curated markdown snapshot + `SOURCE.md`)
- `pages/5_Help.py` (new)
- `pages/2_Inputs.py` (inline help injection only — additive)

### Do-Not-Touch Files
- `src/workspace.py`, `src/examples.py`, `src/run_diagnosis.py`, `src/run_settings.py` — complete and out of scope; `help_docs.py` and the pages may call into them but must not modify them.
- `app.py`, `archive_lib.py`, `report_lib.py`, `pages/3_Results.py`, `pages/4_Archives.py` — unrelated to this ticket. (Adding a `?` popover to `app.py`'s Run controls is explicitly a **later** ticket, deferred until the GENXUI Run-preview work lands — do not start it here.)
- The `st.data_editor` widgets, widget `key=`s, and the `yaml.dump` / CSV `to_csv` save paths in `pages/2_Inputs.py` — wrap them with help UI, do not restructure them.
- The Julia subprocess invocation.

### Verification Steps
- `streamlit run app.py` launches cleanly; the Inputs page renders for a case with `settings/genx_settings.yml`, and selecting that file shows per-key descriptions.
- Selecting `resources/Thermal.csv` shows a "Column reference" expander naming at least `Min_Cap_MW` / `Max_Cap_MW` / `Existing_Cap_MW` with descriptions.
- The Help page opens from the page nav, search for "time domain" returns the TDR topic, and the topic body renders.
- Rename/move the GenX.jl checkout (so `legacy_genx_root()/docs` is absent) → Help page and inline tooltips still work from the bundled snapshot.
- `grep -rn "GenX.jl\"\|parent.parent / \"archives\"" *.py pages/*.py archive_lib.py` (GENXUI-1's check) still returns no matches.

### Est. Nights: 2
*(Helper + table parser + bundled snapshot curation + a new page + inline injection across the Inputs editors — more than a one-file change.)*

---

## Implementation status — done 2026-08-28

All acceptance criteria met. Shipped:

- `src/help_docs.py` — `settings_help()`, `column_help()` / `documented_columns()`, `topics()`, `topic_body()`, `search()`. Parses the GenX doc tables at runtime; prefers a live `GenX.jl/docs/src/` checkout, falls back to the bundle.
- `reference/genx/` — verbatim snapshot of 5 GenX doc pages + `SOURCE.md` (GenX 0.4.6, commit `3d9596a`).
- `pages/5_Help.py` — search box + collapsible topics + hosted-docs link; renders with no workspace configured.
- `pages/2_Inputs.py` — "ℹ️ Settings reference" expander on `*.yml` files, "ℹ️ Column reference" expander on every CSV. Existing editors / `key=`s / save paths untouched.
- `tests/test_help_docs.py` — 20 cases (parsing, wildcard columns, resource-common fallback, search ranking, live-checkout preference). All green; `streamlit` AppTest clean on `app.py`, `pages/2_Inputs.py`, `pages/5_Help.py`.

**Deviation (Plan Issue, resolved):** the ticket named `Model_Reference/TDR.md` and `Model_Reference/policies.md` for the bundle. Both are `@autodocs`/`@docs` stubs with no static prose — they only pull Julia docstrings at doc-build time. Bundled `User_Guide/TDR_input.md` (the real TDR settings reference) instead; policy content is covered by `model_configuration.md` §3 + `model_input.md` Tables 23–27. Recorded in `reference/genx/SOURCE.md`.

**Deferred as specified:** the `?`-popover on `app.py`'s Run controls (waits on the Run-preview work).
