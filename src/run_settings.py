"""Small, comment-preserving edits to a case's GenX settings before a run.

GenX defaults `OverwriteResults: 0`, which makes every run after the first spill
into `results_1/`, `results_2/`, … instead of overwriting `results/`. GenXUI has
its own "Archive this run" feature for keeping history, and every GenXUI read
path expects the live results at `results/`, so for GenXUI-launched runs we set
`OverwriteResults: 1`.

The edit is a targeted line rewrite, not a `yaml` round-trip — `genx_settings.yml`
is full of explanatory comments that `yaml.safe_load` + `yaml.dump` would drop.
"""
from __future__ import annotations

import re
from pathlib import Path

_SETTINGS_REL = ("settings", "genx_settings.yml")
_KEY = "OverwriteResults"
_MANAGED_COMMENT = (
    "  # set by GenXUI: runs overwrite results/ (use \"Archive this run\" to keep copies)"
)
_LINE_RE = re.compile(rf"^(\s*{_KEY}\s*:\s*)(\S+)(.*)$")


def genx_settings_path(case_path: Path) -> Path:
    return case_path.joinpath(*_SETTINGS_REL)


def ensure_overwrite_results(case_path: Path) -> str | None:
    """Ensure the case's genx_settings.yml sets `OverwriteResults: 1`.

    Returns:
        "changed" — an existing `OverwriteResults: 0` (or other value) was set to 1
        "added"   — the key was absent and appended
        None      — already 1, or no settings file to edit (nothing written)
    """
    f = genx_settings_path(case_path)
    if not f.exists():
        return None

    text = f.read_text(encoding="utf-8")
    lines = text.splitlines()

    for i, line in enumerate(lines):
        m = _LINE_RE.match(line)
        if not m:
            continue
        if m.group(2) == "1":
            return None
        comment = m.group(3) if m.group(3).strip() else _MANAGED_COMMENT
        lines[i] = f"{m.group(1)}1{comment}"
        _write(f, lines, trailing_newline=text.endswith("\n"))
        return "changed"

    lines.append(f"{_KEY}: 1{_MANAGED_COMMENT}")
    _write(f, lines, trailing_newline=True)
    return "added"


def _write(f: Path, lines: list[str], *, trailing_newline: bool) -> None:
    body = "\n".join(lines)
    f.write_text(body + "\n" if trailing_newline else body, encoding="utf-8")
