#!/usr/bin/env python3
"""Render the interface to docs/cli.svg and docs/cli.png.

    python3 scripts/make_screenshot.py

Builds a throwaway state folder from tests/fixtures/state so the picture is
identical on any machine: same four bottles, two installed engines, plausible
"last used" times. It lives in the system temporary folder and is removed
afterwards, so the picture never touches the real WehniX data.

The PNG is the image the README shows. Chrome renders it, because rsvg squeezes
the spaces that separate a label from its value in the exported SVG.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from wehnix_cli.tui.app import WehniXCLI  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "state"
OUTPUT = ROOT / "docs" / "cli.svg"
PNG = ROOT / "docs" / "cli.png"
CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")

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
            # The SVG exporter leaves trailing spaces on runs; `git log --check`
            # rightly calls that a whitespace error.
            text = OUTPUT.read_text(encoding="utf-8")
            OUTPUT.write_text(
                "\n".join(line.rstrip() for line in text.splitlines()) + "\n",
                encoding="utf-8",
            )
            print(f"wrote {OUTPUT}")
    finally:
        shutil.rmtree(state.parent, ignore_errors=True)
    render_png()


def render_png() -> None:
    """Turn the SVG into the PNG the README shows, at a readable size."""
    if not CHROME.is_file():
        print("Chrome not installed; docs/cli.png was not refreshed")
        return
    header = re.search(r'<svg[^>]*width="(\d+)"[^>]*height="(\d+)"', OUTPUT.read_text())
    if header is None:
        print("Could not read the SVG size; docs/cli.png was not refreshed")
        return
    width, height = (int(header.group(1)), int(header.group(2)))
    completed = subprocess.run(
        [
            str(CHROME),
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--force-device-scale-factor=1.5",
            f"--window-size={width},{height}",
            f"--screenshot={PNG}",
            OUTPUT.as_uri(),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if completed.returncode != 0 or not PNG.is_file():
        print(f"Chrome could not render the PNG: {completed.stderr.strip()[:200]}")
        return
    print(f"wrote {PNG}")


if __name__ == "__main__":
    asyncio.run(render())
