"""Command line entry point.

``WehniX`` with no arguments opens the interface. Everything else is a plain
subcommand so the CLI is scriptable, and ``--json`` makes it machine-readable.
Exit codes are stable: 0 success, 1 a user/environment error, 2 no data yet.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__
from .actions import (
    ActionError,
    available_bottle_settings,
    reveal,
    set_bottle_setting,
    set_setting,
    tail_log,
)
from .contract import SAFE_SETTINGS, SETTING_HELP
from .doctor import run_checks, summary
from .models import Bottle, human_age, human_bytes
from .state import default_root, prepare_state_dir, read_snapshot, state_root

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NO_DATA = 2


def _console():
    from rich.console import Console

    return Console(highlight=False)


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, indent=2))


def _bottle_payload(bottle: Bottle) -> dict:
    return {
        "name": bottle.name,
        "unique_id": bottle.unique_id,
        "path": str(bottle.path),
        "app_path": str(bottle.app_path) if bottle.app_path else None,
        "c_drive_path": str(bottle.c_drive) if bottle.c_drive else None,
        "engine": bottle.engine,
        "edition": bottle.edition,
        "env_type": bottle.env_type,
        "renderer": bottle.renderer,
        "program_path": bottle.program_path,
        "program_flags": bottle.program_flags,
        "metal_hud": bottle.metal_hud,
        "sync": bottle.sync,
        "high_res": bottle.high_res,
        "size": bottle.size,
        "last_used": bottle.modified,
        "in_registry": bottle.in_registry,
        "runtime": bottle.runtime,
        "settings_source": bottle.settings_source,
        "dxvk_available": bottle.dxvk_available,
        "settings_error": bottle.settings_error,
    }


def _snapshot(with_sizes: bool = False):
    return read_snapshot(with_sizes=with_sizes, with_games=True)


def _require_state(args=None):
    snapshot = _snapshot(getattr(args, "sizes", False))
    if not snapshot.exists:
        console = _console()
        console.print(f"[bold]No WehniX data yet.[/] Looked in {snapshot.root}")
        console.print("Run the WehniX app once, or create the folder with: WehniX --init")
        raise SystemExit(EXIT_NO_DATA)
    return snapshot


def _find_bottle(snapshot, name: str) -> Bottle | None:
    wanted = str(name or "").strip().lower()
    for bottle in snapshot.bottles:
        if bottle.name.lower() == wanted:
            return bottle
    for bottle in snapshot.bottles:
        if bottle.unique_id.lower().startswith(wanted) and wanted:
            return bottle
    return None


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_list(args) -> int:
    snapshot = _require_state(args)
    if args.json:
        _print_json(
            {
                "root": str(snapshot.root),
                "engine_version": snapshot.engine_version,
                "count": len(snapshot.bottles),
                "bottles": [_bottle_payload(bottle) for bottle in snapshot.bottles],
            }
        )
        return EXIT_OK

    console = _console()
    if not snapshot.bottles:
        console.print("No bottles yet. Open WehniX and create one, or press n in `WehniX`.")
        return EXIT_OK
    for bottle in snapshot.bottles:
        console.print(
            f"[bold]{bottle.name}[/]  [dim]{bottle.label_engine}[/]"
            f"  [dim]{bottle.label_env}[/]  [dim]{bottle.renderer_label}[/]"
            f"  [dim]{human_bytes(bottle.size)}[/]  [dim]{human_age(bottle.modified)}[/]",
            soft_wrap=True,
        )
        console.print(f"  [dim]{bottle.path}[/]", soft_wrap=True)
    return EXIT_OK


def cmd_show(args) -> int:
    snapshot = _require_state(args)
    bottle = _find_bottle(snapshot, args.name)
    if bottle is None:
        _console().print(f"No bottle called {args.name!r}.")
        names = ", ".join(b.name for b in snapshot.bottles)
        if names:
            _console().print(f"Known bottles: {names}")
        return EXIT_ERROR
    if args.json:
        _print_json(_bottle_payload(bottle))
        return EXIT_OK

    console = _console()
    rows = [
        ("Name", bottle.name),
        ("Engine", bottle.label_engine),
        ("Edition", bottle.edition or "—"),
        ("Kind", bottle.kind),
        ("Environment", bottle.label_env),
        ("Renderer", bottle.renderer_label),
        ("Program", bottle.program_path or "—"),
        ("Flags", bottle.program_flags or "—"),
        ("Sync", bottle.sync),
        ("Metal HUD", "on" if bottle.metal_hud else "off"),
        ("High resolution", "on" if bottle.high_res else "off"),
        ("Size", human_bytes(bottle.size)),
        ("Last used", human_age(bottle.modified)),
        ("Folder", str(bottle.path)),
        ("App", str(bottle.app_path) if bottle.app_path else "—"),
        ("C: drive", str(bottle.c_drive) if bottle.c_drive else "not provisioned yet"),
        ("Record", "in bottles.json" if bottle.in_registry else "found on disk only"),
    ]
    for label, value in rows:
        console.print(f"[dim]{label:<17}[/] {value}")
    return EXIT_OK


def cmd_games(args) -> int:
    snapshot = _require_state(args)
    if args.json:
        _print_json(
            {
                "count": len(snapshot.games),
                "games": [
                    {"title": g.title, "appid": g.appid, "bottle": g.bottle, "path": str(g.path)}
                    for g in snapshot.games
                ],
            }
        )
        return EXIT_OK
    console = _console()
    if not snapshot.games:
        console.print("No Steam libraries found inside your bottles.")
        console.print("[dim]Epic titles are managed by the desktop app; this CLI reads Steam only.[/]")
        return EXIT_OK
    for game in snapshot.games:
        console.print(f"[bold]{game.title}[/]  [dim]{game.appid}[/]  [dim]{game.bottle}[/]")
    console.print(
        f"\n[dim]{len(snapshot.games)} game(s). Epic titles are managed by the desktop app.[/]"
    )
    return EXIT_OK


def cmd_engines(args) -> int:
    snapshot = _require_state(args)
    if args.json:
        _print_json(
            {
                "engine_version": snapshot.engine_version,
                "engines": [
                    {
                        "name": engine.name,
                        "path": str(engine.path),
                        "version": engine.version,
                        "edition": engine.edition,
                        "size": engine.size,
                        "creatable": engine.creatable,
                        "healthy": engine.healthy,
                    }
                    for engine in snapshot.engines
                ],
            }
        )
        return EXIT_OK
    console = _console()
    if not snapshot.engines:
        console.print("No engine archives installed.")
        console.print("[dim]Open WehniX and run setup, or drop an archive into " + str(snapshot.root / "Engine") + "[/]")
        return EXIT_OK
    for engine in snapshot.engines:
        console.print(
            f"[bold]{engine.name}[/]  [dim]{engine.version}[/]  "
            f"[dim]{human_bytes(engine.size)}[/]  [dim]{engine.state}[/]"
        )
    return EXIT_OK


def cmd_doctor(args) -> int:
    checks = run_checks()
    errors, warnings = summary(checks)
    skipped = sum(1 for check in checks if check.status == "skipped")
    # A missing data folder is "no state yet" (2), not "the environment is
    # broken" (1): the user has not run the app, which the hint says.
    missing_state = not state_root().is_dir()
    if args.json:
        _print_json(
            {
                "errors": errors,
                "warnings": warnings,
                "skipped": skipped,
                "checks": [
                    {
                        "name": check.name,
                        "ok": check.ok,
                        "status": check.status,
                        "detail": check.detail,
                        "hint": check.hint,
                        "severity": check.severity,
                    }
                    for check in checks
                ],
            }
        )
        return EXIT_NO_DATA if missing_state else (EXIT_ERROR if errors else EXIT_OK)

    console = _console()
    console.print(f"[bold]WehniX CLI {__version__}[/] [dim]· doctor[/]\n")
    for check in checks:
        if check.status == "passed":
            mark = "[green]✓[/]"
        elif check.status == "skipped":
            mark = "[dim]–[/]"
        elif check.status == "warning":
            mark = "[yellow]![/]"
        else:
            mark = "[red]✗[/]"
        if check.status == "skipped":
            name = f"[dim]{check.name}[/]"
        elif check.status == "failed":
            name = f"[bold]{check.name}[/]"
        else:
            name = check.name
        console.print(f" {mark} {name}  [dim]{check.detail}[/]")
        if check.status not in ("passed", "skipped") and check.hint:
            console.print(f"     [dim]{check.hint}[/]")
    console.print()
    tail = f"{warnings} warning(s)"
    if skipped:
        tail += f", {skipped} not applicable yet"
    if errors:
        console.print(f"[red]{errors} error(s)[/], {tail}")
    else:
        console.print(f"[green]No errors[/] — {tail}")
    return EXIT_NO_DATA if missing_state else (EXIT_ERROR if errors else EXIT_OK)


def cmd_open(args) -> int:
    snapshot = _require_state(args)
    bottle = _find_bottle(snapshot, args.name)
    if bottle is None:
        console = _console()
        console.print(f"No bottle called {args.name!r}.")
        if snapshot.bottles:
            console.print("Known bottles: " + ", ".join(b.name for b in snapshot.bottles))
        return EXIT_ERROR
    try:
        reveal(bottle.path)
    except ActionError as exc:
        _console().print(f"[red]{exc}[/]")
        return EXIT_ERROR
    return EXIT_OK


def cmd_logs(args) -> int:
    snapshot = _require_state(args)
    if snapshot.log_path is None:
        print("No log yet — WehniX writes one when it runs.")
        return EXIT_ERROR
    lines = tail_log(snapshot.log_path, args.lines)
    if args.json:
        _print_json({"path": str(snapshot.log_path), "lines": [line.rstrip("\n") for line in lines]})
        return EXIT_OK
    sys.stdout.write("".join(lines))
    return EXIT_OK


def cmd_settings(args) -> int:
    root = state_root()
    config_path = root / "config.json"
    if not config_path.is_file():
        _console().print(f"[bold]No config.json yet.[/] Looked in {config_path}")
        return EXIT_NO_DATA

    if args.action == "set":
        try:
            set_setting(args.key, args.value, root)
        except ActionError as exc:
            _console().print(f"[red]{exc}[/]")
            return EXIT_ERROR
        _console().print(f"[green]{args.key}[/] is now [bold]{args.value}[/]")
        return EXIT_OK

    snapshot = _snapshot()
    settings = snapshot.settings
    if args.json:
        _print_json(
            {
                "path": str(config_path),
                "settings": {key: settings.get(key) for key in SAFE_SETTINGS},
                "help": SETTING_HELP,
            }
        )
        return EXIT_OK
    console = _console()
    console.print(f"[bold]Settings[/] [dim]{config_path}[/]\n")
    for key in SAFE_SETTINGS:
        console.print(f"  {key:<20} [bold]{settings.get(key, '—')!s}[/]")
        console.print(f"  [dim]{'':<20} {SETTING_HELP[key]}[/]")
    console.print("\n[dim]Change one with: WehniX settings set graphics_backend dxmt[/]")
    return EXIT_OK


def cmd_bottle_settings(args) -> int:
    """Read one bottle's engine settings, and change only what it supports."""
    snapshot = _require_state(args)
    bottle = _find_bottle(snapshot, args.name)
    if bottle is None:
        console = _console()
        console.print(f"No bottle called {args.name!r}.")
        if snapshot.bottles:
            console.print("Known bottles: " + ", ".join(b.name for b in snapshot.bottles))
        return EXIT_ERROR

    changes: dict[str, object] = {}
    if args.renderer:
        changes["renderer"] = args.renderer
    if args.sync:
        changes["sync"] = args.sync
    if args.metal_hud:
        changes["metal_hud"] = args.metal_hud
    if args.high_res:
        changes["high_res"] = args.high_res
    if args.program is not None:
        changes["program_path"] = args.program
    if args.program_flags is not None:
        changes["program_flags"] = args.program_flags

    try:
        options = available_bottle_settings(bottle)
        for key, value in changes.items():
            options = set_bottle_setting(bottle, key, value)
    except ActionError as exc:
        _console().print(f"[red]{exc}[/]")
        return EXIT_ERROR

    current = options["current"]
    payload = {
        "bottle": bottle.name,
        "engine": options["engine"],
        "runtime": options["runtime"],
        "settings": {
            "renderer": current.get("renderer"),
            "sync": current.get("sync"),
            "metal_hud": current.get("metal_hud"),
            "high_res": current.get("high_res"),
            "program_path": current.get("program_path"),
            "program_flags": current.get("program_flags"),
            "source": current.get("source"),
            "error": current.get("error"),
        },
        "available": {
            "renderers": options["renderers"],
            "sync_modes": list(options["sync_modes"]),
            "metal_hud": options["metal_hud"],
            "high_res": options["high_res"],
            "program_locked": options["program_locked"],
            "program_reason": options["program_reason"],
        },
        "updated": sorted(changes),
    }
    if args.json:
        _print_json(payload)
        return EXIT_OK

    console = _console()
    console.print(f"[bold]{bottle.name}[/] [dim]· {options['engine']} · {options['runtime']}[/]\n")
    console.print(f"  renderer       [bold]{current.get('renderer') or '—'}[/]")
    console.print(f"  sync           [bold]{current.get('sync') or '—'}[/]")
    console.print(f"  metal hud      [bold]{'on' if current.get('metal_hud') else 'off'}[/]")
    console.print(f"  high res       [bold]{'on' if current.get('high_res') else 'off'}[/]")
    console.print(f"  program        {current.get('program_path') or '—'}")
    console.print(f"  flags          {current.get('program_flags') or '—'}")
    if current.get("source") != "app":
        console.print(
            f"  [dim]settings source: {current.get('source')} "
            f"(no engine config read; showing the registry[/])"
        )
    if current.get("error"):
        console.print(f"  [yellow]{current['error']}[/]")
    renderers = ", ".join(
        f"{name}{'' if item['available'] else ' (unavailable)'}"
        for name, item in options["renderers"].items()
    )
    console.print(f"\n[dim]renderers:[/] {renderers}")
    console.print(f"[dim]sync:[/] {', '.join(options['sync_modes'])}")
    console.print(
        f"[dim]high resolution:[/] {'supported' if options['high_res'] else 'not on this engine'}"
    )
    if options["program_locked"]:
        console.print(f"[dim]{options['program_reason']}[/]")
    console.print(
        f"\n[dim]Change with: WehniX settings bottle {bottle.name!r} "
        "--renderer dxmt --sync msync[/]"
    )
    return EXIT_OK


def cmd_storage(args) -> int:
    snapshot = _require_state(args)
    sized = _snapshot(with_sizes=True)
    total_bottles = sum(bottle.size or 0 for bottle in sized.bottles)
    total_engines = sum(engine.size or 0 for engine in sized.engines)
    log_dir = sized.root / "logs"
    log_bytes = 0
    if log_dir.is_dir():
        try:
            log_bytes = sum(
                child.stat().st_size for child in log_dir.glob("*") if child.is_file()
            )
        except OSError:
            log_bytes = 0
    payload = {
        "root": str(sized.root),
        "bottles": {"count": len(sized.bottles), "bytes": total_bottles},
        "engines": {"count": len(sized.engines), "bytes": total_engines},
        "logs": {"bytes": log_bytes},
        "total_bytes": total_bottles + total_engines + log_bytes,
    }
    if args.json:
        _print_json(payload)
        return EXIT_OK
    console = _console()
    console.print(f"[bold]Storage[/] [dim]{sized.root}[/]\n")
    console.print(f"  bottles   [bold]{human_bytes(total_bottles)}[/]  [dim]{len(sized.bottles)} item(s)[/]")
    console.print(f"  engines   [bold]{human_bytes(total_engines)}[/]  [dim]{len(sized.engines)} archive(s)[/]")
    console.print(f"  logs      [bold]{human_bytes(log_bytes)}[/]")
    console.print(f"\n  [bold]{human_bytes(payload['total_bytes'])}[/] [dim]in total[/]")
    return EXIT_OK


def cmd_init(args) -> int:
    result = prepare_state_dir(create_root=True)
    console = _console()
    console.print(f"[bold]Data folder[/] {result['root']}")
    if result["created"]:
        for path in result["created"]:
            console.print(f"  [green]+[/] {path}")
    else:
        console.print("  [dim]already in place[/]")
    return EXIT_OK


def cmd_version(args) -> int:
    print(f"WehniX CLI {__version__} · Apache-2.0 · WEHNIT")
    return EXIT_OK


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="WehniX",
        description="A terminal client for WehniX. Run with no arguments for the interface.",
        epilog="Licensed under Apache-2.0. Copyright 2026 WEHNIT.",
    )
    parser.add_argument("--version", action="version", version=f"WehniX CLI {__version__}")
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=None,
        help=f"override the data folder (default: {default_root()})",
    )
    parser.add_argument("--init", action="store_true", help="create the data folder and exit")

    sub = parser.add_subparsers(dest="command")

    listing = sub.add_parser("list", aliases=["bottles"], help="list bottles")
    listing.add_argument("--json", action="store_true")
    listing.add_argument("--sizes", action="store_true", help="also measure disk usage")
    listing.set_defaults(func=cmd_list)

    show = sub.add_parser("show", help="show one bottle")
    show.add_argument("name")
    show.add_argument("--json", action="store_true")
    show.set_defaults(func=cmd_show)

    games = sub.add_parser("games", help="list Steam games inside bottles")
    games.add_argument("--json", action="store_true")
    games.set_defaults(func=cmd_games)

    engines = sub.add_parser("engines", help="list installed engine archives")
    engines.add_argument("--json", action="store_true")
    engines.set_defaults(func=cmd_engines)

    doctor = sub.add_parser("doctor", help="check the environment")
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(func=cmd_doctor)

    open_cmd = sub.add_parser("open", help="reveal a bottle in Finder")
    open_cmd.add_argument("name")
    open_cmd.set_defaults(func=cmd_open)

    logs = sub.add_parser("logs", help="print the app log")
    logs.add_argument("-n", "--lines", type=int, default=200)
    logs.add_argument("--json", action="store_true")
    logs.set_defaults(func=cmd_logs)

    settings = sub.add_parser("settings", help="read or change the app's safe settings")
    settings_sub = settings.add_subparsers(dest="action")
    settings.set_defaults(func=cmd_settings, action="get")
    settings_get = settings_sub.add_parser("get", help="print the settings")
    settings_get.add_argument("--json", action="store_true")
    settings_get.set_defaults(func=cmd_settings, action="get")
    settings_set = settings_sub.add_parser("set", help="change one setting")
    settings_set.add_argument("key")
    settings_set.add_argument("value")
    settings_set.set_defaults(func=cmd_settings, action="set")

    settings_bottle = settings_sub.add_parser(
        "bottle", help="read or change one bottle's engine settings"
    )
    settings_bottle.add_argument("name")
    settings_bottle.add_argument("--renderer", help="dxmt, d3dmetal, or dxvk where supported")
    settings_bottle.add_argument("--sync", help="none, msync, default or esync, per engine")
    settings_bottle.add_argument("--metal-hud", choices=("on", "off"))
    settings_bottle.add_argument("--high-res", choices=("on", "off"))
    settings_bottle.add_argument("--program", help="program path inside the bottle")
    settings_bottle.add_argument("--flags", dest="program_flags", help="launch arguments")
    settings_bottle.add_argument("--json", action="store_true")
    settings_bottle.set_defaults(func=cmd_bottle_settings, action="bottle")

    storage = sub.add_parser("storage", help="show what the data folder uses")
    storage.add_argument("--json", action="store_true")
    storage.set_defaults(func=cmd_storage)

    init = sub.add_parser("init", help="create the data folder")
    init.set_defaults(func=cmd_init)

    version = sub.add_parser("version", help="print the version")
    version.set_defaults(func=cmd_version)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.state_dir is not None:
        os.environ["WEHNIX_CLI_STATE_DIR"] = str(args.state_dir)

    if args.init:
        return cmd_init(args)

    if getattr(args, "command", None) is None:
        from .tui.app import run

        prepare_state_dir()
        run()
        return EXIT_OK

    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
