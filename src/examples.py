"""Official GenX.jl example-system case discovery & import (GENXUI-2).

Distinct from `workspace.py`'s "Import case from GenX.jl checkout" (which
scans the top level of the checkout for ad hoc case folders): this module
scans the nested `example_systems/<name>/` tree, which is what GenX.jl's own
docs point users to as its canonical example cases.
"""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from src import workspace

EXAMPLES_DIRNAME = "example_systems"


@dataclass(frozen=True)
class ExampleCase:
    name: str
    description: str


def _examples_root() -> Path:
    return workspace.legacy_genx_root() / EXAMPLES_DIRNAME


def _parse_description(readme_path: Path) -> str:
    """First non-heading, non-blank line of the README, with light markdown
    (bold/italic markers) stripped, so it reads as plain descriptive text."""
    if not readme_path.exists():
        return ""
    for line in readme_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        return re.sub(r"[*_`]", "", line)
    return ""


def list_example_cases() -> list[ExampleCase]:
    """List official GenX.jl example cases (subdirectories of example_systems/
    containing Run.jl), each with a short description parsed from its README."""
    root = _examples_root()
    if not root.exists():
        return []

    cases = []
    for p in root.iterdir():
        if p.is_dir() and (p / "Run.jl").exists():
            cases.append(ExampleCase(name=p.name, description=_parse_description(p / "README.md")))
    return sorted(cases, key=lambda c: c.name)


def import_example_case(name: str) -> Path:
    """Copy example_systems/<name> into the active workspace's data_dir().

    Raises FileNotFoundError / FileExistsError on bad input rather than
    silently overwriting an existing imported case (same contract as
    workspace.import_case_from_legacy).
    """
    src = _examples_root() / name
    if not src.exists() or not (src / "Run.jl").exists():
        raise FileNotFoundError(f"No example case named '{name}' found under {_examples_root()}")

    dest = workspace.data_dir() / name
    if dest.exists():
        raise FileExistsError(f"'{name}' already exists in the active workspace data directory.")

    shutil.copytree(src, dest)
    return dest
