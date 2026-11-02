"""The Textual application: sidebar, views, modals, key bindings.

Reading happens once per refresh into a :class:`Snapshot`; views only draw it.
Anything slow — ``du`` over a bottle, scanning Steam manifests, ``--json``-sized
state — runs in a worker so the interface never freezes while it waits.
"""

from __future__ import annotations

from pathlib import Path

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    ContentSwitcher,
    DataTable,
    Footer,
    Input,
    Label,
    ListItem,
    ListView,
    RichLog,
    Select,
    Static,
)

from .. import __version__
from ..actions import (
    ActionError,
    available_bottle_settings,
    create_bottle,
    delete_bottle,
    open_desktop_app,
    open_path,
    reveal,
    set_bottle_setting,
    set_setting,
    tail_log,
)
from ..contract import SETTING_HELP, bottle_types_for_engine, engine_label
from ..doctor import run_checks, summary
from ..models import Bottle, EngineArtifact, compact_path, human_age, human_bytes, short_path
from ..state import app_is_running, prepare_state_dir, read_snapshot
from .style import ACCENT, BRAND, CSS, ERR, MUTED, OK, TEXT, WARN

NAV = (
    ("bottles", "Bottles", "◆"),
    ("games", "Games", "▶"),
    ("engine", "Engines", "▣"),
    ("doctor", "Doctor", "✚"),
    ("logs", "Logs", "≡"),
    ("settings", "Settings", "⚙"),
    ("storage", "Storage", "▤"),
)

REFRESH_SECONDS = 15
TAIL_SECONDS = 3
LOG_LINES = 400


def _mark(ok: bool, severity: str = "error", status: str = "") -> str:
    state = status or (
        "passed" if ok else ("warning" if severity in ("warning", "info") else "failed")
    )
    if state == "passed":
        return f"[{OK}]✓[/]"
    if state == "skipped":
        return f"[{MUTED}]–[/]"
    if state == "warning":
        return f"[{WARN}]![/]"
    return f"[{ERR}]✗[/]"


# --------------------------------------------------------------------------
# Views
# --------------------------------------------------------------------------


class BottlesView(Vertical):
    """The list you actually came for."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._bottles: dict[str, Bottle] = {}

    def compose(self) -> ComposeResult:
        yield Input(placeholder="Filter bottles by name, engine or renderer…", id="bottle-search")
        yield Static("", id="empty", classes="empty")
        yield DataTable(id="bottles-table")
        yield Static("", id="bottle-detail")

    def on_mount(self) -> None:
        table = self.query_one("#bottles-table", DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True
        table.add_columns("NAME", "ENGINE", "TYPE", "RENDERER", "LAST USED", "SIZE")

    def load(self, bottles: list[Bottle], query: str = "", root: Path | None = None) -> None:
        table = self.query_one("#bottles-table", DataTable)
        empty = self.query_one("#empty", Static)
        needle = query.strip().lower()
        visible = [
            bottle
            for bottle in bottles
            if not needle
            or needle in bottle.name.lower()
            or needle in bottle.label_engine.lower()
            or needle in bottle.renderer.lower()
            or needle in bottle.env_type.lower()
        ]
        table.clear()
        self._bottles = {}
        for bottle in visible:
            key = str(bottle.path)
            self._bottles[key] = bottle
            table.add_row(
                bottle.name,
                bottle.label_engine,
                bottle.label_env,
                bottle.renderer_label,
                human_age(bottle.modified),
                human_bytes(bottle.size),
                key=key,
            )
        table.display = bool(visible)
        empty.display = not visible
        if not visible:
            if bottles and needle:
                empty.update(
                    f"[{MUTED}]Nothing matches “{query}”.[/]\n\n"
                    f"Press [{ACCENT}]escape[/] to clear the filter."
                )
            else:
                empty.update(
                    f"[{MUTED}]No bottles yet.[/]\n\n"
                    f"Press [{OK}]n[/] to make one from an installed engine, "
                    f"or [{OK}]o[/] to open the WehniX window.\n\n"
                    f"[{MUTED}]They live in {short_path((root or Path.home()) / 'bottles', 2)}[/]"
                )
        self.update_detail(self.selected_bottle())

    def selected_bottle(self) -> Bottle | None:
        table = self.query_one("#bottles-table", DataTable)
        if not self._bottles or table.cursor_row < 0:
            return None
        try:
            row_key = table.coordinate_to_cell_key((table.cursor_row, 0)).row_key
        except Exception:
            return None
        return self._bottles.get(str(row_key.value))

    def update_detail(self, bottle: Bottle | None) -> None:
        detail = self.query_one("#bottle-detail", Static)
        if bottle is None:
            detail.update(f"[{MUTED}]Select a bottle to see where it lives.[/]")
            return
        c_drive = compact_path(bottle.c_drive, 34) if bottle.c_drive else "not provisioned yet"
        program = bottle.program_path or "—"
        if len(program) > 40:
            program = "…" + program[-38:]
        lines = [
            f"[bold]{bottle.name}[/]   [{MUTED}]{bottle.kind}[/]   "
            f"[{MUTED}]env[/] [{OK}]{bottle.label_env}[/]",
            f"[{MUTED}]engine[/] [{OK}]{bottle.label_engine}[/]   "
            f"[{MUTED}]renderer[/] [{OK}]{bottle.renderer_label}[/]   "
            f"[{MUTED}]size[/] [{OK}]{human_bytes(bottle.size)}[/]",
            # A non-breaking space keeps the value from touching the label when
            # the terminal renders at an odd width (and in the SVG screenshot).
            f"[{MUTED}]program[/]\u00a0{program}",
            f"[{MUTED}]C:[/]\u00a0{c_drive}",
            f"[{MUTED}]{compact_path(bottle.path, 52)}[/]",
        ]
        detail.update("\n".join(lines))


class GamesView(Vertical):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._games: dict[str, object] = {}

    def compose(self) -> ComposeResult:
        yield Static("", id="games-empty", classes="empty")
        yield DataTable(id="games-table")

    def on_mount(self) -> None:
        table = self.query_one("#games-table", DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True
        table.add_columns("GAME", "APP ID", "BOTTLE", "LIBRARY")

    def load(self, games) -> None:
        table = self.query_one("#games-table", DataTable)
        empty = self.query_one("#games-empty", Static)
        table.clear()
        self._games = {}
        for game in games:
            self._games[game.key] = game
            table.add_row(
                game.title,
                game.appid,
                game.bottle,
                short_path(game.path, 2),
                key=game.key,
            )
        table.display = bool(games)
        empty.display = not games
        if not games:
            empty.update(
                f"[{MUTED}]No Steam libraries found inside your bottles yet.[/]\n\n"
                f"Install Steam in a Steam bottle and its games appear here.\n"
                f"[{MUTED}]Epic titles are managed by the desktop app and are not read here.[/]"
            )

    def selected_game(self):
        table = self.query_one("#games-table", DataTable)
        if not self._games or table.cursor_row < 0:
            return None
        try:
            row_key = table.coordinate_to_cell_key((table.cursor_row, 0)).row_key
        except Exception:
            return None
        return self._games.get(str(row_key.value))


class EngineView(Vertical):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._engines: dict[str, EngineArtifact] = {}

    def compose(self) -> ComposeResult:
        yield Static("", id="engine-empty", classes="empty")
        yield DataTable(id="engine-table")

    def on_mount(self) -> None:
        table = self.query_one("#engine-table", DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True
        table.add_columns("ARCHIVE", "VERSION", "SIZE", "STATE", "NEW BOTTLES")

    def load(self, engines: list[EngineArtifact], root: Path) -> None:
        table = self.query_one("#engine-table", DataTable)
        empty = self.query_one("#engine-empty", Static)
        table.clear()
        self._engines = {}
        for engine in engines:
            key = str(engine.path)
            self._engines[key] = engine
            state = f"[{OK}]ready[/]" if engine.healthy else f"[{WARN}]suspiciously small[/]"
            creatable = (
                f"[{OK}]yes[/] — {', '.join(bottle_types_for_engine(engine.version)['allowed'])}"
                if engine.creatable
                else f"[{MUTED}]no[/]"
            )
            table.add_row(engine.name, engine.version, human_bytes(engine.size), state, creatable, key=key)
        table.display = bool(engines)
        empty.display = not engines
        if not engines:
            empty.update(
                f"[{MUTED}]No engines installed.[/]\n\n"
                f"Run [{ACCENT}]WehniX setup[/] to install the Universal engine, or open "
                f"WehniX and finish its setup. An archive dropped into "
                f"[{MUTED}]{root / 'Engine'}[/] is picked up too."
            )


class DoctorView(Vertical):
    def compose(self) -> ComposeResult:
        yield VerticalScroll(id="doctor-scroll")

    def load(self, checks) -> None:
        scroll = self.query_one("#doctor-scroll", VerticalScroll)
        scroll.remove_children()
        for check in checks:
            skipped = check.status == "skipped"
            detail = f"  [{MUTED}]{check.detail}[/]" if check.detail else ""
            hint = "" if check.ok else f"\n[{MUTED}]    {check.hint}[/]"
            if skipped:
                name, classes = f"[{MUTED}]{check.name}[/]", "doctor-row skipped"
            elif check.ok:
                name, classes = check.name, "doctor-row"
            else:
                name, classes = f"[bold]{check.name}[/]", "doctor-row"
            scroll.mount(
                Static(
                    f"{_mark(check.ok, check.severity, check.status)} {name}{detail}{hint}",
                    classes=classes,
                )
            )


class LogsView(Vertical):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.following = True

    def compose(self) -> ComposeResult:
        yield RichLog(id="log-view", wrap=True, highlight=False, markup=False)
        yield Static("", id="log-hint")

    def load(self, snapshot) -> None:
        log = self.query_one("#log-view", RichLog)
        log.clear()
        if not snapshot.log_path:
            log.write("No log yet — WehniX writes one when it runs.")
            self.query_one("#log-hint", Static).update("")
            return
        for line in tail_log(snapshot.log_path, LOG_LINES):
            log.write(line.rstrip("\n"))
        self._paint_hint(snapshot)

    def append(self, lines: list[str]) -> None:
        log = self.query_one("#log-view", RichLog)
        for line in lines:
            log.write(line.rstrip("\n"))
        if self.following:
            log.scroll_end(animate=False)

    def _paint_hint(self, snapshot) -> None:
        state = f"[{OK}]following[/]" if self.following else f"[{MUTED}]paused[/]"
        path = short_path(snapshot.log_path, 3) if snapshot.log_path else "no log yet"
        self.query_one("#log-hint", Static).update(
            f"[{MUTED}]{path}[/]   {state}   [{MUTED}]t toggles · r reloads[/]"
        )

    def toggle_follow(self) -> None:
        self.following = not self.following


class SettingsView(Vertical):
    """The config keys this CLI is allowed to write, and nothing else."""

    KEYS = ("engine_version", "graphics_backend", "auto_check_updates")

    def compose(self) -> ComposeResult:
        yield Static("", id="settings-empty", classes="empty")
        yield DataTable(id="settings-table")

    def on_mount(self) -> None:
        table = self.query_one("#settings-table", DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True
        table.add_columns("SETTING", "VALUE", "WHAT IT DOES")

    def load(self, settings: dict) -> None:
        table = self.query_one("#settings-table", DataTable)
        table.clear()
        for key in self.KEYS:
            table.add_row(key, str(settings.get(key, "—")), SETTING_HELP.get(key, ""), key=key)
        table.display = True
        self.query_one("#settings-empty", Static).display = False

    def selected_key(self) -> str | None:
        table = self.query_one("#settings-table", DataTable)
        if table.cursor_row < 0:
            return None
        try:
            return str(table.coordinate_to_cell_key((table.cursor_row, 0)).row_key.value)
        except Exception:
            return None


class StorageView(Vertical):
    def compose(self) -> ComposeResult:
        yield VerticalScroll(id="storage")

    def load(self, snapshot) -> None:
        scroll = self.query_one("#storage", VerticalScroll)
        scroll.remove_children()
        bottle_bytes = snapshot.total_bottle_bytes
        engine_bytes = snapshot.total_engine_bytes
        total = bottle_bytes + engine_bytes
        cards = [
            ("Bottles", human_bytes(bottle_bytes), f"{len(snapshot.bottles)} bottle(s)"),
            ("Engines", human_bytes(engine_bytes), f"{len(snapshot.engines)} archive(s)"),
            ("Total", human_bytes(total), short_path(snapshot.root, 3)),
        ]
        for title, value, note in cards:
            scroll.mount(
                Static(
                    f"[{MUTED}]{title}[/]\n"
                    f"[{ACCENT}]{value}[/]\n"
                    f"[{MUTED}]{note}[/]",
                    classes="storage-card",
                )
            )


# --------------------------------------------------------------------------
# Modals
# --------------------------------------------------------------------------


class NewBottleModal(ModalScreen):
    """Name a bottle, pick its engine and what kind of bottle it is."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, engines: list[EngineArtifact]) -> None:
        super().__init__()
        self.engines = [engine for engine in engines if engine.creatable]

    def _engine_options(self, engine: EngineArtifact) -> list[tuple[str, str]]:
        allowed = bottle_types_for_engine(engine.version)["allowed"]
        return [(kind.title(), kind) for kind in allowed]

    def compose(self) -> ComposeResult:
        options = [
            (f"{engine_label(engine.version)} — {human_bytes(engine.size)}", str(engine.path))
            for engine in self.engines
        ]
        first = self.engines[0]
        with Vertical(id="dialog"):
            yield Static("New bottle", classes="title")
            yield Static(
                "Built from an engine archive you already have. Nothing is downloaded.",
                classes="hint",
            )
            yield Input(placeholder="Bottle name", id="bottle-name")
            yield Select(options, value=options[0][1], allow_blank=False, id="bottle-engine")
            yield Select(
                self._engine_options(first),
                value=bottle_types_for_engine(first.version)["default"],
                allow_blank=False,
                id="bottle-env",
            )
            yield Static(bottle_types_for_engine(first.version)["note"], id="bottle-note", classes="hint")
            with Horizontal(id="dialog-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Create", id="create", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#bottle-name", Input).focus()

    @on(Select.Changed, "#bottle-engine")
    def _engine_changed(self) -> None:
        engine = self._selected_engine()
        if engine is None:
            return
        kinds = self._engine_options(engine)
        self.query_one("#bottle-env", Select).set_options(kinds)
        self.query_one("#bottle-note", Static).update(bottle_types_for_engine(engine.version)["note"])

    def _selected_engine(self) -> EngineArtifact | None:
        selection = self.query_one("#bottle-engine", Select).value
        return next((engine for engine in self.engines if str(engine.path) == selection), None)

    @on(Button.Pressed, "#cancel")
    def _cancel(self) -> None:
        self.action_cancel()

    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#create")
    def _create(self) -> None:
        name = self.query_one("#bottle-name", Input).value.strip()
        engine = self._selected_engine()
        kinds = self.query_one("#bottle-env", Select).value
        if not name:
            self.notify("Give the bottle a name.", severity="warning")
            return
        if engine is None:
            self.notify("Pick an engine.", severity="warning")
            return
        self.dismiss((name, engine, str(kinds)))

    @on(Input.Submitted, "#bottle-name")
    def _submit(self) -> None:
        self._create()


class BottleDetailsModal(ModalScreen):
    BINDINGS = [Binding("escape", "close", "Close")]

    def __init__(self, bottle: Bottle) -> None:
        super().__init__()
        self.bottle = bottle

    def compose(self) -> ComposeResult:
        bottle = self.bottle
        rows = [
            ("Engine", bottle.label_engine),
            ("Edition", bottle.edition or "—"),
            ("Environment", bottle.label_env),
            ("Renderer", bottle.renderer_label),
            ("Program", bottle.program_path or "—"),
            ("Flags", bottle.program_flags or "—"),
            ("Sync", bottle.sync),
            ("Metal HUD", "on" if bottle.metal_hud else "off"),
            ("High resolution", "on" if bottle.high_res else "off"),
            ("Size", human_bytes(bottle.size)),
            ("Folder", str(bottle.path)),
            ("App", str(bottle.app_path) if bottle.app_path else "—"),
            ("C: drive", str(bottle.c_drive) if bottle.c_drive else "not provisioned yet"),
            ("Registry", "bottles.json" if bottle.in_registry else "found on disk only"),
            ("Settings from", bottle.settings_source or "unknown"),
        ]
        with Vertical(id="help"):
            yield Static(bottle.name, classes="title")
            for label, value in rows:
                yield Static(f"[{ACCENT}]{label:<16}[/] [{MUTED}]{value}[/]")
            yield Static("")
            if bottle.settings_error:
                yield Static(f"[{WARN}]{bottle.settings_error}[/]")
            yield Static(
                f"[{MUTED}]Press [{OK}]e[/] to change the renderer, sync, Metal HUD, "
                f"high resolution or launch program. Only options this engine "
                f"supports are offered.[/]"
            )

    def action_close(self) -> None:
        self.dismiss(None)


class BottleSettingsModal(ModalScreen):
    """Edit one bottle, offering only what its engine supports.

    Copied from wehnix_app.py :: update_bottle_app_settings: the desktop decides
    from the engine, not from the registry, and a value the engine refuses is
    never written. Unsupported fields stay visible but disabled, with the reason.
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+s", "save", "Save"),
    ]

    def __init__(self, bottle: Bottle, options: dict) -> None:
        super().__init__()
        self.bottle = bottle
        self.options = options
        self.current = options.get("current") or {}

    def compose(self) -> ComposeResult:
        options = self.options
        current = self.current
        renderers = [
            (contract_label, name)
            for name, detail in options["renderers"].items()
            if detail["available"]
            for contract_label in (name.upper(),)
        ]
        if not renderers:
            renderers = [("DXMT", "dxmt")]
        renderer_value = current.get("renderer")
        if renderer_value not in {value for _label, value in renderers}:
            renderer_value = renderers[0][1]
        syncs = [(mode.upper(), mode) for mode in options["sync_modes"]]
        sync_value = current.get("sync")
        if sync_value not in {value for _label, value in syncs}:
            sync_value = syncs[0][1]
        locked = bool(options["program_locked"])
        high_res_supported = bool(options["high_res"])

        with Vertical(id="dialog", classes="settings-dialog"):
            yield Static(f"Settings · {self.bottle.name}", classes="title")
            yield Static(
                f"{engine_label(self.bottle.engine)} · {options['runtime']} · "
                f"written to this bottle's own engine files",
                classes="hint",
            )
            with VerticalScroll(id="settings-form"):
                yield Static(f"[{MUTED}]Renderer[/]")
                yield Select(renderers, value=renderer_value, allow_blank=False, id="bs-renderer")
                yield Static(f"[{MUTED}]Sync[/]")
                yield Select(syncs, value=sync_value, allow_blank=False, id="bs-sync")
                yield Static(f"[{MUTED}]Metal HUD[/]")
                yield Select(
                    [("On", "on"), ("Off", "off")],
                    value="on" if current.get("metal_hud") else "off",
                    allow_blank=False,
                    id="bs-hud",
                )
                yield Static(
                    f"[{MUTED}]High resolution[/]"
                    + ("" if high_res_supported else f" [{MUTED}]— not on this engine[/]")
                )
                yield Select(
                    [("On", "on"), ("Off", "off")],
                    value="on" if current.get("high_res") else "off",
                    allow_blank=False,
                    id="bs-high",
                    disabled=not high_res_supported,
                )
                yield Static(
                    f"[{MUTED}]Program[/]"
                    + (f" [{MUTED}]— locked[/]" if locked else "")
                )
                yield Input(
                    value=str(current.get("program_path") or ""),
                    placeholder="C:\\Games\\game.exe",
                    id="bs-program",
                    disabled=locked,
                )
                yield Static(f"[{MUTED}]Launch flags[/]")
                yield Input(
                    value=str(current.get("program_flags") or ""),
                    placeholder="optional arguments",
                    id="bs-flags",
                    disabled=locked,
                )
                if locked:
                    yield Static(f"[{MUTED}]{options['program_reason']}[/]", classes="hint")
                if current.get("error"):
                    yield Static(f"[{WARN}]{current['error']}[/]")
            with Horizontal(id="dialog-buttons"):
                yield Button("Cancel", id="bs-cancel")
                yield Button("Save", id="bs-save", variant="primary")

    def on_mount(self) -> None:
        field = self.query_one("#bs-renderer", Select)
        if field.disabled:
            self.query_one("#bs-program", Input).focus()
        else:
            field.focus()

    @on(Button.Pressed, "#bs-cancel")
    def _cancel(self) -> None:
        self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_save(self) -> None:
        self._save()

    @on(Button.Pressed, "#bs-save")
    def _save_pressed(self) -> None:
        self._save()

    def _changed(self, key: str, value: object) -> bool:
        current = self.current.get(key)
        if key in ("metal_hud", "high_res"):
            return bool(value) != bool(current)
        return str(value or "") != str(current or "")

    def _save(self) -> None:
        changes: dict[str, object] = {}
        renderer = self.query_one("#bs-renderer", Select).value
        if self._changed("renderer", renderer):
            changes["renderer"] = renderer
        sync = self.query_one("#bs-sync", Select).value
        if self._changed("sync", sync):
            changes["sync"] = sync
        hud = self.query_one("#bs-hud", Select).value
        if self._changed("metal_hud", hud == "on"):
            changes["metal_hud"] = hud == "on"
        if self.options["high_res"]:
            high = self.query_one("#bs-high", Select).value
            if self._changed("high_res", high == "on"):
                changes["high_res"] = high == "on"
        if not self.options["program_locked"]:
            program = self.query_one("#bs-program", Input).value.strip()
            if self._changed("program_path", program):
                changes["program_path"] = program
            flags = self.query_one("#bs-flags", Input).value.strip()
            if self._changed("program_flags", flags):
                changes["program_flags"] = flags
        if not changes:
            self.notify("Nothing changed", severity="warning")
            return
        self.dismiss(changes)


class SettingEditModal(ModalScreen):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, key: str, current: object) -> None:
        super().__init__()
        self.key = key
        self.current = current

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(f"Change {self.key}", classes="title")
            yield Static(SETTING_HELP.get(self.key, ""), classes="hint")
            if self.key == "engine_version":
                options = [
                    (engine_label(version), version)
                    for version in ("11.17-universal", "11.17-steam")
                ]
                yield Select(options, value=str(self.current or "11.17-universal"), id="setting-value")
            elif self.key == "graphics_backend":
                options = [("DXMT", "dxmt"), ("D3DMetal", "d3dmetal"), ("DXVK", "dxvk")]
                yield Select(options, value=str(self.current or "dxmt"), id="setting-value")
            else:
                options = [("On", "true"), ("Off", "false")]
                current = "true" if str(self.current).lower() in ("true", "1", "yes") else "false"
                yield Select(options, value=current, id="setting-value")
            with Horizontal(id="dialog-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Save", id="save", variant="primary")

    @on(Button.Pressed, "#cancel")
    def _cancel(self) -> None:
        self.action_cancel()

    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#save")
    def _save(self) -> None:
        value = self.query_one("#setting-value", Select).value
        self.dismiss((self.key, value))


class ConfirmModal(ModalScreen):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, title: str, body: str, confirm: str = "Delete") -> None:
        super().__init__()
        self._title = title
        self._body = body
        self._confirm = confirm

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(self._title, classes="title")
            yield Static(self._body, classes="hint")
            with Horizontal(id="dialog-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button(self._confirm, id="ok", variant="error")

    @on(Button.Pressed, "#cancel")
    def _cancel(self) -> None:
        self.action_cancel()

    def action_cancel(self) -> None:
        self.dismiss(False)

    @on(Button.Pressed, "#ok")
    def _ok(self) -> None:
        self.dismiss(True)


class HelpModal(ModalScreen):
    BINDINGS = [Binding("escape", "close", "Close"), Binding("question_mark", "close", "Close")]

    def compose(self) -> ComposeResult:
        rows = [
            ("↑ ↓ / j k", "move through the list"),
            ("enter", "reveal the selection in Finder"),
            ("/", "filter bottles by name, engine or renderer"),
            ("l", "launch the selected bottle"),
            ("s", "bottle details"),
            ("e", "edit that bottle's settings (engine-aware)"),
            ("n", "new bottle"),
            ("d", "delete a bottle (moves it to the Trash)"),
            ("t", "pause or follow the log"),
            ("r", "refresh everything"),
            ("o", "open the WehniX window"),
            ("1 … 7", "jump to a section"),
            ("ctrl+p", "command palette"),
            ("?", "this list"),
            ("q", "quit"),
        ]
        with Vertical(id="help"):
            yield Static("Keys", classes="title")
            for keys, description in rows:
                yield Static(f"[{ACCENT}]{keys:<14}[/] [{MUTED}]{description}[/]")
            yield Static("")
            yield Static(
                f"[{MUTED}]WehniX CLI {__version__} · Apache-2.0 · WEHNIT[/]",
                classes="hint",
            )

    def action_close(self) -> None:
        self.dismiss(None)


# --------------------------------------------------------------------------
# Application
# --------------------------------------------------------------------------


class WehniXCLI(App):
    CSS = CSS
    TITLE = "WehniX CLI"
    SUB_TITLE = ""
    ENABLE_COMMAND_PALETTE = True

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("r", "refresh", "Refresh", show=True),
        Binding("n", "new_bottle", "New", show=True),
        Binding("d", "delete_bottle", "Delete", show=True),
        Binding("s", "bottle_details", "Details", show=True),
        Binding("e", "edit_bottle", "Edit", show=True),
        Binding("slash", "search", "Filter", show=True),
        Binding("question_mark", "help", "Help", show=True),
        Binding("l", "launch", "Launch", show=False),
        Binding("o", "open_app", "App", show=False),
        Binding("ctrl+p", "command_palette", "Palette", show=False),
        Binding("enter", "reveal", "Reveal", show=False),
        Binding("escape", "escape", "Clear", show=False),
        Binding("1", "goto('bottles')", "Bottles", show=False),
        Binding("2", "goto('games')", "Games", show=False),
        Binding("3", "goto('engine')", "Engines", show=False),
        Binding("4", "goto('doctor')", "Doctor", show=False),
        Binding("5", "goto('logs')", "Logs", show=False),
        Binding("6", "goto('settings')", "Settings", show=False),
        Binding("7", "goto('storage')", "Storage", show=False),
    ]

    def __init__(self, state_dir: Path | None = None) -> None:
        super().__init__()
        self.snapshot = None
        self._current = "bottles"
        self._query = ""
        self._checks = []
        self._app_running = False
        self._settings_target: Bottle | None = None
        if state_dir is not None:
            import os

            os.environ["WEHNIX_CLI_STATE_DIR"] = str(state_dir)

    # ------------------------------------------------------------- compose

    def compose(self) -> ComposeResult:
        with Horizontal(id="topbar"):
            yield Static("", id="topbar-left")
            yield Static("", id="topbar-right")
        with Horizontal(id="shell"):
            with Vertical(id="side"):
                yield Static(BRAND, id="brand")
                yield ListView(
                    *[
                        ListItem(Label(f"{glyph}  {title}"), id=f"nav-{key}")
                        for key, title, glyph in NAV
                    ],
                    id="nav",
                )
                yield Static("", id="sidefoot")
            with Vertical(id="main"):
                yield Static("", id="title")
                with ContentSwitcher(initial="view-bottles", id="content"):
                    yield BottlesView(id="view-bottles")
                    yield GamesView(id="view-games")
                    yield EngineView(id="view-engine")
                    yield DoctorView(id="view-doctor")
                    yield LogsView(id="view-logs")
                    yield SettingsView(id="view-settings")
                    yield StorageView(id="view-storage")
        yield Static("", id="status")
        # The palette is still on ctrl+p and in Help; keeping its key out of the
        # footer is what stops the last binding from being clipped at 80 columns.
        yield Footer(show_command_palette=False)

    def on_mount(self) -> None:
        self.query_one("#nav", ListView).index = 0
        self.refresh_all()
        self.set_interval(REFRESH_SECONDS, self._auto_refresh)
        self.set_interval(TAIL_SECONDS, self._auto_tail)

    # -------------------------------------------------------------- refresh

    def refresh_all(self) -> None:
        snapshot = read_snapshot(with_sizes=False, with_games=False)
        self.snapshot = snapshot
        self._checks = run_checks()
        self._app_running = app_is_running()
        self.query_one("#view-bottles", BottlesView).load(snapshot.bottles, self._query, snapshot.root)
        self.query_one("#view-engine", EngineView).load(snapshot.engines, snapshot.root)
        self.query_one("#view-doctor", DoctorView).load(self._checks)
        self.query_one("#view-logs", LogsView).load(snapshot)
        self.query_one("#view-settings", SettingsView).load(snapshot.settings)
        self.query_one("#view-storage", StorageView).load(snapshot)
        self._paint_chrome()
        self._load_games()
        self._load_sizes()

    def _auto_refresh(self) -> None:
        # Cheap pass only: counts, chrome and the log. Sizes and game scans are
        # explicit because they touch every bottle on disk.
        snapshot = read_snapshot(with_sizes=False, with_games=False)
        self.snapshot = snapshot
        self._checks = run_checks()
        self._app_running = app_is_running()
        if self._current == "bottles":
            self.query_one("#view-bottles", BottlesView).load(snapshot.bottles, self._query, snapshot.root)
        self._paint_chrome()

    @work(thread=True, exclusive=True)
    def _load_games(self) -> None:
        snapshot = read_snapshot(with_sizes=False, with_games=True)
        self.call_from_thread(self._apply_games, snapshot.games)

    def _apply_games(self, games) -> None:
        if self.snapshot is not None:
            self.snapshot.games = games
            self.query_one("#view-games", GamesView).load(games)
            self._paint_chrome()

    @work(thread=True, exclusive=True)
    def _load_sizes(self) -> None:
        """du on a 4 GB bottle is not something to do on the UI thread."""
        snapshot = read_snapshot(with_sizes=True, with_games=False)
        self.call_from_thread(self._apply_sizes, snapshot)

    def _apply_sizes(self, sized) -> None:
        if self.snapshot is None:
            return
        sizes = {str(bottle.path): bottle.size for bottle in sized.bottles}
        for bottle in self.snapshot.bottles:
            bottle.size = sizes.get(str(bottle.path), bottle.size)
        self.query_one("#view-bottles", BottlesView).load(
            self.snapshot.bottles, self._query, self.snapshot.root
        )
        self.query_one("#view-storage", StorageView).load(self.snapshot)
        self._paint_chrome()

    def _auto_tail(self) -> None:
        if self._current != "logs" or self.snapshot is None or self.snapshot.log_path is None:
            return
        view = self.query_one("#view-logs", LogsView)
        if not view.following:
            return
        view.append(tail_log(self.snapshot.log_path, 200))

    def _paint_chrome(self) -> None:
        snapshot = self.snapshot
        if snapshot is None:
            return
        errors, warnings = summary(self._checks)
        state = f"[{OK}]● ready[/]" if snapshot.exists else f"[{WARN}]● no data[/]"
        self.query_one("#topbar-left", Static).update(
            f"[bold]WehniX CLI[/] [{MUTED}]{__version__}[/]   {state}"
        )
        self.query_one("#topbar-right", Static).update(
            f"[{MUTED}]engine[/] [{ACCENT}] {snapshot.engine_version} [/]"
            f"[{MUTED}]bottles[/] [{ACCENT}] {len(snapshot.bottles)} [/]"
        )

        counts = {
            "bottles": len(snapshot.bottles),
            "games": len(snapshot.games),
            "engine": len(snapshot.engines),
        }
        for key, title, glyph in NAV:
            label = self.query_one(f"#nav-{key}", ListItem).query_one(Label)
            if key == "doctor":
                suffix = f"[{ERR}]{errors}[/]" if errors else f"[{OK}]ok[/]"
            elif key in counts:
                suffix = f"[{MUTED}]{counts[key]}[/]"
            else:
                suffix = ""
            label.update(f"{glyph}  {title}  {suffix}".rstrip())

        self.query_one("#sidefoot", Static).update(
            f"[{MUTED}]data[/]\n[{MUTED}]{compact_path(snapshot.root, 26)}[/]\n\n"
            f"[{MUTED}]app  {'running' if self._app_running else 'closed'}[/]"
        )

        # The strip at the very bottom of the interface: identity, licence and
        # credit are always visible, with live health trailing on the same line.
        self.query_one("#status", Static).update(
            f"[bold]WehniX CLI[/] [{MUTED}]{__version__}[/]   "
            f"[{MUTED}]lic[/] [{ACCENT}]Apache-2.0[/]   "
            f"[{MUTED}]by[/] [{ACCENT}]WEHNIT[/]   "
            f"[{MUTED}]·[/]   "
            f"[{MUTED}]bottles[/] [{ACCENT}]{len(snapshot.bottles)}[/]   "
            f"[{MUTED}]games[/] [{ACCENT}]{len(snapshot.games)}[/]   "
            f"[{MUTED}]engines[/] [{ACCENT}]{human_bytes(snapshot.total_engine_bytes)}[/]   "
            f"[{MUTED}]doctor[/] "
            + (f"[{ERR}]{errors} error(s)[/]" if errors else f"[{OK}]clean[/]")
            + (f" [{WARN}]{warnings} warning(s)[/]" if warnings else "")
        )

        titles = {
            "bottles": (
                "Bottles",
                f"{len(snapshot.bottles)} total · {human_bytes(snapshot.total_bottle_bytes)}"
                + (f" · filter “{self._query}”" if self._query else ""),
            ),
            "games": ("Games", f"{len(snapshot.games)} installed in your bottles"),
            "engine": (
                "Engines",
                f"{len(snapshot.engines)} archive(s) · {human_bytes(snapshot.total_engine_bytes)}",
            ),
            "doctor": ("Doctor", f"{errors} error(s), {warnings} warning(s)"),
            "logs": ("Logs", short_path(snapshot.log_path, 3) if snapshot.log_path else "no log yet"),
            "settings": ("Settings", "the keys this CLI may change"),
            "storage": ("Storage", "what the data folder uses"),
        }
        heading, sub = titles.get(self._current, ("", ""))
        self.query_one("#title", Static).update(f"[bold]{heading}[/]  [{MUTED}]{sub}[/]")

    # ------------------------------------------------------------ navigation

    @on(ListView.Selected, "#nav")
    def _nav_selected(self, event: ListView.Selected) -> None:
        key = (event.item.id or "").removeprefix("nav-")
        self.action_goto(key)

    def action_goto(self, key: str) -> None:
        if key not in {nav_key for nav_key, _title, _glyph in NAV}:
            return
        self._current = key
        self.query_one("#content", ContentSwitcher).current = f"view-{key}"
        for index, (nav_key, _title, _glyph) in enumerate(NAV):
            if nav_key == key:
                self.query_one("#nav", ListView).index = index
                break
        if key == "logs":
            self.query_one("#view-logs", LogsView).load(self.snapshot) if self.snapshot else None
        self._paint_chrome()

    def action_help(self) -> None:
        self.push_screen(HelpModal())

    def action_search(self) -> None:
        if self._current != "bottles":
            self.action_goto("bottles")
        field = self.query_one("#bottle-search", Input)
        field.display = True
        field.focus()

    def action_escape(self) -> None:
        field = self.query_one("#bottle-search", Input)
        if field.display:
            field.value = ""
            field.display = False
            self._query = ""
            self._reload_bottles()
            self.query_one("#view-bottles").focus()

    @on(Input.Changed, "#bottle-search")
    def _search_changed(self, event: Input.Changed) -> None:
        self._query = event.value
        self._reload_bottles()

    def _reload_bottles(self) -> None:
        if self.snapshot is None:
            return
        self.query_one("#view-bottles", BottlesView).load(
            self.snapshot.bottles, self._query, self.snapshot.root
        )
        self._paint_chrome()

    # ---------------------------------------------------------------- actions

    def action_refresh(self) -> None:
        self.refresh_all()
        self.notify("Refreshed")

    def action_open_app(self) -> None:
        try:
            open_desktop_app()
        except ActionError as exc:
            self.notify(str(exc), severity="error")

    def _selected_bottle(self) -> Bottle | None:
        return self.query_one("#view-bottles", BottlesView).selected_bottle()

    def action_reveal(self) -> None:
        if self._current != "bottles":
            return
        bottle = self._selected_bottle()
        if bottle is None:
            self.notify("No bottle selected", severity="warning")
            return
        try:
            reveal(bottle.path)
        except ActionError as exc:
            self.notify(str(exc), severity="error")

    def action_bottle_details(self) -> None:
        bottle = self._selected_bottle()
        if bottle is None:
            self.notify("No bottle selected", severity="warning")
            return
        self.push_screen(BottleDetailsModal(bottle))

    def action_edit_bottle(self) -> None:
        bottle = self._selected_bottle()
        if bottle is None:
            self.notify("No bottle selected", severity="warning")
            return
        if app_is_running():
            self.notify("Quit WehniX first — it rewrites bottle settings.", severity="error")
            return
        self._open_settings(bottle)

    @work(thread=True, exclusive=True)
    def _open_settings(self, bottle: Bottle) -> None:
        options = available_bottle_settings(bottle)
        self._settings_target = bottle
        self.call_from_thread(
            self.push_screen,
            BottleSettingsModal(bottle, options),
            self._settings_confirmed,
        )

    def _settings_confirmed(self, changes) -> None:
        if not changes:
            return
        bottle = self._settings_target
        if bottle is None:
            return
        self._do_bottle_edit(bottle, changes)

    @work(thread=True, exclusive=True)
    def _do_bottle_edit(self, bottle: Bottle, changes: dict) -> None:
        applied: list[str] = []
        for key, value in changes.items():
            try:
                set_bottle_setting(bottle, key, value)
            except ActionError as exc:
                message = str(exc)
                if applied:
                    message += f" (already changed: {', '.join(applied)})"
                self.call_from_thread(self.notify, message, severity="error")
                break
            except Exception as exc:  # never a traceback in the UI
                self.call_from_thread(
                    self.notify,
                    f"Could not change {key}: {exc}",
                    severity="error",
                )
                break
            applied.append(key)
        else:
            self.call_from_thread(
                self.notify, f"{bottle.name}: updated {', '.join(applied)}"
            )
        self.call_from_thread(self.refresh_all)

    def action_launch(self) -> None:
        bottle = self._selected_bottle()
        if bottle is None:
            self.notify("No bottle selected", severity="warning")
            return
        try:
            open_path(bottle.path)
        except ActionError as exc:
            self.notify(str(exc), severity="error")

    def action_toggle_tail(self) -> None:
        if self._current != "logs":
            return
        view = self.query_one("#view-logs", LogsView)
        view.toggle_follow()
        if self.snapshot is not None:
            view._paint_hint(self.snapshot)

    def action_delete_bottle(self) -> None:
        bottle = self._selected_bottle()
        if bottle is None:
            self.notify("No bottle selected", severity="warning")
            return
        if app_is_running():
            self.notify("Quit WehniX first — it is open.", severity="error")
            return
        self.push_screen(
            ConfirmModal(
                f"Delete “{bottle.name}”?",
                "It moves to the Trash, so you can put it back. Games inside it go too.",
            ),
            lambda confirmed: self._delete_confirmed(bottle, confirmed),
        )

    def _delete_confirmed(self, bottle: Bottle, confirmed: bool) -> None:
        if confirmed:
            self._do_delete(bottle)

    @work(thread=True, exclusive=True)
    def _do_delete(self, bottle: Bottle) -> None:
        try:
            where = delete_bottle(bottle)
            self.call_from_thread(self.notify, f"“{bottle.name}” moved to {where}")
        except ActionError as exc:
            self.call_from_thread(lambda: self.notify(str(exc), severity="error"))
        self.call_from_thread(self.refresh_all)

    def action_new_bottle(self) -> None:
        if self.snapshot is None:
            return
        candidates = [engine for engine in self.snapshot.engines if engine.creatable and engine.healthy]
        if not candidates:
            self.notify(
                "No bottle-capable engine installed — run WehniX setup first.",
                severity="warning",
            )
            return
        if app_is_running():
            self.notify("Quit WehniX first — it is open.", severity="error")
            return
        self.push_screen(NewBottleModal(candidates), self._create_confirmed)

    def _create_confirmed(self, result) -> None:
        if not result:
            return
        name, engine, env_type = result
        self.notify(f"Creating {name} from {engine_label(engine.version)}…")
        self._do_create(name, engine, env_type)

    @work(thread=True, exclusive=True)
    def _do_create(self, name: str, engine: EngineArtifact, env_type: str) -> None:
        try:
            created = create_bottle(name, engine, env_type)
            message = f"Created {created.name}"
            if created.warnings:
                message += " — " + created.warnings[0]
            self.call_from_thread(self.notify, message, severity="warning" if created.warnings else "information")
        except ActionError as exc:
            self.call_from_thread(lambda: self.notify(str(exc), severity="error"))
        self.call_from_thread(self.refresh_all)

    # ------------------------------------------------------------- settings

    @on(DataTable.RowSelected, "#settings-table")
    def _setting_selected(self, event: DataTable.RowSelected) -> None:
        key = str(event.row_key.value or "")
        if not key or self.snapshot is None:
            return
        self.push_screen(
            SettingEditModal(key, self.snapshot.settings.get(key)),
            lambda result: self._setting_confirmed(result),
        )

    def _setting_confirmed(self, result) -> None:
        if not result:
            return
        key, value = result
        try:
            set_setting(key, value)
        except ActionError as exc:
            self.notify(str(exc), severity="error")
            return
        self.notify(f"{key} is now {value}")
        self.refresh_all()

    # ----------------------------------------------------------------- misc

    @on(DataTable.RowHighlighted, "#bottles-table")
    def _bottle_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if self.snapshot is None:
            return
        view = self.query_one("#view-bottles", BottlesView)
        view.update_detail(view.selected_bottle())


def run(state_dir: Path | None = None) -> None:
    """Create the state tree if needed, then hand over to the TUI."""
    prepare_state_dir()
    WehniXCLI(state_dir=state_dir).run()
