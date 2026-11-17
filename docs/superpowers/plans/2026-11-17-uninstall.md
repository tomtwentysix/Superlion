# Uninstall and Remove from Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Uninstall Steam games through Steam's confirmation dialog without its main window, and remove non-Steam games from the library.

**Architecture:** Both are items in `game_menu()` (`ui/library_view.py`), which builds the details page's ⋮ menu and the library's right-click menu. Uninstall sends `steam://uninstall/<id>` and polls for the manifest to go. Remove queues `{"remove": True}` in `pending.py`, written to `shortcuts.vdf` by `steam_settings.write_changes`.

**Tech Stack:** Python 3, GTK 4, libadwaita (PyGObject).

**Spec:** `docs/superpowers/specs/2026-11-17-uninstall-design.md`

## Global Constraints

- Lean, human-looking code: no section banners, no docstrings restating names, comments only for what code cannot show.
- UI copy: formal British English, GNOME HIG.
- Test only with `./run-dev.sh`; never touch `~/.config/superlion` or the installed app.
- No computer-use. Off-screen scripts for widgets; Tom checks anything visual or anything needing Steam's dialog.
- No test suite exists. Pure functions get a plain `python3 -I` assertion script under the scratchpad.
- Commits carry no Claude co-author line.

## Review Focus

- Uninstall while Steam is closed: Steam starts hidden and only its dialog shows (Task 1 spike, Tom checks).
- Cancelling Steam's dialog: poll times out silently, game stays.
- Removing a shortcut with other queued changes (rename, launch options): the removal wins and the rest are dropped.
- Removing a mod manager that games link to: links cleared, those games lose their Launch Mod Manager button.
- Removing while Steam runs with nothing open: Steam restarts quietly and the game disappears at once.

---

### Task 1: Spike — does `-silent` keep Steam's uninstall dialog?

- [ ] **Step 1:** With Steam closed, ask Tom to run `steam -silent steam://uninstall/<appid of a small installed game>` and say whether only the confirmation dialog appears (and cancel it).
- [ ] **Step 2:** Record the result in the spec. If the dialog does not appear, Task 2 uses the fallback in the spec (start silently, wait for `is_running`, then send the link).

### Task 2: Uninstall Steam games

**Files:**
- Modify: `superlion/steam_control.py` (`BACKGROUND_LINKS`)
- Modify: `superlion/ui/library_view.py` (`game_menu`)
- Modify: `superlion/ui/window.py` (new `uninstall_game`)

**Interfaces:**
- Produces: `window.uninstall_game(game)`.
- Consumes: `installer.is_installed_anywhere(config, appid)`, `window.launch(uri, message)`, `window.reload()`.

- [ ] **Step 1:** Add `"steam://uninstall/"` to `BACKGROUND_LINKS` (or the Task 1 fallback).
- [ ] **Step 2:** `uninstall_game(game)`: launch `steam://uninstall/<appid>` with message "Opening Steam's uninstall dialog", then poll every 2 s up to 60 s with `GLib.timeout_add_seconds`; when `is_installed_anywhere` turns False, pop the details page if its `game` is this one, `reload()`, and toast "<name> uninstalled".
- [ ] **Step 3:** In `game_menu`, add "Uninstall…" (action `game.uninstall`) in a final section, only for `game.props.installed and not game.props.non_steam`.
- [ ] **Step 4:** Off-screen check: build `game_menu` for an installed Steam game, a non-installed one and a shortcut; print item labels. Expected: "Uninstall…" only for the first.
- [ ] **Step 5:** Ask Tom to uninstall a small game from `./run-dev.sh`, with Steam closed and again with it running.
- [ ] **Step 6:** Commit: "Uninstall games through Steam's own dialog".

### Task 3: Remove non-Steam games

**Files:**
- Modify: `superlion/steam_settings.py` (`write_changes`)
- Modify: `superlion/game_collections.py` (new `forget(appid)`)
- Modify: `superlion/ui/library_view.py` (`game_menu`)
- Modify: `superlion/ui/window.py` (new `remove_shortcut`)

**Interfaces:**
- Produces: `steam_settings.remove_shortcuts(data: dict, appids: set[int]) -> dict` — drops matching entries from loaded `shortcuts.vdf` data and renumbers keys "0", "1", … in order; `game_collections.forget(appid)` — removes the app from Superlion's own collections; `window.remove_shortcut(game)`.
- Consumes: `pending.add`, `mod_managers.remove`, `steam_match.clear_override`, `window.write_to_steam(queue, ...)` from the quiet-restart plan (do that plan first).

- [ ] **Step 1:** Assertion script: `remove_shortcuts({"shortcuts": {"0": {"appid": 1}, "1": {"appid": 2}, "2": {"appid": 3}}}, {2})` gives keys `["0", "1"]` with appids 1 and 3; an unknown appid leaves data unchanged.
- [ ] **Step 2:** Run it; expect ImportError/AttributeError.
- [ ] **Step 3:** Implement `remove_shortcuts`. In `write_changes`, collect `removed = {int(a) for a, c in changes.items() if c.get("remove")}`, drop those appids from the other change maps, and apply `remove_shortcuts` before the rename/launch-options write.
- [ ] **Step 4:** Run the script; expect pass.
- [ ] **Step 5:** `remove_shortcut(game)`: `Adw.AlertDialog` heading "Remove from Library?", body "Remove <name> from your Steam library? Its files and compatibility files are kept.", responses "cancel"/"remove" (destructive). On remove: `pending.add(appid, {"remove": True})` replacing other queued keys for that appid; `mod_managers.remove(f"shortcut:{appid}")`, `steam_match.clear_override(appid)`, `game_collections.forget(appid)`; write through `window.write_to_steam` (quiet-restart plan); take the game out of `library.store`, pop its details page, toast "<name> removed".
- [ ] **Step 6:** In `game_menu`, add "Remove from Library…" (action `game.remove`) in the same final section for `game.props.non_steam`.
- [ ] **Step 7:** Ask Tom to add a throwaway shortcut in `./run-dev.sh` and remove it, with Steam closed and running.
- [ ] **Step 8:** Commit: "Remove non-Steam games from the library", then ask Tom about a release.
