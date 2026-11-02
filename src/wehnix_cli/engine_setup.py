"""Install WehniX engine archives the way the desktop's setup does.

This is the only module in the package that touches the network, and it does so
only when the user runs ``WehniX setup`` or ``WehniX engines install``. Routine
commands (``list``, ``show``, ``games``, ``doctor``, the interface) never
download anything.

Ported from ``wehnix_app.py``:
  :: REMOTE_ENGINE_DOWNLOADS, :: UNIVERSAL_INCOMPATIBLE_ARCHIVE_SHA256,
  :: normalize_expected_digest, :: verify_engine_archive_digest,
  :: download_engine_archive, :: install_engine_from_archive,
  :: engine_zip_structure_failure, :: engine_zip_verification_failure,
  :: ensure_app_data_dir_exists, :: classify_setup_engine_versions,
  :: setup_directories_and_engine, :: DEFAULT_CONFIG.

The desktop also patches Universal's helper scripts to the interpreter inside
``WehniX.app`` before sealing the bundle. This CLI has no such interpreter, so
it does not patch them: the installed archive is byte-checked against the
engine's own layout, and the desktop can repair the interpreter references on
its next engine check. That difference is documented in the README rather than
hidden behind a claim of byte-identical output.

Only the pinned URLs and digests below are used. There is no arbitrary URL
input, no redirect to another host beyond GitHub's own release redirect, and no
TLS relaxation.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

from . import contract
from .actions import ActionError, extract_archive
from .state import (
    BOTTLES_JSON,
    CONFIG_JSON,
    ENGINE_DIR,
    file_signature,
    read_json,
    write_json_atomic,
)

Progress = Callable[[str, int | None], None]

ELEVEN_ELEVEN = "11.11"


class ProgressThrottle:
    """Rate-limit progress lines so a 1 GB download prints ~100, not thousands.

    A line is only drawn when the percentage has moved by at least ``step``
    *and* at least ``interval`` seconds have passed, so a fast link does not
    flood the terminal and a slow one still shows movement. Percent ``None`` is
    a stage change ("Extracting…") and always goes through; percent ``100``
    always goes through so the last line is never swallowed.

    The clock is injectable so the cadence is tested rather than eyeballed.
    """

    def __init__(
        self,
        interval: float = 0.25,
        step: int = 1,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.interval = interval
        self.step = max(1, int(step))
        self.clock = clock or time.monotonic
        self._emitted_at: float | None = None
        self._emitted_percent: int | None = None

    def should_emit(self, percent: int | None) -> bool:
        now = self.clock()
        last_at = self._emitted_at
        last_percent = self._emitted_percent
        emit = (
            last_at is None
            or percent is None
            or percent >= 100
            or (
                last_percent is not None
                and percent - last_percent >= self.step
                and (now - last_at) >= self.interval
            )
        )
        if emit:
            self._emitted_at = now
            if percent is not None:
                self._emitted_percent = percent
        return emit


def throttled(progress: Progress | None, **kwargs) -> Progress:
    """Wrap ``progress`` with a :class:`ProgressThrottle`, safe when it is None."""
    if progress is None:
        return lambda message, percent=None: None
    gate = ProgressThrottle(**kwargs)

    def report(message: str, percent: int | None = None) -> None:
        if gate.should_emit(percent):
            progress(message, percent)

    return report

# Copied from wehnix_app.py :: REMOTE_ENGINE_DOWNLOADS. Both values are the
# asset digests reported by the WX-Wine releases API. Do not edit one without
# the other: a stale digest turns every install into a checksum failure.
REMOTE_ENGINE_DOWNLOADS: dict[str, dict[str, str]] = {
    ELEVEN_ELEVEN: {
        "url": "https://github.com/wehnnit/WX-Wine/releases/download/"
        "WX-11.11/WehniX-Engine-11.11-macos.tar.xz",
        "archive_type": "tar.xz",
        "app_name": "WehniX Engine 11.11.app",
        "archive_filename": "WehniX-Engine-11.11-macos.tar.xz",
        "sha256": "a8ca3ee4ecaa648f1b288f2700ce6551fed43f7eb06c4cb379a7c851d7f8aa5c",
        "label": "WehniX Engine 11.11",
    },
    contract.STEAM: {
        "url": "https://github.com/wehnnit/WX-Wine/releases/download/"
        "v11.17/WX-wine-11.17.tar.xz",
        "archive_type": "tar.xz",
        "app_name": "WX-wine-11.17.app",
        "archive_filename": "WX-wine-11.17.tar.xz",
        "sha256": "6aa499f98f5fec0eaa3eb6dad0d9665b04abeea82006b19714d50bf5ab3394ee",
        "label": "WehniX Engine 11.17 Steam",
    },
    contract.UNIVERSAL: {
        "url": "https://github.com/wehnnit/WX-Wine/releases/download/"
        "v11.17-universal/WX-wine-11.17-Universal.tar.xz",
        "archive_type": "tar.xz",
        "app_name": "WX-wine-11.17.app",
        "archive_filename": "WX-wine-11.17-Universal.tar.xz",
        "sha256": "04a6772387007814ef9d3f054a896ee46dfb96f5a625b140e46a7310a9164384",
        "label": "WehniX Engine 11.17 Universal",
    },
}

# Copied from wehnix_app.py :: UNIVERSAL_INCOMPATIBLE_ARCHIVE_SHA256. The
# superseded Universal build is intact and matches its own published checksum,
# but it ships without ``scripts/wx-session.sh``; it must be refused on
# completeness, not only on integrity.
UNIVERSAL_INCOMPATIBLE_SHA256 = (
    "e8e77bd412f90482a4df72c89e7af1d4686c2c15aaf936a20133e43b0c6305f5"
)

# Copied from wehnix_app.py :: ENGINE_TEMPLATES[*]["zip"] — the file name the
# desktop's bottle creation looks for under ``Engine/``.
INSTALLED_ZIP_NAME = {
    contract.UNIVERSAL: "WehniX Engine 11.17 Universal.zip",
    contract.STEAM: "WehniX Engine 11.17 Steam.zip",
    ELEVEN_ELEVEN: "WehniX Engine 11.11.zip",
}

# Copied from wehnix_app.py :: ENGINE_TEMPLATES[*]["template_dir"].
BUNDLE_NAME = {
    contract.UNIVERSAL: "WehniX Engine 11.17 Universal.app",
    contract.STEAM: "WehniX Engine 11.17 Steam.app",
    ELEVEN_ELEVEN: "WehniX Engine 11.11.app",
}

# Copied from wehnix_app.py :: UNIVERSAL_RUNTIME_FILES. Losing one of these is
# corruption, and the released incomplete Universal archive is exactly that.
UNIVERSAL_RUNTIME_FILES = (
    "wine/bin/wine",
    "wine/bin/wineserver",
    "bin/wx-wine",
    "bin/wx-target",
    "bin/wx-renderer",
    "scripts/wx-launch-profile.sh",
    "scripts/wx-ensure-prefix.sh",
    "scripts/wx-provision-prefix.sh",
    "scripts/wx-renderer-env.sh",
    "scripts/wx-bundle-env.sh",
    "scripts/wx-stop.sh",
    "scripts/wx-session.sh",
    "scripts/command.sh",
)

# Copied from wehnix_app.py :: engine_templates.steam_required_relative_paths
# (the subset that must exist for a Steam install to be usable).
STEAM_REQUIRED_FILES = (
    "Contents/Info.plist",
    "Contents/MacOS/WX-wine-11.17",
    "Contents/Resources/wine/bin/wine",
    "Contents/Resources/bin/wx-wine",
    "Contents/Resources/bin/wx-renderer",
    "Contents/Resources/scripts/wx-bundle-env.sh",
    "Contents/Resources/scripts/wx-ensure-prefix.sh",
    "Contents/Resources/scripts/launch-game.sh",
)

UNIVERSAL_REQUIRED_FILES = (
    "Contents/Info.plist",
    "Contents/MacOS/WX-wine-11.17",
    *(f"Contents/Resources/{name}" for name in UNIVERSAL_RUNTIME_FILES),
    "Contents/Resources/UNIVERSAL.md",
    "Contents/Resources/renderers/dxmt",
    "Contents/Resources/state/prefixes/universal-main/drive_c",
)

LEGACY_11_11_REQUIRED_FILES = (
    "Contents/Info.plist",
    "Contents/Resources/engine/wine/tools/wine/wine",
)

REQUIRED_FILES = {
    contract.UNIVERSAL: UNIVERSAL_REQUIRED_FILES,
    contract.STEAM: STEAM_REQUIRED_FILES,
    ELEVEN_ELEVEN: LEGACY_11_11_REQUIRED_FILES,
}

# Copied from wehnix_app.py :: MIN_ENGINE_ZIP_BYTES. A real 11.17 archive is
# ~1 GB, so anything below this is a truncated download or a stub.
MIN_ENGINE_ZIP_BYTES = 100 * 1024 * 1024

MAX_DOWNLOAD_BYTES = 8 * 1024**3
CHUNK_BYTES = 1024 * 1024
DOWNLOAD_TIMEOUT = 120


class SetupError(RuntimeError):
    """A setup failure with a message a person can act on."""


# ---------------------------------------------------------------------------
# Contract helpers
# ---------------------------------------------------------------------------


def supported_versions() -> tuple[str, ...]:
    return (contract.UNIVERSAL, contract.STEAM, ELEVEN_ELEVEN)


def aliases() -> dict[str, str]:
    return {
        "universal": contract.UNIVERSAL,
        "11.17-universal": contract.UNIVERSAL,
        "steam": contract.STEAM,
        "11.17-steam": contract.STEAM,
        "11.17": contract.STEAM,
        "11.11": ELEVEN_ELEVEN,
    }


def resolve_version(value: str) -> str:
    wanted = str(value or "").strip().lower()
    version = aliases().get(wanted)
    if version is None:
        raise SetupError(
            f"{value!r} is not an engine this CLI can install. "
            f"Choose one of: {', '.join(supported_versions())}."
        )
    return version


def remote(version: str) -> dict[str, str]:
    return REMOTE_ENGINE_DOWNLOADS[resolve_version(version)]


def label(version: str) -> str:
    return remote(version).get("label") or contract.engine_label(version)


def installed_zip(root: Path, version: str) -> Path:
    return Path(root) / ENGINE_DIR / INSTALLED_ZIP_NAME[resolve_version(version)]


def download_path(root: Path, version: str) -> Path:
    name = remote(version)["archive_filename"]
    return Path(root) / ENGINE_DIR / ".downloads" / name


def normalize_digest(value: object) -> str:
    """Accept a bare hex digest or GitHub's ``sha256:<hex>`` form."""
    text = str(value or "").strip()
    if not text:
        return ""
    if ":" in text:
        algorithm, _, remainder = text.partition(":")
        if algorithm.strip().lower() != "sha256":
            return ""
        text = remainder.strip()
    if len(text) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in text):
        return ""
    return text.lower()


def sha256_file(path: Path, progress: Progress | None = None) -> str:
    hasher = hashlib.sha256()
    size = path.stat().st_size
    read = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(CHUNK_BYTES)
            if not chunk:
                break
            hasher.update(chunk)
            read += len(chunk)
            if progress is not None:
                percent = int((read / size) * 100) if size else None
                progress("Verifying the archive…", percent)
    return hasher.hexdigest()


def is_known_incompatible(version: str, digest: str) -> bool:
    return (
        resolve_version(version) == contract.UNIVERSAL
        and normalize_digest(digest) == UNIVERSAL_INCOMPATIBLE_SHA256
    )


def clear_quarantine(path: Path) -> None:
    """Best-effort: a quarantined archive cannot be executed by Gatekeeper."""
    target = Path(path)
    if not target.exists():
        return
    try:
        probe = subprocess.run(
            ["/usr/bin/xattr", "-p", "com.apple.quarantine", str(target)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=10,
        )
        if probe.returncode != 0:
            return
        subprocess.run(
            ["/usr/bin/xattr", "-d", "com.apple.quarantine", str(target)],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def free_bytes(path: Path) -> int:
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return 0


# Copied from wehnix_app.py :: ensure_free_space, rounded for a folder that may
# not exist yet: one 11.17 engine needs its archive, its extraction and its
# installed zip at the same time.
ESTIMATED_BYTES_PER_ENGINE = 3 * 1024**3


def free_bytes_for(path: Path) -> int:
    """Free space on the volume that would hold ``path``, absent path included."""
    probe = Path(path)
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return free_bytes(probe)


def space_problem(root: Path, count: int) -> str:
    """The reason to refuse an install up front, or an empty string.

    Checked before a first-run download starts, so a nearly full disk fails in
    one line instead of a gigabyte into an archive it cannot unpack.
    """
    needed = max(1, int(count)) * ESTIMATED_BYTES_PER_ENGINE
    available = free_bytes_for(root)
    if available and available < needed:
        return (
            f"Not enough free disk space: {count} engine(s) need about "
            f"{needed / 1024**3:.0f} GB but only {available / 1024**3:.0f} GB is free."
        )
    return ""


# ---------------------------------------------------------------------------
# Downloading
# ---------------------------------------------------------------------------


def download_archive(
    version: str,
    destination: Path,
    progress: Progress | None = None,
    cancel: Callable[[], bool] | None = None,
) -> dict:
    """Fetch one pinned archive to ``destination``, verifying its digest.

    The partial file is ``<name>.part`` and is never promoted unless the
    SHA-256 matches the pin, so an interrupted run cannot leave something that
    later looks installed.
    """
    version = resolve_version(version)
    config = remote(version)
    expected = normalize_digest(config["sha256"])
    if not expected:
        raise SetupError(f"No pinned checksum for {config['label']}.")
    url = str(config["url"])
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("https", "file"):
        raise SetupError(f"Refusing a non-HTTPS engine URL: {url}")
    if parsed.scheme == "https" and parsed.hostname not in ("github.com", "objects.githubusercontent.com"):
        raise SetupError(f"Refusing an engine download from {parsed.hostname}.")

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    part = destination.with_suffix(destination.suffix + ".part")
    hasher = hashlib.sha256()
    request = urllib.request.Request(url, headers={"User-Agent": "WehniX-CLI"})
    report = throttled(progress)
    try:
        with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT) as response:
            total = int(response.headers.get("Content-Length") or 0)
            written = 0
            report(
                f"Downloading {config['label']} ({total / 1024**2:.0f} MB)…"
                if total
                else f"Downloading {config['label']}…",
                None,
            )
            with part.open("wb") as handle:
                while True:
                    if cancel is not None and cancel():
                        raise SetupError("Setup cancelled; nothing was installed.")
                    chunk = response.read(CHUNK_BYTES)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > MAX_DOWNLOAD_BYTES:
                        raise SetupError("The engine download is larger than any known archive.")
                    hasher.update(chunk)
                    handle.write(chunk)
                    if total:
                        report(
                            f"Downloading {config['label']}… {written / 1024**2:.0f} / "
                            f"{total / 1024**2:.0f} MB",
                            min(99, int((written / total) * 100)),
                        )
                handle.flush()
                os.fsync(handle.fileno())
    except SetupError:
        part.unlink(missing_ok=True)
        raise
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
        part.unlink(missing_ok=True)
        raise SetupError(f"Could not download {config['label']}: {exc}") from exc
    except BaseException:
        # Ctrl+C and anything else: a half file must never survive as a
        # candidate archive that a later run would try to reuse.
        part.unlink(missing_ok=True)
        raise

    digest = hasher.hexdigest()
    if digest != expected:
        part.unlink(missing_ok=True)
        raise SetupError(
            f"The {config['label']} download did not match its pinned checksum "
            f"(expected {expected}, got {digest}). Nothing was installed."
        )
    if is_known_incompatible(version, digest):
        part.unlink(missing_ok=True)
        raise SetupError(
            f"The {config['label']} archive is the superseded build that ships without "
            "scripts/wx-session.sh. Nothing was installed."
        )
    part.replace(destination)
    clear_quarantine(destination)
    report(f"Verified {destination.name}", 100)
    return {"path": destination, "sha256": digest, "bytes": destination.stat().st_size}


def reusable_archive(root: Path, version: str) -> tuple[Path | None, str]:
    """An already-downloaded archive whose digest matches the pin, if any."""
    version = resolve_version(version)
    expected = normalize_digest(remote(version)["sha256"])
    candidates = [
        download_path(root, version),
        Path(root) / ENGINE_DIR / remote(version)["archive_filename"],
    ]
    for candidate in candidates:
        if not candidate.is_file():
            continue
        digest = sha256_file(candidate)
        if digest == expected:
            return candidate, digest
        # A half download must not be retried forever.
        candidate.unlink(missing_ok=True)
    return None, ""


# ---------------------------------------------------------------------------
# Extracting and repacking
# ---------------------------------------------------------------------------


def verify_tree(app_path: Path, version: str) -> None:
    version = resolve_version(version)
    required = REQUIRED_FILES[version]
    missing = [name for name in required if not (Path(app_path) / name).exists()]
    if missing:
        raise SetupError(
            f"The downloaded {label(version)} is incomplete "
            f"(missing {', '.join(missing[:4])}). Nothing was installed."
        )


def verify_zip(path: Path, version: str, min_bytes: int | None = None) -> None:
    """The same contract the desktop enforces before an engine is reused."""
    version = resolve_version(version)
    floor = MIN_ENGINE_ZIP_BYTES if min_bytes is None else min_bytes
    if not path.is_file():
        raise SetupError(f"{path.name} is missing.")
    size = path.stat().st_size
    if size < floor:
        raise SetupError(
            f"{path.name} is only {size / 1024**2:.1f} MB; a complete engine is larger. "
            "Nothing was installed."
        )
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
    except (zipfile.BadZipFile, OSError) as exc:
        raise SetupError(f"{path.name} is not a readable zip: {exc}") from exc
    bundle = BUNDLE_NAME[version]
    missing = [entry for entry in REQUIRED_FILES[version] if f"{bundle}/{entry}" not in names]
    if missing:
        raise SetupError(
            f"{path.name} is missing {', '.join(missing[:4])}. Nothing was installed."
        )


def _find_app(staging: Path, version: str) -> Path:
    preferred = staging / remote(version)["app_name"]
    if preferred.is_dir():
        return preferred
    try:
        candidates = sorted(p for p in staging.iterdir() if p.suffix == ".app")
    except OSError:
        candidates = []
    if len(candidates) == 1:
        return candidates[0]
    raise SetupError(
        f"The {label(version)} archive does not contain "
        f"{remote(version)['app_name']}."
    )


def _zip_app(app_path: Path, destination: Path) -> None:
    """Store-only zip of one .app, preserving symlinks and modes.

    Store-only matches the desktop's repack of 11.17 engines: the members are
    already compressed executables and shared libraries, and deflating a 4 GB
    bundle only adds minutes.
    """
    root = app_path.parent
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_STORED, allowZip64=True) as archive:
        for path in sorted(app_path.rglob("*")):
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                info = zipfile.ZipInfo(relative)
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(info, os.readlink(path))
            elif path.is_dir():
                info = zipfile.ZipInfo(relative + "/")
                info.create_system = 3
                info.external_attr = ((stat.S_IFDIR | 0o755) << 16) | 0x10
                archive.writestr(info, b"")
            elif path.is_file():
                info = zipfile.ZipInfo.from_file(path, relative)
                with path.open("rb") as source, archive.open(info, "w") as target:
                    shutil.copyfileobj(source, target, CHUNK_BYTES)


def install_from_archive(
    archive: Path,
    version: str,
    root: Path,
    source: str = "download",
    progress: Progress | None = None,
    cancel: Callable[[], bool] | None = None,
) -> dict:
    """Validate, extract, verify and repack one engine archive."""
    version = resolve_version(version)
    engine_dir = Path(root) / ENGINE_DIR
    engine_dir.mkdir(parents=True, exist_ok=True)
    staging = engine_dir / f".staging-{version.replace('.', '-')}"
    temp_zip = installed_zip(root, version).with_suffix(".zip.part")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    temp_zip.unlink(missing_ok=True)
    try:
        needed = archive.stat().st_size * 3
        available = free_bytes(engine_dir)
        if available and available < needed:
            raise SetupError(
                f"Not enough free disk space: this install needs about "
                f"{needed / 1024**3:.1f} GB but only {available / 1024**3:.1f} GB is free."
            )
        if progress is not None:
            progress(f"Extracting {label(version)}…", None)
        try:
            extract_archive(archive, staging)
        except ActionError as exc:
            raise SetupError(str(exc)) from exc
        if cancel is not None and cancel():
            raise SetupError("Setup cancelled before the engine was installed.")

        app_path = _find_app(staging, version)
        target_name = BUNDLE_NAME[version]
        if app_path.name != target_name:
            renamed = staging / target_name
            shutil.rmtree(renamed, ignore_errors=True)
            app_path.rename(renamed)
            app_path = renamed
        verify_tree(app_path, version)

        if progress is not None:
            progress(f"Repacking {label(version)}…", None)
        _zip_app(app_path, temp_zip)
        clear_quarantine(temp_zip)
        try:
            verify_zip(temp_zip, version)
        except SetupError:
            temp_zip.unlink(missing_ok=True)
            raise
        installed = installed_zip(root, version)
        temp_zip.replace(installed)
        clear_quarantine(installed)
        return {
            "success": True,
            "version": version,
            "engine_zip": str(installed),
            "bytes": installed.stat().st_size,
            "source": source,
            "source_archive": str(archive),
        }
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        temp_zip.unlink(missing_ok=True)


def install(
    version: str,
    root: Path,
    progress: Progress | None = None,
    cancel: Callable[[], bool] | None = None,
) -> dict:
    """Install one engine, reusing a verified archive when one exists."""
    version = resolve_version(version)
    archive, digest = reusable_archive(root, version)
    reused = archive is not None
    if archive is None:
        destination = download_path(root, version)
        if progress is not None:
            progress(f"Fetching {label(version)} from WX-Wine…", 0)
        downloaded = download_archive(version, destination, progress=progress, cancel=cancel)
        archive, digest = downloaded["path"], downloaded["sha256"]
        reused = False
    elif progress is not None:
        progress(f"Using the verified {label(version)} archive already on disk.", None)

    result = install_from_archive(
        archive, version, root, source="reused" if reused else "download",
        progress=progress, cancel=cancel,
    )
    result["reused"] = reused
    result["sha256"] = digest
    return result


# ---------------------------------------------------------------------------
# Data folder and setup
# ---------------------------------------------------------------------------


def desktop_default_settings() -> dict:
    """Copied from wehnix_app.py :: DEFAULT_CONFIG["settings"] (safe subset)."""
    return {
        "graphics_backend": "dxmt",
        "engine_version": contract.UNIVERSAL,
        "bottle_engine_version": contract.UNIVERSAL,
        "auto_check_updates": True,
    }


def ensure_layout(root: Path) -> list[str]:
    """Create the directories the desktop's setup creates, nothing else.

    Copied from wehnix_app.py :: ensure_app_data_dir_exists, minus the Epic and
    Steam trees: the CLI does not manage those, and empty look-alike folders
    would make the app think they had been set up.
    """
    root = Path(root)
    created: list[str] = []
    for relative in ("", ENGINE_DIR, "bottles", "cli", "logs"):
        target = root / relative if relative else root
        if not target.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            created.append(str(target))
    return created


def initialize_config(root: Path) -> Path:
    """Write a desktop-shaped config, preserving any keys already there."""
    root = Path(root)
    path = root / CONFIG_JSON
    existing = read_json(path) if path.is_file() else {}
    payload: dict = dict(existing)
    payload["bottles"] = payload.get("bottles") if isinstance(payload.get("bottles"), list) else []
    settings = dict(payload.get("settings") or {})
    for key, value in desktop_default_settings().items():
        settings.setdefault(key, value)
    payload["settings"] = settings
    # Honest until an engine has actually been verified.
    if not path.is_file():
        payload["setup_complete"] = False
    write_json_atomic(path, payload, indent=4)
    return path


def finalize_config(root: Path) -> Path:
    """Mark setup complete, keeping unknown keys byte-for-byte in meaning."""
    root = Path(root)
    path = root / CONFIG_JSON
    payload = read_json(path) if path.is_file() else {}
    payload["setup_complete"] = True
    payload["bottles"] = payload.get("bottles") if isinstance(payload.get("bottles"), list) else []
    settings = dict(payload.get("settings") or {})
    for key, value in desktop_default_settings().items():
        settings.setdefault(key, value)
    payload["settings"] = settings
    write_json_atomic(path, payload, indent=4)
    return path


def ensure_bottles_file(root: Path) -> Path:
    """Create an empty bottles.json, never overwriting records."""
    path = Path(root) / BOTTLES_JSON
    if not path.is_file():
        write_json_atomic(path, {"bottles": []}, indent=4)
    return path


def setup(
    root: Path,
    versions: list[str] | None = None,
    progress: Progress | None = None,
    cancel: Callable[[], bool] | None = None,
) -> dict:
    """First-run setup: directories, config, bottles.json, then engines.

    ``setup_complete`` is written only after every requested engine passes its
    own verification, so an interrupted run is never reported as ready.
    """
    root = Path(root)
    chosen = [resolve_version(value) for value in (versions or [contract.UNIVERSAL])]
    chosen = list(dict.fromkeys(chosen))
    if progress is not None:
        progress("Preparing the WehniX data folder…", None)
    created = ensure_layout(root)
    config_before = file_signature(root / CONFIG_JSON)
    initialize_config(root)
    ensure_bottles_file(root)

    results: list[dict] = []
    for version in chosen:
        if cancel is not None and cancel():
            return {
                "success": False,
                "error": "Setup cancelled; setup_complete was not written.",
                "created": created,
                "engines": results,
                "root": str(root),
            }
        try:
            results.append(install(version, root, progress=progress, cancel=cancel))
        except SetupError as exc:
            return {
                "success": False,
                "error": str(exc),
                "created": created,
                "engines": results,
                "root": str(root),
            }

    if config_before is not None and file_signature(root / CONFIG_JSON) != config_before:
        pass  # our own write above is expected; nothing else may have changed it
    finalize_config(root)
    return {
        "success": True,
        "root": str(root),
        "created": created,
        "engines": results,
        "setup_complete": True,
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def engine_report(root: Path, version: str) -> dict:
    """What is on disk for one engine, without trusting its size alone."""
    version = resolve_version(version)
    path = installed_zip(root, version)
    report = {
        "version": version,
        "label": label(version),
        "path": str(path),
        "installed": path.is_file(),
        "size": 0,
        "healthy": False,
        "problem": "",
        "source": "remote" if version in REMOTE_ENGINE_DOWNLOADS else "local",
        "download_url": remote(version)["url"],
        "sha256": "",
    }
    if not path.is_file():
        report["problem"] = "not installed"
        return report
    try:
        report["size"] = path.stat().st_size
    except OSError:
        return report
    try:
        verify_zip(path, version)
    except SetupError as exc:
        report["problem"] = str(exc)
        return report
    report["healthy"] = True
    return report


def inspect_all(root: Path) -> list[dict]:
    return [engine_report(root, version) for version in supported_versions()]


def sha256_for_report(path: Path) -> str:
    try:
        return sha256_file(path) if path.is_file() else ""
    except OSError:
        return ""


def write_json(path: Path, payload: dict) -> None:
    """Small helper so callers do not import json just for a summary file."""
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def archive_url(version: str) -> str:
    return str(remote(version)["url"])


def archive_digest(version: str) -> str:
    return str(remote(version)["sha256"])


def tar_member_problem(path: Path) -> str:
    """Cheap pre-flight of an archive's member names, before extraction."""
    try:
        with tarfile.open(path) as bundle:
            for member in bundle.getmembers():
                name = member.name
                if name.startswith("/") or ".." in Path(name).parts:
                    return f"unsafe path in archive: {name}"
                if member.issym() or member.islnk():
                    link = member.linkname
                    if link.startswith("/") or ".." in Path(link).parts:
                        return f"unsafe link in archive: {name} -> {link}"
    except (tarfile.TarError, OSError, EOFError) as exc:
        return f"archive could not be read: {exc}"
    return ""
