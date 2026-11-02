# Changelog

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
* The app-running guard ignores false positives from its own command line.

**Fixes against the previous prototype**

* Added the README the package metadata already pointed at.
* `prepare_state_dir()` no longer creates the app's data folder implicitly.
* Deleting a bottle matches `unique_id` records, not just `path`/`id`.
* Creating a bottle no longer writes a record the desktop app cannot read.
* Doctor checks grew from six to sixteen, and no longer treats a healthy
  0.92 GB Universal archive as "suspiciously small".
* The TUI no longer reports a traceback when a worker fails; it shows a toast.
