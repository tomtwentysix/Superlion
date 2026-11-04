<img src="data/icons/hicolor/scalable/apps/uk.co.solarflareit.Superlion.svg" width="128" alt="" align="right">

# Superlion

Superlion is a native GNOME app for your Steam library, built with GTK 4 and libadwaita. It shows the games you have installed and the ones you own, lets you browse the store, manage launch options, Proton builds and artwork, and stream games through Sunshine, all without opening Steam's own window. It suits anyone who would rather their games looked and behaved like the rest of their GNOME desktop.

It is named after the Fowler B6 Super Lion steam road locomotive, and its icon shows the flywheel of Supreme of S J Wharton Ltd in Witney. Superlion is dedicated to the memory of John Wharton of S J Wharton Ltd (1953–2026).

## What it does

The library brings together installed games from every Steam library folder and non-Steam games you have added to Steam. Once your Steam account is connected, it also shows the games you own but have not installed, which you can install into the library folder of your choice. You can filter by Steam's collections and your own, search by name, initials or app ID, and sort or group by name, size, last played, release date or genre. Each game has a page with its trailers, screenshots, description and developer updates from the store, along with its install details, launch options and compatibility tool. While a game is running, its Play button becomes Stop.

Non-Steam games can be added straight from Files, renamed with suggestions from the store, and matched to a store game so that they get its store page, news and artwork. Artwork for any game can be chosen from a file or from [SteamGridDB](https://www.steamgriddb.com) inside the app. Linux applications can be added as mod managers and linked to games, which then gain a **Launch Mod Manager** button.

The launch options editor lets you type options directly or switch over 100 common settings on and off, and it warns about settings that are unnecessary, cause problems or conflict with one another. Presets and custom settings are kept in Preferences, where settings can also be applied to every installed game at once.

The Downloads section follows Steam's active, paused and waiting downloads, and games show their progress and any available update on their covers. The store can be browsed natively, with prices in your Steam profile's country, and your wishlist and cart can be managed without opening a web page; checkout uses Steam's own pages inside the app.

Preferences can also install and update [GE-Proton](https://github.com/GloriousEggroll/proton-ge-custom) and [Proton-CachyOS](https://github.com/CachyOS/proton-cachyos), checking each download against its published checksum before unpacking it.

Playing, installing and streaming start Steam hidden when it is needed, and Steam can optionally be kept running in the background from when Superlion opens.

## Streaming with Sunshine

**Add to Sunshine** in a game's menu lists it in [Sunshine](https://github.com/LizardByte/Sunshine) so that Moonlight can start it. HDR streaming needs Sunshine from [LizardByte's COPR](https://copr.fedorainfracloud.org/coprs/lizardbyte/stable/) rather than the Flatpak or AppImage.

During a stream, Superlion switches the chosen display to the client's resolution, refresh rate and dynamic range, and puts everything back when the stream ends. Streams can use the main monitor, with the others turned off, or a dummy plug, which leaves your own monitors untouched. A dummy plug can be made to act as a 4K, 1440p or 1080p HDR display; this installs an EDID file in `/usr/lib/firmware/edid/` and adds the `drm.edid_firmware` boot option, so it asks for your password. Superlion can also quit EasyEffects for surround sound and hide the dock and notifications while streaming.

## Installing

On Fedora, install from [COPR](https://copr.fedorainfracloud.org/coprs/solartw/superlion/):

```bash
sudo dnf copr enable solartw/superlion
sudo dnf install superlion
```

Store trailers need an H.264 decoder, such as `gstreamer1-plugin-libav` or `gstreamer1-plugin-openh264`.

To build the RPM yourself, run `packaging/build-rpm.sh`, which writes it to `dist/`.

## Setup

The first launch opens a setup wizard that finds your Steam installation, account and library folders. It also offers to connect your Steam account using your own Steam Web API key, which Valve provides free to every account, and SteamGridDB using a free API key. Both keys are kept in GNOME Keyring. If your profile's game details are private, the list of owned games is read through the Steam store sign-in instead. Everything the wizard sets can be changed later in Preferences.

## How changes reach Steam

Steam keeps several of its files in memory and overwrites them when it exits, so Superlion only writes to them while Steam is closed. If Steam is running, changes wait until it exits, and a banner offers to relaunch Steam to apply them straight away. Each file is backed up to `<file>.superlion-bak-<date>-<time>` before it is written.

| Change | Steam file |
|---|---|
| Launch options | `userdata/<account>/config/localconfig.vdf` (non-Steam games: `shortcuts.vdf`) |
| Compatibility tool | `config/config.vdf` |
| Non-Steam game names | `userdata/<account>/config/shortcuts.vdf` |
| Collections, Favorites and Hidden | `userdata/<account>/config/cloudstorage/cloud-storage-namespace-1.json` |

Custom artwork goes straight into `userdata/<account>/config/grid`, which Steam does not hold in memory. Games added to Sunshine go into `~/.config/sunshine/apps.json`, and Sunshine is restarted to read them unless a game is streaming.

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
