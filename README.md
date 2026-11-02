<p align="center">
  <img src="docs/cli.png" alt="WehniX CLI — bottles, engines, doctor and logs in one terminal window" width="920">
</p>

<p align="center">
  <a href="https://github.com/wehnnit/WehniX-CLI/releases"><img alt="version" src="https://img.shields.io/badge/version-0.2.0-7c5cff?style=flat-square"></a>
  <img alt="platform" src="https://img.shields.io/badge/platform-macOS%2013%2B-000000?style=flat-square">
  <img alt="license" src="https://img.shields.io/badge/license-Apache--2.0-6d9cff?style=flat-square">
  <img alt="python" src="https://img.shields.io/badge/python-3.9%2B-3ddc97?style=flat-square">
  <img alt="tests" src="https://img.shields.io/badge/tests-82%20passing-3ddc97?style=flat-square">
  <img alt="status" src="https://img.shields.io/badge/status-beta-ffb454?style=flat-square">
</p>

<h1 align="center">WehniX CLI</h1>

<p align="center">
  The same bottles, the same engines, no window.<br>
  A terminal client for <a href="https://github.com/wehnnit/WehniX">WehniX</a> — Apache-2.0, no account, local only.
</p>

---

WehniX CLI reads the data folder the WehniX desktop app already owns
(`~/Library/Application Support/WehniX`) and gives you a keyboard-first view of
it: bottles, the engines behind them, the Steam games installed inside them, a
doctor that explains what is wrong, and the app log without opening the app.

It is a second front end, not a second app. Create a bottle in the terminal and
the window shows it; delete one in the window and the terminal stops listing it.
There is no sign-in, no sync, no telemetry, and nothing is downloaded.

## Install

```sh
curl -fsSL https://raw.githubusercontent.com/wehnnit/WehniX-CLI/main/scripts/install.sh | bash
```

That creates a private virtualenv in `~/.local/share/wehniX-cli`, puts a
`WehniX` command in `~/.local/bin`, and adds that folder to your shell's `PATH`
if it is missing. No `sudo`, and it never touches the desktop app's data.

Any of these also work:

```sh
pipx install git+https://github.com/wehnnit/WehniX-CLI.git
uv tool install git+https://github.com/wehnnit/WehniX-CLI.git
python3 -m pip install --user git+https://github.com/wehnnit/WehniX-CLI.git
```

The command answers to `WehniX`, `wehniX`, `wehnix` and `Wehnix`; the installer
creates every spelling the filesystem can tell apart.

Requires macOS 13 or newer and Python 3.9+. The desktop app must have run at
least once, because this CLI has no setup of its own — it reads the app's folder
and refuses to invent one.

## Quick start

```sh
WehniX                 # the interface
WehniX list            # bottles, one line each
WehniX list --json     # the same, for scripts
WehniX doctor          # is this machine ready to run a bottle?
WehniX logs -n 50      # the tail of wehniX.log
```

## Keys

| Key | What it does |
| --- | --- |
| `↑` `↓` / `j` `k` | move through the list |
| `enter` | reveal the selection in Finder |
| `/` | filter bottles by name, engine or renderer (`escape` clears) |
| `l` | launch the selected bottle |
| `s` | bottle details, read from the bottle's own engine files |
| `e` | edit that bottle: renderer, sync, Metal HUD, high resolution, program |
| `n` | new bottle from an installed engine |
| `d` | delete a bottle — it moves to the Trash |
| `t` | pause or follow the log |
| `r` | refresh everything |
| `o` | open the WehniX window |
| `1` … `7` | jump to a section |
| `ctrl+p` | command palette |
| `?` | the key list |
| `q` | quit |

Every action is also in the command palette, so nothing needs memorising.
[`docs/cli-commands.md`](docs/cli-commands.md) lists every key and subcommand,
including JSON shapes and exit codes.

## How it works

**It reads the app's files, not a copy of them.** The CLI understands the exact
shapes the desktop writes:

| Path | What the CLI does with it |
| --- | --- |
| `config.json` | reads `settings.engine_version`, `graphics_backend`, `auto_check_updates`; can change only those three |
| `bottles.json` | reads records keyed by `unique_id`, `id`, `path` or bundle name — all four spellings the two front ends have used |
| `bottles/<unique_id>/<Name>.app/Contents/Resources/wehnix.json` | Universal and Steam 11.17 launch settings: renderer, sync, Metal HUD, program, arguments |
| `.../Contents/Resources/engine/wehnix.json` | the same launch settings for 11.11 bottles |
| `bottles/<unique_id>/<Name>.app/Contents/Info.plist` | GPTK and 11.0 settings, plus the engine version, edition and environment type |
| `Engine/*.zip` | identifies the build by name and reports whether it can create bottles |
| `logs/wehniX.log` | tails it, no parsing of private data |

**Reads are read-only and cheap.** One snapshot per refresh; `du` over a bottle
and the Steam-manifest scan run in worker threads so the interface never blocks.
The log follows on a timer only while the Logs section is open.

**Writes are few, guarded, and reversible.**

* Every write first checks whether the desktop app is open. If it is, the CLI
  refuses instead of racing it — the app rewrites `config.json` while running.
* `n` stages the engine archive in `bottles/.creating-<uuid>`, validates the app
  bundle it produced, brands the plist the way the desktop does, ad-hoc signs
  it, and only then moves it to `bottles/<uuid>/<Name>.app`. A failure removes
  the staging folder and nothing else. No record is written until the bundle
  passes verification.
* `d` moves the bottle to the Trash and drops exactly its record. Names,
  records and files belonging to other bottles stay byte-identical.
* `e` writes the selected bottle's own engine file — `wehnix.json` for
  11.17/11.11, `Info.plist` for GPTK/11.0 — and only after checking that engine
  offers the value. DXVK is refused unless the renderer payload reports
  `renders=1`; esync is refused on Universal; high resolution is refused on
  11.17; a Steam bottle's program stays locked. Universal's program is written
  through the bundle's `wx-target` tool before the JSON is touched, so a refused
  target leaves the old path in place. `bottles.json` is updated afterwards,
  only as the cache the app expects.
* Settings changes use optimistic concurrency: if `config.json` changed between
  the read and the write, the write is refused with "refresh and try again".
* Archive extraction validates every member and every symlink target, so an
  archive cannot write outside its staging folder.

**What it deliberately does not do.** No account, no cloud, no playtime
upload, no Epic login, no Steam launch, no engine download, no silent updater,
and no deleting anything the user did not select. Epic titles are managed by the
desktop app and are not guessed at from a cache. Those limits are in
[Limitations](#limitations) rather than hidden behind a button that fails.

## How the code works

```text
src/wehnix_cli/
├── contract.py    desktop rules: engine table, bottle types, env normalisation,
│                  name sanitising, record shape, allowed settings
├── models.py      dataclasses only (Bottle, EngineArtifact, Game, Check, Snapshot)
├── state.py       reads config/bottles/launch configs/Info.plist/manifests;
│                  atomic writes; prepare_state_dir; the app-running guard
├── actions.py     reveal, launch, create, delete, set_setting, tail_log,
│                  available_bottle_settings, set_bottle_setting; archive
│                  extraction with symlink and traversal validation
├── doctor.py      the health checks behind the Doctor section and `doctor`
├── cli.py         argparse subcommands, JSON output, exit codes
└── tui/
    ├── app.py     Textual app: views, modals, bindings, workers
    └── style.py   the brand palette and stylesheet
```

The flow is one direction, which is why the views never drift out of sync:

```text
files on disk ──► state.read_snapshot() ──► Snapshot ──► views draw it
                                   │
user action ──► actions.<verb>() ───┘  (guard, stage, validate, write)
                                   │
                                   └──► refresh_all() reads again
```

Views hold no logic of their own: they are handed a `Snapshot` and render it.
Anything that changes state goes through `actions.py`, so the app-running guard,
staging and validation cannot be skipped by a code path that forgot them.
`contract.py` is the single copy of the desktop's rules — engine support,
bottle types, environment normalisation — so the CLI cannot offer a bottle the
window would refuse, or accept an environment the engine cannot run.

Every ported rule names its source, for example:

```python
# Copied from wehnix_app.py :: bottle_types_for_engine
def bottle_types_for_engine(version): ...
```

## Uninstall

Quit WehniX and WehniX CLI first, then pick one of the two paths below. Both
are safe to run twice: a path that is already gone is reported, not treated as
an error.

The launchers are `WehniX`, `wehniX`, `wehnix` and `Wehnix`. On a
case-insensitive volume they are one file, but every spelling is removed so the
result is the same on any disk.

### Keep your bottles (remove the CLI only)

`~/Library/Application Support/WehniX` — bottles, engine archives, settings,
saves and logs — is left exactly as it is, so reinstalling finds everything.

```sh
# 1. Optional: remove a pip, pipx or editable install
python3 -m pip uninstall -y wehnix-cli 2>/dev/null || true

# 2. The installer's private runtime
rm -rf "${HOME}/.local/share/wehniX-cli"

# 3. Every launcher spelling
rm -f \
  "${HOME}/.local/bin/wehniX-cli" \
  "${HOME}/.local/bin/wehniX" \
  "${HOME}/.local/bin/WehniX" \
  "${HOME}/.local/bin/wehnix" \
  "${HOME}/.local/bin/Wehnix"

# 4. The CLI's own folder inside the app data (preferences only)
rm -rf "${HOME}/Library/Application Support/WehniX/cli"

# 5. Screenshot and demo files, if the script ever ran on this Mac
rm -rf "${HOME}/.cache/wehniX-cli-demo"
```

`.../WehniX/logs` is deliberately not in that list: the desktop app writes there
too, so it belongs to the app, not the CLI.

Remove the PATH line the installer added only if you do not use `~/.local/bin`
for anything else:

```sh
sed -i.bak '/export PATH="\$HOME\/\.local\/bin:\$PATH"/d' \
  "${HOME}/.zshrc" "${HOME}/.bashrc" 2>/dev/null || true
rm -f "${HOME}/.zshrc.bak" "${HOME}/.bashrc.bak"
```

Keep `~/.local/bin` itself. Deleting the folder to get rid of five launchers
takes every other tool installed there with it.

Open a new terminal, then confirm the command is gone:

```sh
command -v WehniX || true
WehniX --version || true
```

### Remove everything (the CLI and all WehniX data)

**This deletes `~/Library/Application Support/WehniX`: every bottle, every
installed engine, every game inside a bottle, every setting, save and log.
There is no undo.** Copy anything you want to keep somewhere else first.

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

The PATH line is optional, exactly as above. This does **not** remove
`/Applications/WehniX.app`; drag it to the Trash yourself if you want it gone.
It does not touch the website folder or a developer checkout either.

### Or run the script

```sh
scripts/uninstall.sh                 # CLI only, keeps your bottles
scripts/uninstall.sh --all-data      # CLI and every bottle; asks first
```

| Flag | Effect |
| --- | --- |
| `--all-data` | also delete `~/Library/Application Support/WehniX` |
| `--yes` | skip the confirmation prompt (needed outside a terminal) |
| `--pip` | also run `python3 -m pip uninstall -y wehnix-cli` |
| `--clean-path` | remove the installer's `~/.local/bin` line from your shell rc |

It prints every path it touches, verifies the result, and exits `1` if anything
is left behind. Custom `--state-dir` folders, and anything you pointed
`WEHNIX_CLI_STATE_DIR` at, are yours: the script never guesses at them, so
remove those yourself if you used one.

## Development

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"

pytest                                  # 82 tests, no network, no real data
WEHNIX_CLI_STATE_DIR="$PWD/tests/fixtures/state" WehniX
python scripts/make_screenshot.py       # regenerate docs/cli.svg
```

Tests copy `tests/fixtures/state` into a temporary folder and redirect `HOME`,
so the suite never reads or writes `~/Library/Application Support/WehniX` and
never sends anything to the real Trash.

## Limitations

* **No account features.** There is no sign-in, so playtime, cloud sync and the
  dashboard are not here. That is the point of this client, not a gap to fill.
* **Epic is read-only elsewhere.** Epic environments, logins and launches are
  the desktop app's job. `WehniX games` lists Steam libraries only.
* **Bottle settings follow the engine, not every switch the app has.** `e`
  changes the renderer, sync, Metal HUD, high resolution and launch program,
  but only where that engine supports them: DXVK needs the Universal payload to
  report `renders=1`, Universal has no esync, 11.17 has no high resolution, and
  a Steam bottle always launches Steam. Window geometry and per-game overrides
  stay in the app.
* **Creation is local.** It needs an engine archive already in `Engine/`; it
  never downloads one, and it reports a failed `codesign` instead of hiding it.
* **Beta.** The interface and the JSON shapes may still change between 0.x
  releases.

## License

Apache-2.0. See [LICENSE](LICENSE), [NOTICE](NOTICE),
[TRADEMARKS.md](TRADEMARKS.md) and
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

WehniX and WehniX CLI are trademarks of WEHNIT. The licence covers the code, not
the name — see [TRADEMARKS.md](TRADEMARKS.md) before publishing a fork.
