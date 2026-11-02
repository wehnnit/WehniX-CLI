"""Health checks, shared by the Doctor screen and ``WehniX doctor``.

Each check answers a question a person would actually ask before creating a
bottle or filing a bug: is the data folder there, does the app agree it is set
up, is the engine a real one, will the bottle launch once it exists. Hints are
commands you can paste, not advice.

Every check also carries a ``status``: ``passed``, ``failed``, ``warning`` or
``skipped``. A skipped check is a question that cannot be answered yet, almost
always because the data folder has never been created. It is not a failure, is
not counted as one, and is drawn dim instead of red — otherwise a Mac that has
simply never run WehniX reports a dozen "errors" for one missing folder.

Engines are installed by the desktop app's setup, not by this CLI, so the
engine checks say that rather than implying the terminal client is broken.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path

from . import contract
from .models import Check, Snapshot
from .state import (
    BOTTLES_JSON,
    CONFIG_JSON,
    ENGINE_MIN_BYTES,
    app_is_running,
    load_records,
    read_snapshot,
    state_root,
)

GIB = 1024**3
MIN_MACOS = (13, 0)
MIN_FREE_GIB = 15

SETUP_HINT = (
    "Open WehniX.app once and finish its setup — the app creates this folder "
    "and installs the engines. `WehniX --init` only adds terminal-only files."
)


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


def _skipped(name: str, detail: str, hint: str = "") -> Check:
    """A question that cannot be judged yet — not a failure."""
    return Check(name, True, detail, hint, severity="info", status="skipped")


# ---------------------------------------------------------------------------
# State that belongs to the desktop app
# ---------------------------------------------------------------------------


def _state_checks(root: Path, exists: bool, ready: bool, snapshot: Snapshot) -> list[Check]:
    checks: list[Check] = []

    if ready:
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
            )
        )
    else:
        checks.append(
            _skipped(
                "Private data folder",
                "not created yet" if not exists else "cannot be checked — the folder is not readable",
            )
        )

    config_path = root / CONFIG_JSON
    if not ready:
        checks.append(_skipped("config.json", "no data folder yet"))
        checks.append(_skipped("Setup complete", "no data folder yet"))
    else:
        readable_config = config_path.is_file()
        if not readable_config:
            checks.append(
                Check(
                    "config.json",
                    False,
                    "missing — the app writes it during setup",
                    "Open WehniX.app and finish setup, or `WehniX --init` if you "
                    "deliberately want terminal-only files.",
                    severity="warning",
                )
            )
        else:
            checks.append(
                Check(
                    "config.json",
                    bool(snapshot.config),
                    "readable" if snapshot.config else "unreadable or not a JSON object",
                    "Move it aside and let WehniX write a fresh one, or fix the JSON.",
                )
            )
        if snapshot.setup_complete:
            checks.append(Check("Setup complete", True, "yes"))
        elif not readable_config:
            checks.append(
                Check(
                    "Setup complete",
                    False,
                    "not yet — the app asks on first launch",
                    "Finish setup in WehniX; the CLI cannot run it for you.",
                    severity="warning",
                )
            )
        else:
            checks.append(
                Check(
                    "Setup complete",
                    False,
                    "no — the app will ask on first launch",
                    "Finish setup in the app.",
                    severity="warning",
                )
            )

    bottles_dir = root / "bottles"
    bottles_ready = ready and bottles_dir.is_dir()
    if not ready:
        checks.append(_skipped("Bottles folder", "no data folder yet"))
        checks.append(_skipped("Bottle bundles", "no data folder yet"))
        checks.append(_skipped("bottles.json", "no data folder yet"))
        return checks

    if bottles_dir.is_dir():
        checks.append(
            Check("Bottles folder", True, f"{len(snapshot.bottles)} bottle(s)")
        )
    else:
        checks.append(
            Check(
                "Bottles folder",
                False,
                "missing — created when the first bottle is made",
                "Create a bottle in WehniX, or press n in this CLI.",
                severity="warning",
            )
        )

    broken = [bottle.name for bottle in snapshot.bottles if bottle.app_path is None]
    if bottles_ready:
        checks.append(
            Check(
                "Bottle bundles",
                not broken,
                "all readable" if not broken else "no app bundle in: " + ", ".join(broken[:3]),
                "Open the bottle in WehniX; a partial copy has to be recreated.",
            )
        )
    else:
        checks.append(_skipped("Bottle bundles", "no bottles yet"))

    records_path = root / BOTTLES_JSON
    if not records_path.is_file():
        checks.append(_skipped("bottles.json", "no bottle records yet"))
    else:
        records = load_records(root)
        identifiers = [
            str(record.get("unique_id") or record.get("id") or "") for record in records
        ]
        duplicates = sorted(
            {value for value in identifiers if value and identifiers.count(value) > 1}
        )
        checks.append(
            Check(
                "bottles.json",
                not duplicates,
                "no duplicate records" if not duplicates else "duplicate ids: " + ", ".join(duplicates),
                "The desktop app rewrites this file on its next scan; open it and refresh.",
                severity="warning",
            )
        )
    return checks


# ---------------------------------------------------------------------------
# Engines
# ---------------------------------------------------------------------------


def _engine_checks(
    snapshot: Snapshot, ready: bool, app_installed: bool
) -> list[Check]:
    names = (
        "Engine 11.17 Universal",
        "Engine 11.17 Steam",
        "Engine archives look complete",
        "Engine for new bottles",
    )
    if not ready:
        return [_skipped(name, "no data folder yet") for name in names]

    checks: list[Check] = []
    installed = {engine.version for engine in snapshot.engines if engine.healthy}

    universal = [
        engine
        for engine in snapshot.engines
        if engine.version == contract.UNIVERSAL and engine.size >= ENGINE_MIN_BYTES
    ]
    checks.append(
        Check(
            "Engine 11.17 Universal",
            bool(universal),
            f"{universal[0].size / GIB:.2f} GB" if universal else "not installed yet",
            "Open WehniX and finish setup — the app downloads it."
            if app_installed
            else "Install WehniX.app, then run its setup; the CLI cannot download engines.",
            severity="warning",
        )
    )

    steam = [
        engine
        for engine in snapshot.engines
        if engine.version == contract.STEAM and engine.size >= ENGINE_MIN_BYTES
    ]
    checks.append(
        Check(
            "Engine 11.17 Steam",
            bool(steam),
            f"{steam[0].size / GIB:.2f} GB" if steam else "not installed yet",
            "Only needed for Steam bottles; install it from setup in WehniX.",
            severity="warning",
        )
    )

    tiny = [engine.name for engine in snapshot.engines if not engine.healthy]
    if not snapshot.engines:
        checks.append(_skipped("Engine archives look complete", "no engine archives yet"))
    else:
        checks.append(
            Check(
                "Engine archives look complete",
                not tiny,
                "all plausible" if not tiny else "too small: " + ", ".join(tiny[:3]),
                "Re-download the engine in WehniX setup; a partial file cannot be extracted.",
            )
        )

    if not snapshot.engines:
        checks.append(_skipped("Engine for new bottles", "no engine installed yet"))
    else:
        checks.append(
            Check(
                "Engine for new bottles",
                bool(installed),
                snapshot.engine_version,
                "Re-download a complete engine in WehniX setup, or set the version "
                "with `WehniX settings set engine_version 11.17-universal`.",
            )
        )
    return checks


# ---------------------------------------------------------------------------
# The Mac itself
# ---------------------------------------------------------------------------


def _machine_checks(disk_path: Path) -> list[Check]:
    checks: list[Check] = []

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
            "not required on Intel"
            if machine not in ("arm64", "aarch64")
            else ("installed" if rosetta else "missing"),
            "softwareupdate --install-rosetta --agree-to-license",
        )
    )

    free = free_space_gb(disk_path)
    checks.append(
        Check(
            "Free disk space",
            free >= MIN_FREE_GIB,
            f"{free:.0f} GB available",
            "A bottle plus an engine needs roughly 15 GB.",
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
    return checks


def _log_checks(root: Path, ready: bool, snapshot: Snapshot) -> list[Check]:
    if not ready:
        return [
            _skipped("Log file", "no data folder yet"),
            _skipped("Log folder writable", "no data folder yet"),
        ]
    log_dir = root / "logs"
    return [
        Check(
            "Log file",
            snapshot.log_path is not None,
            str(snapshot.log_path) if snapshot.log_path else "not written yet",
            "Created when the app runs.",
            severity="warning",
        ),
        Check(
            "Log folder writable",
            os.access(log_dir, os.W_OK) if log_dir.is_dir() else False,
            str(log_dir) if log_dir.is_dir() else "missing",
            "`WehniX --init` adds it without touching your bottles.",
            severity="warning",
        ),
    ]


def _app_checks(copies: list[Path]) -> list[Check]:
    checks: list[Check] = [
        Check(
            "WehniX.app installed",
            bool(copies),
            ", ".join(str(path) for path in copies[:2]) or "not in Applications",
            "Install WehniX.app in /Applications; its setup is what installs engines "
            "and creates the data folder.",
            severity="warning",
        )
    ]
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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_checks() -> list[Check]:
    root = state_root()
    checks: list[Check] = []

    exists = root.is_dir()
    readable = exists and os.access(root, os.R_OK | os.X_OK)

    if exists:
        checks.append(Check("Data folder", True, str(root)))
        checks.append(
            Check(
                "Data folder permissions",
                readable,
                "readable" if readable else "not readable by this user",
                f"ls -ld '{root}'",
            )
        )
    else:
        checks.append(
            Check(
                "Data folder",
                False,
                f"{root} does not exist yet",
                SETUP_HINT,
            )
        )

    ready = exists and readable
    snapshot = read_snapshot(with_sizes=False, with_games=False) if ready else Snapshot(root=root, exists=exists)
    copies = _app_copies()

    checks.extend(_state_checks(root, exists, ready, snapshot))
    checks.extend(_engine_checks(snapshot, ready, bool(copies)))
    checks.extend(_machine_checks(root if ready else Path.home()))
    checks.extend(_log_checks(root, ready, snapshot))
    checks.extend(_app_checks(copies))
    return checks


def summary(checks: list[Check]) -> tuple[int, int]:
    """Failures and cautions. A skipped check is neither."""
    errors = sum(1 for check in checks if check.status == "failed")
    warnings = sum(1 for check in checks if check.status == "warning")
    return errors, warnings
