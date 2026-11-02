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
  "runtime": "11.17-universal",
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
  "in_registry": true,
  "settings_source": "app",
  "dxvk_available": true
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
`graphics_backend` is the app-wide default for new surfaces, not a bottle's
renderer; the bottle's own renderer is set with `settings bottle` below.

### `WehniX settings bottle <name>`

```
WehniX settings bottle Main [--json]
WehniX settings bottle Main --renderer d3dmetal --sync msync --metal-hud on
WehniX settings bottle Main --program "C:\Games\Game.exe" --flags "-windowed"
```

Reads the bottle's own engine files, not the registry: `wehnix.json` for
11.17 Universal/Steam and for 11.11, `Info.plist` for GPTK and 11.0. Only the
values that engine offers are accepted, and a refused value writes nothing.

| Engine | Renderers | Sync | Metal HUD | High resolution | Program |
| --- | --- | --- | --- | --- | --- |
| 11.17 Universal | `dxmt`, `d3dmetal`, `dxvk` only if `renderers/dxvk/.wx-capability` says `renders=1` | `none`, `msync` | yes | no | editable; `wx-target` is written first |
| 11.17 Steam | `dxmt`, `d3dmetal` | `none` | yes | no | locked — always launches Steam |
| Game Porting Toolkit | `d3dmetal` | `default`, `esync`, `msync` | yes | yes | editable |
| 11.11 / 11.0 | `dxmt` | `default`, `esync`, `msync` | yes | yes | editable |

`--program` accepts a Windows path or a macOS path. A macOS path inside the
bottle's C: drive becomes `C:\…`; anything else becomes `Z:\…`, the same
mapping the app's file picker uses. There is no flag for a value the engine does
not publish: the CLI offers only what the engine itself supports.

The JSON output reports the engine, the normalised settings, every renderer
with an `available` flag and a reason, the sync list, and whether the program is
locked. A bottle with no readable engine file reports `source: default` and
`error`, and the write is refused rather than guessed.

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
| `e` | edit bottle settings (only what the engine supports) |
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
| Bottles | `bottles.json`, `bottles/*/Contents/Resources/wehnix.json`, `bottles/*/Contents/Info.plist` | create, delete (Trash), bottle settings (`e`) |
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
6. A bottle setting is checked against the engine's own files before writing:
   an unavailable renderer, sync mode, high-resolution flag or a locked program
   is refused with the reason, and nothing is written.

## Uninstall

Quit WehniX and WehniX CLI first. Both sets are safe to repeat: a path that is
already gone is reported, not treated as an error. The launchers answer to
`WehniX`, `wehniX`, `wehnix` and `Wehnix`.

### Set 1 — remove the CLI, keep your bottles

```sh
python3 -m pip uninstall -y wehnix-cli 2>/dev/null || true
rm -rf "${HOME}/.local/share/wehniX-cli"
rm -f \
  "${HOME}/.local/bin/wehniX-cli" \
  "${HOME}/.local/bin/wehniX" \
  "${HOME}/.local/bin/WehniX" \
  "${HOME}/.local/bin/wehnix" \
  "${HOME}/.local/bin/Wehnix"
rm -rf "${HOME}/Library/Application Support/WehniX/cli"
rm -rf "${HOME}/.cache/wehniX-cli-demo"
```

`~/Library/Application Support/WehniX` stays, including `config.json`,
`bottles.json`, `bottles/`, `Engine/` and `logs/`. `logs/` is app-owned, so it
is not listed as CLI cleanup here.

Optional PATH cleanup, only if `~/.local/bin` is not used for anything else:

```sh
sed -i.bak '/export PATH="\$HOME\/\.local\/bin:\$PATH"/d' \
  "${HOME}/.zshrc" "${HOME}/.bashrc" 2>/dev/null || true
rm -f "${HOME}/.zshrc.bak" "${HOME}/.bashrc.bak"
```

Never delete `~/.local/bin` itself — other tools live there.

```sh
command -v WehniX || true
```

### Set 2 — remove the CLI and all WehniX data

Deletes every bottle, engine archive, game inside a bottle, setting, save and
log. Back up first; there is no undo. The app bundle in `/Applications` is not
removed.

```sh
python3 -m pip uninstall -y wehnix-cli 2>/dev/null || true
rm -rf "${HOME}/.local/share/wehniX-cli"
rm -f \
  "${HOME}/.local/bin/wehniX-cli" \
  "${HOME}/.local/bin/wehniX" \
  "${HOME}/.local/bin/WehniX" \
  "${HOME}/.local/bin/wehnix" \
  "${HOME}/.local/bin/Wehnix"
rm -rf "${HOME}/.cache/wehniX-cli-demo"
rm -rf "${HOME}/Library/Application Support/WehniX"
```

PATH cleanup is the same optional block as set 1.

### Script

```sh
scripts/uninstall.sh                # CLI only
scripts/uninstall.sh --all-data     # CLI and app data (asks first)
scripts/uninstall.sh --pip          # also pip uninstall wehnix-cli
scripts/uninstall.sh --clean-path   # also drop the installer's PATH line
scripts/uninstall.sh --yes          # skip the prompt (non-interactive)
```

Exit codes: `0` removed and verified, `1` refused (no `--yes` outside a TTY) or
something could not be removed, `64` bad option or `HOME` unset.

A custom `--state-dir` folder, or wherever `WEHNIX_CLI_STATE_DIR` pointed, is
not touched by the script; delete it yourself if you used one.
