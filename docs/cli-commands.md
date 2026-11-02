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

## Network use

Read-only commands (`list`, `show`, `games`, `engines`, `doctor`, `open`,
`logs`, `settings`, `storage`) and the interface never use the network.
`setup` and `engines install` do, and only against the pinned assets below,
over HTTPS, with a SHA-256 check before anything is extracted. There is no flag
for a custom URL, no mirror list, and no redirect to another host.

| Engine | Asset | SHA-256 |
| --- | --- | --- |
| `11.17-universal` | `WX-wine-11.17-Universal.tar.xz` | `04a6772387007814ef9d3f054a896ee46dfb96f5a625b140e46a7310a9164384` |
| `11.17-steam` | `WX-wine-11.17.tar.xz` | `6aa499f98f5fec0eaa3eb6dad0d9665b04abeea82006b19714d50bf5ab3394ee` |
| `11.11` | `WehniX-Engine-11.11-macos.tar.xz` | `a8ca3ee4ecaa648f1b288f2700ce6551fed43f7eb06c4cb379a7c851d7f8aa5c` |

The superseded Universal build (`e8e77bd412f90482a4df72c89e7af1d4686c2c15aaf936a20133e43b0c6305f5`)
is rejected on completeness: it is missing `scripts/wx-session.sh`.

Archives are validated before extraction (absolute paths, `..`, escaping
symlinks, member count and expansion ratio), after extraction (required engine
files) and after repacking to `Engine/<zip name>` (required zip members and a
100 MB floor). Extraction happens in `Engine/.staging-<version>` and is removed
on every path, success or failure. A download is written to `.part` and only
renamed once its digest matches.

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

### `WehniX` (no subcommand)

```
WehniX [--state-dir PATH] [--no-setup]
```

Opens the interface. If the data folder is missing, unreadable, or unfinished
(`setup_complete: false`, which is what an interrupted run leaves behind), the
first-run screen starts installing immediately — no Install button, no engine
question, no confirmation. Opening the CLI *is* the confirmation. Progress, the
engine in flight and a cancel hint are shown; `q` stops at a safe boundary and
keeps whatever finished, `r` retries after a failure.

A folder that is complete but missing an engine (say Steam) is **not**
re-downloaded on launch: Doctor reports it and `WehniX setup` repairs it, so a
1.8 GB download never happens behind your back.

With no terminal (piped, cron, a CI job) a plain `WehniX` runs the same setup in
plain text and exits `0` or `1`; it never tries to draw the interface.

`--no-setup` turns all of that off. With no data folder it prints the "no data
yet" message and exits `2`, without opening the interface and without writing
anything. It is for scripts and for anyone who wants the old behaviour.

The setup screen calls the same `engine_setup.setup` coordinator as
`WehniX setup` — same lock, same layout, same validation — so the two can be
told apart only by what they draw. `--state-dir` and `WEHNIX_CLI_STATE_DIR`
apply to first-run setup exactly as they do to everyday use, including an
alternate folder that does not exist yet.

### `WehniX setup`

```
WehniX setup [--engines universal,steam] [--engine universal|steam|11.11 ...]
             [--force] [--json]
WehniX --no-setup     # no first-run offer; exit 2 when there is no data
```

First-run setup, and the same coordinator the interface uses. Creates the whole
desktop layout (`Engine/`, `bottles/`, `Updates/`, `cli/`, `logs/`,
`WehniX-Epic/**`, `WehniX-Steam/**`), writes the desktop's `config.json`
defaults (`graphics_backend`, `bottle_location`, `engine_version`,
`bottle_engine_version`, `update_manifest_url`, `auto_check_updates`,
`install_extra_dependencies`) and an empty `bottles.json`, installs the missing
engines, validates the result, and only then writes `setup_complete: true`.

A failed or cancelled run leaves `setup_complete: false`, keeps the engines that
finished, and resumes from there on the next launch. A malformed `config.json`
is copied to `config.json.corrupt-<stamp>` before a repaired one is written;
unknown keys and existing bottle records are preserved.

Both 11.17 engines are installed by default, matching the desktop's
`ACTIVE_ENGINE_VERSIONS` and its own wizard: about 1.8 GiB together.
`--engines universal` installs Universal alone (about 1 GB);
`--engines universal,steam` (comma or space separated) and the repeatable
`--engine steam` mean the same thing. 11.11 stays an explicit
`engines install` for bottles you already have.

Setup takes a per-folder lock (`cli/.setup.lock`, advisory `flock`, released
automatically if the process dies), so two CLI processes cannot write the same
folder at once, and it refuses while WehniX.app is open unless `--force` is
passed. Before any download it checks the platform (macOS 14+ on Apple Silicon
for Universal), Rosetta 2 (installing it when missing and re-probing), and free
disk space.

The archive is downloaded with `urllib` over HTTPS from the pinned WX-Wine
release asset, hashed while it streams, and promoted from `.part` only when the
SHA-256 matches. A verified archive already in `Engine/.downloads/` is reused.
The superseded Universal build (`e8e77b…05f5`) is refused even when its own
checksum matches, because it is missing `scripts/wx-session.sh`.

Setup refuses to run while WehniX.app is open unless `--force` is passed, and
checks free disk space (about 3 GB per 11.17 engine) before starting. Progress
is throttled to about one line per percent and per quarter second, so a 1 GB
download fills a few lines instead of thousands. `Ctrl+C` before the final
config write cancels cleanly: the partial `.part` file and the extraction
staging folder are deleted and `setup_complete` stays `false`.

```json
{
  "success": true,
  "root": "~/Library/Application Support/WehniX",
  "setup_complete": true,
  "engines": [
    {
      "version": "11.17-universal",
      "engine_zip": "…/Engine/WehniX Engine 11.17 Universal.zip",
      "bytes": 1048576000,
      "reused": false,
      "sha256": "04a6772387007814ef9d3f054a896ee46dfb96f5a625b140e46a7310a9164384"
    }
  ]
}
```

### `WehniX engines`

```
WehniX engines [list] [--json]
WehniX engines install universal|steam|11.11 [--force] [--json]
WehniX engines doctor [--json]
```

`list` shows installed archives with their identity, size, health and whether
they can create a bottle. An archive under 100 MB is reported as "suspiciously
small" rather than called broken.

`install` runs the same pinned, checksum-verified path as setup for one engine,
without touching `config.json`.

`doctor` reports, per engine, the path, size, health and where the archive can
come from, and checks the required members inside the installed zip. It exits
`1` when any engine is missing or unhealthy.

### `WehniX doctor`

```
WehniX doctor [--json]
```

Checks, in order: data folder, its permissions, the private-folder mode,
`config.json`, setup flag, bottles folder, bottle bundles, duplicate records,
both 11.17 engines, plausible archives, the engine new bottles use, macOS
version, Rosetta on Apple Silicon, free disk (15 GB), the log file and its
folder, this CLI on `PATH`, installed WehniX.app copies, and whether the app is
open for writes.

Every check has a `status`: `passed`, `failed`, `warning` or `skipped`.
`skipped` means the question cannot be answered yet. On a Mac that has never
run WehniX there is no data folder, so that is the single failure and
`config.json`, the bottles checks, both engines and the logs are skipped rather
than reported as a dozen separate problems — the app creates all of them during
its setup. Skips are drawn dim, are never counted as errors or warnings, and
still appear in `--json` so a script can tell "not set up" from "broken".

`--json` returns `errors`, `warnings`, `skipped` and a `checks` array where each
entry carries `status`. Exits `2` when the data folder has never been created,
`1` when a failed check remains, `0` otherwise. Warnings alone do not fail the
command.

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
