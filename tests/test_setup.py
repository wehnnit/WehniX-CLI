"""Setup, engine installs and the pinned download contract.

No test reaches the network: the downloader is pointed at ``file://`` archives
built in ``tmp_path``, and every setup writes only under the temporary
``WEHNIX_CLI_STATE_DIR``/``HOME`` from ``conftest.py``.
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import tarfile
import zipfile
from pathlib import Path

import pytest

from wehnix_cli import cli, engine_setup

# The exact published assets, independent of the module's own table, so a
# drifted URL or digest fails here instead of at a user's first setup.
PUBLISHED = {
    engine_setup.contract.UNIVERSAL: (
        "https://github.com/wehnnit/WX-Wine/releases/download/"
        "v11.17-universal/WX-wine-11.17-Universal.tar.xz",
        "04a6772387007814ef9d3f054a896ee46dfb96f5a625b140e46a7310a9164384",
    ),
    engine_setup.contract.STEAM: (
        "https://github.com/wehnnit/WX-Wine/releases/download/v11.17/WX-wine-11.17.tar.xz",
        "6aa499f98f5fec0eaa3eb6dad0d9665b04abeea82006b19714d50bf5ab3394ee",
    ),
    engine_setup.ELEVEN_ELEVEN: (
        "https://github.com/wehnnit/WX-Wine/releases/download/"
        "WX-11.11/WehniX-Engine-11.11-macos.tar.xz",
        "a8ca3ee4ecaa648f1b288f2700ce6551fed43f7eb06c4cb379a7c851d7f8aa5c",
    ),
}

INCOMPATIBLE = "e8e77bd412f90482a4df72c89e7af1d4686c2c15aaf936a20133e43b0c6305f5"


def _is_directory(entry: str) -> bool:
    return entry.endswith("drive_c") or entry.endswith("renderers/dxmt")


def build_archive(path: Path, version: str) -> Path:
    """A tiny archive with exactly the layout that engine requires."""
    app = engine_setup.remote(version)["app_name"]
    with tarfile.open(path, "w:xz") as bundle:
        for entry in engine_setup.REQUIRED_FILES[version]:
            name = f"{app}/{entry}"
            if _is_directory(entry):
                info = tarfile.TarInfo(name)
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                bundle.addfile(info)
                continue
            payload = f"test fixture: {entry}".encode()
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            info.mode = 0o755
            bundle.addfile(info, io.BytesIO(payload))
    return path


@pytest.fixture()
def fake_engine(tmp_path, monkeypatch):
    """Point one pinned entry at a local archive, with its real digest.

    The zip floor is lowered for the same reason: a 4 GB engine is not a unit
    test, and every other verification stays exactly as shipped.
    """
    monkeypatch.setattr(engine_setup, "MIN_ENGINE_ZIP_BYTES", 1)

    def build(version: str) -> tuple[Path, str]:
        archive = build_archive(tmp_path / f"{version}.tar.xz", version)
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        entry = dict(engine_setup.REMOTE_ENGINE_DOWNLOADS[version])
        entry["url"] = archive.as_uri()
        entry["sha256"] = digest
        monkeypatch.setitem(engine_setup.REMOTE_ENGINE_DOWNLOADS, version, entry)
        return archive, digest

    return build


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------


def test_pins_match_the_desktop_release_contract():
    for version, (url, digest) in PUBLISHED.items():
        entry = engine_setup.REMOTE_ENGINE_DOWNLOADS[version]
        assert entry["url"] == url
        assert engine_setup.normalize_digest(entry["sha256"]) == digest
    assert engine_setup.UNIVERSAL_INCOMPATIBLE_SHA256 == INCOMPATIBLE
    assert engine_setup.INSTALLED_ZIP_NAME[engine_setup.contract.UNIVERSAL] == (
        "WehniX Engine 11.17 Universal.zip"
    )


def test_version_aliases_are_explicit():
    assert engine_setup.resolve_version("universal") == engine_setup.contract.UNIVERSAL
    assert engine_setup.resolve_version("steam") == engine_setup.contract.STEAM
    assert engine_setup.resolve_version("11.11") == "11.11"
    with pytest.raises(engine_setup.SetupError):
        engine_setup.resolve_version("10.0")


def test_digest_normalisation_accepts_github_form():
    digest = PUBLISHED[engine_setup.contract.UNIVERSAL][1]
    assert engine_setup.normalize_digest(f"sha256:{digest.upper()}") == digest
    assert engine_setup.normalize_digest("not-a-digest") == ""


# ---------------------------------------------------------------------------
# Data folder
# ---------------------------------------------------------------------------


def test_initial_config_matches_the_desktop_defaults(tmp_path):
    root = tmp_path / "WehniX"
    created = engine_setup.ensure_layout(root)
    assert str(root) in created
    assert (root / "Engine").is_dir()
    assert (root / "bottles").is_dir()
    assert (root / "logs").is_dir()

    engine_setup.initialize_config(root)
    payload = json.loads((root / "config.json").read_text())
    assert payload["setup_complete"] is False  # honest until an engine verifies
    assert payload["bottles"] == []
    assert payload["settings"]["graphics_backend"] == "dxmt"
    assert payload["settings"]["engine_version"] == engine_setup.contract.UNIVERSAL
    assert payload["settings"]["bottle_engine_version"] == engine_setup.contract.UNIVERSAL
    assert payload["settings"]["auto_check_updates"] is True

    engine_setup.finalize_config(root)
    assert json.loads((root / "config.json").read_text())["setup_complete"] is True


def test_existing_config_keys_are_preserved(tmp_path):
    root = tmp_path / "WehniX"
    root.mkdir()
    (root / "config.json").write_text(
        json.dumps({"setup_complete": False, "custom": {"keep": True}, "settings": {}})
    )
    engine_setup.initialize_config(root)
    payload = json.loads((root / "config.json").read_text())
    assert payload["custom"] == {"keep": True}


# ---------------------------------------------------------------------------
# Installing
# ---------------------------------------------------------------------------


def test_setup_downloads_an_engine_and_marks_setup_complete(tmp_path, fake_engine):
    fake_engine(engine_setup.ELEVEN_ELEVEN)
    root = tmp_path / "WehniX"
    result = engine_setup.setup(root, [engine_setup.ELEVEN_ELEVEN])
    assert result["success"] is True
    assert result["setup_complete"] is True

    installed = engine_setup.installed_zip(root, engine_setup.ELEVEN_ELEVEN)
    assert installed.is_file()
    with zipfile.ZipFile(installed) as archive:
        names = archive.namelist()
    bundle = engine_setup.BUNDLE_NAME[engine_setup.ELEVEN_ELEVEN]
    assert f"{bundle}/Contents/Info.plist" in names

    config = json.loads((root / "config.json").read_text())
    assert config["setup_complete"] is True
    assert json.loads((root / "bottles.json").read_text()) == {"bottles": []}
    assert not list((root / "bottles").iterdir())  # no placeholder bottles


def test_checksum_mismatch_installs_nothing(tmp_path, fake_engine, monkeypatch):
    fake_engine(engine_setup.ELEVEN_ELEVEN)
    entry = dict(engine_setup.REMOTE_ENGINE_DOWNLOADS[engine_setup.ELEVEN_ELEVEN])
    entry["sha256"] = "0" * 64
    monkeypatch.setitem(engine_setup.REMOTE_ENGINE_DOWNLOADS, engine_setup.ELEVEN_ELEVEN, entry)

    root = tmp_path / "WehniX"
    result = engine_setup.setup(root, [engine_setup.ELEVEN_ELEVEN])
    assert result["success"] is False
    assert "checksum" in result["error"]
    assert not engine_setup.installed_zip(root, engine_setup.ELEVEN_ELEVEN).exists()
    downloads = root / "Engine" / ".downloads"
    assert not list(downloads.glob("*.part")) if downloads.is_dir() else True
    assert json.loads((root / "config.json").read_text())["setup_complete"] is False


def test_a_verified_download_is_reused_without_network(tmp_path, fake_engine, monkeypatch):
    archive, digest = fake_engine(engine_setup.ELEVEN_ELEVEN)
    root = tmp_path / "WehniX"
    cached = engine_setup.download_path(root, engine_setup.ELEVEN_ELEVEN)
    cached.parent.mkdir(parents=True)
    shutil.copyfile(archive, cached)

    def refuse(*args, **kwargs):
        raise AssertionError("the installer must not go to the network here")

    monkeypatch.setattr(engine_setup.urllib.request, "urlopen", refuse)
    result = engine_setup.install(engine_setup.ELEVEN_ELEVEN, root)
    assert result["reused"] is True
    assert result["sha256"] == digest


def test_known_incompatible_universal_is_refused(tmp_path, fake_engine, monkeypatch):
    _archive, digest = fake_engine(engine_setup.contract.UNIVERSAL)
    monkeypatch.setattr(engine_setup, "UNIVERSAL_INCOMPATIBLE_SHA256", digest)

    root = tmp_path / "WehniX"
    result = engine_setup.setup(root, [engine_setup.contract.UNIVERSAL])
    assert result["success"] is False
    assert "superseded" in result["error"]
    assert not engine_setup.installed_zip(root, engine_setup.contract.UNIVERSAL).exists()


def test_incomplete_engine_is_rejected(tmp_path, fake_engine, monkeypatch):
    archive, _digest = fake_engine(engine_setup.contract.STEAM)
    # Rebuild without one required helper, keeping the pinned digest valid.
    with tarfile.open(archive, "w:xz") as bundle:
        app = engine_setup.remote(engine_setup.contract.STEAM)["app_name"]
        payload = b"x"
        info = tarfile.TarInfo(f"{app}/Contents/Info.plist")
        info.size = len(payload)
        bundle.addfile(info, io.BytesIO(payload))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    entry = dict(engine_setup.REMOTE_ENGINE_DOWNLOADS[engine_setup.contract.STEAM])
    entry["sha256"] = digest
    monkeypatch.setitem(
        engine_setup.REMOTE_ENGINE_DOWNLOADS, engine_setup.contract.STEAM, entry
    )

    root = tmp_path / "WehniX"
    result = engine_setup.setup(root, [engine_setup.contract.STEAM])
    assert result["success"] is False
    assert "incomplete" in result["error"]
    assert not engine_setup.installed_zip(root, engine_setup.contract.STEAM).exists()


def test_tar_traversal_is_refused(tmp_path):
    archive = tmp_path / "bad.tar.xz"
    with tarfile.open(archive, "w:xz") as bundle:
        payload = b"escaped"
        info = tarfile.TarInfo("../escaped")
        info.size = len(payload)
        bundle.addfile(info, io.BytesIO(payload))

    assert "unsafe path" in engine_setup.tar_member_problem(archive)
    with pytest.raises(engine_setup.SetupError):
        engine_setup.install_from_archive(
            archive, engine_setup.ELEVEN_ELEVEN, tmp_path / "WehniX"
        )
    assert not (tmp_path / "escaped").exists()


def test_engine_report_flags_a_stub(tmp_path, monkeypatch):
    monkeypatch.setattr(engine_setup, "MIN_ENGINE_ZIP_BYTES", 1024)
    root = tmp_path / "WehniX"
    stub = engine_setup.installed_zip(root, engine_setup.contract.UNIVERSAL)
    stub.parent.mkdir(parents=True)
    with zipfile.ZipFile(stub, "w") as archive:
        archive.writestr("nothing", b"")

    report = engine_setup.engine_report(root, engine_setup.contract.UNIVERSAL)
    assert report["installed"] is True
    assert report["healthy"] is False
    assert "MB" in report["problem"]


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def test_setup_refuses_while_the_app_is_open(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("WEHNIX_CLI_STATE_DIR", str(tmp_path / "WehniX"))
    monkeypatch.setattr("wehnix_cli.cli.app_is_running", lambda: True)
    assert cli.main(["setup"]) == 1
    assert "Quit" in capsys.readouterr().out
    assert not (tmp_path / "WehniX").exists()


def test_setup_exit_codes(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("WEHNIX_CLI_STATE_DIR", str(tmp_path / "WehniX"))
    monkeypatch.setattr("wehnix_cli.cli.app_is_running", lambda: False)
    monkeypatch.setattr(
        engine_setup,
        "setup",
        lambda root, versions, progress=None: {
            "success": True,
            "engines": [],
            "root": str(root),
        },
    )
    assert cli.main(["setup", "--json"]) == 0

    def explode(*args, **kwargs):
        raise engine_setup.SetupError("the disk is full")

    monkeypatch.setattr(engine_setup, "setup", explode)
    assert cli.main(["setup"]) == 1
    assert "disk is full" in capsys.readouterr().out


def test_setup_and_engines_json(tmp_path, fake_engine, monkeypatch, capsys):
    fake_engine(engine_setup.ELEVEN_ELEVEN)
    monkeypatch.setenv("WEHNIX_CLI_STATE_DIR", str(tmp_path / "WehniX"))
    monkeypatch.setattr("wehnix_cli.cli.app_is_running", lambda: False)

    assert cli.main(["setup", "--engine", "11.11", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["setup_complete"] is True
    assert payload["engines"][0]["version"] == "11.11"

    assert cli.main(["engines", "doctor", "--json"]) == 1  # universal/steam absent
    reports = {item["version"]: item for item in json.loads(capsys.readouterr().out)["engines"]}
    assert reports["11.11"]["healthy"] is True
    assert reports[engine_setup.contract.UNIVERSAL]["installed"] is False


def test_read_commands_never_download(state_dir, no_app, monkeypatch, capsys):
    def refuse(*args, **kwargs):
        raise AssertionError("a read command reached the network")

    monkeypatch.setattr(engine_setup.urllib.request, "urlopen", refuse)
    monkeypatch.setattr("wehnix_cli.doctor._app_copies", lambda: [])

    assert cli.main(["list", "--json"]) == 0
    assert cli.main(["games", "--json"]) == 0
    # The exit code depends on this machine; the point is that no command
    # above reached the downloader, which would have raised AssertionError.
    assert cli.main(["doctor", "--json"]) in (0, 1, 2)
    assert "Engine 11.17 Universal" in capsys.readouterr().out


def test_install_aliases_and_unknown_version(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("WEHNIX_CLI_STATE_DIR", str(tmp_path / "WehniX"))
    monkeypatch.setattr("wehnix_cli.cli.app_is_running", lambda: False)
    assert cli.main(["engines", "install", "10.0"]) == 1
    assert "not an engine" in capsys.readouterr().out
