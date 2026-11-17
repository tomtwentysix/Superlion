# Starting updates

## Intent

Steam should sit in the background and its main window should never need opening. The
Downloads section shows waiting and paused updates but can only send you to Steam to start
them ("Resume these in Steam").

## Goals

- Start a waiting update, or resume a paused one, from Superlion.
- Let a game's updates download as soon as Steam finds them instead of at the scheduled time.

## Non-goals

- Pausing or cancelling downloads, reordering the queue, bandwidth limits.

## Constraints

- Steam has no link that starts an update. It reads app manifests only when it starts and
  overwrites them while running, so manifests are written while Steam is closed.
- Closing Steam closes running games, so restarting must not happen while one runs.

## Approaches

- **A: close Steam, flag the manifest, restart hidden (chosen).** Same flags `installer.py`
  writes to make Steam resume an install. Costs a Steam restart; Update All shares one.
- B: `steam://validate/<id>`. No restart, but checks every file of the game and shows a
  Steam progress window. Rejected.
- **C: per-game high priority (chosen, alongside A).** Sets the manifest's
  `AutoUpdateBehavior` so Steam fetches updates as soon as it finds them.

## Design

### Update Now and Resume (A)

- In Downloads, each "Updates Waiting" row gets an "Update Now" button and each "Paused"
  row a "Resume" button. Those two groups get a header button, "Update All" and
  "Resume All".
- A click queues `pending.add(appid, {"start_update": True})` for each game and goes through
  the quiet-restart method (`2026-11-17-quiet-restart-design.md`). When Steam was closed,
  it is then started hidden so the download begins. Other queued changes are written in the
  same restart.
- Applying sets the manifest's `StateFlags` to
  `(flags | UPDATE_REQUIRED | UPDATE_STARTED) & ~UPDATE_PAUSED`, in whichever library folder
  holds the manifest. A missing manifest (game uninstalled meanwhile) is skipped.
- While a game is running, the quiet-restart method asks first and names it.
- The "Paused" group description changes from "Resume these in Steam." to something that
  no longer sends you to Steam (my call: no description).
- A spike first confirms Steam starts a flagged update on launch. If it only does so for
  paused downloads and not waiting ones, stop and come back to Tom.

### Update Immediately (C)

- A switch on a game's Steam Settings tab, installed Steam games only: title "Update
  Immediately", subtitle "Download updates as soon as Steam finds them". On writes
  `AutoUpdateBehavior` "2", off writes "0".
- A game currently set to "1" (update only on launch, set in Steam) shows the switch off and
  keeps "1" unless the switch is changed.
- It is a normal Steam setting: queued as `{"auto_update": "2" | "0"}` and written through
  the Apply button, which uses the quiet-restart method.

## Left to the builder

- Exact placement of the header buttons and their style.
