"""Test setup.

Every test that touches state gets its own copy of ``tests/fixtures/state`` in
``tmp_path``, and ``HOME`` is redirected too. Nothing in this suite may reach
``~/Library/Application Support/WehniX`` or the real Trash.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "state"

# A terabyte of pretend free space: the real check is exercised by its own tests,
# and no suite should fail because the machine running it is nearly full.
PLENTY_OF_SPACE = 1024**4


@pytest.fixture(autouse=True)
def portable_setup(monkeypatch):
    """Keep the installer runnable off a supported Mac.

    The platform gate, the Rosetta probe and the free-space check are real
    behaviour with their own tests; here they are neutralised so a CI box on
    Linux does not turn every install test into a refusal.
    """
    monkeypatch.setattr("wehnix_cli.engine_setup.platform_problem", lambda *a, **k: "")
    monkeypatch.setattr(
        "wehnix_cli.engine_setup.rosetta_status",
        lambda *a, **k: {
            "needed": False,
            "installed": True,
            "machine": "arm64",
            "message": "Rosetta 2 is installed.",
        },
    )
    monkeypatch.setattr(
        "wehnix_cli.engine_setup.ensure_rosetta",
        lambda *a, **k: {"needed": False, "installed": True},
    )
    monkeypatch.setattr(
        "wehnix_cli.engine_setup.free_bytes", lambda *a, **k: PLENTY_OF_SPACE
    )
    return True


@pytest.fixture()
def state_dir(tmp_path, monkeypatch):
    """A disposable copy of the fixture data folder."""
    target = tmp_path / "WehniX"
    shutil.copytree(FIXTURE, target)
    monkeypatch.setenv("WEHNIX_CLI_STATE_DIR", str(target))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    # The CLI does not depend on send2trash; make sure an installed copy in the
    # developer's environment cannot send test bottles to the real Trash.
    monkeypatch.setitem(sys.modules, "send2trash", None)
    return target


@pytest.fixture()
def no_app(monkeypatch):
    """Pretend the desktop app is closed, so writes are allowed."""
    monkeypatch.setattr("wehnix_cli.state.app_is_running", lambda *args, **kwargs: False)
    monkeypatch.setattr("wehnix_cli.actions.app_is_running", lambda *args, **kwargs: False)
    monkeypatch.setattr("wehnix_cli.tui.app.app_is_running", lambda *args, **kwargs: False)
    monkeypatch.setattr("wehnix_cli.doctor.app_is_running", lambda *args, **kwargs: False)
    return False
