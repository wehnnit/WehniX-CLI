"""Reading the desktop app's data, and refusing to invent our own."""

from __future__ import annotations

import json

from wehnix_cli import state as state_module
from wehnix_cli.state import (
    app_is_running,
    prepare_state_dir,
    read_json,
    read_snapshot,
    record_index,
    scan_bottles,
    scan_engines,
    write_json_atomic,
)


def test_fixture_snapshot_has_all_four_bottles(state_dir):
    snapshot = read_snapshot(with_games=False)
    assert snapshot.exists
    names = [bottle.name for bottle in snapshot.bottles]
    assert sorted(names) == ["Epic", "Legacy", "Main", "Steam"]
    main = next(bottle for bottle in snapshot.bottles if bottle.name == "Main")
    assert main.engine == "11.17-universal"
    assert main.edition == "Universal"
    assert main.app_path == state_dir / "bottles" / "Main.app"
    assert main.in_registry is True
    assert main.size == 1_284_000_000  # from the record, not measured
    assert snapshot.log_path is not None


def test_unknown_engine_is_not_silently_called_universal(tmp_path, monkeypatch):
    monkeypatch.setenv("WEHNIX_CLI_STATE_DIR", str(tmp_path))
    bottle = tmp_path / "bottles" / "abc"
    macos = bottle / "Mystery.app" / "Contents" / "MacOS"
    macos.mkdir(parents=True)
    (macos / "WehniX").write_text("#!/bin/sh\n")
    (bottle / "Mystery.app" / "Contents" / "Info.plist").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">'
        '<plist version="1.0"><dict>'
        "<key>CFBundleName</key><string>Mystery</string>"
        "</dict></plist>"
    )
    scanned = scan_bottles(tmp_path)
    assert len(scanned) == 1
    assert scanned[0].engine == "unknown"


def test_prepare_state_dir_never_creates_the_app_folder_by_default(tmp_path):
    root = tmp_path / "WehniX"
    result = prepare_state_dir(root)
    assert result["missing"] is True
    assert result["created"] == []
    assert not root.exists(), "a half-made data folder makes the app think setup ran"


def test_prepare_state_dir_can_create_when_asked(tmp_path):
    root = tmp_path / "WehniX"
    result = prepare_state_dir(root, create_root=True)
    assert result["missing"] is False
    assert (root / "cli" / "config.json").is_file()
    assert (root / "logs").is_dir()
    # Again: nothing new, and no user data touched.
    again = prepare_state_dir(root, create_root=True)
    assert again["created"] == []


def test_record_index_understands_every_identifier():
    index = record_index(
        [
            {"unique_id": "abc", "path": "/x/bottles/abc", "name": "Main"},
            {"id": "Play.app", "app_path": "/x/bottles/def/Play.app"},
        ]
    )
    assert index["abc"]["name"] == "Main"
    assert index["Main"]["name"] == "Main"
    assert index["abc"]["unique_id"] == "abc"
    assert index["Play.app"]["id"] == "Play.app"
    assert index["def"]["id"] == "Play.app"


def test_engine_scan_rejects_tiny_and_backup_archives(state_dir):
    engines_dir = state_dir / "Engine"
    engines_dir.mkdir(exist_ok=True)
    (engines_dir / "WehniX Engine 11.17 Universal.zip").write_bytes(b"not really")
    (engines_dir / "WehniX Engine 11.11.zip").write_bytes(b"old")
    (engines_dir / ".WehniX Engine 11.17 Universal.zip.previous").write_bytes(b"old")
    engines = scan_engines(state_dir)
    assert len(engines) == 2
    universal = next(engine for engine in engines if engine.version == "11.17-universal")
    assert universal.healthy is False
    assert universal.creatable is True
    assert all(".previous" not in engine.name for engine in engines)


def test_write_json_atomic_leaves_valid_json(state_dir):
    target = state_dir / "cli" / "notes.json"
    write_json_atomic(target, {"bottles": [1, 2]})
    assert json.loads(target.read_text()) == {"bottles": [1, 2]}
    assert not list(target.parent.glob("*.tmp"))


def test_app_is_running_ignores_the_pattern_in_its_own_command_line():
    def pgrep_says_yes(command):
        if command[0] == "/usr/bin/pgrep":
            return 0, "4242\n"
        return 0, "/bin/sh -c pgrep -f WehniX.app/Contents/MacOS/WehniX\n"

    assert app_is_running(pgrep_says_yes) is False


def test_app_is_running_detects_the_real_binary():
    def runner(command):
        if command[0] == "/usr/bin/pgrep":
            return 0, "4242\n"
        return 0, "/Applications/WehniX.app/Contents/MacOS/WehniX\n"

    assert app_is_running(runner) is True


def test_app_is_running_handles_no_match_and_failures():
    assert app_is_running(lambda command: (1, "")) is False

    def broken(command):
        raise OSError("pgrep is gone")

    assert app_is_running(broken) is False


def test_read_json_tolerates_garbage(tmp_path):
    bad = tmp_path / "config.json"
    bad.write_text("{not json")
    assert read_json(bad) == {}
    assert read_json(tmp_path / "missing.json") == {}
    assert state_module.state_root() == state_module.default_root()
