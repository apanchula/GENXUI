<!-- status: Parts 1 & 2 implemented 2026-08-28 · Part 3 (cleanup) not done · owner: GenXUI -->
<!-- shipped: src/run_settings.py (Part 1), workspace.resolve_results_dir (Part 2),
     wired into app.py / pages/3_Results.py / archive_lib.py;
     tests in tests/test_results_resolution.py.
     Deviation: resolve_results_dir picks by most-recent mtime (suffix number only
     as tie-breaker), not "highest suffix" — so a fresh in-place results/ wins over
     a stale results_1/ once Part 1 is active. -->


# Proposal: `results/` vs `results_1/` — run output resolution

## Why `results_1` was created

It's GenX.jl's built-in "don't clobber previous results" behaviour, not a
GenXUI bug.

`configure_settings.jl` defaults `OverwriteResults => 0`. With that setting,
`write_outputs()` (and the multi-stage runner) call
[`choose_output_dir()`](../../GenX.jl/src/write_outputs/choose_output_dir.jl):

```julia
function choose_output_dir(pathinit::String)
    path = pathinit; counter = 1
    while isdir(path)                       # results/ already exists ...
        path = string(pathinit, "_", counter)  # ... so try results_1, results_2, ...
        counter += 1
    end
    return path
end
```

The case's `settings/genx_settings.yml` has **no `OverwriteResults` key**, so
it takes the `0` default. The first run created `results/`; the next run saw
`results/` already there and wrote to `results_1/`.

## Why the Results viewer can't see it

Every GenXUI read path hard-codes the literal folder name `results`:

| Location | Code |
|---|---|
| [`pages/3_Results.py:67`](../pages/3_Results.py) | `results_dir = case_path / "results"` |
| [`archive_lib.py:160`](../archive_lib.py) | `results_src = case_path / "results"` |

So after a second run: `results/` holds the **stale first run**, `results_1/`
holds the **current** one, and GenXUI shows the stale one (and would archive
the stale one).

---

## Design position

GenXUI already owns run preservation — the **"Archive this run"** feature
snapshots `results/` + inputs + solver commit into `archive/`. Within GenXUI's
model, the live case's `results/` is just "the latest run"; history lives in
the archive. GenX's `results_N` fan-out is therefore redundant here *and*
actively breaks the viewer.

The cases under `workspace/data/<case>` are GenXUI-managed copies (imported by
`examples.import_example_case` / `workspace.import_case_from_legacy`), not the
pristine GenX.jl originals — so it is legitimate for GenXUI to set a run
setting on them.

Recommendation: **make GenXUI runs overwrite `results/` (primary fix), and
make GenXUI reads tolerant of `results_N/` anyway (defense in depth).**

---

## Part 1 — GenXUI runs overwrite `results/`

Before launching Julia, ensure the case's `settings/genx_settings.yml` sets
`OverwriteResults: 1`.

**Targeted line edit, not a YAML round-trip** — `genx_settings.yml` is full of
explanatory comments that `yaml.safe_load` + `yaml.dump` would destroy.

```python
# src/run_settings.py  (new)
import re
from pathlib import Path

_MANAGED = "  # set by GenXUI: runs overwrite results/ — use Archive to keep a copy"

def ensure_overwrite_results(case_path: Path) -> str | None:
    """Make GenX overwrite results/ instead of spilling to results_1/.
    Returns 'added' | 'changed' | None (already 1). Comment-preserving."""
    f = case_path / "settings" / "genx_settings.yml"
    if not f.exists():
        return None
    lines = f.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^(\s*OverwriteResults\s*:\s*)(\S+)(.*)$", line)
        if m:
            if m.group(2) == "1":
                return None
            lines[i] = f"{m.group(1)}1{m.group(3)}"
            f.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return "changed"
    lines.append(f"OverwriteResults: 1{_MANAGED}")
    f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return "added"
```

Wire into the Run-launch block in `app.py` (before the thread starts):

```python
if run_btn:
    _change = run_settings.ensure_overwrite_results(case_path)
    if _change:
        st.toast("GenXUI set OverwriteResults: 1 for this case — "
                 "runs now overwrite results/. Use “Archive this run” to keep copies.")
    ...
```

Plus a permanent one-liner near the Run button:

> Runs overwrite this case's `results/`. Use **Archive this run** to keep a copy.

### Consequence

After this, a rerun overwrites `results/` in place; no `results_N/` is ever
created by a GenXUI-launched run. The viewer and the archiver are correct with
zero further changes.

---

## Part 2 — reads tolerate `results_N/` (defense in depth)

Covers folders that already exist (`results_1/` from before this fix),
externally-run cases, and races.

```python
# src/workspace.py  (add)
import re

def resolve_results_dir(case_path: Path) -> Path | None:
    """The results folder GenXUI should display for a case.

    Prefers plain results/ when it exists and is non-empty; otherwise the
    newest results_N/ (highest N, tie-broken by mtime). None if there are no
    results at all. Does NOT descend into multi-stage results_p*/ layouts.
    """
    plain = case_path / "results"
    candidates = []
    if plain.is_dir() and any(plain.iterdir()):
        candidates.append((0, plain.stat().st_mtime, plain))
    for p in case_path.glob("results_*"):
        m = re.fullmatch(r"results_(\d+)", p.name)
        if p.is_dir() and m and any(p.iterdir()):
            candidates.append((int(m.group(1)), p.stat().st_mtime, p))
    if not candidates:
        return None
    # highest suffix wins; if only results_N exist, newest of them
    return max(candidates, key=lambda t: (t[0], t[1]))[2]
```

- `pages/3_Results.py`: replace `results_dir = case_path / "results"` with
  `results_dir = workspace.resolve_results_dir(case_path)`; the existing
  "no results yet" guard already handles `None`. Show the resolved name in the
  caption that's already there (`Live case — .../results_1`) so a non-default
  folder is visible, not silent.
- `archive_lib.create_archive`: resolve the same way so Archive snapshots the
  run the user is actually looking at.

> ⚠️ **Order matters:** "highest N" is right *only* because GenX increments.
> If Part 1 ships, `results/` is always the latest and this path is rarely
> exercised — but keep the suffix-priority so a stray pre-existing `results_1`
> from the old behaviour is preferred over a stale `results/`.

---

## Part 3 — cleanup (optional)

A "Tidy result folders" button on the Runner, enabled when any `results_N/`
exists:

- move the resolved-latest into `results/` (replacing it),
- delete the other `results_N/`.

With Part 1 in place this is a one-time migration aid for cases that already
have the fan-out, not an ongoing need.

---

## Out of scope

- **Multi-stage** (`6_three_zones_w_multistage`) writes
  `results/results_p1/`, `results_p2/`, … — a nested layout the Results page
  doesn't render regardless of this issue. Track separately.
- Changing GenX.jl's default. Not ours to change; the per-case setting is the
  supported knob.

---

## Recommended sequencing

1. Part 2 (`resolve_results_dir`) — immediately unbreaks the viewer for the
   `results_1/` that already exists, low risk, no input mutation.
2. Part 1 (`ensure_overwrite_results`) — stops new fan-out at the source.
3. Part 3 — only if fan-out folders are common in existing workspaces.
