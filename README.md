# Superlion

A native GNOME (GTK 4 and libadwaita) front end for your Steam library, named after the Fowler B6 Super Lion steam road locomotive. Its icon shows the flywheel of Supreme of S J Wharton Ltd in Witney.

Superlion is dedicated to the memory of John Wharton of S J Wharton Ltd (1953–2026).

## Features

### Library
- Installed games from every Steam library folder, plus non-Steam games added to Steam, with Steam's cover art and any custom artwork you have set.
- Once your Steam account is connected, the games you own but have not installed, each with an **Install** button on its cover.
- **Install** asks which library folder to use, showing the download size and each drive's free space, then has Steam download the game there, restarting Steam if it is running. **Use Steam's Dialog** opens Steam's own install dialog instead.
- A sidebar with views (All Games, Installed, Not Installed, VR Games, Non-Steam Games, Mod Managers), Steam's own collections, and your own collections.
- Search that ignores case, punctuation and ™, and matches initials (“re3” finds *Resident Evil 3*) and app IDs.
- Sort by name, size, last played or release date, and group by genre, release year or installed state.
- A right-click menu on every game, the same as the **⋮** menu on its page: play or install, details, favourite and collections, a **Manage** submenu (launch options, Sunshine, cover, game and compatibility files, store page), and hide.

### Game pages
- **Overview**: trailers, screenshots, description and developer updates from the Steam store.
- **Information**: install size, location, compatibility files (the Proton prefix), release date, genres, VR support, collections, a linked mod manager, and artwork.
- **Steam Settings**: launch options and compatibility tool (Proton version).
- **Play**, **Launch Mod Manager** when a mod manager is linked, and the game's **⋮** menu. **Choose Cover…** offers SteamGridDB artwork or a file.

### Non-Steam games
- Rename them; suggestions from the Steam store fill in a game's exact name.
- Match them to the same game on the Steam store, automatically by exact name or by choosing it yourself. A matched game gets that game's store page, news, release date, genres and artwork. Steam's artwork fills any missing images, and you are asked before custom images are replaced.

### Collections
- Steam's collections, Favorites and Hidden are shown, and can be renamed, deleted and added to. Hiding a game adds it to Steam's Hidden collection.
- Your own collections can be copied into Steam with **Sync Collections to Steam**.

### Mod managers
- Add Linux applications as mod managers, or mark a non-Steam game as one with its **Mod Manager** switch. Non-Steam mod managers are listed under Mod Managers instead of with your games.
- Link a game to a mod manager to get a **Launch Mod Manager** button on its page and in its right-click menu.

### Launch options
- Choose **Launch Options** on a game's Steam Settings to open the editor. Type the launch options directly, or switch settings on and off below them; each updates the other.
- The editor offers over 100 common settings, mostly as documented by Proton-CachyOS, plus any found in your games' launch options. They are grouped as Tools, Display and HDR, Upscaling and Frame Generation (including FSR 1, for any graphics card), Performance and Latency, NVIDIA, AMD (including FSR 4), DirectX and OpenGL, Mods and DLLs, Compatibility Fixes, Videos and Cutscenes, Online and Anti-Cheat, Input, Audio, VR, Logging and game arguments, and can be searched. Each says what it does and how many of your games use it, and settings with a value offer the values your games already use. Lists such as DLL Overrides have a row per item, with a load order for each DLL, and settings with known values, such as Audio Output (this PC's outputs) and Audio Channels, have a drop-down with **Other…**.
- **Warnings** lists settings that are not needed on this computer, such as NVIDIA settings without an NVIDIA card or a variable set twice, settings that cause problems, such as `LD_PRELOAD=""`, which stops the Steam overlay, and settings that conflict, such as Gamescope with Wayland or two frame rate limits. Each warning can be fixed, which removes the setting (or keeps the last value, or replaces a misspelt or old name such as `PROTON_ENABLE_HDR`), or ignored. A game's page shows how many warnings it has, not counting ignored ones, under its **Play** button.
- **Use a Preset** fills in a saved preset, and **Save as Preset…** saves the current launch options as one.
- **Add Custom Setting** (the + button) adds your own variable, program or game argument, offered for every game.
- **Preferences → Launch Options** manages presets and custom settings, and lists every game's launch options by setting name; choose one to change it in the editor or save it as a preset. Games that are not installed, named from Steam's app database or the store, are listed after the rest. It also lists every game's warnings, to fix or ignore. **Global Settings** lists every setting by category, with how many games use it and any warnings, and turns a setting on or off, or applies its warning's fix, for all your installed games at once.

### Artwork
- Choose a cover, background, logo or wide cover from a file, or from [SteamGridDB](https://www.steamgriddb.com) inside the app. Steam uses the same artwork after it restarts.

### Downloads
- Steam's downloads and updates, read from its own files: downloading (with progress and the current download rate), paused, and updates waiting with their scheduled time. The tab shows a count of them.
- Games that are downloading show their state on their cover and game page: **Play** becomes “Updating 42%” or “Update Paused” and is greyed out until Steam finishes, with a progress bar, amount downloaded and current speed.
- A game with an update waiting, or a newer build in Steam's app database than the one installed, shows “Update Available” on its cover, and **Play** becomes **Update and Play**: Steam downloads the update, then starts the game.
- **Check for Updates** starts Steam hidden if it is closed, as Steam checks for updates when it starts and while it runs.

### Store
- Native store browsing, search and game pages, with prices in your Steam profile's country (or the United Kingdom's when it shows none).
- A sidebar with Featured, Specials, New and Trending, Top Sellers, Coming Soon and Free to Play, your wishlist and cart with their counts, and genres, those most common in your library first.
- **Wishlist** lists your wishlist with prices, sales marked, sorted by your order, price, discount or release date. A private wishlist needs the store sign-in.
- **Add to Wishlist** and removing from the wishlist use the store sign-in kept inside Superlion, without opening the store's web page. **Add to Cart** offers each edition and bundle with its price, and the **Cart** in the sidebar lists what is in it, with discounts, gifts and the total, and removes items. **Check Out** opens Steam's own checkout inside the app for payment.

### Steam in the background
- Playing, installing and streaming a game start Steam hidden, so they work without Steam's window appearing. Steam's window only opens for its own pages, such as **Open Downloads in Steam**.
- **Preferences → Steam → Start Steam With Superlion** keeps Steam running in the background from when Superlion opens, so games stay updated and start faster. While Steam is closed, the Downloads tab says that updates are paused and offers to start it.

### Streaming with Sunshine
- **Add to Sunshine** in a game's **⋮** menu lists it in [Sunshine](https://github.com/LizardByte/Sunshine), so Moonlight can start it. Setup and **Preferences → Streaming** show whether Sunshine is installed, running and able to stream HDR, which needs Sunshine from [LizardByte's COPR](https://copr.fedorainfracloud.org/coprs/lizardbyte/stable/) rather than the Flatpak or AppImage.
- **Stream Display** shows games on the main monitor, which switches to each stream's resolution, refresh rate and HDR or SDR while other monitors are turned off, or on a dummy plug, which leaves your monitors as they are and keeps your windows off the stream.
- A dummy plug's resolutions, refresh rates and HDR support are shown, and **Act As** can make it a 4K HDR display at 60 Hz, or 1440p or 1080p HDR at 120 Hz. This installs display information (EDID) for it in `/usr/lib/firmware/edid/` and adds the `drm.edid_firmware` boot option, and asks for your password. It works with AMD, Intel and NVIDIA graphics.
- **Resolution** matches each Moonlight client, or is fixed. **Sound** plays games in surround straight into Sunshine's 5.1 or 7.1 output with EasyEffects quit, or in stereo through EasyEffects. The dock and pop-up notifications are hidden during streams unless you turn this off.
- Quitting from Moonlight closes the game and puts the displays, EasyEffects, the dock and notifications back. Turn on HDR and surround sound in Moonlight on each client.

## Installing

On Fedora, install from [COPR](https://copr.fedorainfracloud.org/coprs/solartw/superlion/). Updates then arrive with your other system updates.

```bash
sudo dnf copr enable solartw/superlion
```

```bash
sudo dnf install superlion
```

Store trailers need an H.264 decoder (`gstreamer1-plugin-libav` or `gstreamer1-plugin-openh264`).

To build the RPM yourself, run `packaging/build-rpm.sh`; it is written to `dist/`.

## Setup and Preferences

The first launch opens a setup wizard. It finds your Steam installation and the kind of package it came from (such as RPM, Debian, Arch, Flatpak or Snap), your account and your library folders; **Change…** chooses Steam's data folder and command by hand. If nobody has signed in to Steam on this computer yet, setup can open Steam and carry on without an account. It then offers Moonlight streaming settings and two optional steps:

- **Steam account**, using your own Steam Web API key.
- **SteamGridDB**, using a free API key.

**Preferences** in the main menu changes the same settings and can run the wizard again.

## How changes reach Steam

Steam keeps several of its files in memory and overwrites them when it exits, so Superlion writes to these only while Steam is closed:

| Change | Steam file |
|---|---|
| Launch options | `userdata/<account>/config/localconfig.vdf` (non-Steam games: `shortcuts.vdf`) |
| Compatibility tool | `config/config.vdf` |
| Non-Steam game names | `userdata/<account>/config/shortcuts.vdf` |
| Collections, Favorites and Hidden | `userdata/<account>/config/cloudstorage/cloud-storage-namespace-1.json` |

Games added to Sunshine go into Sunshine's own `~/.config/sunshine/apps.json`, and Superlion restarts Sunshine so it reads them, unless a game is streaming.

If Steam is running, changes wait until it exits, and a banner offers to relaunch Steam to apply them straight away.

Each file is backed up to `<file>.superlion-bak-<date>-<time>` before it is written.

Custom artwork goes straight into `userdata/<account>/config/grid`, as Steam doesn't hold that folder in memory.

## Accounts

### Steam account

Superlion lists the games you own using your own Steam Web API key (`GetOwnedGames` and `GetPlayerSummaries`). To connect, choose **Connect Steam Account…** in the main menu:

1. Press **Get My Key Automatically**. Steam's key page opens inside Superlion.
2. Sign in to Steam if asked.
3. Agree to the Steam Web API terms and press **Register**. The domain name is filled in for you.
4. Superlion picks up the key and saves it in GNOME Keyring.

If you already have a key, you can paste it instead. If your profile's game details are private, the owned games list is read from the Steam store instead.

### SteamGridDB

SteamGridDB needs a free API key from your SteamGridDB account. It is also kept in GNOME Keyring.

## Privacy

Superlion only talks to Valve and SteamGridDB. API keys are kept in GNOME Keyring, and account data is cached in `~/.cache/superlion/`.

## Files

| Location | Contents |
|---|---|
| `~/.config/superlion/config.json` | Choices from setup and Preferences |
| `~/.config/superlion/collections.json` | Your own collections, and edits waiting to be synced to Steam |
| `~/.config/superlion/steam_matches.json` | Store matches you chose for non-Steam games |
| `~/.config/superlion/mod_managers.json` | Mod managers and the games linked to them |
| `~/.config/superlion/launch_presets.json` | Launch option presets |
| `~/.config/superlion/launch_settings.json` | Your custom settings for the launch options editor |
| `~/.local/share/superlion/` | Changes waiting for Steam to close, the store's cookies, and covers for Sunshine |
| `~/.cache/superlion/` | Owned-games list, Steam's app data, store data, downloaded artwork, automatic store matches and your account's country |
