# Quiet Restart Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restart Steam to write changes without asking, unless a game or shortcut is running, and then name it in the prompt.

**Architecture:** `window.apply_settings` becomes a thin wrapper over a new `window.write_to_steam(queue, ...)` that holds the closed / quiet / ask decision. `sync_collections` uses it too. Later plans (uninstall, updates) call it.

**Tech Stack:** Python 3, GTK 4, libadwaita (PyGObject).

**Spec:** `docs/superpowers/specs/2026-11-17-quiet-restart-design.md`

## Global Constraints

- Lean, human-looking code: no section banners, no docstrings restating names, comments only for what code cannot show.
- UI copy: formal British English, GNOME HIG.
- Test only with `./run-dev.sh`; never touch `~/.config/superlion` or the installed app.
- No computer-use; Tom checks anything visual.
- No test suite exists. Pure functions get a plain `python3 -I` assertion script under the scratchpad.
- Commits carry no Claude co-author line.

## Review Focus

- A running shortcut (mod manager) counts as running: `running_games()` reports shortcut IDs.
- A running app ID not in the library reads "a game", not a number.
- Two quick changes while Steam runs and nothing is open: one restart, both written (`_relaunching` guard plus the queue).
- The Steam Settings tab's Apply marks the settings applied after a quiet restart, as it does after Relaunch Steam Now.
- Sync Collections' quiet path still toasts that Steam uploads them to Steam Cloud.

---

### Task 1: `write_to_steam` and the running list

**Files:**
- Modify: `superlion/ui/window.py` (`apply_settings`, `sync_collections`, new `write_to_steam`, new module function `will_close_text`)

**Interfaces:**
- Produces: `will_close_text(names: list[str]) -> str`; `window.write_to_steam(queue: Callable[[], None], on_applied=None, parent=None, reload=False, saved_message="Settings saved", later_label="Apply When Steam Closes")`.
- Consumes: `steam_control.running_games()`, `window.find_game`, `window.relaunch_steam(reload)`.

- [ ] **Step 1:** Assertion script for `will_close_text`:
  - `["Vortex"]` → `"Vortex will close if Steam restarts now."`
  - `["Vortex", "Cyberpunk 2077"]` → `"Vortex and Cyberpunk 2077 will close if Steam restarts now."`
  - `["A", "B", "C"]` → `"A, B and C will close if Steam restarts now."`
- [ ] **Step 2:** Run it; expect ImportError.
- [ ] **Step 3:** Implement `will_close_text`; run the script; expect pass.
- [ ] **Step 4:** Implement `write_to_steam`: Steam closed → current closed-path behaviour of `apply_settings` with `saved_message`; running with `running_games()` empty → `queue()`, `on_applied()`, toast "Restarting Steam to apply your changes", `relaunch_steam(reload)`; otherwise the existing dialog, body "Steam keeps these settings in memory and overwrites any changes made while it is running. " + `will_close_text(names)`, middle response labelled `later_label`. Names from `find_game(appid).props.name`, else "a game".
- [ ] **Step 5:** `apply_settings(changes, ...)` calls `write_to_steam` with a queue that adds each game's changes. `sync_collections` calls it with `pending.add_collections_sync`, `saved_message` "Collections synced. Steam uploads them to Steam Cloud when it next starts." and `later_label` "Sync When Steam Closes".
- [ ] **Step 6:** Ask Tom to change a launch option in `./run-dev.sh` with Steam running and nothing open (expect a quiet restart), then again with a game open (expect the prompt naming it).
- [ ] **Step 7:** Commit: "Restart Steam without asking when nothing would close".
