# Starting Updates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Start waiting updates and resume paused downloads from Superlion, and let games update as soon as Steam finds an update.

**Architecture:** Two new pending keys, `start_update` and `auto_update`, are written to app manifests by `installer.py` while Steam is closed, through `window.write_to_steam` (quiet-restart plan). Downloads rows get buttons; the Steam Settings tab gets a switch.

**Tech Stack:** Python 3, GTK 4, libadwaita (PyGObject).

**Spec:** `docs/superpowers/specs/2026-11-17-start-updates-design.md`

## Global Constraints

- Lean, human-looking code: no section banners, no docstrings restating names, comments only for what code cannot show.
- UI copy: formal British English, GNOME HIG.
- Test only with `./run-dev.sh`; never touch `~/.config/superlion` or the installed app.
- No computer-use; Tom checks anything visual or anything needing Steam.
- No test suite exists. Pure functions get a plain `python3 -I` assertion script under the scratchpad.
- Commits carry no Claude co-author line.
- Do the quiet-restart plan first.

## Review Focus

- Steam closed when Update Now is clicked: manifest written, then Steam started hidden so the download begins.
- Game uninstalled between queueing and applying: its manifest is missing and it is skipped without an error.
- A game set to "1" (update on launch) in Steam: the switch shows off and a save that does not touch it keeps "1".
- Update All with five games: one restart.
- A queued `start_update` alongside a queued `auto_update` for the same game: both land in one manifest write.

---

### Task 1: Spike — does Steam start a flagged update?

- [ ] **Step 1:** With Tom: pick a game in "Updates Waiting", close Steam, back up its manifest, set its `StateFlags` to `(flags | 2 | 1024) & ~512` (with Tom's go-ahead, as this is his real Steam), start `steam -silent`, and watch Downloads in `./run-dev.sh`.
- [ ] **Step 2:** If the update starts, record it in the spec and go on. If not, stop and bring the result to Tom before Task 2.

### Task 2: Manifest writes

**Files:**
- Modify: `superlion/installer.py`
- Modify: `superlion/pending.py` (`apply_now`)

**Interfaces:**
- Produces: `installer.started_flags(flags: int) -> int`; `installer.find_manifest(config, appid) -> Path | None`; `installer.read_auto_update(config, appid) -> str` ("0" when missing); `installer.update_manifests(config, changes: dict[int, dict]) -> None` applying `start_update` and `auto_update` keys, skipping missing manifests. Steam must not be running.
- Consumes: `downloads.UPDATE_REQUIRED`, `UPDATE_STARTED`, `UPDATE_PAUSED`.

- [ ] **Step 1:** Assertion script: `started_flags(4 | 2) == 4 | 2 | 1024`; `started_flags(4 | 2 | 1024 | 512) == 4 | 2 | 1024`; `started_flags(4) == 4 | 2 | 1024`.
- [ ] **Step 2:** Run it; expect AttributeError.
- [ ] **Step 3:** Implement the four functions. `update_manifests` loads each manifest once with `vdf.load`, edits `AppState.StateFlags` and/or `AppState.AutoUpdateBehavior`, and writes atomically like `write_manifest`.
- [ ] **Step 4:** Run the script; expect pass. Extend it with a temp library folder holding one manifest: after `update_manifests` with both keys the file has the new flags and `AutoUpdateBehavior "2"`; an appid with no manifest raises nothing.
- [ ] **Step 5:** In `pending.apply_now`, after installs, pop `start_update` and `auto_update` from each queued game into one dict, call `installer.update_manifests`, then pass what remains to `steam_settings.write_changes`. `count()` still counts them as changes.
- [ ] **Step 6:** Commit: "Write update starts and update priority to app manifests".

### Task 3: Update Now, Resume and Update All

**Files:**
- Modify: `superlion/ui/window.py` (`write_to_steam` gains `start=False`; new `start_updates`)
- Modify: `superlion/ui/downloads_view.py`

**Interfaces:**
- Produces: `window.start_updates(appids: list[int])`.
- Consumes: `window.write_to_steam(queue, ..., start=True)` — with `start`, the closed path starts Steam hidden after writing.

- [ ] **Step 1:** Add `start` to `write_to_steam`. `start_updates` queues `{"start_update": True}` per app ID and calls it with `saved_message` "Starting updates", `later_label` "Update When Steam Closes", `start=True`.
- [ ] **Step 2:** `DownloadRow` gets a button for waiting ("Update Now") and paused ("Resume") items, hidden for downloading ones and refreshed in `update()`. The Waiting and Paused groups get header-suffix buttons "Update All" and "Resume All". The Paused group loses its "Resume these in Steam." description.
- [ ] **Step 3:** Off-screen check: build `DownloadsView` with fake `Download` items of each status and print each row's suffix labels and the group header buttons.
- [ ] **Step 4:** Ask Tom to try Update Now on a waiting game in `./run-dev.sh`.
- [ ] **Step 5:** Commit: "Start and resume updates from Downloads".

### Task 4: Update Immediately

**Files:**
- Modify: `superlion/ui/details.py` (`_build_settings`, `_current_settings`)

**Interfaces:**
- Consumes: `installer.read_auto_update`, the `auto_update` pending key.

- [ ] **Step 1:** For installed Steam games, add an `Adw.SwitchRow` titled "Update Immediately", subtitle "Download updates as soon as Steam finds them", to the settings group. Loaded value from the pending queue, else `read_auto_update`; active when "2".
- [ ] **Step 2:** `_current_settings` reports `auto_update` as "2" when on; when off it reports "0", except when the loaded value was "1" and the switch is untouched, where it reports "1" so nothing changes.
- [ ] **Step 3:** Off-screen check: build the page for an installed game and print the switch state; flip it and print `_changed_settings()`. Expected `{"auto_update": "2"}`.
- [ ] **Step 4:** Commit: "Let games update as soon as Steam finds an update", then ask Tom about a release.
