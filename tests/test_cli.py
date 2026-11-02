"""Doctor checks and the scriptable command line."""

from __future__ import annotations

import json

import pytest

from wehnix_cli import cli
from wehnix_cli.doctor import macos_version, rosetta_ok, run_checks, summary


def test_doctor_runs_against_a_fixture_home(state_dir, no_app):
    checks = run_checks()
    names = [check.name for check in checks]
    assert "Data folder" in names
    assert "config.json" in names
    assert "Engine 11.17 Universal" in names
    assert "Setup complete" in names
    folder = next(check for check in checks if check.name == "Data folder")
    assert folder.ok is True
    errors, warnings = summary(checks)
    assert isinstance(errors, int) and isinstance(warnings, int)


def test_doctor_reports_a_missing_folder(tmp_path, monkeypatch, no_app):
    monkeypatch.setenv("WEHNIX_CLI_STATE_DIR", str(tmp_path / "nope"))
    checks = run_checks()
    folder = next(check for check in checks if check.name == "Data folder")
    assert folder.ok is False
    assert "missing" in folder.detail


def test_macos_version_is_a_tuple():
    version = macos_version()
    assert isinstance(version, tuple) and version
    assert isinstance(rosetta_ok(), bool)


def test_list_json_is_scriptable(state_dir, no_app, capsys):
    assert cli.main(["list", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 4
    assert {bottle["name"] for bottle in payload["bottles"]} == {"Main", "Steam", "Epic", "Legacy"}
    main = next(bottle for bottle in payload["bottles"] if bottle["name"] == "Main")
    assert main["unique_id"] == "Main.app"  # the record's only identifier
    assert main["env_type"] == "game"
    assert main["app_path"].endswith("Main.app/Contents/Info.plist") is False


def test_show_json(state_dir, no_app, capsys):
    assert cli.main(["show", "main", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["name"] == "Main"
    assert payload["engine"] == "11.17-universal"
    assert payload["in_registry"] is True


def test_show_unknown_bottle_returns_one(state_dir, no_app, capsys):
    assert cli.main(["show", "Nope"]) == 1
    assert "No bottle called" in capsys.readouterr().out


def test_missing_state_exits_two(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("WEHNIX_CLI_STATE_DIR", str(tmp_path / "absent"))
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["list"])
    assert exit_info.value.code == 2


def test_doctor_on_missing_state_exits_two(tmp_path, monkeypatch, capsys, no_app):
    monkeypatch.setenv("WEHNIX_CLI_STATE_DIR", str(tmp_path / "absent"))
    assert cli.main(["doctor"]) == 2
    assert "Data folder" in capsys.readouterr().out
    assert cli.main(["doctor", "--json"]) == 2


def test_state_dir_option_accepts_a_relative_path(state_dir, monkeypatch, capsys):
    monkeypatch.chdir(state_dir.parent)
    assert cli.main(["--state-dir", state_dir.name, "list", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["count"] == 4


def test_settings_get_and_set(state_dir, no_app, capsys):
    assert cli.main(["settings", "get", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert set(payload["settings"]) == {"engine_version", "graphics_backend", "auto_check_updates"}

    assert cli.main(["settings", "set", "graphics_backend", "d3dmetal"]) == 0
    config = json.loads((state_dir / "config.json").read_text())
    assert config["settings"]["graphics_backend"] == "d3dmetal"


def test_settings_set_rejects_a_retired_engine(state_dir, no_app, capsys):
    assert cli.main(["settings", "set", "engine_version", "11.11"]) == 1
    assert "cannot create bottles" in capsys.readouterr().out


def test_storage_json(state_dir, no_app, capsys):
    assert cli.main(["storage", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["bottles"]["count"] == 4
    assert payload["total_bytes"] >= 0


def test_engines_and_games_json(state_dir, no_app, capsys):
    assert cli.main(["engines", "--json"]) == 0
    engines = json.loads(capsys.readouterr().out)
    assert engines["engines"] == []

    assert cli.main(["games", "--json"]) == 0
    games = json.loads(capsys.readouterr().out)
    assert games["count"] == 0


def test_init_creates_the_folder_when_missing(tmp_path, monkeypatch, capsys):
    root = tmp_path / "fresh"
    monkeypatch.setenv("WEHNIX_CLI_STATE_DIR", str(root))
    assert cli.main(["--init"]) == 0
    assert (root / "logs").is_dir()
    assert (root / "cli" / "config.json").is_file()


def test_version_command(capsys):
    assert cli.main(["version"]) == 0
    assert "Apache-2.0" in capsys.readouterr().out
