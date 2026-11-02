# Changelog

## 0.3.1

Setup is quieter, cancellable, and takes either engine spelling.

**Added**

* `WehniX setup --engines universal,steam` — a comma or space separated list,
  alongside the existing repeatable `--engine`.

**Fixed**

* Download progress was drawn once per megabyte, so a 1 GB engine produced
  thousands of lines. It is now rate limited to about one line per percent and
  per quarter second, and a stage change or the final `100%` is always shown.
  `ProgressThrottle` is pure logic with an injectable clock and is tested.
* `Ctrl+C` during setup or `engines install` used to surface as a traceback and
  could leave a `.part` download behind. It now prints a cancellation line,
  returns exit code `1`, deletes the partial file and the extraction staging
  folder, and leaves `setup_complete` at `false`.

## 0.3.0

First-run setup, with pinned and verified engine downloads.

**Added**

* `WehniX setup` creates the same data folder the desktop app does (`Engine/`,
  `bottles/`, `cli/`, `logs/`), writes a desktop-shaped `config.json`, an empty
  `bottles.json`, and installs the Universal engine.
  `--engine steam` and `--engine 11.11` add or install others.
* `WehniX engines install universal|steam|11.11` installs one engine without
  touching `config.json`, and `WehniX engines doctor` reports each engine's
  path, size, health and required members.
* Downloads are pinned to three WX-Wine release assets, over HTTPS, verified by
  SHA-256 while streaming, written to `.part` and promoted only on a match.
* A verified archive already in `Engine/.downloads/` is reused instead of being
  fetched again; mismatched or partial files are deleted.
* The superseded Universal build (`e8e77b…05f5`, missing
  `scripts/wx-session.sh`) is refused even though its own checksum is valid.
* Archives are validated before extraction, after extraction and after
  repacking to the desktop's `Engine/WehniX Engine ….zip`; `setup_complete` is
  written only after that verification passes.
* `--force` is required to install while WehniX.app is open.

**Changed**

* The README's "nothing is downloaded" claim now states exactly what the
  network is used for: an explicit `setup` or `engines install`, nothing else.
* `doctor` names the installed engine's path and suggests `WehniX setup` when
  the Universal archive is missing.
* The Engines empty state points at `WehniX setup` instead of only the app.

**Limits**

* Universal's helper scripts are installed as shipped. The desktop repoints
  them at the Python inside `WehniX.app` before sealing the bundle; the CLI has
  no such interpreter to point at.

## 0.2.1

Doctor tells first run apart from breakage.

**Fixed**

* A Mac that has never run WehniX no longer reports a dozen errors. The missing
  data folder is the single failure; `config.json`, setup, the bottles checks,
  both engines and the logs are `skipped` instead, with one hint naming the next
  step: open WehniX.app and finish setup, which is what installs engines.
* The private-folder check is skipped when there is no folder to judge, instead
  of failing with a `chmod` hint for a path that does not exist.
* A missing `config.json` is a warning, not an error, while an unreadable one
  stays an error.
* `Engine archives look complete` reports `skipped` when no archive exists, so
  it can no longer pass without checking anything.
* `Engine for new bottles` is answered from installed archives only.
* An absent `WehniX.app` is a warning: this CLI is a front end, not the
  installer.

**Added**

* `Check.status` (`passed`, `failed`, `warning`, `skipped`), exposed in
  `doctor --json` together with `skipped` totals. Skips are not counted as
  errors or warnings and are drawn dim in the interface.
* Tests for a missing folder, an unreadable one, a world-writable one, a
  missing config, an absent app, and empty / near-threshold / healthy engine
  archives.

## 0.2.0

Per-bottle settings, read from the engine instead of the registry.

**Added**

* `e` opens a bottle settings editor: renderer, sync, Metal HUD, high
  resolution, launch program and launch flags, with unsupported fields disabled
  and the reason shown.
* `WehniX settings bottle <name>` reads one bottle and accepts `--renderer`,
  `--sync`, `--metal-hud on|off`, `--high-res on|off`, `--program` and
  `--flags`, with the same engine checks as the interface.
* Engine capability matrix ported from the desktop: Universal offers DXMT,
  D3DMetal and capability-gated DXVK with `none`/`msync`; Steam offers
  DXMT/D3DMetal with `none` only and a locked program; GPTK is D3DMetal with the
  legacy sync set; 11.11/11.0 are DXMT-only. `high_res` is offered on GPTK and
  legacy builds, never on 11.17.
* `state.read_bottle_app_settings()` reads `wehnix.json` (Universal, Steam,
  11.11) or `Info.plist` (GPTK, 11.0), including Universal's shared target via
  the bundle's own `wx-target` tool — with a documented failure instead of a
  traceback when the file or tool is missing.
* `actions.set_bottle_setting()` validates every value before writing, writes
  Universal's target before its JSON, keeps plist values as the integers the
  app reads, and syncs the `bottles.json` record afterwards.
* `--program` accepts a macOS path and maps it to `C:\…` or `Z:\…`.

**Changed**

* Scanning reads renderer, sync, Metal HUD, high resolution and the program from
  the bottle's engine files first; a stale `bottles.json` value no longer
  overrides what the bottle will actually launch with. The new `settings_source`
  field reports `app`, `record`, `default` or `error`.
* Bottle details (`s`) stay read-only and now point at `e`.

## 0.1.0

First public release.

**Interface**

* Keyboard-first Textual interface with seven sections: Bottles, Games,
  Engines, Doctor, Logs, Settings, Storage.
* Live filter (`/`) over bottle name, engine, environment and renderer.
* Bottle details (`s`) read straight from the bottle's `Info.plist` and record.
* Command palette entries for every action, plus a single-line status strip
  showing the version, licence, credit and live health.
* Empty states for every section that name the next action.
* Runs cleanly at 80×24 and looks intentional at 140×40.

**Data**

* Reads the desktop app's real layout: `config.json`, `bottles.json`,
  `bottles/<unique_id>/<Name>.app`, `Engine/` and `logs/wehniX.log`.
* Understands records keyed by `unique_id`, `id`, `path` or bundle name, and
  bottles stored flat (`.app` directly under `bottles/`) or nested.
* Engine identity comes from the archive name, and only the word "universal"
  earns `11.17-universal`; a bare `11.17` is the Steam build.
* Bottle creation follows the desktop's engine and environment rules, stages
  the extraction, brands the plist, signs the bundle and writes a
  desktop-shaped record — or leaves nothing behind.
* Settings writes are limited to three keys and use optimistic concurrency.
* Every archive member and symlink target is validated before extraction.

**Commands**

* `list`, `show`, `games`, `engines`, `doctor`, `open`, `logs`, `settings`,
  `storage`, `init`, `version`, with `--json` and stable exit codes (0, 1, 2).
* `scripts/uninstall.sh` removes the CLI and keeps your bottles by default;
  `--all-data` also removes the shared data folder after a confirmation.
* The app-running guard ignores false positives from its own command line.

**Fixes against the previous prototype**

* Added the README the package metadata already pointed at.
* `prepare_state_dir()` no longer creates the app's data folder implicitly.
* Deleting a bottle matches `unique_id` records, not just `path`/`id`.
* Creating a bottle no longer writes a record the desktop app cannot read.
* Doctor checks grew from six to sixteen, and no longer treats a healthy
  0.92 GB Universal archive as "suspiciously small".
* The TUI no longer reports a traceback when a worker fails; it shows a toast.
* `scripts/install.sh` hands pip a `git+` URL, so a fresh install completes
  instead of failing with "cannot detect archive format".
* `doctor` exits `2` when the data folder does not exist yet, matching the
  documented exit codes for every other command.
* The installer detects a case-insensitive volume by file contents, so it
  creates `WehniX` (not whichever spelling ran last) and never duplicates it
  on a re-run.
