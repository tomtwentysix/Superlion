# Moving games and managing library folders

## Intent

Tom keeps Steam closed in the background and never wants its main window. Moving games
between drives, and clearing out a drive, still need Steam's Storage settings. Superlion
should move Steam games between libraries and non-Steam games to any folder, and let Tom
open a library folder in Preferences, select games and act on them together: "click the SSD
library, select two games and move them to the NVMe library".

## Goals

- Move an installed Steam game to another Steam library, with its Proton prefix, shader
  cache and Workshop content, without Steam re-downloading or verifying it.
- Move a non-Steam game's folder to a folder Tom picks, and keep its shortcut working.
- In Preferences, open a library folder to see its games with their sizes, select several,
  and Move, Uninstall, Add to Collection, Hide or Set Proton Version for all of them at once.
- Show progress for moves across drives; same-drive moves are instant renames.

## Non-goals

- Adding or creating Steam libraries.
- Bulk actions on non-Steam games (they do not live in library folders).
- Moving a non-Steam game's Proton prefix: it lives in Steam's main library, keyed by the
  shortcut's app ID, and does not depend on where the game is.
- Changing single-game Uninstall, which keeps Steam's own confirmation dialog.

## Anti-goals

- Opening Steam's main window.
- Leaving a game half-moved, or deleting the original before the copy is complete.
- Moving or deleting files that belong to other games.
- Anything starting Steam, or writing Steam's files, while a move is under way.

## Constraints

- Steam must be closed while a manifest moves or is deleted, or `shortcuts.vdf` is rewritten:
  it reads both at start and overwrites them on exit.
- No steam:// link or command-line option starts Steam's own mover, so Superlion moves the
  files itself.
- `steam_control.relaunch` runs its work on the main thread; a copy of tens of gigabytes
  cannot, so moving needs its own close → work (worker thread) → start sequence.
- `Gio.Menu` items have no tooltips and are built once, so whether a game can move is
  checked when the item is chosen, and the reason shown in a dialog.

## Test result (19 November 2026)

Star Trek Online (9900, 546 MB, with prefix and shader cache) was moved by hand with Steam
closed, from `/mnt/ssd/SteamLibrary` to `~/.local/share/Steam` (across drives, 67 s):
`common/Star Trek Online`, `compatdata/9900`, `shadercache/9900`, then
`appmanifest_9900.acf`. Steam started with `-silent`:

- It showed the game Fully Installed on the same build, with nothing to download or verify.
- It rewrote `libraryfolders.vdf` itself, listing 9900 under the new library.
- It recreated nothing in the old library.
- It ran a 990 MB shader download, which it also ran the day before with no move, so that is
  the game's normal shader refresh.

Not yet tested: Workshop content, and deleting a game while Steam is closed (bulk Uninstall).
The plan starts with a test of the latter on a small game Tom picks.

## Approaches

- **Superlion moves and deletes the files with Steam closed (chosen).** Proven for moving by
  the test; keeps Steam hidden; one confirmation for a bulk uninstall.
- Steam's Storage page for moves: shows the main window.
- Steam's uninstall link per game for bulk uninstall: one Steam dialog per game (Tom chose
  Superlion deleting instead).

## Design

### The job runner

One component runs a list of jobs (move a Steam game, move a shortcut's folder, delete a
Steam game) as one sequence:

1. Steam running and nothing running under it: close it without asking. Something running:
   the "Steam Must Be Closed" dialog naming it, with Cancel and "Close Steam and Move" (or
   "… and Uninstall"). No "later" option: Tom is waiting for the result.
2. Jobs run one at a time in a worker thread. Progress is shown as "Moving Star Trek
   Online (1 of 2)… 4.2 of 12.0 GB" on the moved game's details page and on the library
   folder page, whichever is open; a toast says when it starts.
3. When all jobs end: apply anything queued in `pending.json` (as `relaunch` does), then the
   shortcut path rewrites, so a queued launch option cannot put an old path back. Reload the
   library, toast the result ("2 games moved to /mnt/nvme/SteamLibrary"), and start Steam
   hidden if it was running before.
4. A failed job (disk full, permission denied, I/O error) rolls back only itself; later jobs
   still run. An `Adw.AlertDialog` lists what failed and why.

While a job list runs, Superlion holds everything else that touches Steam:

- the pending watcher does not write;
- `write_to_steam` queues changes and toasts "Saved. Steam gets this when the move finishes.";
- Play, Install, Uninstall, Start Updates and the Relaunch Steam banner do not start Steam,
  and toast "Steam starts when the move finishes" instead;
- Move, Uninstall and the bulk actions are unavailable.

Quitting during a job list (window close or Ctrl+Q; neither is hooked today) asks first,
"A Game Is Being Moved"; quitting anyway stops after rolling back the current job, applies
pending changes, and starts Steam if it was running.

### Moving a Steam game

Destinations are the libraries in `libraryfolders.vdf` other than the game's, including ones
turned off in Superlion. Games in "Other Folders" (libraries Steam does not list) can move
to a Steam library, which is how an old drive is emptied; they cannot be a destination.

What moves, from `<old>/steamapps` to `<new>/steamapps`, in this order:

1. `common/<installdir>`
2. `compatdata/<appid>`, `shadercache/<appid>`, `workshop/content/<appid>` and
   `workshop/appworkshop_<appid>.acf`, each only if present
3. `appmanifest_<appid>.acf`, last, so the game only appears in the new library once its
   files are there

Same drive: `os.rename` each. Across drives: copy everything first, then move the manifest,
then delete the originals. If any destination already exists, the job fails before touching
anything and names the folder in the way.

A Steam game can move when it is installed and not downloading, updating or paused (fully
installed, with or without an update waiting), is not running, and there is another library.

Single move: "Move…" in `game_menu()`, in the section with Uninstall and Remove from
Library. It opens an `Adw.AlertDialog`, heading "Move <name>", listing the other libraries
with path and free space. A library on another drive without room is listed but cannot be
picked ("Not enough space"). The size is the manifest's `SizeOnDisk` plus the measured size
of the prefix, shader cache and Workshop content.

### Moving a non-Steam game

Superlion suggests the folder to move: the highest folder above the shortcut's executable
(from `Exe`, falling back to `StartDir`) that contains no other shortcut's executable, is
not the home folder or a mount point, and is not inside a Steam library's `steamapps`. If
the executable's own folder fails that, other shortcuts share it: those shortcuts move with
it (the three Jak games share `/mnt/ssd/Games/Jak and Daxter`).

The dialog, heading "Move <name>", shows "Folder to move" with the suggestion, a button to
pick a parent folder instead, the other shortcuts that will move with it, and "Move To" with
a folder chooser (`Gtk.FileDialog.select_folder`). The folder moves into the chosen folder
under its own name; the chosen folder must not be inside it, and `<chosen>/<name>` must not
exist. Shortcuts whose executable is not a file path (Heroic, Lutris, `flatpak run`) cannot
move; the dialog says so.

In each moved shortcut's `shortcuts.vdf` entry, the old folder as a path prefix is replaced
with the new one in `Exe`, `StartDir`, `icon` and `LaunchOptions`. Shortcuts keep their
stored app IDs, so artwork, Proton prefixes, mod manager links and collections stay
attached. When Steam is the Flatpak and cannot read the new folder,
`shortcuts.grant_flatpak_access` is called, as Add Game does.

### Library folder pages

In Preferences, each row under Library Folders and Other Folders gets a "Show Games" suffix
button (`go-next-symbolic`) that pushes a subpage titled with the folder's short path:

- a summary line: "12 games · 486 GB used · 284 GB free";
- one row per installed game in that library, sorted by name, with its size and a check
  button; tools and runtimes (Proton, Steam Linux Runtime) are listed last under "Tools";
- a header toggle to select all or none;
- an action bar showing "2 selected · 38.4 GB" with Move To…, Uninstall… (destructive) and
  a menu button for Add to Collection, Hide and Set Proton Version.

Actions:

- **Move To…**: the destination list from single Move, sized for the whole selection; one
  job list.
- **Uninstall…**: one `Adw.AlertDialog`, "Uninstall 2 Games?", naming them and the space
  freed, saying saves kept only in the prefix are deleted too. Then one job list that
  deletes each game's folder, prefix, shader cache, Workshop content and manifest (the
  manifest first, so an interrupted delete leaves Steam seeing it uninstalled, not broken).
- **Add to Collection**, **Hide** and **Set Proton Version**: the same changes the details
  page makes, for every selected game, written through one `write_to_steam` call.

Selections clear after an action; the page refreshes when its job list ends.

## Left to the builder

- Widget layout of the rows, action bar and progress display.
- How copy progress is measured (bytes copied over total, polled from the worker).
- Whether the size check uses a margin.
- Task order, as long as the deletion test comes before bulk Uninstall is built.
