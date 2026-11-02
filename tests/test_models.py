"""Formatting helpers and the C: lookup on a bottle."""

from __future__ import annotations

import time
from pathlib import Path

from wehnix_cli.models import Bottle, human_age, human_bytes, short_path


def test_human_bytes_reads_like_a_person():
    assert human_bytes(None) == "—"
    assert human_bytes(0) == "0 B"
    assert human_bytes(999) == "999 B"
    assert human_bytes(1536) == "1.5 KB"
    assert human_bytes(1024**3) == "1.0 GB"


def test_human_age_never_shows_an_epoch():
    assert human_age(None) == "—"
    assert human_age(0) == "—"
    assert human_age(time.time()) == "just now"
    assert human_age(time.time() - 600) == "10 min ago"
    assert human_age(time.time() - 7200) == "2 h ago"
    assert human_age(time.time() - 86400 * 3) == "3 d ago"


def test_short_path_trims_from_the_left(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    deep = tmp_path / "Library" / "Application Support" / "WehniX" / "bottles" / "abc"
    text = short_path(deep, keep=2)
    assert text.startswith("~/")
    assert text.endswith("bottles/abc")
    assert short_path(Path("/Applications/WehniX.app"), keep=2) == "/Applications/WehniX.app"


def test_c_drive_prefers_the_layout_that_exists(tmp_path):
    flat = tmp_path / "flat" / "drive_c"
    flat.mkdir(parents=True)
    assert Bottle(name="flat", path=tmp_path / "flat").c_drive == flat

    app = tmp_path / "nested" / "Main.app"
    prefix = app / "Contents" / "Resources" / "state" / "prefixes" / "universal-main" / "drive_c"
    prefix.mkdir(parents=True)
    bottle = Bottle(name="nested", path=tmp_path / "nested", app_path=app)
    assert bottle.c_drive == prefix

    nothing = Bottle(name="none", path=tmp_path / "nothing")
    assert nothing.c_drive is None


def test_labels_are_human_readable():
    bottle = Bottle(
        name="Main",
        path=Path("/tmp/Main.app"),
        engine="11.17-universal",
        env_type="game",
        renderer="d3dmetal",
    )
    assert bottle.label_engine == "11.17 Universal"
    assert bottle.label_env == "Game"
    assert bottle.renderer_label == "D3DMETAL"
