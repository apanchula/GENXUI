# GenX.jl documentation snapshot

These files are a verbatim copy of selected pages from the GenX.jl documentation
source, bundled so GenXUI's inline help and Help page work without a GenX.jl
checkout on disk. `src/help_docs.py` prefers a live `GenX.jl/docs/src/` copy
when one is present (see `workspace.legacy_genx_root()`), falling back to these.

| Bundled file | Upstream path (`GenX.jl/docs/src/`) |
| --- | --- |
| `model_configuration.md` | `User_Guide/model_configuration.md` |
| `solver_configuration.md` | `User_Guide/solver_configuration.md` |
| `model_input.md` | `User_Guide/model_input.md` |
| `model_output.md` | `User_Guide/model_output.md` |
| `TDR_input.md` | `User_Guide/TDR_input.md` |
| `model_introduction.md` | `Model_Concept_Overview/model_introduction.md` |

**Note:** the roadmap ticket (GENXUI-3) named `Model_Reference/TDR.md` and
`Model_Reference/policies.md`. Those two pages are `@autodocs`/`@docs` stubs — they
contain no static prose, only directives that pull Julia docstrings at doc-build
time. `User_Guide/TDR_input.md` (the actual TDR settings reference) is bundled
instead; policy settings are already covered by `model_configuration.md` §3 and
`model_input.md` Tables 23–27.

## Provenance

- Source repo: https://github.com/GenXProject/GenX.jl
- GenX version: **0.4.6**
- Commit: `3d9596ad9ce69e66ed0404754e58250059bf612b` (2026-01-10)
- Snapshot taken: 2026-08-28

## Updating

Re-copy the files from a newer `GenX.jl/docs/src/` checkout and update the
version / commit / date above. No code changes are needed — `help_docs.py`
parses these at runtime.
