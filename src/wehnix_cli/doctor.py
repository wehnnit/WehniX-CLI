"""Health checks, shared by the Doctor screen and ``WehniX doctor``.

Each check answers a question a person would actually ask before creating a
bottle or filing a bug: is the data folder there, does the app agree it is set
up, is the engine a real one, will the bottle launch once it exists. Hints are
commands you can paste, not advice.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path

from . import contract
from .models import Check
from .state import (
    ENGINE_MIN_BYTES,
    app_is_running,
    load_records,
    read_snapshot,
    state_root,
)

GIB = 1024**3
MIN_MACOS = (13, 0)
MIN_FREE_GIB = 15


def _run(command: list[str], timeout: float = 6.0) -> tuple[int, str]:
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
        return completed.returncode, (completed.stdout or completed.stderr or "").strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)


def macos_version() -> tuple[int, ...]:
    code, raw = _run(["/usr/bin/sw_vers", "-productVersion"])
    parts: list[int] = []
    if code == 0:
        for chunk in raw.split("."):
            try:
                parts.append(int(chunk))
            except ValueError:
                break
    return tuple(parts) or (0,)


def rosetta_ok() -> bool:
    if platform.machine() not in ("arm64", "aarch64"):
        return True  # not needed on Intel
    code, _ = _run(["/usr/bin/arch", "-x86_64", "/usr/bin/true"])
    return code == 0


def free_space_gb(path: Path) -> float:
    try:
        return shutil.disk_usage(path).free / GIB
    except OSError:
        return 0.0


def _app_copies() -> list[Path]:
    """Every WehniX.app macOS can see in the usual two Applications folders."""
    found: list[Path] = []
    for base in (Path("/Applications"), Path.home() / "Applications"):
        try:
            found.extend(sorted(base.glob("WehniX*.app")))
        except OSError:
            continue
    return found


def run_checks() -> list[Check]:
    root = state_root()
    checks: list[Check] = []

    exists = root.is_dir()
    checks.append(
        Check(
            "Data folder",
            exists,
            str(root) if exists else f"{root} is missing",
            "Run the WehniX app once, or `WehniX --init` to create it.",
        )
    )
    if exists:
        readable = os.access(root, os.R_OK | os.X_OK)
        checks.append(
            Check(
                "Data folder permissions",
                readable,
                "readable" if readable else "not readable by this user",
                f"ls -ld '{root}'",
            )
        )
        try:
            mode = root.stat().st_mode & 0o777
        except OSError:
            mode = 0
        world_writable = bool(mode & 0o002)
        checks.append(
            Check(
                "Private data folder",
                not world_writable,
                f"mode {mode:o}" + (" — writable by everyone" if world_writable else ""),
                f"chmod 700 '{root}'",
                severity="warning",
            )
        )
    else:
        checks.append(
            Check(
                "Private data folder",
                False,
                "not checked",
                "Create the folder first.",
                severity="warning",
            )
        )

    snapshot = read_snapshot(with_sizes=False, with_games=False)
    checks.append(
        Check(
            "config.json",
            bool(snapshot.config),
            "readable" if snapshot.config else "missing or unreadable",
            "Launch WehniX and finish setup.",
        )
    )
    checks.append(
        Check(
            "Setup complete",
            snapshot.setup_complete,
            "yes" if snapshot.setup_complete else "no — the app will ask on first launch",
            "Finish setup in the app.",
            severity="warning",
        )
    )

    bottles_dir = root / "bottles"
    checks.append(
        Check(
            "Bottles folder",
            bottles_dir.is_dir(),
            f"{len(snapshot.bottles)} bottle(s)" if bottles_dir.is_dir() else "missing",
            "Created on first run.",
        )
    )

    broken = [bottle.name for bottle in snapshot.bottles if bottle.app_path is None]
    checks.append(
        Check(
            "Bottle bundles",
            not broken,
            "all readable" if not broken else "no app bundle in: " + ", ".join(broken[:3]),
            "Open the bottle in WehniX; a partial copy has to be recreated.",
        )
    )

    records = load_records(root)
    identifiers = [str(record.get("unique_id") or record.get("id") or "") for record in records]
    duplicates = sorted({value for value in identifiers if value and identifiers.count(value) > 1})
    checks.append(
        Check(
            "bottles.json",
            not duplicates,
            "no duplicate records" if not duplicates else "duplicate ids: " + ", ".join(duplicates),
            "The desktop app rewrites this file on its next scan; open it and refresh.",
            severity="warning",
        )
    )

    installed = {engine.version for engine in snapshot.engines if engine.healthy}
    universal = [
        engine for engine in snapshot.engines
        if engine.version == contract.UNIVERSAL and engine.size >= ENGINE_MIN_BYTES
    ]
    checks.append(
        Check(
            "Engine 11.17 Universal",
            bool(universal),
            f"{universal[0].size / GIB:.2f} GB" if universal else "not installed",
            "Install it from the app's setup screen.",
        )
    )
    steam = [
        engine for engine in snapshot.engines
        if engine.version == contract.STEAM and engine.size >= ENGINE_MIN_BYTES
    ]
    checks.append(
        Check(
            "Engine 11.17 Steam",
            bool(steam),
            f"{steam[0].size / GIB:.2f} GB" if steam else "not installed",
            "Only needed for Steam bottles.",
            severity="warning",
        )
    )
    tiny = [engine.name for engine in snapshot.engines if not engine.healthy]
    checks.append(
        Check(
            "Engine archives look complete",
            not tiny,
            "all plausible" if not tiny else "too small: " + ", ".join(tiny[:3]),
            "Re-download the engine in WehniX setup; a partial file cannot be extracted.",
        )
    )
    checks.append(
        Check(
            "Engine for new bottles",
            bool(snapshot.engines) or bool(installed),
            snapshot.engine_version,
            "Set it in the app or with `WehniX settings set engine_version 11.17-universal`.",
            severity="warning",
        )
    )

    version = macos_version()
    checks.append(
        Check(
            "macOS version",
            version >= MIN_MACOS,
            ".".join(str(part) for part in version) or "unknown",
            "WehniX needs macOS 13 or newer.",
        )
    )

    machine = platform.machine()
    rosetta = rosetta_ok()
    checks.append(
        Check(
            "Rosetta 2",
            rosetta,
            "not required on Intel" if machine not in ("arm64", "aarch64") else ("installed" if rosetta else "missing"),
            "softwareupdate --install-rosetta --agree-to-license",
        )
    )

    free = free_space_gb(root if exists else Path.home())
    checks.append(
        Check(
            "Free disk space",
            free >= MIN_FREE_GIB,
            f"{free:.0f} GB available",
            "A bottle plus an engine needs roughly 15 GB.",
        )
    )

    log_dir = root / "logs"
    checks.append(
        Check(
            "Log file",
            snapshot.log_path is not None,
            str(snapshot.log_path) if snapshot.log_path else "not written yet",
            "Created when the app runs.",
            severity="warning",
        )
    )
    checks.append(
        Check(
            "Log folder writable",
            os.access(log_dir, os.W_OK) if log_dir.is_dir() else False,
            str(log_dir) if log_dir.is_dir() else "missing",
            "`WehniX --init` adds it without touching your bottles.",
            severity="warning",
        )
    )

    cli_on_path = any(
        (Path(entry) / name).exists()
        for entry in os.environ.get("PATH", "").split(os.pathsep)
        if entry
        for name in ("WehniX", "wehnix", "wehniX", "Wehnix")
    )
    checks.append(
        Check(
            "CLI on PATH",
            cli_on_path,
            "yes" if cli_on_path else "not found",
            "Add ~/.local/bin to PATH, or run scripts/install.sh.",
            severity="warning",
        )
    )

    copies = _app_copies()
    loop_bundle = any(part.endswith(".app") for part in Path.cwd().parts)
    checks.append(
        Check(
            "WehniX.app installed",
            bool(copies),
            ", ".join(str(path) for path in copies[:2]) or "not in Applications",
            "Drag WehniX.app into /Applications so bottles can find it.",
            severity="warning" if loop_bundle else "error",
        )
    )
    if len(copies) > 1:
        checks.append(
            Check(
                "One copy of WehniX.app",
                False,
                f"{len(copies)} copies found — updates can replace the wrong one",
                "Keep the copy in /Applications and move the others to the Trash.",
                severity="warning",
            )
        )

    running = app_is_running()
    checks.append(
        Check(
            "WehniX app closed for writes",
            not running,
            "running — the CLI will refuse to write" if running else "not running",
            "Quit WehniX before creating, deleting or changing settings.",
            severity="warning",
        )
    )
    return checks


def summary(checks: list[Check]) -> tuple[int, int]:
    errors = sum(1 for check in checks if not check.ok and check.severity == "error")
    warnings = sum(1 for check in checks if not check.ok and check.severity == "warning")
    return errors, warnings
