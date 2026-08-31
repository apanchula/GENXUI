"""Shared test fixtures.

`src.workspace` persists the chosen workspace root to `~/.genxui/config.json`.
Several tests call `workspace.set_workspace_root(<tmpdir>)`, which would otherwise
overwrite the developer's real config (and leave it pointing at a deleted temp
dir). Redirect that config at a throwaway location for the whole test session.
"""
import sys
from pathlib import Path

import pytest

_GENXUI = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_GENXUI))


@pytest.fixture(autouse=True)
def _isolate_workspace_config(tmp_path_factory, monkeypatch):
    from src import workspace

    cfg_dir = tmp_path_factory.mktemp("genxui-config")
    monkeypatch.setattr(workspace, "CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(workspace, "CONFIG_PATH", cfg_dir / "config.json")
    yield
