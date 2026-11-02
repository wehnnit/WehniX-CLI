"""Creating, deleting and re-configuring bottles, all inside a temp folder."""

from __future__ import annotations

import json
import os
import plistlib
import zipfile

import pytest

from wehnix_cli import actions, contract
from wehnix_cli.actions import ActionError, create_bottle, delete_bottle, set_setting
from wehnix_cli.models import Bottle, EngineArtifact


def make_engine_zip(path, bundle="WX-wine-11.17.app", universal=True):
    """A minimal engine archive: plist, executable, resource, internal symlink."""
    version = contract.UNIVERSAL if universal else "11.11"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            f"{bundle}/Contents/Info.plist",
            plistlib.dumps({"CFBundleName": "WX-wine-11.17", "CFBundleExecutable": "WehniX"}),
        )
        binary = zipfile.ZipInfo(f"{bundle}/Contents/MacOS/WehniX")
        binary.external_attr = 0o100755 << 16
        archive.writestr(binary, "#!/bin/sh\nexit 0\n")
        archive.writestr(f"{bundle}/Contents/Resources/version.txt", version)
        link = zipfile.ZipInfo(f"{bundle}/Contents/Resources/current")
        link.external_attr = 0o120777 << 16
        archive.writestr(link, "version.txt")
    return path


def engine_for(path, version=contract.UNIVERSAL):
    return EngineArtifact(
        name=path.name,
        path=path,
        size=path.stat().st_size,
        version=version,
        edition="Universal" if version == contract.UNIVERSAL else "",
        label=contract.engine_label(version),
        creatable=contract.bottle_types_for_engine(version)["creatable"],
    )


def test_create_bottle_produces_the_desktop_layout(state_dir, tmp_path, no_app):
    archive = make_engine_zip(tmp_path / "WehniX Engine 11.17 Universal.zip")
    created = create_bottle(
        "Play Time",
        engine_for(archive),
        root=state_dir,
        signer=lambda app_path, unique_id: (True, ""),
    )

    assert created.bottle_path.parent == state_dir / "bottles"
    assert created.unique_id == created.bottle_path.name
    assert created.app_path.name == "Play Time.app"
    assert (created.app_path / "Contents" / "MacOS" / "WehniX").is_file()
    assert (created.app_path / "Contents" / "Resources" / "current").is_symlink()
    assert not list((state_dir / "bottles").glob(".creating-*"))

    info = plistlib.loads((created.app_path / "Contents" / "Info.plist").read_bytes())
    assert info["WehniXEngineVersion"] == contract.UNIVERSAL
    assert info["WehniXEnvType"] == "game"
    assert info["CFBundleIdentifier"] == "com.wehnix.bottle." + created.unique_id.replace("-", "")
    assert info["CFBundleExecutable"] == "WehniX"  # the engine's own key survives

    records = json.loads((state_dir / "bottles.json").read_text())["bottles"]
    record = next(item for item in records if item.get("unique_id") == created.unique_id)
    assert record["name"] == "Play Time"
    assert record["path"] == str(created.bottle_path)
    assert record["app_path"] == str(created.app_path)
    assert record["engine_version"] == contract.UNIVERSAL
    assert record["env_type"] == "game"
    assert record["advanced"] == {"sync": "auto", "high_res": False}
    assert record["created_at"]


def test_create_bottle_keeps_existing_records_untouched(state_dir, tmp_path, no_app):
    before = (state_dir / "bottles.json").read_text()
    archive = make_engine_zip(tmp_path / "engine.zip")
    create_bottle("Second", engine_for(archive), root=state_dir, signer=lambda *a: (True, ""))
    after = json.loads((state_dir / "bottles.json").read_text())
    assert len(after["bottles"]) == len(json.loads(before)["bottles"]) + 1


def test_create_bottle_refuses_engines_that_cannot_create(state_dir, tmp_path, no_app):
    archive = make_engine_zip(tmp_path / "WehniX Engine 11.11.zip", universal=False)
    with pytest.raises(ActionError) as error:
        create_bottle("Nope", engine_for(archive, "11.11"), root=state_dir)
    assert "cannot create bottles" in str(error.value)
    assert not (state_dir / "bottles" / "Nope.app").exists()


def test_create_bottle_refuses_a_steam_env_on_universal(state_dir, tmp_path, no_app):
    archive = make_engine_zip(tmp_path / "engine.zip")
    with pytest.raises(ActionError) as error:
        create_bottle("Steamish", engine_for(archive), env_type="steam", root=state_dir)
    assert "can't be steam" in str(error.value)


def test_create_bottle_failure_leaves_nothing_behind(state_dir, tmp_path, no_app):
    archive = tmp_path / "empty.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("readme.txt", "no app here")
    with pytest.raises(ActionError):
        create_bottle("Broken", engine_for(archive), root=state_dir, signer=lambda *a: (True, ""))
    assert not list((state_dir / "bottles").glob(".creating-*"))
    assert not [p for p in (state_dir / "bottles").iterdir() if p.name not in {
        "Main.app", "Steam.app", "Epic.app", "Legacy.app",
    }]


def test_create_bottle_reports_a_signing_failure_without_losing_the_bottle(
    state_dir, tmp_path, no_app
):
    archive = make_engine_zip(tmp_path / "engine.zip")
    created = create_bottle(
        "Unsigned",
        engine_for(archive),
        root=state_dir,
        signer=lambda app_path, unique_id: (False, "codesign: rejected"),
    )
    assert created.warnings and "signing failed" in created.warnings[0]
    assert created.app_path.is_dir()


def test_create_bottle_refuses_while_the_app_is_running(state_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(actions, "app_is_running", lambda *a, **k: True)
    archive = make_engine_zip(tmp_path / "engine.zip")
    with pytest.raises(ActionError) as error:
        create_bottle("Blocked", engine_for(archive), root=state_dir)
    assert "Quit WehniX" in str(error.value)


def test_extract_rejects_a_zip_slip(tmp_path):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../escaped.txt", "nope")
    destination = tmp_path / "stage"
    destination.mkdir()
    with pytest.raises(ActionError):
        actions.extract_archive(archive, destination)
    assert not (tmp_path / "escaped.txt").exists()


def test_extract_rejects_an_escaping_symlink(tmp_path):
    archive = tmp_path / "evil-link.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        link = zipfile.ZipInfo("App.app/Contents/link")
        link.external_attr = 0o120777 << 16
        bundle.writestr(link, "../../../../etc/passwd")
    destination = tmp_path / "stage"
    destination.mkdir()
    with pytest.raises(ActionError):
        actions.extract_archive(archive, destination)


def test_delete_moves_a_bottle_to_trash_and_forgets_its_record(state_dir, no_app):
    bottle = next(b for b in __import__("wehnix_cli.state", fromlist=["scan_bottles"]).scan_bottles(state_dir) if b.name == "Main")
    destination = delete_bottle(bottle, state_dir)
    assert destination.exists()
    assert not bottle.path.exists()
    records = json.loads((state_dir / "bottles.json").read_text())["bottles"]
    assert [record["name"] for record in records] == ["Steam", "Epic", "Legacy"]


def test_delete_refuses_paths_outside_the_bottles_folder(state_dir, no_app):
    with pytest.raises(ActionError):
        delete_bottle(Bottle(name="root", path=state_dir), state_dir)
    assert state_dir.exists()


def test_forget_record_matches_unique_id_records(state_dir):
    bottle = Bottle(name="Anything", path=state_dir / "bottles" / "Main.app", unique_id="unknown-id")
    assert actions.forget_record(bottle, state_dir) is True
    records = json.loads((state_dir / "bottles.json").read_text())["bottles"]
    assert "Main" not in [record["name"] for record in records]


def test_set_setting_writes_only_the_named_key(state_dir, no_app):
    before = json.loads((state_dir / "config.json").read_text())
    actions.set_setting("graphics_backend", "d3dmetal", state_dir)
    after = json.loads((state_dir / "config.json").read_text())
    assert after["settings"]["graphics_backend"] == "d3dmetal"
    assert after["settings"]["engine_version"] == before["settings"]["engine_version"]
    assert after["setup_complete"] == before["setup_complete"]


def test_set_setting_rejects_unknown_keys(state_dir, no_app):
    with pytest.raises(ActionError):
        set_setting("setup_complete", "true", state_dir)


def test_set_setting_refuses_to_clobber_a_concurrent_edit(state_dir, no_app, monkeypatch):
    original = actions.read_json

    def racing_read(path):
        data = original(path)
        changed = {"settings": dict(data.get("settings") or {}, graphics_backend="dxvk")}
        path.write_text(json.dumps(changed))
        stamp = os.stat(path).st_mtime + 5
        os.utime(path, (stamp, stamp))
        return data

    monkeypatch.setattr(actions, "read_json", racing_read)
    with pytest.raises(ActionError) as error:
        set_setting("graphics_backend", "dxmt", state_dir)
    assert "changed while it was being edited" in str(error.value)


def test_tail_log_returns_the_last_lines(state_dir):
    lines = actions.tail_log(state_dir / "logs" / "wehniX.log", 2)
    assert [line.strip() for line in lines] == [
        "[ENGINE] Engine 11.17-universal installed | source=remote",
        "[BOTTLE] Main ready | renderer=dxmt",
    ]
    assert actions.tail_log(state_dir / "missing.log", 5) == []
