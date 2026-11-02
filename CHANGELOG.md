# Changelog

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
