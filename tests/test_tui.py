"""The interface has to open, paint, and switch sections without a traceback."""

from __future__ import annotations

import asyncio

from textual.widgets import ContentSwitcher, DataTable, Footer, Input

from wehnix_cli.tui.app import BottlesView, WehniXCLI


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
