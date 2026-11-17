# Uninstall and Remove from Library

## Intent

Steam should sit in the background and its main window should never need opening.
Superlion cannot uninstall games today. Steam's small confirmation dialog is acceptable;
its main window is not.

## Goals

- Uninstall installed Steam games from Superlion.
- Remove non-Steam games, mod managers included, from the Steam library.

## Non-goals

- Deleting a shortcut's Proton prefix or its files.
- Uninstalling Proton or other Steam tools.

## Approaches

- **Steam's uninstall link (chosen for Steam games).** `steam://uninstall/<id>` shows
  Steam's own confirmation and Steam removes files and prefix itself.
- Deleting files and manifest ourselves while Steam is closed: more control, but a Steam
  restart for every uninstall and a second implementation of Steam's own cleanup.
- Non-Steam games: Superlion edits `shortcuts.vdf` through the waiting-changes queue
  (`pending.py`), as renaming already does. Tom chose this over offering nothing.

## Design

### Steam games

- "Uninstall…" in the details page's ⋮ menu and the library's right-click menu
  (`game_menu`), for installed Steam games only.
- Sends `steam://uninstall/<id>` through `steam_control.open_uri`. `steam://uninstall/` joins
  `BACKGROUND_LINKS` so a closed Steam starts with `-silent`. A spike first confirms that the
  confirmation dialog still appears when Steam starts silently; if it does not, start Steam
  silently, wait until it is running, then send the link.
- Afterwards Superlion polls for the game's manifest to disappear (every 2 seconds, giving
  up after 60). When it goes, the library refreshes and an open details page for the game
  is popped. Cancelling in Steam's dialog leaves the manifest, so the poll just times out.

### Non-Steam games

- "Remove from Library…" in the same two menus, for non-Steam games.
- An `Adw.AlertDialog`: heading "Remove from Library?", body "Remove <name> from your Steam
  library? Its files and compatibility files are kept.", destructive response "Remove".
- Queued as `pending.add(appid, {"remove": True})` and written through the quiet-restart
  method (`2026-11-17-quiet-restart-design.md`). Applying deletes the entry from
  `shortcuts.vdf`.
- Superlion's own records are cleared straight away: `mod_managers.remove("shortcut:<id>")`
  (which also unlinks games), the store match override, and Superlion collection memberships.
- The game leaves the library immediately and an open details page for it is popped.

## Left to the builder

- Where the remove is written within `steam_settings.write_changes`.
- Whether other queued changes for a removed shortcut (rename, launch options) are dropped
  (my call: yes, a removal replaces them).
