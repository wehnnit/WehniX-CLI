"""Doctor checks and the scriptable command line."""

from __future__ import annotations

import json
import os

import pytest

from wehnix_cli import cli
from wehnix_cli.doctor import macos_version, rosetta_ok, run_checks, summary


def test_no_setup_without_data_exits_two_and_creates_nothing(tmp_path, monkeypatch, capsys):
    root = tmp_path / "absent" / "WehniX"
    monkeypatch.setenv("WEHNIX_CLI_STATE_DIR", str(root))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)

    assert cli.main(["--no-setup"]) == 2
    out = capsys.readouterr().out
    assert "No WehniX data yet" in out
    assert not root.exists()


def test_first_run_launch_routes_to_setup_without_creating_the_folder(
    tmp_path, monkeypatch
):
    root = tmp_path / "absent" / "WehniX"
    monkeypatch.setenv("WEHNIX_CLI_STATE_DIR", str(root))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("wehnix_cli.cli._interactive", lambda: True)
    calls: dict[str, object] = {"prepared": 0, "first_run": None}

    def note_prepare(*args, **kwargs):
        calls["prepared"] = int(calls["prepared"]) + 1

    class FakeApp:
        def __init__(self, state_dir=None, first_run=False):
            calls["first_run"] = first_run

        def run(self) -> None:
            return None

    monkeypatch.setattr("wehnix_cli.tui.app.prepare_state_dir", note_prepare)
    monkeypatch.setattr("wehnix_cli.tui.app.WehniXCLI", FakeApp)

    assert cli.main([]) == 0
    assert calls["first_run"] is True
    assert calls["prepared"] == 0, "first run must not create the data folder"
    assert not root.exists()


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


def test_missing_data_folder_is_one_failure_not_a_cascade(tmp_path, monkeypatch, no_app):
    monkeypatch.setenv("WEHNIX_CLI_STATE_DIR", str(tmp_path / "fresh"))
    monkeypatch.setattr("wehnix_cli.doctor._app_copies", lambda: [])
    checks = run_checks()
    errors, _warnings = summary(checks)
    assert errors == 1
    assert next(check for check in checks if check.name == "Data folder").status == "failed"
    skipped = {check.name for check in checks if check.status == "skipped"}
    assert {
        "Private data folder",
        "config.json",
        "Setup complete",
        "Bottles folder",
        "Bottle bundles",
        "bottles.json",
        "Engine 11.17 Universal",
        "Engine 11.17 Steam",
        "Engine archives look complete",
        "Engine for new bottles",
        "Log file",
        "Log folder writable",
    } <= skipped
    # Machine-level checks still run without a data folder.
    by_name = {check.name: check for check in checks}
    assert by_name["macOS version"].status in ("passed", "failed")
    assert by_name["Free disk space"].status in ("passed", "failed")
    assert by_name["Rosetta 2"].status in ("passed", "failed")


def test_skipped_checks_are_never_counted(tmp_path, monkeypatch, no_app):
    monkeypatch.setenv("WEHNIX_CLI_STATE_DIR", str(tmp_path / "fresh"))
    checks = run_checks()
    errors, warnings = summary(checks)
    assert errors == sum(1 for check in checks if check.status == "failed")
    assert warnings == sum(1 for check in checks if check.status == "warning")
    skipped = [check for check in checks if check.status == "skipped"]
    assert skipped and all(check.ok for check in skipped)


def test_private_folder_absent_is_skipped_not_red(tmp_path, monkeypatch, no_app):
    monkeypatch.setenv("WEHNIX_CLI_STATE_DIR", str(tmp_path / "fresh"))
    checks = run_checks()
    private = next(check for check in checks if check.name == "Private data folder")
    assert private.status == "skipped"
    assert "chmod" not in private.hint


def test_world_writable_data_folder_fails(state_dir, no_app):
    os.chmod(state_dir, 0o777)
    checks = run_checks()
    private = next(check for check in checks if check.name == "Private data folder")
    assert private.status == "failed"
    assert "writable by everyone" in private.detail


def test_unreadable_data_folder_skips_its_dependants(state_dir, no_app):
    os.chmod(state_dir, 0o000)
    try:
        checks = run_checks()
    finally:
        os.chmod(state_dir, 0o755)
    folder = next(check for check in checks if check.name == "Data folder")
    assert folder.status == "passed"  # it does exist
    permissions = next(check for check in checks if check.name == "Data folder permissions")
    assert permissions.status == "failed"
    for name in ("config.json", "Engine 11.17 Universal", "Log file"):
        assert next(check for check in checks if check.name == name).status == "skipped"


def test_missing_config_is_a_warning_not_an_error(state_dir, no_app):
    (state_dir / "config.json").unlink()
    checks = run_checks()
    config = next(check for check in checks if check.name == "config.json")
    assert config.ok is False
    assert config.status == "warning"
    setup = next(check for check in checks if check.name == "Setup complete")
    assert setup.status == "warning"


def test_absent_app_is_a_warning(state_dir, no_app, monkeypatch):
    monkeypatch.setattr("wehnix_cli.doctor._app_copies", lambda: [])
    checks = run_checks()
    app = next(check for check in checks if check.name == "WehniX.app installed")
    assert app.status == "warning"


def test_engine_health_follows_the_archive_size(state_dir, no_app):
    engine_dir = state_dir / "Engine"
    engine_dir.mkdir(exist_ok=True)
    assert not list(engine_dir.iterdir())

    # An empty Engine folder has nothing to judge, so it is not a pass.
    checks = run_checks()
    assert next(
        check for check in checks if check.name == "Engine archives look complete"
    ).status == "skipped"

    universal = engine_dir / "WehniX Engine 11.17 Universal.zip"

    # Present but empty: not a usable engine.
    universal.write_bytes(b"")
    checks = run_checks()
    archives = next(check for check in checks if check.name == "Engine archives look complete")
    assert archives.status == "failed"

    # A sparse file just under the floor is still too small.
    with universal.open("wb") as handle:
        handle.truncate(99 * 1024 * 1024)
    checks = run_checks()
    assert next(
        check for check in checks if check.name == "Engine archives look complete"
    ).status == "failed"
    assert next(
        check for check in checks if check.name == "Engine 11.17 Universal"
    ).status == "warning"

    # 200 MiB is a plausible archive, sparse or not.
    with universal.open("wb") as handle:
        handle.truncate(200 * 1024 * 1024)
    checks = run_checks()
    assert next(
        check for check in checks if check.name == "Engine archives look complete"
    ).status == "passed"
    assert next(
        check for check in checks if check.name == "Engine 11.17 Universal"
    ).status == "passed"


def test_doctor_json_reports_status_and_skips(tmp_path, monkeypatch, capsys, no_app):
    monkeypatch.setenv("WEHNIX_CLI_STATE_DIR", str(tmp_path / "fresh"))
    monkeypatch.setattr("wehnix_cli.doctor._app_copies", lambda: [])
    assert cli.main(["doctor", "--json"]) == 2
    payload = json.loads(capsys.readouterr().out)
    statuses = {check["name"]: check["status"] for check in payload["checks"]}
    assert statuses["Data folder"] == "failed"
    assert statuses["Engine 11.17 Universal"] == "skipped"
    assert payload["errors"] == 1
    assert payload["skipped"] == sum(
        1 for check in payload["checks"] if check["status"] == "skipped"
    )
    assert payload["warnings"] == sum(
        1 for check in payload["checks"] if check["status"] == "warning"
    )


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


def test_plain_launch_without_a_terminal_sets_up_instead_of_drawing(
    tmp_path, monkeypatch, capsys
):
    root = tmp_path / "WehniX"
    monkeypatch.setenv("WEHNIX_CLI_STATE_DIR", str(root))
    monkeypatch.setattr("wehnix_cli.cli._interactive", lambda: False)
    monkeypatch.setattr("wehnix_cli.cli.app_is_running", lambda: False)
    called: dict[str, object] = {}

    def fake_setup(path, versions=None, progress=None, cancel=None, force=False):
        called["root"] = os.fspath(path)
        return {"success": True, "engines": [], "root": str(path)}

    def no_tui(*args, **kwargs):  # a non-interactive launch must not draw
        raise AssertionError("the interface was started without a terminal")

    monkeypatch.setattr("wehnix_cli.engine_setup.setup", fake_setup)
    monkeypatch.setattr("wehnix_cli.tui.app.run", no_tui)

    assert cli.main([]) == 0
    assert called["root"] == str(root)
    assert "Setup complete" in capsys.readouterr().out


def test_setup_installs_both_active_engines_by_default(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("WEHNIX_CLI_STATE_DIR", str(tmp_path / "WehniX"))
    monkeypatch.setattr("wehnix_cli.cli.app_is_running", lambda: False)
    seen: dict[str, list[str]] = {}

    def fake_setup(root, versions, progress=None, cancel=None):
        seen["versions"] = list(versions)
        return {"success": True, "engines": [], "root": str(root)}

    monkeypatch.setattr("wehnix_cli.engine_setup.setup", fake_setup)
    assert cli.main(["setup", "--json"]) == 0
    assert seen["versions"] == list(cli.engine_setup.DEFAULT_SETUP_VERSIONS)
    assert seen["versions"] == [
        cli.engine_setup.contract.UNIVERSAL,
        cli.engine_setup.contract.STEAM,
    ]


def test_no_setup_never_installs_even_with_an_existing_folder(
    state_dir, no_app, monkeypatch, capsys
):
    def refuse(*args, **kwargs):
        raise AssertionError("--no-setup started the installer")

    started: list[int] = []
    monkeypatch.setattr("wehnix_cli.engine_setup.setup", refuse)
    monkeypatch.setattr("wehnix_cli.cli._interactive", lambda: True)
    monkeypatch.setattr("wehnix_cli.tui.app.run", lambda *a, **k: started.append(1))

    assert cli.main(["--no-setup"]) == 0
    assert started == [1]


def test_a_plain_launch_does_not_set_up_a_finished_install(state_dir, no_app, monkeypatch):
    monkeypatch.setattr("wehnix_cli.cli._interactive", lambda: True)
    seen: dict[str, bool] = {}

    class FakeApp:
        def __init__(self, state_dir=None, first_run=False):
            seen["first_run"] = first_run

        def run(self) -> None:
            return None

    monkeypatch.setattr("wehnix_cli.tui.app.WehniXCLI", FakeApp)
    assert cli.main([]) == 0
    assert seen["first_run"] is False
