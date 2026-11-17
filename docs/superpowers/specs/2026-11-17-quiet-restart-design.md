# Restarting Steam quietly

## Intent

Steam should sit in the background. Writing settings while it runs means restarting it,
and Superlion asks "Steam Must Be Closed" every time. Tom wants the question only when the
restart would close something he is using.

## Design

- One window method decides how queued changes reach Steam:
  - Steam closed: write now, as today.
  - Steam running and `steam_control.running_games()` empty: `relaunch_steam()` straight
    away, toast "Restarting Steam to apply your changes".
  - Something running: the existing dialog (Cancel / Apply When Steam Closes / Relaunch
    Steam Now), with the body naming what would close, e.g. "Vortex and Cyberpunk 2077 will
    close if Steam restarts now." Names come from the library; an app ID not in the library
    reads "a game".
- Used by: Apply on the Steam Settings tab, Sync Collections, Remove from Library, Update
  Now / Resume / Update All / Resume All, Update Immediately.
- Unchanged: renaming, hiding and favouriting keep waiting for Steam to close (Tom's
  approval of my call: avoids a restart per click).
- The pending banner's Relaunch Steam button is unchanged.

## Approaches

- **One shared method (chosen):** the two existing dialogs are near copies; the new features
  need the same decision.
- Per-feature checks: would repeat the logic five times.
