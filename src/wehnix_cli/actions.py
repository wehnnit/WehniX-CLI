"""The things the CLI can actually do, and the guards around them.

Every destructive path has the same shape: refuse while the desktop app is
open, stage the work, validate it, and only then put it where the app will look.
A delete moves a bottle to the Trash instead of unlinking four gigabytes of
prefix, so a mistake is reversible.
"""

from __future__ import annotations

import os
import plistlib
import shlex
import shutil
import stat
import subprocess
import tarfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from . import contract
from .models import Bottle, EngineArtifact
from .state import (
    app_is_running,
    file_signature,
    iso_now,
    launch_config_path,
    windows_program_path,
    load_records,
    move_to_trash,
    read_bottle_app_settings,
    read_json,
    read_launch_config,
    read_plist,
    save_records,
    set_universal_shared_target,
    state_root,
    write_json_atomic,
)

CODESIGN_TIMEOUT_SECONDS = 900
EXTRACT_TIMEOUT_SECONDS = 1800


class ActionError(RuntimeError):
    """Something the user should read, not a traceback."""


@dataclass
class CreationResult:
    bottle_path: Path
    app_path: Path
    unique_id: str
    warnings: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.app_path.stem


def _run(command: list[str], timeout: float = 600.0) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        return completed.returncode, (completed.stderr or completed.stdout or "").strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)


# ---------------------------------------------------------------------------
# Opening things
# ---------------------------------------------------------------------------


def reveal(path: Path) -> None:
    """Show the item in Finder."""
    if not path.exists():
        raise ActionError(f"{path} no longer exists")
    code, detail = _run(["/usr/bin/open", "-R", str(path)], timeout=20)
    if code != 0:
        raise ActionError(f"Finder would not open {path.name}: {detail or 'unknown error'}")


def open_path(path: Path) -> None:
    if not path.exists():
        raise ActionError(f"{path} no longer exists")
    code, detail = _run(["/usr/bin/open", str(path)], timeout=30)
    if code != 0:
        raise ActionError(f"macOS would not open {path.name}: {detail or 'unknown error'}")


def open_desktop_app() -> None:
    code, _ = _run(["/usr/bin/open", "-a", "WehniX"], timeout=30)
    if code != 0:
        raise ActionError("The WehniX app is not in /Applications. Drag it there first.")


# ---------------------------------------------------------------------------
# Deleting
# ---------------------------------------------------------------------------


def _record_matches(record: dict, bottle: Bottle) -> bool:
    """Match a record by the identifiers desktop and CLI can each have written."""
    identifiers = {
        str(record.get("unique_id") or "").strip(),
        str(record.get("id") or "").strip(),
    } - {""}
    if bottle.unique_id and bottle.unique_id in identifiers:
        return True
    if bottle.path.name in identifiers:
        return True
    for key in ("path", "app_path"):
        value = str(record.get(key) or "").strip()
        if not value:
            continue
        if value == str(bottle.path):
            return True
        candidate = Path(value)
        if candidate.name == bottle.path.name:
            return True
        try:
            if candidate.resolve() == bottle.path.resolve():
                return True
        except OSError:
            continue
    return False


def forget_record(bottle: Bottle, root: Path | None = None) -> bool:
    """Drop the bottle's record, leaving every other record byte-identical."""
    root = Path(root) if root is not None else state_root()
    records = load_records(root)
    kept = [record for record in records if not _record_matches(record, bottle)]
    if len(kept) == len(records):
        return False
    save_records(kept, root)
    return True


def delete_bottle(bottle: Bottle, root: Path | None = None) -> Path:
    """Move a bottle to the Trash, refusing while the app is running."""
    root = Path(root) if root is not None else state_root()
    if app_is_running():
        raise ActionError("Quit WehniX first — it is open and would fight this change.")
    bottle_path = bottle.path
    if not bottle_path.exists():
        raise ActionError(f"{bottle_path} no longer exists")
    bottles_dir = (root / "bottles").resolve()
    try:
        resolved = bottle_path.resolve()
    except OSError as exc:
        raise ActionError(f"Could not resolve {bottle_path}: {exc}") from exc
    if resolved == bottles_dir or bottles_dir not in resolved.parents:
        raise ActionError(
            f"{bottle_path} is not inside {bottles_dir}, so the CLI will not move it."
        )
    if resolved == root.resolve():
        raise ActionError("That is the WehniX data folder, not a bottle.")

    destination = move_to_trash(bottle_path, root)
    forget_record(bottle, root)
    return destination


# ---------------------------------------------------------------------------
# Creating
# ---------------------------------------------------------------------------


def _safe_member_path(name: str, destination: Path) -> Path:
    member = Path(name)
    if member.is_absolute() or ".." in member.parts:
        raise ActionError(f"The engine archive contains an unsafe path: {name}")
    target = destination / member
    normal = Path(os.path.normpath(str(target)))
    root = Path(os.path.normpath(str(destination)))
    if normal != root and root not in normal.parents:
        raise ActionError(f"The engine archive escapes its folder: {name}")
    return target


def _check_link(link: str, target: Path, destination: Path) -> None:
    """A link may point anywhere inside the extraction folder, nowhere else."""
    if not link:
        raise ActionError(f"Empty link target beside {target}")
    link_path = Path(link)
    if link_path.is_absolute():
        raise ActionError(f"The engine archive links outside its folder: {link}")
    joined = Path(os.path.normpath(str(target.parent / link_path)))
    root = Path(os.path.normpath(str(destination)))
    if joined != root and root not in joined.parents:
        raise ActionError(f"The engine archive links outside its folder: {link}")


MAX_MEMBERS = 250_000
MAX_EXPANDED_BYTES = 40 * 1024**3


def _extract_zip(archive: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive) as bundle:
        infos = bundle.infolist()
        if len(infos) > MAX_MEMBERS:
            raise ActionError(f"The engine archive has too many files ({len(infos)}).")
        if sum(info.file_size for info in infos) > MAX_EXPANDED_BYTES:
            raise ActionError("The engine archive expands to an implausible size.")
        for info in infos:
            name = info.filename
            if name.startswith("__MACOSX/") or "/__MACOSX/" in name:
                continue
            target = _safe_member_path(name, destination)
            mode = info.external_attr >> 16
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if stat.S_ISLNK(mode):
                _check_link(bundle.read(info).decode("utf-8", "surrogateescape"), target, destination)
                if target.is_symlink() or target.exists():
                    target.unlink()
                target.symlink_to(bundle.read(info).decode("utf-8", "surrogateescape"))
                continue
            if target.is_symlink():
                target.unlink()
            with bundle.open(info) as source, target.open("wb") as handle:
                shutil.copyfileobj(source, handle)
            if mode & 0o777:
                os.chmod(target, mode & 0o777)


def _extract_tar(archive: Path, destination: Path) -> None:
    with tarfile.open(archive) as bundle:
        members = bundle.getmembers()
        if len(members) > MAX_MEMBERS:
            raise ActionError(f"The engine archive has too many files ({len(members)}).")
        if sum(member.size for member in members) > MAX_EXPANDED_BYTES:
            raise ActionError("The engine archive expands to an implausible size.")
        for member in members:
            if member.name.startswith("./"):
                member.name = member.name[2:]
            target = _safe_member_path(member.name, destination)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if member.issym():
                _check_link(member.linkname, target, destination)
                if target.is_symlink() or target.exists():
                    target.unlink()
                target.symlink_to(member.linkname)
                continue
            if member.islnk():
                source = _safe_member_path(member.linkname, destination)
                if not source.is_file():
                    raise ActionError(f"The engine archive links to a missing file: {member.linkname}")
                shutil.copy2(source, target)
                continue
            if not member.isfile():
                continue
            extracted = bundle.extractfile(member)
            if extracted is None:
                continue
            with extracted, target.open("wb") as handle:
                shutil.copyfileobj(extracted, handle)
            if member.mode & 0o777:
                os.chmod(target, member.mode & 0o777)


def extract_archive(archive: Path, destination: Path) -> None:
    """Extract an engine archive, preserving modes and safe symlinks."""
    if not archive.is_file():
        raise ActionError(f"Engine archive missing: {archive}")
    suffix = archive.name.lower()
    try:
        if suffix.endswith(".zip"):
            _extract_zip(archive, destination)
        elif suffix.endswith((".tar.xz", ".txz", ".tar.gz", ".tgz", ".tar.bz2")):
            _extract_tar(archive, destination)
        else:
            raise ActionError(f"{archive.name} is not an engine archive this CLI can unpack.")
    except (zipfile.BadZipFile, tarfile.TarError, OSError, EOFError) as exc:
        raise ActionError(f"Could not unpack {archive.name}: {exc}") from exc


def find_app_bundle(staging: Path) -> Path | None:
    """The shallowest ``.app`` with an Info.plist — the engine, not a helper."""
    candidates: list[Path] = []
    try:
        for child in staging.iterdir():
            if child.suffix == ".app" and (child / "Contents" / "Info.plist").is_file():
                candidates.append(child)
            elif child.is_dir():
                for grand in child.iterdir():
                    if grand.suffix == ".app" and (grand / "Contents" / "Info.plist").is_file():
                        candidates.append(grand)
    except OSError:
        return None
    if not candidates:
        return None
    return sorted(candidates, key=lambda path: len(path.parts))[0]


def _brand_plist(app_path: Path, unique_id: str, engine_version: str, env_type: str) -> None:
    """Write the keys the desktop reads, leaving the engine's own keys alone."""
    plist_path = app_path / "Contents" / "Info.plist"
    data = read_plist(plist_path)
    if not data:
        raise ActionError(f"{app_path.name} has no readable Contents/Info.plist.")
    edition = "steam" if engine_version == contract.STEAM else "universal"
    data["CFBundleIdentifier"] = "com.wehnix.bottle." + unique_id.replace("-", "")
    data["CFBundleName"] = "WehniX"
    data["CFBundleDisplayName"] = "WehniX"
    data["WehniXEngineVersion"] = engine_version
    data["WehniXEngineEdition"] = edition
    data["WehniXEnvType"] = env_type
    data["NSLocalNetworkUsageDescription"] = (
        "WehniX needs local network access for Windows apps and games."
    )
    with plist_path.open("wb") as handle:
        plistlib.dump(data, handle)


def verify_app(app_path: Path) -> tuple[bool, str]:
    """The minimum a bottle needs before the app is willing to launch it."""
    plist_path = app_path / "Contents" / "Info.plist"
    if not plist_path.is_file():
        return False, f"{app_path.name} is missing Contents/Info.plist."
    macos = app_path / "Contents" / "MacOS"
    if not macos.is_dir():
        return False, f"{app_path.name} is missing Contents/MacOS."
    try:
        executables = [child for child in macos.iterdir() if child.is_file()]
    except OSError:
        executables = []
    if not executables:
        return False, f"{app_path.name} has no executable in Contents/MacOS."
    if not (app_path / "Contents" / "Resources").is_dir():
        return False, f"{app_path.name} is missing Contents/Resources."
    return True, ""


def sign_app(app_path: Path, unique_id: str, runner=None) -> tuple[bool, str]:
    """Ad-hoc sign the bottle the way the desktop does."""
    run = runner or _run
    identifier = "com.wehnix.bottle." + unique_id.replace("-", "")
    code, detail = run(
        [
            "/usr/bin/codesign",
            "--force",
            "--deep",
            "--sign",
            "-",
            "--identifier",
            identifier,
            str(app_path),
        ],
        CODESIGN_TIMEOUT_SECONDS,
    )
    return code == 0, detail


def create_bottle(
    name: str,
    engine: EngineArtifact,
    env_type: str | None = None,
    root: Path | None = None,
    signer=None,
) -> CreationResult:
    """Make a new bottle from an engine archive, exactly as the app would.

    Staged in a hidden folder, validated, then moved into ``bottles/<uuid>/``.
    A failure removes only the staged copy; nothing that already existed is
    touched, and no record is written until the bundle passes verification.
    """
    root = Path(root) if root is not None else state_root()
    if app_is_running():
        raise ActionError("Quit WehniX first — it is open and would fight this change.")
    if engine is None:
        raise ActionError("Pick an engine archive to build the bottle from.")
    if not engine.path.is_file():
        raise ActionError(f"Engine archive missing: {engine.path}")

    engine_version = contract.normalize_engine_version(engine.version)
    rules = contract.bottle_types_for_engine(engine_version)
    if not rules["creatable"]:
        raise ActionError(
            f"{rules['label']} cannot create bottles. {rules['note']}".strip()
        )

    # Validate the request before normalising: normalising "steam" onto a
    # Universal engine would turn an unsupported choice into "game" silently.
    requested = str(env_type or rules["default"] or "").strip().lower()
    if requested not in rules["allowed"]:
        raise ActionError(
            f"{rules['label']} bottles can't be {requested or 'that type'}. {rules['note']}".strip()
        )
    wanted = contract.normalize_bottle_env_type(requested, engine_version)

    clean = contract.sanitize_bundle_name(name)
    bundle_name = contract.bottle_bundle_name(clean, engine_version)
    bottles_dir = root / "bottles"
    try:
        bottles_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ActionError(f"Could not create {bottles_dir}: {exc}") from exc

    unique_id = contract.generate_unique_id()
    bottle_path = bottles_dir / unique_id
    staging = bottles_dir / f".creating-{unique_id}"
    warnings: list[str] = []

    try:
        staging.mkdir(parents=True, exist_ok=False)
        extract_archive(engine.path, staging)
        extracted = find_app_bundle(staging)
        if extracted is None:
            raise ActionError(
                f"{engine.name} did not contain a WehniX engine app bundle. "
                "It may be a partial download."
            )

        bottle_path.mkdir(parents=True, exist_ok=False)
        app_path = bottle_path / bundle_name
        shutil.move(str(extracted), str(app_path))

        _brand_plist(app_path, unique_id, engine_version, wanted)

        ok, detail = verify_app(app_path)
        if not ok:
            raise ActionError(detail)

        signer = signer or sign_app
        signed, sign_detail = signer(app_path, unique_id)
        if not signed:
            warnings.append(
                "macOS code signing failed, so the bottle may refuse to launch. "
                f"codesign said: {sign_detail or 'unknown error'}"
            )

        renderer = str(
            (read_json(root / "config.json").get("settings") or {}).get("graphics_backend")
            or "dxmt"
        )
        record = contract.record_for_bottle(
            name=clean,
            unique_id=unique_id,
            bottle_path=bottle_path,
            app_path=app_path,
            c_drive_path=_c_drive(app_path),
            engine_version=engine_version,
            env_type=wanted,
            renderer=renderer,
            created_at=iso_now(),
        )
        records = load_records(root)
        records.append(record)
        save_records(records, root)
        return CreationResult(bottle_path, app_path, unique_id, warnings)
    except BaseException:
        shutil.rmtree(bottle_path, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _c_drive(app_path: Path) -> Path:
    """Where the engine will provision C:, without creating anything."""
    candidates = [app_path / "drive_c"]
    prefixes = app_path / "Contents" / "Resources" / "state" / "prefixes"
    if prefixes.is_dir():
        candidates.extend(sorted(prefixes.glob("*/drive_c")))
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return app_path / "Contents" / "Resources" / "state" / "prefixes"


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def set_setting(key: str, value: object, root: Path | None = None) -> dict:
    """Change one allow-listed key in ``config.json``.

    Optimistic concurrency: if the file changed between reading it and writing
    it, the write is refused rather than clobbering what the app just saved
    (the app rewrites config.json while it runs).
    """
    root = Path(root) if root is not None else state_root()
    path = root / "config.json"
    if app_is_running():
        raise ActionError("Quit WehniX first — it rewrites config.json while it runs.")
    before = file_signature(path)
    data = read_json(path)
    if not data:
        raise ActionError(f"No readable {path}. Finish setup in the app first.")
    try:
        normalised = contract.validate_setting(key, value)
    except ValueError as exc:
        raise ActionError(str(exc)) from exc
    if file_signature(path) != before:
        raise ActionError("config.json changed while it was being edited — refresh and try again.")
    settings = data.setdefault("settings", {})
    if not isinstance(settings, dict):
        raise ActionError("config.json has an unexpected shape; the CLI will not rewrite it.")
    settings[key] = normalised
    write_json_atomic(path, data)
    return data


# ---------------------------------------------------------------------------
# Log
# ---------------------------------------------------------------------------


def tail_log(path: Path, lines: int = 200) -> list[str]:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            return handle.readlines()[-max(1, lines):]
    except OSError:
        return []


# ---------------------------------------------------------------------------
# Per-bottle settings
# ---------------------------------------------------------------------------
# Copied from wehnix_app.py :: get_bottle_app_settings /
# update_bottle_app_settings. ``config.json``'s ``graphics_backend`` is the app
# default for new surfaces; it is never treated as a bottle's renderer here.

BOTTLE_SETTING_KEYS = (
    "renderer",
    "sync",
    "metal_hud",
    "high_res",
    "program_path",
    "program_flags",
)


def available_bottle_settings(bottle: Bottle) -> dict:
    """What the selected bottle may change, plus what it currently says.

    CPU-only: reads files, never writes. A bottle without a readable bundle
    still returns its capabilities so the UI can explain the refusal.
    """
    runtime = bottle.runtime or bottle.engine
    capabilities = contract.bottle_capabilities(runtime, bottle.app_path)
    current = read_bottle_app_settings(bottle.app_path)
    locked = str(bottle.env_type or "").strip().lower() == "steam"
    capabilities["program_locked"] = locked
    capabilities["program_reason"] = (
        "Steam bottles always launch Steam, so the program cannot be changed."
        if locked
        else ""
    )
    capabilities["engine"] = bottle.engine
    capabilities["current"] = current
    return capabilities


def _setting_flag(value: object, label: str) -> bool:
    text = str(value).strip().lower()
    if text in ("1", "true", "on", "yes"):
        return True
    if text in ("0", "false", "off", "no"):
        return False
    raise ActionError(f"{label} expects on or off, not {value!r}.")


def _block(config: dict, key: str) -> dict:
    value = config.get(key)
    if not isinstance(value, dict):
        value = {}
        config[key] = value
    return value


def _write_launch_config(app_path: Path, runtime: str, updates: dict) -> None:
    """Write Universal/Steam/11.11 settings to their own wehnix.json."""
    config = read_launch_config(app_path, runtime)
    if "renderer" in updates:
        renderer = _block(config, "renderer")
        renderer["active"] = updates["renderer"]
        renderer["enabled"] = True
    if "sync" in updates:
        _block(config, "sync")["mode"] = updates["sync"]
    graphics = _block(config, "graphics")
    if "metal_hud" in updates:
        graphics["metalHud"] = bool(updates["metal_hud"])
    if "high_res" in updates:
        if runtime == "11.11":
            graphics["retina"] = bool(updates["high_res"])
        else:
            graphics.pop("retina", None)
    if runtime != "11.11":
        # 11.17 has no high-resolution switch; never leave a stale key behind.
        graphics.pop("retina", None)
    launch = _block(config, "launch")
    if "program_path" in updates:
        launch["exePath"] = updates["program_path"] or "nothing.exe"
    if "program_flags" in updates:
        raw = str(updates["program_flags"] or "").strip()
        # posix=False keeps Windows backslashes in a quoted argument, exactly
        # like wehnix_app.py :: update_bottle_app_settings.
        try:
            launch["arguments"] = shlex.split(raw, posix=False) if raw else []
        except ValueError:
            launch["arguments"] = raw.split() if raw else []
    write_json_atomic(launch_config_path(app_path, runtime), config)


def _write_plist(path: Path, plist: dict) -> None:
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temp.open("wb") as handle:
        plistlib.dump(plist, handle)
        handle.flush()
        try:
            os.fsync(handle.fileno())
        except OSError:
            pass
    os.replace(temp, path)


def _write_plist_settings(app_path: Path, updates: dict) -> None:
    """Write GPTK/11.0 settings to the bundle's Info.plist.

    Copied from wehnix_app.py :: set_renderer_in_plist and its sync, Metal HUD,
    high-resolution and program writers.
    """
    path = app_path / "Contents" / "Info.plist"
    plist = read_plist(path)
    if not plist:
        raise ActionError(
            f"{path} is missing or unreadable, so this bottle's settings cannot be changed."
        )
    # Copied from wehnix_app.py :: set_renderer_in_plist and its siblings: the
    # desktop writes integers, and its reader treats any non-zero value as on.
    # Strings here would make "0" truthy in the app.
    if "renderer" in updates:
        keys = {
            "dxmt": "DXMT",
            "dxvk": "DXVK",
            "d3dmetal": "D3DMETAL",
            "d9vk": "D9VK",
            "cnc-ddraw": "CNC_DDRAW",
        }
        for key in keys.values():
            plist[key] = 0
        plist[keys[updates["renderer"]]] = 1
    if "sync" in updates:
        plist["WINEESYNC"] = 1 if updates["sync"] == "esync" else 0
        plist["WINEMSYNC"] = 1 if updates["sync"] == "msync" else 0
    if "metal_hud" in updates:
        plist["METAL_HUD"] = 1 if updates["metal_hud"] else 0
    if "high_res" in updates:
        plist["RetinaMode"] = 1 if updates["high_res"] else 0
    if "program_path" in updates:
        plist["Program Name and Path"] = updates["program_path"] or "/nothing.exe"
    if "program_flags" in updates:
        plist["Program Flags"] = str(updates["program_flags"] or "")
    _write_plist(path, plist)


def _record_matches(record: dict, bottle: Bottle) -> bool:
    for key in ("unique_id", "id"):
        value = str(record.get(key) or "").strip()
        if value and value in (bottle.unique_id, bottle.path.name):
            return True
    for key in ("path", "app_path"):
        value = str(record.get(key) or "").strip()
        if not value:
            continue
        recorded = Path(value)
        if recorded == bottle.path or (bottle.app_path and recorded == bottle.app_path):
            return True
        if recorded.name == bottle.path.name:
            return True
    return False


def _sync_record(bottle: Bottle, updates: dict, root: Path) -> None:
    """Update the cached record after the app file was written successfully."""
    records = load_records(root)
    changed = False
    for record in records:
        if not _record_matches(record, bottle):
            continue
        if "renderer" in updates:
            record["renderer"] = updates["renderer"]
        if "program_path" in updates:
            record["program_path"] = updates["program_path"] or "nothing.exe"
        if "program_flags" in updates:
            record["program_flags"] = str(updates["program_flags"] or "")
        if "metal_hud" in updates:
            record["metal_hud"] = bool(updates["metal_hud"])
        advanced = record.get("advanced")
        if not isinstance(advanced, dict):
            advanced = {}
            record["advanced"] = advanced
        if "sync" in updates:
            advanced["sync"] = updates["sync"]
        if "high_res" in updates:
            advanced["high_res"] = bool(updates["high_res"])
        changed = True
    if changed:
        save_records(records, root)


def set_bottle_setting(
    bottle: Bottle,
    key: str,
    value: object,
    root: Path | None = None,
) -> dict:
    """Change one per-bottle setting after checking the engine allows it.

    Every check runs before a single byte is written, so a refused change leaves
    the bottle exactly as it was. Universal's shared target is written through
    ``wx-target`` first, matching the desktop's order.
    """
    if key not in BOTTLE_SETTING_KEYS:
        raise ActionError(f"{key} is not a bottle setting this CLI can change.")
    if app_is_running():
        raise ActionError("Quit WehniX first — it rewrites bottle settings while it runs.")
    if bottle.app_path is None or not Path(bottle.app_path).is_dir():
        raise ActionError(f"{bottle.name} has no app bundle on disk to change.")

    root = Path(root) if root is not None else state_root()
    options = available_bottle_settings(bottle)
    runtime = options["runtime"]
    label = contract.engine_label(bottle.engine)
    updates: dict = {}

    if key == "renderer":
        choice = str(value or "").strip().lower()
        detail = options["renderers"].get(choice)
        if detail is None:
            offered = ", ".join(name for name, item in options["renderers"].items() if item["available"])
            raise ActionError(f"{label} does not offer {choice or 'that renderer'}. Choose: {offered}.")
        if not detail["available"]:
            raise ActionError(detail["reason"])
        updates["renderer"] = choice
    elif key == "sync":
        choice = str(value or "").strip().lower()
        if choice not in options["sync_modes"]:
            if runtime == contract.UNIVERSAL and choice == "esync":
                raise ActionError(
                    "Universal cannot run esync sync; it offers none or msync."
                )
            offered = ", ".join(options["sync_modes"])
            raise ActionError(f"{label} sync modes are {offered}; {choice or 'that'} is not one.")
        updates["sync"] = choice
    elif key in ("metal_hud", "high_res"):
        flag = _setting_flag(value, key.replace("_", " "))
        if key == "high_res" and not options["high_res"]:
            raise ActionError(f"{label} does not support high resolution.")
        if key == "metal_hud" and not options["metal_hud"]:
            raise ActionError(f"{label} does not support the Metal HUD.")
        updates[key] = flag
    else:
        if options["program_locked"]:
            raise ActionError(options["program_reason"] or "This bottle's program is locked.")
        if key == "program_path":
            # Accept a Finder-style path and store the Windows path the engine
            # launches, the same mapping the desktop's file picker applies.
            updates[key] = windows_program_path(bottle.app_path, str(value or ""))
        else:
            updates[key] = str(value or "")

    if key == "program_path" and runtime == contract.UNIVERSAL:
        shared = set_universal_shared_target(bottle.app_path, updates["program_path"])
        if not shared["success"]:
            raise ActionError(shared["error"] or "Universal refused the new target.")

    if runtime in (contract.UNIVERSAL, contract.STEAM, "11.11"):
        _write_launch_config(bottle.app_path, runtime, updates)
    else:
        _write_plist_settings(bottle.app_path, updates)

    _sync_record(bottle, updates, root)
    return available_bottle_settings(bottle)
