"""The uninstaller runs against a throwaway HOME, never the real one."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "uninstall.sh"
LAUNCHERS = ("wehniX-cli", "WehniX", "wehniX", "wehnix", "Wehnix")


def make_home(tmp_path: Path) -> tuple[Path, Path]:
    """A HOME that looks like a real install plus a few bottles."""
    home = tmp_path / "home"
    (home / ".local" / "share" / "wehniX-cli" / "bin").mkdir(parents=True)
    (home / ".local" / "share" / "wehniX-cli" / "bin" / "python").write_text("", encoding="utf-8")
    (home / ".local" / "bin").mkdir(parents=True)
    for name in LAUNCHERS:
        launcher = home / ".local" / "bin" / name
        launcher.write_text("#!/bin/sh\n", encoding="utf-8")
        launcher.chmod(0o755)
    (home / ".cache" / "wehniX-cli-demo").mkdir(parents=True)

    data = home / "Library" / "Application Support" / "WehniX"
    (data / "cli").mkdir(parents=True)
    (data / "cli" / "config.json").write_text('{"schema": 1}', encoding="utf-8")
    (data / "logs").mkdir()
    (data / "logs" / "wehniX.log").write_text("boot\n", encoding="utf-8")
    bottle = data / "bottles" / "abc" / "Main.app" / "Contents"
    bottle.mkdir(parents=True)
    (bottle / "Info.plist").write_text("plist\n", encoding="utf-8")
    (data / "config.json").write_text('{"setup_complete": true}', encoding="utf-8")
    (data / "bottles.json").write_text('{"bottles": []}', encoding="utf-8")
    return home, data


def run(home: Path, *arguments: str, stdin: int | None = subprocess.DEVNULL):
    env = dict(os.environ, HOME=str(home))
    return subprocess.run(
        ["bash", str(SCRIPT), *arguments],
        capture_output=True,
        text=True,
        env=env,
        stdin=stdin,
        timeout=60,
        check=False,
    )


def assert_launchers_gone(home: Path) -> None:
    for name in LAUNCHERS:
        assert not (home / ".local" / "bin" / name).exists(), name


def test_cli_only_removal_keeps_the_bottles(tmp_path):
    home, data = make_home(tmp_path)
    result = run(home, "--yes")

    assert result.returncode == 0, result.stderr
    assert not (home / ".local" / "share" / "wehniX-cli").exists()
    assert not (home / ".cache" / "wehniX-cli-demo").exists()
    assert_launchers_gone(home)
    assert not (data / "cli").exists()

    # Everything the desktop app owns is still there, byte for byte.
    assert (data / "config.json").read_text(encoding="utf-8") == '{"setup_complete": true}'
    assert (data / "bottles.json").is_file()
    assert (data / "bottles" / "abc" / "Main.app" / "Contents" / "Info.plist").is_file()
    assert (data / "logs" / "wehniX.log").is_file()
    assert str(data) in result.stdout


def test_all_data_removes_the_shared_folder(tmp_path):
    home, data = make_home(tmp_path)
    result = run(home, "--all-data", "--yes")

    assert result.returncode == 0, result.stderr
    assert not data.exists()
    assert not (home / ".local" / "share" / "wehniX-cli").exists()
    assert_launchers_gone(home)


def test_all_data_requires_confirmation_without_yes(tmp_path):
    home, data = make_home(tmp_path)
    result = run(home, "--all-data")

    assert result.returncode == 1
    assert "Refusing" in result.stderr
    assert (data / "bottles").is_dir()


def test_second_run_is_clean_and_changes_nothing(tmp_path):
    home, data = make_home(tmp_path)
    assert run(home, "--yes").returncode == 0
    again = run(home, "--yes")
    assert again.returncode == 0
    assert "absent" in again.stdout
    assert data.is_dir()

    assert run(home, "--all-data", "--yes").returncode == 0
    assert not data.exists()


def test_clean_path_removes_only_the_installer_line(tmp_path):
    home, _data = make_home(tmp_path)
    zshrc = home / ".zshrc"
    zshrc.write_text(
        'export EDITOR=vim\nexport PATH="$HOME/.local/bin:$PATH"\nalias ll="ls -l"\n',
        encoding="utf-8",
    )
    result = run(home, "--yes", "--clean-path")

    assert result.returncode == 0, result.stderr
    text = zshrc.read_text(encoding="utf-8")
    assert "export EDITOR=vim" in text
    assert 'alias ll="ls -l"' in text
    assert ".local/bin" not in text
    assert not (home / ".zshrc.bak").exists()


def test_the_app_bundle_is_never_touched(tmp_path):
    home, _data = make_home(tmp_path)
    app = home / "Applications" / "WehniX.app"
    app.mkdir(parents=True)
    assert run(home, "--all-data", "--yes").returncode == 0
    assert app.is_dir()
