# Superlion

A native GNOME (GTK 4 and libadwaita) front end for your Steam library, named after the Fowler B6 Super Lion steam road locomotive. Its icon shows the flywheel of Supreme of S J Wharton Ltd in Witney.

Superlion is dedicated to the memory of John Wharton of S J Wharton Ltd (1953–2026).

## Features

### Library
- Installed games from every Steam library folder, plus non-Steam games added to Steam, with Steam's cover art and any custom artwork you have set.
- Once your Steam account is connected, the games you own but have not installed, each with an **Install** button on its cover.
- A sidebar with views (All Games, Installed, Not Installed, VR Games, Non-Steam Games, Mod Managers), Steam's own collections, and your own collections.
- Search that ignores case, punctuation and ™, and matches initials (“re3” finds *Resident Evil 3*) and app IDs.
- Sort by name, size, last played or release date, and group by genre, release year or installed state.
- A right-click menu on every game: play or install, details, store page, game and compatibility files, favourite, collections, and hide.

### Game pages
- **Overview**: trailers, screenshots, description and developer updates from the Steam store.
- **Information**: install size, location, compatibility files (the Proton prefix), release date, genres, VR support, collections, a linked mod manager, and artwork.
- **Steam Settings**: launch options and compatibility tool (Proton version). The ⚙ button beside the launch options opens the launch options builder; the menu beside it fills in a preset, saves the current launch options as one, or opens the preset manager.
- **Play**, **Launch Mod Manager** when a mod manager is linked, and a **⋮** menu with View in Store, Browse Game Files and Open Compatibility Files.

### Non-Steam games
- Rename them; suggestions from the Steam store fill in a game's exact name.
- Match them to the same game on the Steam store, automatically by exact name or by choosing it yourself. A matched game gets that game's store page, news, release date, genres and artwork. Steam's artwork fills any missing images, and you are asked before custom images are replaced.

### Collections
- Steam's collections, Favorites and Hidden are shown, and can be renamed, deleted and added to. Hiding a game adds it to Steam's Hidden collection.
- Your own collections can be created, renamed and deleted, and copied into Steam with **Sync Collections to Steam**.

### Mod managers
- Add Linux applications as mod managers, or mark a non-Steam game as one with its **Mod Manager** switch. Non-Steam mod managers are listed under Mod Managers instead of with your games.
- Link a game to a mod manager to get a **Launch Mod Manager** button on its page and in its right-click menu.

### Launch options builder
- Build a game's launch options by switching settings on and off instead of typing them. The settings offered are gathered from the launch options of all your games, plus GameMode, MangoHud, Gamescope and Proton's log, grouped as Tools, Display and HDR, NVIDIA and DLSS, Proton and Wine, Audio, VR, other variables and game arguments.
- Each setting says what it does, where Superlion knows, and how many of your games use it. Settings with a value, such as DLL overrides or Gamescope's options, can be edited, and offer the values your games already use.
- **Add Setting** (the + button) adds a setting to the builder for every game: one of Superlion's suggestions, such as Disable Fsync, DXVK Frame Rate Limit or the CachyOS performance profile, or your own environment variable, program or game argument, with an optional display name, group and description. Settings you added have a remove button.
- Anything else can be typed once in **Your Own**. Settings the game already has keep their order, and nothing unrecognised is dropped.

### Launch option presets
- Save launch options you use often, such as `gamemoderun mangohud %command%`, as named presets, and fill them into any game's launch options from its Steam Settings.
- **Launch Option Presets** in the main menu creates, edits and deletes presets, and lists the launch options already set for your games so any of them can be saved as a preset.
- Presets are kept by Superlion only; a game's launch options are written to Steam when you press **Apply**, as with any other change.

### Artwork
- Choose a cover, background, logo or wide cover from a file, or from [SteamGridDB](https://www.steamgriddb.com) inside the app. Custom artwork is saved where Steam keeps its own, so Steam uses it too after it restarts.

### Downloads
- Steam's downloads and updates, read from its own files: downloading (with progress and the current download rate), paused, and updates waiting with their scheduled time. The tab shows a count of them.
- Games that are downloading show their state on their cover and game page: **Play** becomes “Updating 42%”, “Update Paused” or “Update Queued” and is greyed out until Steam finishes, with a progress bar, amount downloaded and current speed.
- Downloads are controlled in Steam; **Open Downloads in Steam** goes straight there.

### Store
- Native store browsing, search and game pages, with prices in your Steam profile's country (or the United Kingdom's when it shows none).
- Buying, the cart and the wishlist use Steam's own web pages inside the app, where you sign in on Steam's own sign-in page as in any browser.

## Requirements

Fedora with GNOME already provides everything Superlion needs: GTK 4, libadwaita, WebKitGTK 6.0, GStreamer, libsecret and `python3-requests`. The RPM below installs anything missing.

## Installing

Build an RPM from the project folder, then install it with `dnf`, which also installs any missing dependencies:

```bash
packaging/build-rpm.sh
```

```bash
sudo dnf install ./dist/superlion-0.6-1.fc44.noarch.rpm
```

This installs the `superlion` command, the app grid launcher and the icons. Store trailers need an H.264 decoder; `dnf` installs one if it is available from your enabled repositories (`gstreamer1-plugin-libav` or `gstreamer1-plugin-openh264`).

## Running from the project folder

From the project folder:

```bash
python3 -m superlion
```

To show Superlion in the GNOME app grid and dock, install its launcher for your user:

```bash
install -Dm644 data/uk.co.solarflareit.Superlion.desktop ~/.local/share/applications/uk.co.solarflareit.Superlion.desktop
```

The launcher runs the app from `/home/tom/Documents/Claude/Code/Superlion` and uses the PNG icon there by its full path, because GNOME Shell on this system cannot load SVG icons. If you move the project, edit `Path=` and `Icon=` in `data/uk.co.solarflareit.Superlion.desktop` and install it again.

## Setup and Preferences

The first launch opens a setup wizard. It detects your Steam installation (native or Flatpak), the command used to start Steam, your account and your library folders, and every choice has an **Other…** option for entering a value by hand. It then offers two optional steps, each with links to the pages involved:

- **Steam account**, by your own Steam Web API key, which Superlion can fetch for you.
- **SteamGridDB**, by pasting a free API key.

After that, **Preferences** in the main menu changes the same settings, signs in or out of Steam, connects or disconnects SteamGridDB, and can run the setup wizard again.

## How changes reach Steam

Steam keeps several of its files in memory and overwrites them when it exits, so Superlion writes to these only while Steam is closed:

| Change | Steam file |
|---|---|
| Launch options | `userdata/<account>/config/localconfig.vdf` (non-Steam games: `shortcuts.vdf`) |
| Compatibility tool | `config/config.vdf` |
| Non-Steam game names | `userdata/<account>/config/shortcuts.vdf` |
| Collections, Favorites and Hidden | `userdata/<account>/config/cloudstorage/cloud-storage-namespace-1.json` |

If Steam is closed, changes are written straight away. If Steam is running, they wait, and a banner shows how many are waiting with a **Relaunch Steam** button. Waiting changes are also written as soon as Steam exits while Superlion is open, or the next time Superlion starts with Steam closed. Changing a game's settings while Steam is running instead asks whether to relaunch Steam now or apply the change when Steam closes.

Before each write, the original file is copied to `<file>.superlion-bak-<date>-<time>`; for settings files, the five most recent copies are kept. Collection changes are also marked for Steam to upload to Steam Cloud when it next starts.

Custom artwork is the exception: it is saved to `userdata/<account>/config/grid` at any time, as Steam reads that folder rather than holding it in memory.

## Accounts

### Steam account

Superlion lists the games you own with your own **Steam Web API key**, which Valve provides free to every Steam account (except limited accounts) for apps like this. It uses only the documented Web API calls `GetOwnedGames` and `GetPlayerSummaries`, for the account already signed in to Steam on this computer. Superlion never asks for your password and never signs in as another device.

To connect, choose **Connect Steam Account…** in the main menu, or the Steam Account step of the setup wizard:

1. Press **Get My Key Automatically**. Steam's own key page opens inside Superlion.
2. If asked, sign in on Steam's own sign-in page (password and Steam Guard, or Steam's QR code).
3. Tick the box to agree to Valve's Steam Web API terms and press **Register**. The domain name is filled in for you. Approve on your phone if Steam asks.
4. Superlion picks up the key, checks it with Valve and saves it in GNOME Keyring.

If you already have a key, paste it instead. **Disconnect** in Preferences removes it.

If your profile's game details are private, Superlion reads your owned games from the list the Steam store keeps for your sign-in on Steam's website in Superlion, so nothing needs to be made public.

The store, the key page and buying share one browser sign-in, made on Steam's own pages. **Sign Out of Website** in Preferences ends it.

### SteamGridDB

SteamGridDB needs a free API key from your SteamGridDB account. The key is checked with SteamGridDB before it is saved, and kept in GNOME Keyring.

## Privacy

Superlion runs entirely on your computer. Your Steam Web API key and SteamGridDB key are kept in GNOME Keyring, and the data Superlion fetches about your account (owned games, profile country) is stored only in `~/.cache/superlion/` on this computer. Superlion fetches your Steam data only when you use it, sends it nowhere else, and makes requests only to Valve's and SteamGridDB's own services. Disconnecting your Steam account removes the key and the stored owned-games list.

## Undocumented interfaces

Some things Superlion relies on are not documented by Valve and may change: the owned-games list read from the store when game details are private, the public store data, and the layout of Steam's collection, shortcut and app data files. Listing owned games with your Web API key is documented. Each is isolated, so if one stops working the rest of the app, and in particular the library of installed games, keeps working.

## Files

| Location | Contents |
|---|---|
| `~/.config/superlion/config.json` | Choices from setup and Preferences |
| `~/.config/superlion/collections.json` | Your own collections, and edits waiting to be synced to Steam |
| `~/.config/superlion/steam_matches.json` | Store matches you chose for non-Steam games |
| `~/.config/superlion/mod_managers.json` | Mod managers and the games linked to them |
| `~/.config/superlion/launch_presets.json` | Launch option presets |
| `~/.config/superlion/launch_settings.json` | Settings you added to the launch options builder |
| `~/.local/share/superlion/` | Changes waiting for Steam to close, and the store's cookies |
| `~/.cache/superlion/` | Owned-games list, Steam's app data, store data, downloaded artwork, automatic store matches and your account's country |
