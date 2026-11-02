"""The interface has to open, paint, and switch sections without a traceback."""

from __future__ import annotations

import asyncio

from pathlib import Path

from textual.widgets import Button, ContentSwitcher, DataTable, Footer, Input, ListView, Static

from wehnix_cli import engine_setup
from wehnix_cli.tui.app import BottlesView, SetupView, WehniXCLI


def test_tui_opens_with_the_fixture(state_dir, no_app):
    async def scenario():
        app = WehniXCLI()
        async with app.run_test(size=(118, 34)) as pilot:
            await pilot.pause()
            table = app.query_one("#bottles-table", DataTable)
            assert table.row_count == 4
            assert app.query_one("#topbar-left").render()
            assert app.query_one("#status").render()

            app.action_goto("doctor")
            await pilot.pause()
            assert app.query_one("#content", ContentSwitcher).current == "view-doctor"

            app.action_goto("settings")
            await pilot.pause()
            settings = app.query_one("#settings-table", DataTable)
            assert settings.row_count == 3

            app.action_goto("storage")
            await pilot.pause()
            assert app.query_one("#content", ContentSwitcher).current == "view-storage"

            app.action_goto("logs")
            await pilot.pause()
            assert app.query_one("#log-view").lines

    asyncio.run(scenario())


def test_search_filter_narrows_and_clears(state_dir, no_app):
    async def scenario():
        app = WehniXCLI()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            field = app.query_one("#bottle-search", Input)
            app.action_search()
            await pilot.pause()
            assert field.display is True
            field.value = "steam"
            await pilot.pause()
            table = app.query_one("#bottles-table", DataTable)
            assert table.row_count == 1
            app.action_escape()
            await pilot.pause()
            assert field.display is False
            assert table.row_count == 4

    asyncio.run(scenario())


def _bare_machine(tmp_path, monkeypatch):
    """No data folder at all: the first-run state, with HOME redirected."""
    root = tmp_path / "absent" / "WehniX"
    monkeypatch.setenv("WEHNIX_CLI_STATE_DIR", str(root))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    return root


def test_first_run_opens_setup_and_creates_nothing(tmp_path, monkeypatch, no_app):
    root = _bare_machine(tmp_path, monkeypatch)

    async def scenario():
        app = WehniXCLI(first_run=True)
        # 80x24 is the narrowest supported terminal: the setup screen has to
        # fit there too, not only on a wide one.
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            assert app.query_one("#content", ContentSwitcher).current == "view-setup"
            assert app.query_one("#view-setup", SetupView).display is True
            assert app.query_one("#setup-start", Button).size.width > 0
            assert app.query_one(Footer).size.height == 1
            # Other sections are not reachable until setup has run.
            app.action_goto("games")
            app.action_goto("settings")
            await pilot.pause()
            assert app.query_one("#content", ContentSwitcher).current == "view-setup"
            assert app.query_one("#nav", ListView).disabled is True

    asyncio.run(scenario())
    assert not root.exists(), "opening the interface must not create the data folder"


def test_first_run_install_uses_the_shared_installer(tmp_path, monkeypatch, no_app):
    root = _bare_machine(tmp_path, monkeypatch)
    calls: dict[str, object] = {}

    def fake_setup(path, versions, progress=None, cancel=None):
        calls["root"] = Path(path)
        calls["versions"] = list(versions)
        if progress is not None:
            progress("Pretending to install…", 42)
        return {
            "success": True,
            "root": str(path),
            "engines": [{"version": version} for version in versions],
            "setup_complete": True,
        }

    monkeypatch.setattr(engine_setup, "setup", fake_setup)

    async def scenario():
        app = WehniXCLI(first_run=True)
        async with app.run_test(size=(118, 34)) as pilot:
            await pilot.pause()
            app.action_setup_start()
            for _ in range(60):
                await pilot.pause(0.02)
                if app.query_one("#content", ContentSwitcher).current == "view-bottles":
                    break
            assert app.query_one("#content", ContentSwitcher).current == "view-bottles"
            assert app.query_one("#nav", ListView).disabled is False
            assert app.snapshot is not None  # the snapshot was reloaded

    asyncio.run(scenario())
    assert calls["root"] == root
    # The default first-run choice installs both 11.17 engines.
    assert calls["versions"] == [
        engine_setup.contract.UNIVERSAL,
        engine_setup.contract.STEAM,
    ]


def test_failed_setup_stays_on_the_first_run_screen(tmp_path, monkeypatch, no_app):
    _bare_machine(tmp_path, monkeypatch)
    monkeypatch.setattr(
        engine_setup,
        "setup",
        lambda *args, **kwargs: {"success": False, "error": "The disk is full."},
    )

    async def scenario():
        app = WehniXCLI(first_run=True)
        async with app.run_test(size=(118, 34)) as pilot:
            await pilot.pause()
            app.action_setup_start()
            for _ in range(60):
                await pilot.pause(0.02)
                if not app.query_one("#setup-start", Button).disabled and app._setup_done is False:
                    break
            assert app._setup_running is False
            assert app.query_one("#content", ContentSwitcher).current == "view-setup"
            # Retry stays possible after a failure.
            assert app.query_one("#setup-start", Button).disabled is False
            assert "disk is full" in str(app.query_one("#setup-result", Static).render())

    asyncio.run(scenario())


def test_setup_refuses_while_the_desktop_app_is_open(tmp_path, monkeypatch):
    _bare_machine(tmp_path, monkeypatch)
    monkeypatch.setattr("wehnix_cli.tui.app.app_is_running", lambda *a, **k: True)
    started: list[int] = []
    monkeypatch.setattr(engine_setup, "setup", lambda *a, **k: started.append(1))

    async def scenario():
        app = WehniXCLI(first_run=True)
        async with app.run_test(size=(118, 34)) as pilot:
            await pilot.pause()
            app.action_setup_start()
            for _ in range(20):
                await pilot.pause(0.02)

    asyncio.run(scenario())
    assert started == [], "the installer must not run while WehniX is open"


def test_small_terminal_does_not_crash(state_dir, no_app):
    async def scenario():
        app = WehniXCLI()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            assert app.query_one("#view-bottles", BottlesView).size.width > 0

            # The footer must stay one line at the narrowest supported width,
            # and the status strip must not need horizontal scrolling.
            assert app.query_one(Footer).size.height == 1
            assert app.query_one("#status").size.width <= 80

    asyncio.run(scenario())
