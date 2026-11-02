"""Per-bottle settings: read from the engine, write only what it supports.

Every bundle here is synthetic and lives in ``tmp_path``; nothing reads the real
application-support folder. The layouts copy what the desktop's
``is_wehnix_11_17_universal_runtime`` and friends look for.
"""

from __future__ import annotations

import asyncio
import json
import plistlib

import pytest

from wehnix_cli import cli, contract
from wehnix_cli.actions import (
    ActionError,
    available_bottle_settings,
    set_bottle_setting,
)
from wehnix_cli.models import Bottle
from wehnix_cli.state import read_bottle_app_settings, read_snapshot

WX_TARGET = """#!/bin/bash
set -u
file="$PWD/Contents/Resources/.wx-target"
case "${1:-}" in
  get) if [ -f "$file" ]; then cat "$file"; fi; exit 0 ;;
  set)
    if [ "${2:-}" = "FAIL" ]; then echo "target refused" >&2; exit 3; fi
    printf '%s' "${2:-}" > "$file"; exit 0 ;;
esac
exit 2
"""

BASE_CONFIG = {
    "launch": {"exePath": "/nothing.exe", "arguments": []},
    "renderer": {"active": "dxmt", "enabled": True},
    "graphics": {"metalHud": False, "retina": False},
    "sync": {"mode": "none"},
}

BASE_PLIST = {
    "CFBundleDisplayName": "Probe",
    "Program Name and Path": "C:\\nothing.exe",
    "Program Flags": "",
    "DXMT": "1",
    "DXVK": "0",
    "D3DMETAL": "0",
    "METAL_HUD": "0",
    "RetinaMode": "0",
    "WINEESYNC": "0",
    "WINEMSYNC": "0",
}


def _write_plist(path, values):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        plistlib.dump(values, handle)


def make_app(root, runtime, version=None, config=None, plist=None):
    """Build a bottle bundle with the payload markers the engine would ship."""
    app = root / "bottles" / f"{runtime}-id" / "Probe.app"
    contents = app / "Contents"
    resources = contents / "Resources"
    (contents / "MacOS").mkdir(parents=True)
    (contents / "MacOS" / "WehniX").write_text("#!/bin/sh\n", encoding="utf-8")
    resources.mkdir(parents=True)

    info = dict(BASE_PLIST)
    info["WehniXEngineVersion"] = version or runtime

    if runtime in (contract.UNIVERSAL, contract.STEAM):
        (resources / "wine" / "bin").mkdir(parents=True)
        (resources / "wine" / "bin" / "wine").write_text("", encoding="utf-8")
        (resources / "scripts").mkdir()
        (resources / "scripts" / "wx-bundle-env.sh").write_text("", encoding="utf-8")
        (resources / "bin").mkdir()
        tool = resources / "bin" / "wx-target"
        tool.write_text(WX_TARGET, encoding="utf-8")
        tool.chmod(0o755)
        if runtime == contract.UNIVERSAL:
            (resources / "UNIVERSAL.md").write_text("universal\n", encoding="utf-8")
            (resources / "scripts" / "wx-launch-profile.sh").write_text("", encoding="utf-8")
            (resources / "renderers" / "d3dmetal" / "external").mkdir(parents=True)
            (resources / "renderers" / "d3dmetal" / "external" / "libd3dshared.dylib").write_text(
                "", encoding="utf-8"
            )
            (resources / "renderers" / "dxvk").mkdir(parents=True)
            (resources / "renderers" / "dxvk" / ".wx-capability").write_text(
                "renders=1\n", encoding="utf-8"
            )
            (resources / "state" / "prefixes" / "universal-main" / "drive_c").mkdir(parents=True)
        else:
            (resources / "prefix-template" / "drive_c").mkdir(parents=True)
        payload = dict(BASE_CONFIG)
        for key, value in (config or {}).items():
            payload[key] = value
        if config:
            for block in ("launch", "renderer", "graphics", "sync"):
                if block in config:
                    merged = dict(BASE_CONFIG[block])
                    merged.update(config[block])
                    payload[block] = merged
        (resources / "wehnix.json").write_text(json.dumps(payload), encoding="utf-8")
    elif runtime == "11.11":
        (resources / "engine" / "wine" / "tools" / "wine").mkdir(parents=True)
        (resources / "engine" / "wine" / "tools" / "wine" / "wine").write_text(
            "", encoding="utf-8"
        )
        payload = dict(BASE_CONFIG)
        if config:
            for block in ("launch", "renderer", "graphics", "sync"):
                if block in config:
                    merged = dict(BASE_CONFIG[block])
                    merged.update(config[block])
                    payload[block] = merged
        (resources / "engine" / "wehnix.json").write_text(json.dumps(payload), encoding="utf-8")
    elif runtime == contract.GPTK:
        (app / ".gptk-engine").write_text("", encoding="utf-8")
    elif runtime == "11.0":
        (contents / "MacOS" / "wehnix-engine-launch").write_text("", encoding="utf-8")

    if plist:
        info.update(plist)
    _write_plist(contents / "Info.plist", info)
    return app


def bottle_for(app, runtime, env_type="game"):
    return Bottle(
        name="Probe",
        path=app.parent,
        unique_id=app.parent.name,
        app_path=app,
        engine=runtime,
        runtime=runtime,
        env_type=env_type,
        settings_source="app",
    )


def read_config(app, runtime="universal"):
    base = app / "Contents" / "Resources"
    path = base / "engine" / "wehnix.json" if runtime == "11.11" else base / "wehnix.json"
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Universal
# ---------------------------------------------------------------------------


def test_universal_reads_its_own_launch_config(state_dir):
    app = make_app(
        state_dir,
        contract.UNIVERSAL,
        config={
            "launch": {"exePath": "C:\\Games\\Game.exe", "arguments": ["-windowed"]},
            "renderer": {"active": "d3dmetal"},
            "graphics": {"metalHud": True},
            "sync": {"mode": "msync"},
        },
    )
    settings = read_bottle_app_settings(app)
    assert settings["source"] == "app"
    assert settings["runtime"] == contract.UNIVERSAL
    assert settings["renderer"] == "d3dmetal"
    assert settings["program_path"] == "C:\\Games\\Game.exe"
    assert settings["program_flags"] == "-windowed"
    assert settings["metal_hud"] is True
    assert settings["sync"] == "msync"
    assert settings["high_res"] is False
    assert settings["dxvk_available"] is True


def test_universal_shared_target_overrides_stale_json(state_dir):
    app = make_app(state_dir, contract.UNIVERSAL, config={"launch": {"exePath": "C:\\stale.exe"}})
    (app / "Contents" / "Resources" / ".wx-target").write_text("C:\\Shared.exe", encoding="utf-8")
    settings = read_bottle_app_settings(app)
    assert settings["program_path"] == "C:\\Shared.exe"


def test_universal_renderer_matrix_follows_the_payload(state_dir):
    app = make_app(state_dir, contract.UNIVERSAL)
    bottle = bottle_for(app, contract.UNIVERSAL)
    options = available_bottle_settings(bottle)
    assert options["renderers"]["dxmt"]["available"] is True
    assert options["renderers"]["d3dmetal"]["available"] is True
    assert options["renderers"]["dxvk"]["available"] is True
    assert options["sync_modes"] == ("none", "msync")
    assert options["metal_hud"] is True
    assert options["high_res"] is False

    marker = app / "Contents" / "Resources" / "renderers" / "dxvk" / ".wx-capability"
    marker.write_text("renders=0\n", encoding="utf-8")
    options = available_bottle_settings(bottle)
    assert options["renderers"]["dxvk"]["available"] is False
    assert "renders=1" in options["renderers"]["dxvk"]["reason"]
    with pytest.raises(ActionError, match="renders=1"):
        set_bottle_setting(bottle, "renderer", "dxvk")

    marker.unlink()
    with pytest.raises(ActionError):
        set_bottle_setting(bottle, "renderer", "dxvk")


def test_universal_refuses_esync_and_writes_msync(state_dir, no_app):
    app = make_app(state_dir, contract.UNIVERSAL)
    bottle = bottle_for(app, contract.UNIVERSAL)
    with pytest.raises(ActionError, match="esync"):
        set_bottle_setting(bottle, "sync", "esync")
    assert read_config(app)["sync"]["mode"] == "none"

    set_bottle_setting(bottle, "sync", "msync")
    assert read_config(app)["sync"]["mode"] == "msync"
    assert read_bottle_app_settings(app)["sync"] == "msync"


def test_universal_program_write_goes_through_wx_target_first(state_dir, no_app):
    app = make_app(state_dir, contract.UNIVERSAL)
    bottle = bottle_for(app, contract.UNIVERSAL)
    set_bottle_setting(bottle, "program_path", "C:\\Games\\New.exe")
    target = app / "Contents" / "Resources" / ".wx-target"
    assert target.read_text(encoding="utf-8") == "C:\\Games\\New.exe"
    assert read_config(app)["launch"]["exePath"] == "C:\\Games\\New.exe"

    with pytest.raises(ActionError, match="target refused|wx-target"):
        set_bottle_setting(bottle, "program_path", "FAIL")
    assert read_config(app)["launch"]["exePath"] == "C:\\Games\\New.exe"


def test_universal_accepts_a_mac_path_and_maps_it_to_c_or_z(state_dir, no_app):
    app = make_app(state_dir, contract.UNIVERSAL)
    bottle = bottle_for(app, contract.UNIVERSAL)
    drive_c = app / "Contents" / "Resources" / "state" / "prefixes" / "universal-main" / "drive_c"
    (drive_c / "Games").mkdir(parents=True)
    (drive_c / "Games" / "Game.exe").write_text("", encoding="utf-8")

    set_bottle_setting(bottle, "program_path", str(drive_c / "Games" / "Game.exe"))
    assert read_config(app)["launch"]["exePath"] == "C:\\Games\\Game.exe"

    set_bottle_setting(bottle, "program_path", "/tmp/Some Game.exe")
    assert read_config(app)["launch"]["exePath"] == "Z:\\tmp\\Some Game.exe"


def test_universal_metal_hud_and_flags(state_dir, no_app):
    app = make_app(state_dir, contract.UNIVERSAL)
    bottle = bottle_for(app, contract.UNIVERSAL)
    set_bottle_setting(bottle, "metal_hud", "on")
    set_bottle_setting(bottle, "program_flags", "-fullscreen -novid")
    config = read_config(app)
    assert config["graphics"]["metalHud"] is True
    assert config["launch"]["arguments"] == ["-fullscreen", "-novid"]


# ---------------------------------------------------------------------------
# Steam
# ---------------------------------------------------------------------------


def test_steam_matrix_and_locked_program(state_dir):
    app = make_app(state_dir, contract.STEAM)
    bottle = bottle_for(app, contract.STEAM, env_type="steam")
    options = available_bottle_settings(bottle)
    assert options["renderers"]["dxmt"]["available"] is True
    assert options["renderers"]["d3dmetal"]["available"] is True
    assert options["renderers"]["dxvk"]["available"] is False
    assert options["sync_modes"] == ("none",)
    assert options["metal_hud"] is True
    assert options["high_res"] is False
    assert options["program_locked"] is True

    with pytest.raises(ActionError, match="Steam"):
        set_bottle_setting(bottle, "sync", "esync")
    with pytest.raises(ActionError, match="Steam"):
        set_bottle_setting(bottle, "renderer", "dxvk")
    with pytest.raises(ActionError, match="Steam"):
        set_bottle_setting(bottle, "program_path", "C:\\Game.exe")

    set_bottle_setting(bottle, "metal_hud", True)
    assert read_config(app, contract.STEAM)["graphics"]["metalHud"] is True


# ---------------------------------------------------------------------------
# Legacy and GPTK
# ---------------------------------------------------------------------------


def test_high_resolution_is_legacy_only(state_dir, no_app):
    universal = make_app(state_dir, contract.UNIVERSAL)
    with pytest.raises(ActionError, match="high resolution"):
        set_bottle_setting(bottle_for(universal, contract.UNIVERSAL), "high_res", "on")

    legacy = make_app(state_dir, "11.11")
    set_bottle_setting(bottle_for(legacy, "11.11"), "high_res", "on")
    assert read_config(legacy, "11.11")["graphics"]["retina"] is True
    assert read_bottle_app_settings(legacy)["high_res"] is True


def test_legacy_plist_reads_and_writes(state_dir, no_app):
    app = make_app(
        state_dir,
        "11.0",
        plist={
            "Program Name and Path": "C:\\Old\\Game.exe",
            "WINEESYNC": "1",
            "METAL_HUD": "1",
            "RetinaMode": "1",
        },
    )
    settings = read_bottle_app_settings(app)
    assert settings["source"] == "app"
    assert settings["runtime"] == "11.0"
    assert settings["renderer"] == "dxmt"
    assert settings["sync"] == "esync"
    assert settings["metal_hud"] is True
    assert settings["high_res"] is True
    assert settings["dxvk_available"] is False

    bottle = bottle_for(app, "11.0")
    set_bottle_setting(bottle, "sync", "msync")
    set_bottle_setting(bottle, "metal_hud", "off")
    set_bottle_setting(bottle, "program_path", "C:\\New\\Game.exe")
    with app.joinpath("Contents", "Info.plist").open("rb") as handle:
        plist = plistlib.load(handle)
    assert plist["WINEMSYNC"] == 1
    assert plist["WINEESYNC"] == 0
    assert plist["METAL_HUD"] == 0
    assert int(plist["DXMT"]) == 1
    assert plist["Program Name and Path"] == "C:\\New\\Game.exe"

    with pytest.raises(ActionError, match="DXVK|dxvk"):
        set_bottle_setting(bottle, "renderer", "dxvk")


def test_gptk_is_d3dmetal_only_with_legacy_sync(state_dir):
    app = make_app(state_dir, contract.GPTK, plist={"D3DMETAL": "1", "DXMT": "0"})
    options = available_bottle_settings(bottle_for(app, contract.GPTK))
    assert options["runtime"] == contract.GPTK
    assert options["renderers"]["d3dmetal"]["available"] is True
    assert options["renderers"]["dxmt"]["available"] is False
    assert options["sync_modes"] == ("default", "esync", "msync")
    assert options["high_res"] is True
    assert read_bottle_app_settings(app)["renderer"] == "d3dmetal"


# ---------------------------------------------------------------------------
# Scanning and broken files
# ---------------------------------------------------------------------------


def test_scan_prefers_engine_files_over_a_stale_record(state_dir):
    app = make_app(
        state_dir,
        contract.UNIVERSAL,
        config={"renderer": {"active": "dxmt"}, "sync": {"mode": "none"}},
    )
    records = json.loads((state_dir / "bottles.json").read_text(encoding="utf-8"))
    records["bottles"].append(
        {
            "name": "Probe",
            "unique_id": "universal-id",
            "path": str(app.parent),
            "app_path": str(app),
            "engine_version": "11.17-universal",
            "env_type": "game",
            "renderer": "dxvk",
            "program_path": "C:\\stale.exe",
            "advanced": {"sync": "esync", "high_res": True},
        }
    )
    (state_dir / "bottles.json").write_text(json.dumps(records), encoding="utf-8")

    snapshot = read_snapshot(with_games=False)
    probe = next(bottle for bottle in snapshot.bottles if bottle.name == "Probe")
    assert probe.settings_source == "app"
    assert probe.renderer == "dxmt"
    assert probe.sync == "none"
    assert probe.high_res is False
    assert probe.program_path == "/nothing.exe"


def test_malformed_engine_files_do_not_raise(state_dir, no_app):
    app = make_app(state_dir, contract.UNIVERSAL)
    (app / "Contents" / "Resources" / "wehnix.json").write_text("{not json", encoding="utf-8")
    settings = read_bottle_app_settings(app)
    assert settings["renderer"] == "dxmt"
    assert settings["sync"] == "none"

    broken = make_app(state_dir, "11.0")
    (broken / "Contents" / "Info.plist").write_bytes(b"not a plist")
    settings = read_bottle_app_settings(broken)
    assert settings["source"] in ("default", "error")
    assert settings["error"] == "" or isinstance(settings["error"], str)


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def test_settings_bottle_json_round_trip(state_dir, no_app, capsys):
    app = make_app(state_dir, contract.UNIVERSAL)
    assert cli.main(["settings", "bottle", app.parent.name, "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["settings"]["renderer"] == "dxmt"
    assert payload["available"]["sync_modes"] == ["none", "msync"]
    assert payload["available"]["high_res"] is False

    assert (
        cli.main(
            [
                "settings",
                "bottle",
                app.parent.name,
                "--renderer",
                "d3dmetal",
                "--sync",
                "msync",
                "--metal-hud",
                "on",
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["settings"]["renderer"] == "d3dmetal"
    assert payload["settings"]["sync"] == "msync"
    assert payload["settings"]["metal_hud"] is True
    assert payload["updated"] == ["metal_hud", "renderer", "sync"]


def test_settings_bottle_rejects_unsupported_values(state_dir, no_app, capsys):
    app = make_app(state_dir, contract.STEAM)
    assert cli.main(["settings", "bottle", app.parent.name, "--renderer", "dxvk"]) == 1
    assert "DXVK" in capsys.readouterr().out
    assert cli.main(["settings", "bottle", app.parent.name, "--sync", "esync"]) == 1
    assert "none" in capsys.readouterr().out
    assert cli.main(["settings", "bottle", "Nope", "--json"]) == 1


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------


def test_settings_modal_offers_only_supported_options(state_dir):
    from textual.widgets import Input, Select

    from wehnix_cli.tui.app import BottleSettingsModal, WehniXCLI

    app_path = make_app(state_dir, contract.STEAM)
    bottle = bottle_for(app_path, contract.STEAM, env_type="steam")
    options = available_bottle_settings(bottle)
    tui = WehniXCLI()

    async def scenario():
        async with tui.run_test(size=(80, 24)) as pilot:
            await tui.push_screen(BottleSettingsModal(bottle, options))
            await pilot.pause()
            renderer = tui.screen.query_one("#bs-renderer", Select)
            sync = tui.screen.query_one("#bs-sync", Select)
            assert len(renderer._options) == 2  # dxmt, d3dmetal — no dxvk
            assert len(sync._options) == 1  # none only
            assert tui.screen.query_one("#bs-high", Select).disabled is True
            assert tui.screen.query_one("#bs-program", Input).disabled is True
            assert tui.screen.query_one("#bs-flags", Input).disabled is True

    asyncio.run(scenario())


def test_settings_modal_reports_changed_values(state_dir):
    from wehnix_cli.tui.app import BottleSettingsModal, WehniXCLI

    app_path = make_app(state_dir, contract.UNIVERSAL)
    bottle = bottle_for(app_path, contract.UNIVERSAL)
    options = available_bottle_settings(bottle)
    tui = WehniXCLI()
    captured = {}

    async def scenario():
        async with tui.run_test(size=(100, 34)) as pilot:
            modal = BottleSettingsModal(bottle, options)
            tui.push_screen(modal, lambda result: captured.setdefault("result", result))
            await pilot.pause()
            modal.query_one("#bs-renderer").value = "d3dmetal"
            modal._save()
            await pilot.pause()

    asyncio.run(scenario())
    assert captured["result"] == {"renderer": "d3dmetal"}
