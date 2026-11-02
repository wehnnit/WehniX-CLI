"""Read and (carefully) write the state the desktop app already owns.

The CLI is a second front end onto ``~/Library/Application Support/WehniX``. It
never invents a parallel layout: it reads ``config.json``, ``bottles.json``,
``bottles/``, ``Engine/`` and ``logs/wehniX.log`` exactly as the app writes them,
and its only additions are ``cli/`` (preferences and trash) and ``logs/`` when
missing. Create a bottle in the terminal and the window shows it; the other way
round too.
"""

from __future__ import annotations

import json
import os
import plistlib
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from . import contract
from .models import Bottle, EngineArtifact, Game, Snapshot

APP_DIR_NAME = "WehniX"
ENV_OVERRIDE = "WEHNIX_CLI_STATE_DIR"
BOTTLES_JSON = "bottles.json"
CONFIG_JSON = "config.json"
ENGINE_DIR = "Engine"
LOG_RELATIVE = Path("logs") / "wehniX.log"
ARCHIVE_SUFFIXES = (".zip", ".tar.xz", ".txz", ".tar.gz", ".tgz", ".tar.bz2")

# Anything smaller than this is not a full engine build. Universal's real
# archive is ~0.92 GiB, so a 1 GiB threshold would call a healthy install
# suspicious — the number has to come from the payload, not from a guess.
ENGINE_MIN_BYTES = 100 * 1024 * 1024


def default_root() -> Path:
    return Path.home() / "Library" / "Application Support" / APP_DIR_NAME


def state_root() -> Path:
    """Where the app keeps its data, honouring an override for tests/screenshots."""
    override = os.environ.get(ENV_OVERRIDE, "").strip()
    if override:
        return Path(override).expanduser()
    return default_root()


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def read_json(path: Path) -> dict:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def read_plist(path: Path) -> dict:
    try:
        with path.open("rb") as handle:
            loaded = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException, ValueError, TypeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def file_signature(path: Path) -> tuple[int, int] | None:
    """(mtime_ns, size) — enough to notice someone else edited the file."""
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


def directory_size(path: Path, timeout: float = 20.0) -> int | None:
    """Bytes used by *path*, via du. Walking a 4 GB bottle in Python is slower."""
    try:
        completed = subprocess.run(
            ["/usr/bin/du", "-sk", str(path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        if completed.returncode == 0 and completed.stdout.strip():
            return int(completed.stdout.split()[0]) * 1024
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return None


def engine_identity(filename: str) -> tuple[str, str]:
    return contract.engine_identity(filename)


def find_bottle_app(entry: Path) -> Path | None:
    """The ``.app`` inside a bottle folder, for flat and nested layouts alike."""
    if (entry / "Contents" / "Info.plist").is_file():
        return entry
    try:
        children = sorted(entry.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return None
    for child in children:
        if child.suffix == ".app" and (child / "Contents" / "Info.plist").is_file():
            return child
    # One level deeper covers an archive root left inside the bottle folder.
    for child in children:
        if not child.is_dir():
            continue
        try:
            grand_children = sorted(child.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            continue
        for grand in grand_children:
            if grand.suffix == ".app" and (grand / "Contents" / "Info.plist").is_file():
                return grand
    return None


def record_index(records: list[dict]) -> dict[str, dict]:
    """Index records by every identifier a writer might have used."""
    index: dict[str, dict] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        for key in ("unique_id", "id", "name", "path", "app_path"):
            value = str(record.get(key) or "").strip()
            if not value:
                continue
            index.setdefault(value, record)
            index.setdefault(Path(value).name, record)
            if key == "app_path":
                # bottles/<id>/<Name>.app — the folder is the unique_id.
                index.setdefault(Path(value).parent.name, record)
    return index


def _derive_edition(info: dict, engine: str) -> str:
    explicit = str(info.get("WehniXEngineEdition") or "").strip()
    if explicit:
        return explicit.capitalize()
    if engine == contract.UNIVERSAL:
        return "Universal"
    if engine == contract.STEAM:
        return "Steam"
    if engine == contract.GPTK:
        return "GPTK"
    return ""


def _bottle_from(entry: Path, record: dict, renderer: str) -> Bottle:
    """One bottle, with its settings read from the engine first.

    Copied from wehnix_app.py :: list_engine_bottles_from_disk: the registry is
    a cache, so the bottle's own launch config / plist wins whenever it can be
    read. Doc: bottles.json is only the fallback for a bundle that has no
    readable settings file.
    """
    app_path = find_bottle_app(entry)
    info = read_plist(app_path / "Contents" / "Info.plist") if app_path else {}
    kind = runtime_kind(app_path)

    raw_engine = str(info.get("WehniXEngineVersion") or record.get("engine_version") or "").strip()
    if kind:
        engine = kind
    elif raw_engine:
        engine = contract.normalize_engine_version(raw_engine)
    else:
        engine = "unknown"

    raw_env = str(info.get("WehniXEnvType") or record.get("env_type") or "").strip()
    if not raw_env and kind == contract.STEAM:
        raw_env = "steam"
    env_type = contract.normalize_bottle_env_type(raw_env, engine) if (raw_env or engine != "unknown") else ""

    advanced = record.get("advanced") if isinstance(record.get("advanced"), dict) else {}
    settings = read_bottle_app_settings(app_path) if app_path else {}
    source = str(settings.get("source") or ("record" if record else "none"))
    live = source == "app"
    try:
        modified = entry.stat().st_mtime
    except OSError:
        modified = 0.0
    recorded_size = record.get("size")
    return Bottle(
        name=(app_path.stem if app_path else "") or str(record.get("name") or "") or entry.stem,
        path=entry,
        unique_id=str(record.get("unique_id") or record.get("id") or entry.name),
        app_path=app_path,
        engine=engine,
        edition=_derive_edition(info, engine),
        env_type=env_type,
        renderer=(
            str(settings.get("renderer") or "")
            if live
            else str(record.get("renderer") or renderer or "")
        ),
        program_path=(
            str(settings.get("program_path") or "")
            if live
            else str(record.get("program_path") or "")
        ),
        program_flags=(
            str(settings.get("program_flags") or "")
            if live
            else str(record.get("program_flags") or "")
        ),
        metal_hud=(
            bool(settings.get("metal_hud"))
            if live
            else bool(record.get("metal_hud"))
        ),
        sync=(
            str(settings.get("sync") or "auto")
            if live
            else str(advanced.get("sync") or "auto")
        ),
        high_res=(
            bool(settings.get("high_res"))
            if live
            else bool(advanced.get("high_res"))
        ),
        modified=modified,
        size=int(recorded_size) if isinstance(recorded_size, int) else None,
        in_registry=bool(record),
        runtime=kind,
        settings_source=source,
        dxvk_available=settings.get("dxvk_available"),
        settings_error=str(settings.get("error") or ""),
    )


def scan_bottles(root: Path, with_sizes: bool = False) -> list[Bottle]:
    bottles_dir = root / "bottles"
    if not bottles_dir.is_dir():
        return []
    records = record_index((read_json(root / BOTTLES_JSON).get("bottles") or []))
    default_renderer = str((read_json(root / CONFIG_JSON).get("settings") or {}).get("graphics_backend") or "")

    found: list[Bottle] = []
    try:
        entries = sorted(bottles_dir.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return []
    for entry in entries:
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        # An interrupted create leaves `.creating-<id>` behind; it is not a bottle.
        record = (
            records.get(entry.name)
            or records.get(str(entry))
            or records.get(entry.stem)
            or {}
        )
        bottle = _bottle_from(entry, record, default_renderer)
        if bottle.app_path is None and not record:
            continue
        if with_sizes and bottle.size is None:
            bottle.size = directory_size(entry)
        found.append(bottle)
    found.sort(key=lambda b: b.modified, reverse=True)
    return found


def scan_engines(root: Path) -> list[EngineArtifact]:
    engine_dir = root / ENGINE_DIR
    if not engine_dir.is_dir():
        return []
    engines: list[EngineArtifact] = []
    try:
        archives = sorted(engine_dir.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return []
    for archive in archives:
        if not archive.is_file() or archive.name.startswith("."):
            continue
        if not archive.name.lower().endswith(ARCHIVE_SUFFIXES):
            continue
        if ".previous" in archive.name or archive.name.endswith((".tmp", ".download", ".part")):
            continue
        version, edition = contract.engine_identity(archive.name)
        try:
            size = archive.stat().st_size
        except OSError:
            size = 0
        rule = contract.bottle_types_for_engine(version)
        engines.append(
            EngineArtifact(
                name=archive.name,
                path=archive,
                size=size,
                version=version,
                edition=edition,
                label=contract.engine_label(version),
                creatable=rule["creatable"],
                note=rule["note"],
                healthy=size >= ENGINE_MIN_BYTES,
            )
        )
    return engines


_MANIFEST = re.compile(r'"(\w+)"\s+"([^"]*)"')


def _parse_acf(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    values: dict[str, str] = {}
    for key, value in _MANIFEST.findall(text):
        values.setdefault(key, value)
    return values


def scan_games(bottles: list[Bottle]) -> list[Game]:
    """Steam games inside bottles, read from the appmanifests Steam writes.

    Read-only, and deliberately not a marketplaces feature: Epic titles are
    managed by the desktop app and are not guessed at here.
    """
    games: dict[tuple[str, str], Game] = {}
    for bottle in bottles:
        base = bottle.app_path or bottle.path
        prefixes = base / "Contents" / "Resources" / "state" / "prefixes"
        roots = [prefixes] if prefixes.is_dir() else [base]
        for root in roots:
            try:
                manifests = list(root.glob("**/steamapps/appmanifest_*.acf"))
            except OSError:
                continue
            for manifest in manifests:
                values = _parse_acf(manifest)
                appid = str(values.get("appid") or "").strip()
                title = str(values.get("name") or "").strip()
                if not appid or not title:
                    continue
                games.setdefault(
                    (bottle.unique_id or bottle.name, appid),
                    Game(title=title, appid=appid, bottle=bottle.name, path=manifest.parent),
                )
    return sorted(games.values(), key=lambda game: game.title.lower())


def read_snapshot(with_sizes: bool = False, with_games: bool = True) -> Snapshot:
    """One consistent read of everything the UI shows."""
    root = state_root()
    snapshot = Snapshot(root=root, exists=root.is_dir())
    if not snapshot.exists:
        snapshot.error = f"{root} does not exist yet — run WehniX once to create it."
        return snapshot

    snapshot.config = read_json(root / CONFIG_JSON)
    snapshot.bottles = scan_bottles(root, with_sizes=with_sizes)
    snapshot.engines = scan_engines(root)
    log = root / LOG_RELATIVE
    snapshot.log_path = log if log.is_file() else None
    if with_games:
        snapshot.games = scan_games(snapshot.bottles)
    return snapshot


# ---------------------------------------------------------------------------
# Writing. Additive only, and always inside the app's own tree.
# ---------------------------------------------------------------------------


def write_json_atomic(path: Path, data: dict, indent: int = 2) -> None:
    """Write beside the target, fsync, then replace — never a half file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=indent)
        handle.write("\n")
        handle.flush()
        try:
            os.fsync(handle.fileno())
        except OSError:
            pass
    os.replace(temp, path)


def load_records(root: Path | None = None) -> list[dict]:
    data = read_json((root or state_root()) / BOTTLES_JSON)
    records = data.get("bottles")
    if not isinstance(records, list):
        return []
    return [record for record in records if isinstance(record, dict)]


def save_records(records: list[dict], root: Path | None = None) -> None:
    write_json_atomic((root or state_root()) / BOTTLES_JSON, {"bottles": records}, indent=4)


def cli_dir(root: Path | None = None, create: bool = True) -> Path:
    path = (root or state_root()) / "cli"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def prepare_state_dir(root: Path | None = None, create_root: bool = False) -> dict:
    """Make the tree usable by the CLI without changing anything the app owns.

    ``create_root=False`` never creates the app's data directory: a half-made
    WehniX folder would make the app think it had been set up. When the folder
    does exist, the CLI only adds ``cli/`` and ``logs/``.
    """
    root = Path(root) if root is not None else state_root()
    created: list[str] = []
    if not root.is_dir():
        if not create_root:
            return {"root": root, "created": [], "missing": True}
        root.mkdir(parents=True, exist_ok=True)
        created.append(str(root))
    for relative in ("cli", "logs"):
        target = root / relative
        if not target.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            created.append(str(target))
    marker = root / "cli" / "config.json"
    if not marker.exists():
        write_json_atomic(marker, {"schema": 1, "created_by": "WehniX CLI"})
        created.append(str(marker))
    return {"root": root, "created": created, "missing": False}


def trash_dir(root: Path | None = None) -> Path:
    path = cli_dir(root) / "trash"
    path.mkdir(parents=True, exist_ok=True)
    return path


def move_to_trash(path: Path, root: Path | None = None) -> Path:
    """Remove a bottle without destroying it.

    Uses the Finder Trash when send2trash is available (it is a desktop-app
    dependency, not ours), otherwise moves it into ``cli/trash`` on the same
    volume, which is instant and reversible.
    """
    try:
        from send2trash import send2trash  # type: ignore

        send2trash(str(path))
        return Path.home() / ".Trash"
    except Exception:
        pass

    destination = trash_dir(root) / path.name
    counter = 1
    while destination.exists():
        destination = trash_dir(root) / f"{path.name}.{counter}"
        counter += 1
    shutil.move(str(path), str(destination))
    return destination


# ---------------------------------------------------------------------------
# Process guard
# ---------------------------------------------------------------------------


def _default_runner(command: list[str]) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return completed.returncode, completed.stdout or ""


APP_BINARY_SUFFIX = "/wehniX.app/contents/macos/wehniX".lower()


def app_is_running(runner=None) -> bool:
    """Whether the desktop app is open, so writes can be refused instead of raced.

    ``pgrep -f`` happily matches the shell that is running ``pgrep -f`` — the
    pattern appears in its own command line. So a match only counts when the
    process's *executable* is the app binary inside ``WehniX.app``, which also
    keeps this CLI's own arguments from ever looking like the app.
    """
    run = runner or _default_runner

    def call(command):
        # The guard is advisory: a missing ps or pgrep must never break a write.
        try:
            return run(command)
        except Exception:
            return 1, ""

    pids: list[str] = []
    for arguments in (["-x", "WehniX"], ["-f", "WehniX.app/Contents/MacOS/WehniX"]):
        code, out = call(["/usr/bin/pgrep", *arguments])
        if code == 0 and out.strip():
            pids.extend(out.split())
        if pids:
            break

    own_pid = str(os.getpid())
    for pid in pids:
        if not pid.isdigit() or pid == own_pid:
            continue
        _, command = call(["/bin/ps", "-o", "command=", "-p", pid])
        executable = command.strip().split(" ", 1)[0].strip('"').lower()
        if executable.endswith(APP_BINARY_SUFFIX):
            return True
    return False


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def timestamp_for(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return time.time()


# ---------------------------------------------------------------------------
# Bottle settings: the files the engine actually launches from
# ---------------------------------------------------------------------------
# Copied from wehnix_app.py :: get_bottle_app_settings and the runtime table.
# bottles.json is a cache; these files are the truth.

UNIVERSAL_PREFIX = contract.UNIVERSAL_PREFIX
LAUNCH_TOOL_TIMEOUT_SECONDS = 20


def runtime_kind(app_path: Path | None) -> str:
    """Identify the engine from the bundle layout.

    Copied from wehnix_app.py :: is_wehnix_11_17_universal_runtime,
    is_wehnix_11_17_steam_runtime, is_wehnix_11_11_runtime and is_gptk_runtime:
    the 11.11 tree is checked before 11.17 so a bundle carrying both is not
    misread, and a display label is never consulted.
    """
    if app_path is None:
        return ""
    app_path = Path(app_path)
    resources = app_path / "Contents" / "Resources"
    if (app_path / ".gptk-engine").exists():
        return contract.GPTK
    if (resources / "engine" / "wine" / "tools" / "wine" / "wine").is_file():
        return "11.11"
    if not (resources / "wine" / "bin" / "wine").is_file():
        return _legacy_runtime(app_path)
    template = resources / "prefix-template" / "drive_c"
    shipped = resources / "state" / "prefixes" / UNIVERSAL_PREFIX / "drive_c"
    if (resources / "UNIVERSAL.md").is_file():
        return contract.UNIVERSAL
    if template.is_dir():
        return contract.STEAM
    if shipped.is_dir() or (resources / "scripts" / "wx-launch-profile.sh").is_file():
        return contract.UNIVERSAL
    return contract.STEAM


def _legacy_runtime(app_path: Path) -> str:
    info = read_plist(app_path / "Contents" / "Info.plist")
    raw = str(info.get("WehniXEngineVersion") or "").strip().lower()
    if raw in ("11.0", "11.11", "gptk"):
        return raw
    # A stripped bundle can still name its engine in the plist even when its
    # payload is unreadable; that is enough to read the right settings file.
    if raw in (contract.UNIVERSAL, "universal"):
        return contract.UNIVERSAL
    if raw in (contract.STEAM, "11.17", "steam"):
        return contract.STEAM
    if (app_path / "Contents" / "MacOS" / "wehnix-engine-launch").is_file():
        return "11.0"
    return ""


def launch_config_path(app_path: Path, runtime: str | None = None) -> Path:
    """Copied from wehnix_app.py :: _wehnix_11_17_config_path / 11_11."""
    app_path = Path(app_path)
    runtime = runtime or runtime_kind(app_path)
    resources = app_path / "Contents" / "Resources"
    if runtime == "11.11":
        return resources / "engine" / "wehnix.json"
    return resources / "wehnix.json"


def default_launch_config() -> dict:
    """Copied from wehnix_app.py :: _default_wehnix_11_launch_config."""
    return {
        "launch": {"exePath": "nothing.exe", "arguments": []},
        "renderer": {"active": "dxmt", "enabled": True},
        "graphics": {"metalHud": False, "retina": False},
        "sync": {"mode": "default"},
    }


def read_launch_config(app_path: Path, runtime: str | None = None) -> dict:
    """Defaults filled in, so a partial file still yields a complete config."""
    config = default_launch_config()
    loaded = read_json(launch_config_path(app_path, runtime))
    for block, defaults in config.items():
        value = loaded.get(block)
        if isinstance(value, dict):
            defaults.update(value)
    for key, value in loaded.items():
        if key not in config:
            config[key] = value
    return config


def universal_prefix_name(app_path: Path) -> str:
    """The prefix this Universal build launches, if it kept one."""
    shipped = Path(app_path) / "Contents" / "Resources" / "state" / "prefixes"
    if (shipped / UNIVERSAL_PREFIX / "drive_c").is_dir():
        return UNIVERSAL_PREFIX
    try:
        candidates = sorted(p.name for p in shipped.iterdir() if (p / "drive_c").is_dir())
    except OSError:
        candidates = []
    return candidates[0] if candidates else UNIVERSAL_PREFIX


def launch_environment(app_path: Path) -> dict:
    """The environment the 11.17 scripts expect, minus anything host-Python.

    Copied from wehnix_app.py :: wx_11_17_launch_env. Never raises.
    """
    app_path = Path(app_path)
    resources = app_path / "Contents" / "Resources"
    prefix_name = universal_prefix_name(app_path)
    prefix = resources / "state" / "prefixes" / prefix_name
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in ("PYTHONHOME", "PYTHONPATH", "PYTHONEXECUTABLE", "PYTHONSTARTUP")
    }
    env["WX_BUNDLE_ROOT"] = str(resources)
    env["WX_LAUNCHER_PREFIX"] = prefix_name
    env["WINEPREFIX"] = str(prefix)
    env["WX_WINE_HOME"] = str(resources / "wine")
    env["WX_WINE_VIEW"] = str(resources / "wine")
    icd = resources / "wine" / "share" / "vulkan" / "icd.d" / "MoltenVK_icd.json"
    if icd.is_file():
        env["VK_ICD_FILENAMES"] = str(icd)
        env["VK_DRIVER_FILES"] = str(icd)
    entries = [str(resources / "wine" / "bin"), str(resources / "bin")]
    existing = [part for part in env.get("PATH", "").split(os.pathsep) if part]
    env["PATH"] = os.pathsep.join(entries + [part for part in existing if part not in entries])
    return env


def universal_shared_target(app_path: Path) -> dict:
    """Read Universal's shared target through its own tool.

    Copied from wehnix_app.py :: universal_shared_target. A missing tool is a
    readable failure, not an exception: the caller falls back to the JSON.
    """
    app_path = Path(app_path)
    tool = app_path / "Contents" / "Resources" / "bin" / "wx-target"
    if not tool.is_file():
        return {
            "success": False,
            "target": "",
            "error": "bin/wx-target is missing from this Universal build.",
        }
    command = ["/bin/bash", str(tool), "get", "--prefix", universal_prefix_name(app_path)]
    try:
        completed = subprocess.run(
            command,
            cwd=str(app_path),
            env=launch_environment(app_path),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=LAUNCH_TOOL_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"success": False, "target": "", "error": f"wx-target could not run: {exc}"}
    target = (completed.stdout or "").strip()
    if completed.returncode != 0:
        detail = (completed.stderr or "").strip() or f"exit {completed.returncode}"
        return {"success": False, "target": target, "error": f"wx-target get failed: {detail}"}
    return {"success": True, "target": target, "error": ""}


def set_universal_shared_target(app_path: Path, target: str) -> dict:
    """Write Universal's shared target. The desktop does this before exePath."""
    app_path = Path(app_path)
    tool = app_path / "Contents" / "Resources" / "bin" / "wx-target"
    if not tool.is_file():
        return {
            "success": False,
            "error": "bin/wx-target is missing, so the shared target cannot be set.",
        }
    # Copied from wehnix_app.py :: set_universal_shared_target: an empty choice
    # means the engine's bundled no-op, and WX_TARGET must never be blank.
    value = str(target or "").strip() or "nothing.exe"
    command = [
        "/bin/bash",
        str(tool),
        "set",
        value,
        "--prefix",
        universal_prefix_name(app_path),
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=str(app_path),
            env=launch_environment(app_path),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=LAUNCH_TOOL_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"success": False, "error": f"wx-target could not run: {exc}"}
    if completed.returncode != 0:
        detail = (completed.stderr or "").strip() or f"exit {completed.returncode}"
        return {"success": False, "error": f"wx-target set failed: {detail}"}
    return {"success": True, "error": ""}


def _plist_renderer(plist: dict, runtime: str) -> str:
    """Copied from wehnix_app.py :: get_renderer_from_plist."""
    # Desktop order: DXMT first, then DXVK, then D3DMetal.
    for name, key in (("dxmt", "DXMT"), ("dxvk", "DXVK"), ("d3dmetal", "D3DMETAL")):
        try:
            enabled = int(plist.get(key) or 0) == 1
        except (TypeError, ValueError):
            enabled = str(plist.get(key) or "").strip() == "1"
        if enabled:
            return contract.normalize_bottle_renderer(name, runtime)
    return contract.normalize_bottle_renderer("", runtime)


def _plist_sync(plist: dict) -> str:
    if str(plist.get("WINEMSYNC") or "").strip() == "1":
        return "msync"
    if str(plist.get("WINEESYNC") or "").strip() == "1":
        return "esync"
    return "default"


def windows_program_path(app_path: Path, selected: str) -> str:
    """Map a macOS path onto the bottle's C: drive, or Z: when it is outside.

    Copied from wehnix_app.py :: mac_exe_path_to_windows_path. A path that is
    already a Windows path is returned untouched.
    """
    text = str(selected or "").strip()
    if not text or not text.startswith("/"):
        return text
    app_path = Path(app_path)
    resources = app_path / "Contents" / "Resources"
    candidates = [
        resources / "state" / "prefixes" / universal_prefix_name(app_path) / "drive_c",
        resources / "prefix-template" / "drive_c",
        resources / "engine" / "drive_c",
    ]
    c_drive = next((path for path in candidates if path.is_dir()), candidates[0])
    try:
        relative = Path(text).expanduser().resolve().relative_to(c_drive.resolve())
    except (ValueError, OSError):
        return "Z:\\" + "\\".join(part for part in text.split("/") if part)
    return "C:\\" + "\\".join(relative.parts)


def read_bottle_app_settings(app_path: Path | None) -> dict:
    """Everything one bottle's engine files say about how it launches.

    Read-only and exception-free: the UI runs this inside a worker, and a
    malformed config must become a readable ``error`` with safe defaults.
    """
    result = {
        "runtime": "",
        "renderer": "dxmt",
        "program_path": "",
        "program_flags": "",
        "metal_hud": False,
        "sync": "default",
        "high_res": False,
        "dxvk_available": False,
        "source": "none",
        "error": "",
    }
    if app_path is None:
        result["error"] = "This bottle has no app bundle to read."
        return result
    app_path = Path(app_path)
    runtime = runtime_kind(app_path)
    result["runtime"] = runtime
    if not runtime:
        result["source"] = "error"
        result["error"] = "Could not identify the engine inside this bundle."
        return result

    capabilities = contract.bottle_capabilities(runtime, app_path)
    result["dxvk_available"] = bool(capabilities["renderers"]["dxvk"]["available"])
    try:
        if runtime in (contract.UNIVERSAL, contract.STEAM, "11.11"):
            path = launch_config_path(app_path, runtime)
            if not path.is_file():
                result["source"] = "default"
                return result
            config = read_launch_config(app_path, runtime)
            launch = config.get("launch") if isinstance(config.get("launch"), dict) else {}
            renderer = config.get("renderer") if isinstance(config.get("renderer"), dict) else {}
            graphics = config.get("graphics") if isinstance(config.get("graphics"), dict) else {}
            sync = config.get("sync") if isinstance(config.get("sync"), dict) else {}
            arguments = launch.get("arguments")
            if not isinstance(arguments, list):
                arguments = []
            result.update(
                {
                    "renderer": contract.normalize_bottle_renderer(
                        renderer.get("active"), runtime
                    ),
                    "program_path": str(launch.get("exePath") or "").strip(),
                    "program_flags": " ".join(str(item) for item in arguments if str(item)),
                    "metal_hud": bool(graphics.get("metalHud")),
                    "sync": contract.normalize_bottle_sync(sync.get("mode"), runtime),
                    "high_res": bool(graphics.get("retina")) if runtime == "11.11" else False,
                    "source": "app",
                }
            )
            if runtime == contract.UNIVERSAL:
                shared = universal_shared_target(app_path)
                if shared["success"] and shared["target"]:
                    result["program_path"] = shared["target"]
                elif shared["error"]:
                    result["error"] = shared["error"]
            return result

        plist = read_plist(app_path / "Contents" / "Info.plist")
        if not plist:
            result["source"] = "default"
            result["renderer"] = contract.normalize_bottle_renderer("", runtime)
            return result
        result.update(
            {
                "renderer": _plist_renderer(plist, runtime),
                "program_path": str(plist.get("Program Name and Path") or "").strip(),
                "program_flags": str(plist.get("Program Flags") or "").strip(),
                "metal_hud": str(plist.get("METAL_HUD") or "").strip() == "1",
                "sync": _plist_sync(plist),
                "high_res": str(plist.get("RetinaMode") or "").strip() == "1",
                "source": "app",
            }
        )
        return result
    except Exception as exc:  # a broken file must not become a traceback
        result["source"] = "error"
        result["error"] = f"Could not read this bottle's settings: {exc}"
        return result
