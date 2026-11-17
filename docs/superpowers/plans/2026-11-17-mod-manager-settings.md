# Mod Manager Settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reach a non-Steam mod manager's details page from the Mod Managers page, and make that page read as a mod manager's.

**Architecture:** A cog button on each non-Steam manager row calls the existing `window.open_game()` with the shortcut's `Game`. `GameDetailsPage` checks whether its game is a mod manager to change the primary label and add a Used By row.

**Tech Stack:** Python 3, GTK 4, libadwaita (PyGObject).

**Spec:** `docs/superpowers/specs/2026-11-17-mod-manager-settings-design.md`

## Global Constraints

- Lean, human-looking code: no section banners, no docstrings restating names, comments only for what code cannot show.
- UI copy: formal British English, GNOME HIG (title case for titles and buttons, sentence case for subtitles).
- Test only with `./run-dev.sh` (settings in `~/.config/superlion-devel`); never touch `~/.config/superlion`.
- No computer-use. Check UI by building widgets off screen in a script; ask Tom to look at anything visual.
- The project has no test suite. Verification is an off-screen script under the scratchpad that builds the widgets and prints rows.
- Commits carry no Claude co-author line.

## Review Focus

- A linked game that is no longer in the library (uninstalled non-Steam game, removed licence): Used By skips it rather than showing an app ID or crashing.
- A manager linked to no games: Used By reads "No games".
- A shortcut manager whose shortcut was deleted in Steam: no cog, row still offers Launch and Remove.
- Turning the Mod Manager switch off on the details page opened from the cog: the page stays usable and Mod Managers refreshes when you go back (existing `set_mod_manager_shortcut` path).
- Linux application managers: no cog.

---

### Task 1: Cog button on Mod Managers rows

**Files:**
- Modify: `superlion/ui/library_view.py` (`_show_mod_managers`)

**Interfaces:**
- Consumes: `window.find_game(appid) -> Game | None`, `window.open_game(game)`, `ModManager.is_app`, `ModManager.shortcut_appid`.

- [ ] **Step 1:** In `_show_mod_managers`, for each manager that is not `is_app` and whose `self.window.find_game(manager.shortcut_appid)` is not None, add a flat `Gtk.Button(icon_name="emblem-system-symbolic", tooltip_text="Settings", valign=CENTER)` that calls `self.window.open_game(game)`. Suffix order: Launch, cog, remove.
- [ ] **Step 2:** Off-screen check: a scratch script with `SUPERLION_DEVEL=1` that builds the window's library view, switches to `mod_managers`, and prints each row's title and suffix button tooltips/labels. Expected: shortcut managers show `Launch, Settings, Stop Using as Mod Manager`; app managers show no `Settings`.
- [ ] **Step 3:** Commit: "Open a mod manager's settings from the Mod Managers page".

### Task 2: Mod manager details page

**Files:**
- Modify: `superlion/mod_managers.py`
- Modify: `superlion/ui/details.py` (`_play_label`, `_build_info`)

**Interfaces:**
- Produces: `mod_managers.linked_games(manager_id: str) -> list[int]` — game app IDs linked to that manager.
- Consumes: `window.find_game(appid)`, `mod_managers.shortcut_ids()`.

- [ ] **Step 1:** Add `linked_games(manager_id)` beside `link_counts`, reading `_load()["links"]`.
- [ ] **Step 2:** In `GameDetailsPage`, a manager is `game.props.non_steam and game.props.appid in mod_managers.shortcut_ids()`. `_play_label` returns `"Launch"` for an installed manager (managers do not get Steam updates, so no "Update and" variant).
- [ ] **Step 3:** In `_build_info`, for a manager, add after the Mod Manager switch an `info_row("Used By", ...)` with the found games' names sorted case-insensitively and joined with ", ", or `"No games"` when none are found. Missing games are skipped.
- [ ] **Step 4:** Off-screen check: script opens `GameDetailsPage` for one of the dev config's shortcut managers and prints the primary label and the Information rows. Expected: label `Launch`, a `Used By` row listing names. Then for a normal game: label `Play`, no `Used By`.
- [ ] **Step 5:** Commit: "Show Launch and the games using a mod manager on its page".
- [ ] **Step 6:** Ask Tom to look at both in `./run-dev.sh`, then ask whether to release.
