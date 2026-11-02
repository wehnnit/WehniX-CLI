"""The desktop app's bottle and engine rules, ported for the open CLI.

The authority is ``WehniX/wehnix_app.py`` plus
``WehniX/ui/data/wehnix_engine_support.json``. Each function below names the
desktop function it mirrors so the two copies can be compared when either
changes. Nothing here invents a rule the desktop does not already enforce: the
CLI must never offer a bottle the window would refuse to create.

No account, no network, no engine download — this module is pure data.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

# Copied from wehnix_app.py :: ENGINE_11_17_UNIVERSAL_VERSION and friends.
UNIVERSAL = "11.17-universal"
STEAM = "11.17-steam"
GPTK = "gptk"
DEFAULT_ENGINE_VERSION = UNIVERSAL

BOTTLE_ENV_TYPES = ("steam", "game", "application")

# Copied from ui/data/wehnix_engine_support.json :: engines + bottle_types.
# `existing_only` is the important one: those engines stay usable for bottles
# the user already has, but they must never be offered for a new one.
ENGINE_RULES: dict[str, dict] = {
    UNIVERSAL: {
        "label": "WehniX Engine 11.17 Universal",
        "allowed": ("game", "application"),
        "default": "game",
        "existing_only": False,
        "recommended": True,
        "note": (
            "Game and Application bottles. Runs the Windows program you choose, "
            "or an installed launcher."
        ),
    },
    STEAM: {
        "label": "WehniX Engine 11.17 Steam",
        "allowed": ("steam",),
        "default": "steam",
        "existing_only": False,
        "recommended": False,
        "note": "Steam-client bottles only. Game and Application bottles use Universal.",
    },
    "11.17": {
        "label": "WehniX Engine 11.17 Steam",
        "allowed": (),
        "default": None,
        "existing_only": True,
        "recommended": False,
        "note": "An earlier 11.17 build. Existing bottles keep working; new ones use Universal.",
    },
    "11.11": {
        "label": "WehniX Engine 11.11",
        "allowed": (),
        "default": None,
        "existing_only": True,
        "recommended": False,
        "note": "Kept for bottles you already have. New bottles use Universal.",
    },
    "11.0": {
        "label": "WehniX Engine 11.0",
        "allowed": (),
        "default": None,
        "existing_only": True,
        "recommended": False,
        "note": "Kept for bottles you already have. New bottles use Universal.",
    },
    GPTK: {
        "label": "Game Porting Toolkit 3.0",
        "allowed": (),
        "default": None,
        "existing_only": True,
        "recommended": False,
        "note": "Game Porting Toolkit is an Epic option in the app, not a bottle engine.",
    },
}

ENGINE_ORDER = (UNIVERSAL, STEAM, "11.17", "11.11", "11.0", GPTK)

# Renderers the desktop's bottle drawer can persist. DXVK is offered only when
# the Universal payload carries its capability marker (read by the app, not by
# this read-only CLI), so the CLI shows it as "in app only" rather than
# pretending it can verify the payload.
RENDERERS = ("dxmt", "d3dmetal", "dxvk")

# The only config.json keys the CLI is allowed to write. Everything else is the
# desktop app's business, and a half-written config is worse than no feature.
SAFE_SETTINGS = ("engine_version", "graphics_backend", "auto_check_updates")

SETTING_HELP = {
    "engine_version": "Engine new bottles use. Must be a bottle-capable engine.",
    "graphics_backend": "Default renderer: dxmt, d3dmetal, or dxvk where the engine allows it.",
    "auto_check_updates": "true or false — whether the app checks for updates on launch.",
}

_SUPPORT_CACHE: dict[str, dict] = {}


def support_data(path: Path | None = None) -> dict:
    """Optionally overlay the desktop's support table when it is reachable.

    A CLI install does not ship that file, so the table above is the fallback
    and the normal path. When the file *is* present (running from a checkout)
    it wins, which keeps the two front ends honest without a copy drifting.
    """
    if path is None:
        return {}
    key = str(path)
    if key not in _SUPPORT_CACHE:
        try:
            import json

            _SUPPORT_CACHE[key] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _SUPPORT_CACHE[key] = {}
    return _SUPPORT_CACHE[key]


# Copied from wehnix_app.py :: normalize_engine_version
def normalize_engine_version(version: object | None) -> str:
    value = str(version or "").strip()
    if value == GPTK:
        return GPTK
    # 4.0.5 stored the Steam 11.17 edition as "11.17"; keep those bottles on
    # Steam identity instead of silently calling them Universal.
    if value in {"11.17", "11.17-beta", "WehniX Engine 11.17 Steam"}:
        return STEAM
    if value not in ENGINE_RULES:
        return DEFAULT_ENGINE_VERSION
    return value


# Copied from wehnix_app.py :: engine_user_label
def engine_label(version: object | None) -> str:
    engine = normalize_engine_version(version)
    return str(ENGINE_RULES.get(engine, {}).get("label") or f"WehniX Engine {engine}")


# Copied from wehnix_app.py :: bottle_types_for_engine
def bottle_types_for_engine(version: object | None) -> dict:
    engine = normalize_engine_version(version)
    rule = ENGINE_RULES.get(engine) or {}
    allowed = tuple(kind for kind in (rule.get("allowed") or ()) if kind in BOTTLE_ENV_TYPES)
    default = rule.get("default")
    if default not in allowed:
        default = allowed[0] if allowed else None
    return {
        "engine": engine,
        "allowed": allowed,
        "default": default,
        "note": str(rule.get("note") or ""),
        "creatable": bool(allowed),
        "label": engine_label(engine),
    }


# Copied from wehnix_app.py :: bottle_env_type_supported
def bottle_env_type_supported(env_type: object, engine_version: object | None = None) -> bool:
    return str(env_type or "").strip().lower() in bottle_types_for_engine(engine_version)["allowed"]


# Copied from wehnix_app.py :: normalize_bottle_env_type
def normalize_bottle_env_type(env_type: object, engine_version: object | None = None) -> str:
    value = str(env_type or "").strip().lower()
    engine = normalize_engine_version(engine_version)
    if engine == UNIVERSAL:
        # A bottle created before the Game/Application split may still store
        # "steam"; it reads as Game so the same bottle can take an executable.
        return "application" if value == "application" else "game"
    if engine == STEAM:
        return "steam"
    if engine in ("11.11", "11.0"):
        return "application" if value == "application" else "game"
    if value == "application":
        return "application"
    if value == "game":
        return "game"
    return "steam"


# Copied from wehnix_app.py :: sanitize_bundle_name
def sanitize_bundle_name(name: object) -> str:
    safe_name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "-", str(name or ""))
    safe_name = re.sub(r"\s+", " ", safe_name)
    safe_name = safe_name.strip(". ")
    return safe_name or "Bottle"


# Copied from wehnix_app.py :: bottle_app_bundle_name
def bottle_bundle_name(safe_name: str, engine_version: object | None = None) -> str:
    name = str(safe_name or "Bottle")
    if normalize_engine_version(engine_version) in (UNIVERSAL, STEAM) and not name.endswith(".app"):
        return name + ".app"
    return name


# Copied from wehnix_app.py :: generate_unique_id
def generate_unique_id() -> str:
    return str(uuid.uuid4())


def engine_identity(filename: str) -> tuple[str, str]:
    """Identify an engine archive by name, without trusting the number alone.

    ``WehniX Engine 11.17 Universal.zip`` -> ``("11.17-universal", "Universal")``.
    A bare ``11.17`` is the older Steam build: the desktop treats "11.17" as
    Steam identity, and calling it Universal is the mistake that shipped the
    wrong engine to Epic. Only the word "universal" earns that label.
    """
    stem = str(filename or "")
    for suffix in (".tar.xz", ".tar.gz", ".tar.bz2", ".txz", ".tgz", ".zip"):
        if stem.lower().endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    text = stem.lower()
    if "gptk" in text or "game porting toolkit" in text:
        return GPTK, "GPTK"
    if "universal" in text:
        return UNIVERSAL, "Universal"
    if "steam" in text:
        return STEAM, "Steam"
    if re.search(r"\b11\.17\b", text):
        return STEAM, "Steam"
    for version in ("11.11", "11.0"):
        if re.search(rf"\b{re.escape(version)}\b", text):
            return version, "Universal"
    return "unknown", ""


def record_for_bottle(
    *,
    name: str,
    unique_id: str,
    bottle_path: Path,
    app_path: Path,
    c_drive_path: Path,
    engine_version: str,
    env_type: str,
    renderer: str = "dxmt",
    created_at: str = "",
) -> dict:
    """The exact shape ``list_engine_bottles_from_disk`` writes.

    A record the desktop cannot read is a bottle that disappears when the app
    rescans, so these keys are the contract, not a convenience.
    """
    return {
        "name": name,
        "unique_id": unique_id,
        "env_type": env_type,
        "path": str(bottle_path),
        "app_path": str(app_path),
        "c_drive_path": str(c_drive_path),
        "program_path": "/nothing.exe",
        "program_flags": "",
        "engine_version": normalize_engine_version(engine_version),
        "renderer": renderer,
        "metal_hud": False,
        "advanced": {"sync": "auto", "high_res": False},
        "created_at": created_at,
    }


# ─── Per-bottle capabilities ────────────────────────────────────────────────
# Copied from wehnix_app.py :: environment_capabilities and the four
# ``*_capabilities`` helpers. A renderer is offered only when the engine's own
# payload backs it; the display label never decides what a bottle can run.

UNIVERSAL_PREFIX = "universal-main"

# Copied from wehnix_app.py :: UNIVERSAL_SYNC_MODES and friends.
SYNC_MODES: dict[str, tuple[str, ...]] = {
    UNIVERSAL: ("none", "msync"),
    STEAM: ("none",),
    GPTK: ("default", "esync", "msync"),
    "11.11": ("default", "esync", "msync"),
    "11.0": ("default", "esync", "msync"),
}

RENDERER_LABELS = {
    "dxmt": "DXMT",
    "d3dmetal": "D3DMetal",
    "dxvk": "DXVK",
}


def normalize_runtime(value: object) -> str:
    """Map a detected runtime id or engine version onto one capability set."""
    text = str(value or "").strip()
    if text in (UNIVERSAL, STEAM, GPTK, "11.11", "11.0"):
        return text
    return normalize_engine_version(text)


def universal_dxvk_available(app_path: Path | None) -> bool:
    """Copied from wehnix_app.py :: wehnix_11_17_universal_dxvk_capability."""
    if app_path is None:
        return False
    marker = (
        Path(app_path)
        / "Contents"
        / "Resources"
        / "renderers"
        / "dxvk"
        / ".wx-capability"
    )
    try:
        text = marker.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return any(line.strip() == "renders=1" for line in text.splitlines())


def universal_d3dmetal_available(app_path: Path | None) -> bool:
    """Copied from wehnix_app.py :: universal_d3dmetal_payload."""
    if app_path is None:
        return False
    return (
        Path(app_path)
        / "Contents"
        / "Resources"
        / "renderers"
        / "d3dmetal"
        / "external"
        / "libd3dshared.dylib"
    ).is_file()


def bottle_capabilities(engine: object | None, app_path: Path | None = None) -> dict:
    """What this bottle may change, derived from the engine and its payload.

    Mirrors the desktop matrix: Universal is DXMT/D3DMetal plus capability-gated
    DXVK with none/msync; Steam is DXMT/D3DMetal with no sync choice; GPTK is
    D3DMetal with the legacy sync set; 11.11/11.0 are DXMT-only.
    """
    runtime = normalize_runtime(engine)
    if runtime == UNIVERSAL:
        d3dmetal = universal_d3dmetal_available(app_path)
        dxvk = universal_dxvk_available(app_path)
        renderers = {
            "dxmt": {
                "available": True,
                "reason": "The DXMT bridge ships with every Universal build.",
            },
            "d3dmetal": {
                "available": d3dmetal,
                "reason": (
                    "renderers/d3dmetal/external/libd3dshared.dylib is present."
                    if d3dmetal
                    else "renderers/d3dmetal payload is missing from this build."
                ),
            },
            "dxvk": {
                "available": dxvk,
                "reason": (
                    "renderers/dxvk/.wx-capability reports renders=1."
                    if dxvk
                    else "renderers/dxvk/.wx-capability is missing or does not report renders=1."
                ),
            },
        }
        return {
            "runtime": runtime,
            "renderers": renderers,
            "sync_modes": SYNC_MODES[UNIVERSAL],
            "metal_hud": True,
            "high_res": False,
            "program_locked": False,
            "note": "Universal runs the program you choose through its own target.",
        }
    if runtime == STEAM:
        return {
            "runtime": runtime,
            "renderers": {
                "dxmt": {"available": True, "reason": "DXMT is the Steam edition default."},
                "d3dmetal": {"available": True, "reason": "D3DMetal ships with the Steam edition."},
                "dxvk": {
                    "available": False,
                    "reason": "The Steam edition has no DXVK payload; Universal carries it.",
                },
            },
            "sync_modes": SYNC_MODES[STEAM],
            "metal_hud": True,
            "high_res": False,
            "program_locked": False,
            "note": "Steam bottles always launch Steam; sync is fixed to none.",
        }
    if runtime == GPTK:
        return {
            "runtime": runtime,
            "renderers": {
                "dxmt": {"available": False, "reason": "Game Porting Toolkit renders through D3DMetal."},
                "d3dmetal": {"available": True, "reason": "D3DMetal is the GPTK renderer."},
                "dxvk": {"available": False, "reason": "Game Porting Toolkit has no DXVK payload."},
            },
            "sync_modes": SYNC_MODES[GPTK],
            "metal_hud": True,
            "high_res": True,
            "program_locked": False,
            "note": "Game Porting Toolkit is an Epic option in the app.",
        }
    legacy = runtime if runtime in ("11.11", "11.0") else "11.11"
    return {
        "runtime": legacy,
        "renderers": {
            "dxmt": {"available": True, "reason": f"WehniX Engine {legacy} renders through DXMT."},
            "d3dmetal": {"available": False, "reason": f"WehniX Engine {legacy} has no D3DMetal payload."},
            "dxvk": {"available": False, "reason": f"WehniX Engine {legacy} has no DXVK payload."},
        },
        "sync_modes": SYNC_MODES[legacy],
        "metal_hud": True,
        "high_res": True,
        "program_locked": False,
        "note": "Kept for bottles you already have.",
    }


def normalize_bottle_renderer(value: object, engine: object | None) -> str:
    """Copied from the desktop's three renderer normalizers, by runtime."""
    runtime = normalize_runtime(engine)
    text = str(value or "").strip().lower()
    if runtime == UNIVERSAL:
        return text if text in ("dxmt", "d3dmetal", "dxvk") else "dxmt"
    if runtime == STEAM:
        return text if text in ("dxmt", "d3dmetal") else "dxmt"
    if runtime == GPTK:
        return "d3dmetal"
    return "dxmt"


def normalize_bottle_sync(value: object, engine: object | None) -> str:
    """Normalise a stored sync mode; writing uses the capability list."""
    runtime = normalize_runtime(engine)
    modes = SYNC_MODES.get(runtime, SYNC_MODES["11.0"])
    text = str(value or "").strip().lower()
    if text in modes:
        return text
    return modes[0]


def validate_setting(key: str, value: object) -> object:
    """Reject a config write the desktop would not understand.

    Returns the normalised value so the caller stores exactly one spelling, and
    raises ``ValueError`` with a sentence a person can act on.
    """
    if key not in SAFE_SETTINGS:
        raise ValueError(
            f"{key!r} is not a setting this CLI changes. It can change: "
            + ", ".join(SAFE_SETTINGS)
            + "."
        )
    if key == "auto_check_updates":
        text = str(value).strip().lower()
        if text in ("1", "true", "yes", "on"):
            return True
        if text in ("0", "false", "no", "off"):
            return False
        raise ValueError("auto_check_updates expects true or false.")
    if key == "engine_version":
        engine = str(value or "").strip()
        if engine not in ENGINE_RULES:
            raise ValueError(
                "engine_version must be one of: " + ", ".join(ENGINE_ORDER) + "."
            )
        if not bottle_types_for_engine(engine)["creatable"]:
            raise ValueError(
                f"{engine_label(engine)} cannot create bottles. "
                "New bottles use WehniX Engine 11.17 Universal."
            )
        return engine
    if key == "graphics_backend":
        renderer = str(value or "").strip().lower()
        if renderer not in RENDERERS:
            raise ValueError("graphics_backend must be one of: " + ", ".join(RENDERERS) + ".")
        return renderer
    raise ValueError(f"Unsupported setting: {key}")
