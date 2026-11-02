"""The things the CLI can actually do, and the guards around them.

Every destructive path has the same shape: refuse while the desktop app is
open, stage the work, validate it, and only then put it where the app will look.
A delete moves a bottle to the Trash instead of unlinking four gigabytes of
prefix, so a mistake is reversible.
"""

from __future__ import annotations

import os
import plistlib
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
    load_records,
    move_to_trash,
    read_json,
    read_plist,
    save_records,
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
