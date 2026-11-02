"""Plain data shapes shared by the state layer and the UI.

These mirror what the desktop app writes into ``bottles.json`` and into each
bottle's ``Info.plist``. A field that exists here but nowhere in the app would
be a lie in the interface, so every one traces back to a real key.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path


def human_bytes(value: int | None) -> str:
    """1.4 GB, 812 MB, 3.2 TB — the way a person reads a size."""
    if value is None:
        return "—"
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(size)} B"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def human_age(timestamp: float | None) -> str:
    """'3 min ago', '2 days ago' — never a raw epoch."""
    if not timestamp:
        return "—"
    delta = max(0, time.time() - timestamp)
    if delta < 90:
        return "just now"
    if delta < 3600:
        return f"{int(delta // 60)} min ago"
    if delta < 86400:
        return f"{int(delta // 3600)} h ago"
    if delta < 86400 * 30:
        return f"{int(delta // 86400)} d ago"
    return time.strftime("%Y-%m-%d", time.localtime(timestamp))


def short_path(path: Path | None, keep: int = 3) -> str:
    """~-relative path, trimmed from the left when it is too long for a panel."""
    if path is None:
        return "—"
    text = str(path)
    home = str(Path.home())
    if text.startswith(home):
        text = "~" + text[len(home):]
    parts = [part for part in text.split("/") if part]
    if len(parts) <= keep:
        return text if text.startswith("/") else "/" + text
    prefix = "~/" if text.startswith("~/") else "…/"
    return prefix + "/".join(parts[-keep:])


def compact_path(path: Path | None, width: int = 28) -> str:
    """A path that fits a narrow sidebar: home-aware, then only the leaf."""
    if path is None:
        return "—"
    text = str(path)
    home = str(Path.home())
    if text.startswith(home):
        text = "~" + text[len(home):]
    if len(text) <= width:
        return text
    parts = [part for part in text.split("/") if part]
    leaf = parts[-1] if parts else text
    prefix = "~/…/" if text.startswith("~") else "…/"
    candidate = prefix + leaf
    if len(candidate) <= width:
        return candidate
    return candidate[: max(4, width - 1)] + "…"


@dataclass
class Bottle:
    """One Windows environment, exactly as the desktop app stores it.

    ``path`` is the folder under ``bottles/`` and ``app_path`` is the ``.app``
    inside it; for flat bottle folders they are the same path. Keeping both is
    what lets a record written by either front end be understood.
    """

    name: str
    path: Path
    unique_id: str = ""
    app_path: Path | None = None
    engine: str = "unknown"
    edition: str = ""
    env_type: str = ""
    renderer: str = ""
    program_path: str = ""
    program_flags: str = ""
    metal_hud: bool = False
    sync: str = "auto"
    high_res: bool = False
    modified: float = 0.0
    size: int | None = None
    in_registry: bool = False

    @property
    def kind(self) -> str:
        return "bundle" if (self.path / "Contents" / "Info.plist").is_file() else "prefix"

    @property
    def c_drive(self) -> Path | None:
        """Where this bottle's C: actually lives, whichever layout it uses."""
        base = self.app_path or self.path
        candidates = [
            base / "drive_c",
            base / "Contents" / "SharedSupport" / "prefix" / "drive_c",
        ]
        prefixes = base / "Contents" / "Resources" / "state" / "prefixes"
        if prefixes.is_dir():
            candidates.extend(sorted(prefixes.glob("*/drive_c")))
        for candidate in candidates:
            if candidate.is_dir():
                return candidate
        return None

    @property
    def label_engine(self) -> str:
        if self.engine in ("", "unknown"):
            return "unknown"
        return self.engine.replace("11.17-", "11.17 ").replace("-", " ").title()

    @property
    def label_env(self) -> str:
        return (self.env_type or "—").title()

    @property
    def renderer_label(self) -> str:
        return (self.renderer or "—").upper()


@dataclass
class EngineArtifact:
    """An installed engine archive in ``Engine/``."""

    name: str
    path: Path
    size: int
    version: str = "unknown"
    edition: str = ""
    label: str = ""
    creatable: bool = False
    note: str = ""
    healthy: bool = True

    @property
    def state(self) -> str:
        if not self.healthy:
            return "suspiciously small"
        if self.creatable:
            return "ready"
        return "existing bottles only"


@dataclass
class Game:
    """A Windows game found inside a bottle's Steam library."""

    title: str
    appid: str
    bottle: str
    path: Path
    source: str = "steam"

    @property
    def key(self) -> str:
        return f"{self.bottle}:{self.appid}"


@dataclass
class Check:
    """One doctor line."""

    name: str
    ok: bool
    detail: str = ""
    hint: str = ""
    severity: str = "error"  # error | warning


@dataclass
class Snapshot:
    """Everything the UI draws, read once per refresh."""

    root: Path
    exists: bool
    config: dict = field(default_factory=dict)
    bottles: list[Bottle] = field(default_factory=list)
    engines: list[EngineArtifact] = field(default_factory=list)
    games: list[Game] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)
    log_path: Path | None = None
    error: str = ""
    read_at: float = field(default_factory=time.time)

    @property
    def settings(self) -> dict:
        return (self.config or {}).get("settings") or {}

    @property
    def engine_version(self) -> str:
        return str(self.settings.get("engine_version") or "not set")

    @property
    def setup_complete(self) -> bool:
        return bool((self.config or {}).get("setup_complete"))

    @property
    def total_bottle_bytes(self) -> int:
        return sum(b.size or 0 for b in self.bottles)

    @property
    def total_engine_bytes(self) -> int:
        return sum(e.size or 0 for e in self.engines)
