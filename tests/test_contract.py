"""The desktop rules the CLI ports must not drift."""

from __future__ import annotations

import pytest

from wehnix_cli import contract


def test_engine_identity_requires_the_word_universal():
    assert contract.engine_identity("WehniX Engine 11.17 Universal.zip") == (
        contract.UNIVERSAL,
        "Universal",
    )
    assert contract.engine_identity("WX-wine-11.17-Universal.tar.xz") == (
        contract.UNIVERSAL,
        "Universal",
    )
    # A bare 11.17 is the older Steam build, never Universal.
    assert contract.engine_identity("WehniX Engine 11.17.zip")[0] == contract.STEAM
    assert contract.engine_identity("WehniX Engine 11.17 Steam.zip")[0] == contract.STEAM


def test_engine_identity_handles_legacy_and_unknown_names():
    assert contract.engine_identity("WehniX Engine 11.11.zip") == ("11.11", "Universal")
    assert contract.engine_identity("WehniX Engine 11.0.zip") == ("11.0", "Universal")
    assert contract.engine_identity("Game Porting Toolkit 3.0.zip")[0] == contract.GPTK
    assert contract.engine_identity("holiday-photos.zip") == ("unknown", "")


def test_normalize_engine_version_keeps_steam_for_bare_11_17():
    assert contract.normalize_engine_version("11.17") == contract.STEAM
    assert contract.normalize_engine_version("11.17-beta") == contract.STEAM
    assert contract.normalize_engine_version(contract.UNIVERSAL) == contract.UNIVERSAL
    assert contract.normalize_engine_version("not-an-engine") == contract.UNIVERSAL


def test_bottle_types_follow_the_support_table():
    universal = contract.bottle_types_for_engine(contract.UNIVERSAL)
    assert universal["creatable"] is True
    assert universal["allowed"] == ("game", "application")
    assert universal["default"] == "game"

    steam = contract.bottle_types_for_engine(contract.STEAM)
    assert steam["allowed"] == ("steam",)
    assert steam["default"] == "steam"

    for retired in ("11.11", "11.0", contract.GPTK):
        assert contract.bottle_types_for_engine(retired)["creatable"] is False


def test_env_type_is_normalised_per_engine():
    assert contract.normalize_bottle_env_type("steam", contract.UNIVERSAL) == "game"
    assert contract.normalize_bottle_env_type("application", contract.UNIVERSAL) == "application"
    assert contract.normalize_bottle_env_type("game", contract.STEAM) == "steam"
    assert contract.normalize_bottle_env_type("steam", "11.11") == "game"


def test_sanitize_bundle_name_matches_the_app():
    assert contract.sanitize_bundle_name("My Bottle") == "My Bottle"
    assert contract.sanitize_bundle_name("a/b:c?d") == "a-b-c-d"
    assert contract.sanitize_bundle_name("  ..  ") == "Bottle"
    assert contract.sanitize_bundle_name("") == "Bottle"


def test_bundle_name_gets_app_suffix_only_for_11_17_engines():
    assert contract.bottle_bundle_name("Play", contract.UNIVERSAL) == "Play.app"
    assert contract.bottle_bundle_name("Play.app", contract.UNIVERSAL) == "Play.app"
    assert contract.bottle_bundle_name("Play", "11.11") == "Play"


def test_validate_setting_accepts_only_safe_keys():
    assert contract.validate_setting("auto_check_updates", "TRUE") is True
    assert contract.validate_setting("auto_check_updates", "no") is False
    assert contract.validate_setting("graphics_backend", "D3DMetal") == "d3dmetal"
    assert contract.validate_setting("engine_version", "11.17-universal") == contract.UNIVERSAL

    with pytest.raises(ValueError):
        contract.validate_setting("graphics_backend", "opengl")
    with pytest.raises(ValueError):
        contract.validate_setting("engine_version", "11.11")
    with pytest.raises(ValueError):
        contract.validate_setting("auto_check_updates", "maybe")
    with pytest.raises(ValueError):
        contract.validate_setting("setup_complete", "true")


def test_record_has_the_desktop_shape(tmp_path):
    record = contract.record_for_bottle(
        name="Main",
        unique_id="abc",
        bottle_path=tmp_path / "abc",
        app_path=tmp_path / "abc" / "Main.app",
        c_drive_path=tmp_path / "abc" / "Main.app" / "drive_c",
        engine_version=contract.UNIVERSAL,
        env_type="game",
        created_at="2026-11-02T00:00:00+00:00",
    )
    for key in (
        "name",
        "unique_id",
        "env_type",
        "path",
        "app_path",
        "c_drive_path",
        "program_path",
        "program_flags",
        "engine_version",
        "renderer",
        "metal_hud",
        "advanced",
        "created_at",
    ):
        assert key in record
    assert record["advanced"] == {"sync": "auto", "high_res": False}
