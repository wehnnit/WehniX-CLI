# WehniX CLI — commands and keys

Everything the terminal client can do, in one page.

```
WehniX [--state-dir PATH] [--init]
WehniX <command> [options]
```

`--state-dir` overrides the data folder for one run (the default is
`~/Library/Application Support/WehniX`). It is the same override as the
`WEHNIX_CLI_STATE_DIR` environment variable, which is what the tests and the
screenshot script use.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | success |
| `1` | a user or environment error — unknown bottle, refused write, doctor errors |
| `2` | no WehniX data folder yet |

`--json` output is stable enough to pipe into `jq`. Nothing is ever printed to
stdout except the requested output; warnings go to stderr or the TUI toast.

## Subcommands

### `WehniX list` (alias `bottles`)

```
WehniX list [--json] [--sizes]
```

One line per bottle: name, engine, environment, renderer, size, last used.
`--sizes` measures each bottle with `du` (a few seconds on 4 GB bottles).

```json
{
  "root": "/Users/you/Library/Application Support/WehniX",
  "engine_version": "11.17-universal",
  "count": 2,
  "bottles": [
    {
      "name": "Main",
      "unique_id": "8f1c…",
      "path": "…/bottles/8f1c…",
      "app_path": "…/bottles/8f1c…/Main.app",
      "c_drive_path": "…/drive_c",
      "engine": "11.17-universal",
      "edition": "Universal",
      "env_type": "game",
      "renderer": "dxmt",
      "program_path": "/nothing.exe",
      "program_flags": "",
      "metal_hud": false,
      "sync": "auto",
      "high_res": false,
      "size": 1284000000,
      "last_used": 1767000000.0,
      "in_registry": true
    }
  ]
}
```

### `WehniX show <name>`

```
WehniX show Main [--json]
```

Every field the CLI knows, including the C: path and whether the bottle has a
record in `bottles.json` or was only found on disk. Matching is
case-insensitive, then by `unique_id` prefix.

### `WehniX games`

```
WehniX games [--json]
```

Steam games inside the bottles, read from the `appmanifest_*.acf` files Steam
writes. Epic titles are the desktop app's domain and are not guessed at.

### `WehniX engines`

```
WehniX engines [--json]
```

Installed engine archives with their identity, size, health and whether they can
create a bottle. An archive under 100 MB is reported as "suspiciously small"
rather than called broken.

### `WehniX doctor`

```
WehniX doctor [--json]
```

Checks, in order: data folder, its permissions, `config.json`, setup flag,
bottles folder, bottle bundles, duplicate records, both 11.17 engines, plausible
archives, the engine new bottles use, macOS version, Rosetta on Apple Silicon,
free disk (15 GB), the log file and its folder, this CLI on `PATH`, installed
WehniX.app copies, and whether the app is open for writes.

Exits `1` when an error-severity check fails. Warnings do not fail the command.

### `WehniX settings`

```
WehniX settings [get] [--json]
WehniX settings set <key> <value>
```

Only three keys, because they are the only ones the desktop app will not
disagree with:

| Key | Values |
| --- | --- |
| `engine_version` | `11.17-universal`, `11.17-steam` (retired engines are refused) |
| `graphics_backend` | `dxmt`, `d3dmetal`, `dxvk` |
| `auto_check_updates` | `true`, `false` |

If `config.json` changes while the command is running, the write is refused.

### `WehniX storage`

```
WehniX storage [--json]
```

Bottles, engines and logs, by size.

### `WehniX open <name>`

Reveals the bottle in Finder. Refuses a path that no longer exists.

### `WehniX logs`

```
WehniX logs [-n 200] [--json]
```

The tail of `logs/wehniX.log`.

### `WehniX init` / `WehniX --init`

Creates the data folder, `logs/` and `cli/` when they are missing. It does not
touch `config.json`, `bottles.json`, any bottle, or any engine — a half-made
folder is worse than none, so nothing is invented.

### `WehniX version`

Prints `WehniX CLI <version> · Apache-2.0 · WEHNIT`.

## Interface keys

| Key | Action |
| --- | --- |
| `↑` `↓` `j` `k` | move |
| `enter` | reveal the selection in Finder (Bottles section) |
| `/` | focus the bottle filter |
| `escape` | clear the filter |
| `l` | launch the selected bottle |
| `s` | bottle details |
| `n` | new bottle |
| `d` | delete the selected bottle (to the Trash, after confirmation) |
| `t` | pause/follow the log (Logs section) |
| `r` | refresh |
| `o` | open WehniX.app |
| `1`–`7` | Bottles, Games, Engines, Doctor, Logs, Settings, Storage |
| `ctrl+p` | command palette |
| `?` | key list |
| `q` | quit |

## Sections

| Section | Reads | Writes |
| --- | --- | --- |
| Bottles | `bottles.json`, `bottles/*/Contents/Info.plist` | create, delete (Trash) |
| Games | `steamapps/appmanifest_*.acf` | — |
| Engines | `Engine/*.zip`, `*.tar.xz` | — |
| Doctor | everything above, `sw_vers`, `arch`, `df` | — |
| Logs | `logs/wehniX.log` | — |
| Settings | `config.json` | the three keys above |
| Storage | `du` per bottle | — |

## Safety rules the commands obey

1. The desktop app being open blocks create, delete and settings writes.
2. Creating stages the extraction, validates the bundle, then promotes it. A
   failure leaves no half bottle and no record.
3. Deleting moves the bottle to the Trash, not to `/dev/null`, and removes only
   its own record.
4. Archive members and symlink targets are validated before extraction; a
   traversal attempt aborts the whole operation.
5. No command downloads anything, signs in anywhere, or starts Wine.
