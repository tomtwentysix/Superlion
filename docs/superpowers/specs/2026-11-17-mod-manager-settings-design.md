# Mod manager settings

## Intent

Steam should sit in the background as a service and never need opening. Mod managers
that run as non-Steam shortcuts (Vortex, Fluffy, AC Content Manager and so on) need their
Proton version, launch options, prefix folder and install folder changed now and then.
Marking a shortcut as a mod manager hides it from every library view, and the Mod Managers
page only offers Launch and Remove, so those settings are out of reach without Steam.

## Goals

- Reach a non-Steam mod manager's full details page from the Mod Managers page.
- Make that page read as a mod manager's rather than a game's.

## Non-goals

- Settings for Linux application mod managers: they have no Steam settings.
- Separate launch settings per linked game. Steam keeps one set per shortcut.

## Approaches

- **Reuse the game details page (chosen).** It already has Compatibility Tool and Launch
  Options (Steam Settings tab) and Location and Compatibility Files (Information tab),
  plus artwork, renaming and the apply-while-Steam-is-closed flow.
- A separate mod manager settings page: duplicates the above and drifts from it.

## Design

- Each non-Steam manager's row on the Mod Managers page gets a cog button
  (`emblem-system-symbolic`, tooltip "Settings") between Launch and the remove button. It
  opens `GameDetailsPage` for that shortcut. The row itself stays unactivatable.
- No cog for Linux application managers, nor for a manager whose shortcut is no longer in
  the library.
- On a mod manager's details page:
  - the primary button reads "Launch" instead of "Play";
  - the Information tab gains a "Used By" row listing the linked games' names.

## Left to the builder

- How the Used By row lays out long lists (my call: names joined with commas, wrapping).
- How the cog finds the `Game` object for a shortcut app ID.
