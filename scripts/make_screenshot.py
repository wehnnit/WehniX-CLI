#!/usr/bin/env python3
"""Render the interface to docs/cli.svg.

    python3 scripts/make_screenshot.py

Builds a throwaway state folder from tests/fixtures/state so the picture is
identical on any machine: same four bottles, two installed engines, plausible
"last used" times. It lives in the system temporary folder and is removed
afterwards, so the picture never touches the real WehniX data.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from wehnix_cli.tui.app import WehniXCLI  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "state"
OUTPUT = ROOT / "docs" / "cli.svg"

# Sparse files: the CLI only ever stats an engine archive, so 4.2 GB costs no
# disk and keeps the picture honest about what a real install looks like.
ENGINES = (
    ("WehniX Engine 11.17 Universal.zip", 4_512_777_633),
    ("WehniX Engine 11.17 Steam.zip", 4_206_510_914),
)
LAST_USED = {
    "Main.app": 40 * 60,
    "Steam.app": 5 * 3600,
    "Epic.app": 2 * 86400,
    "Legacy.app": 26 * 86400,
}


def build_state() -> Path:
    work = Path(tempfile.mkdtemp(prefix="wehniX-cli-demo-"))
    state = work / "WehniX"
    shutil.copytree(FIXTURE, state)
    (state / "Engine").mkdir(parents=True, exist_ok=True)
    for name, size in ENGINES:
        target = state / "Engine" / name
        with target.open("wb") as handle:
            handle.truncate(size)
    now = time.time()
    for bundle, age in LAST_USED.items():
        path = state / "bottles" / bundle
        if path.exists():
            stamp = now - age
            os.utime(path, (stamp, stamp))
    return state


async def render() -> None:
    state = build_state()
    os.environ["WEHNIX_CLI_STATE_DIR"] = str(state)
    try:
        app = WehniXCLI(state_dir=state)
        async with app.run_test(size=(118, 34)) as pilot:
            await pilot.pause()
            app.action_goto("bottles")
            app.query_one("#nav").index = 0
            await pilot.pause()
            OUTPUT.parent.mkdir(parents=True, exist_ok=True)
            app.save_screenshot(str(OUTPUT))
            print(f"wrote {OUTPUT}")
    finally:
        shutil.rmtree(state.parent, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(render())
