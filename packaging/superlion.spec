Name:           superlion
Version:        0.9.7
Release:        1%{?dist}
Summary:        Native GNOME front end for your Steam library
License:        GPL-3.0-or-later
Vendor:         SolarFlare Developments
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch

BuildRequires:  desktop-file-utils

Requires:       python3
Requires:       python3-gobject-base
Requires:       python3-requests
Requires:       gtk4
Requires:       libadwaita
Requires:       webkitgtk6.0
Requires:       libsecret
Requires:       gdk-pixbuf2
Requires:       gstreamer1
Requires:       gstreamer1-plugins-base
Requires:       gstreamer1-plugins-good
Requires:       gstreamer1-plugin-gtk4
# Store trailers are H.264; either decoder plays them. Everything else works without one.
Recommends:     (gstreamer1-plugin-libav or gstreamer1-plugin-openh264)

%description
Superlion is a native GNOME (GTK 4 and libadwaita) front end for your Steam
library: installed and owned games, non-Steam games, Steam collections and your
own, mod managers, downloads, artwork from SteamGridDB and a built-in store.

Dedicated to the memory of John Wharton of S J Wharton Ltd (1953-2026).

%prep
%autosetup

%build

%install
install -d %{buildroot}%{_datadir}/%{name}
cp -a superlion %{buildroot}%{_datadir}/%{name}/
install -Dm644 data/dedication/john-wharton.png %{buildroot}%{_datadir}/%{name}/data/dedication/john-wharton.png
install -Dm755 packaging/superlion %{buildroot}%{_bindir}/superlion
desktop-file-install --dir=%{buildroot}%{_datadir}/applications packaging/uk.co.solarflareit.Superlion.desktop
install -Dm644 packaging/uk.co.solarflareit.Superlion.metainfo.xml %{buildroot}%{_metainfodir}/uk.co.solarflareit.Superlion.metainfo.xml
install -Dm644 packaging/superlion-copr.repo %{buildroot}%{_datadir}/dnf5/repos.override.d/50-superlion.repo
install -Dm644 data/icons/hicolor/symbolic/apps/uk.co.solarflareit.Superlion-symbolic.svg %{buildroot}%{_datadir}/icons/hicolor/symbolic/apps/uk.co.solarflareit.Superlion-symbolic.svg
# PNG only: some systems cannot draw SVG application icons, and a scalable SVG
# would be chosen for any size without a PNG, leaving the icon blank there.
for size in 16 24 32 48 64 96 128 192 256 512; do
    install -Dm644 packaging/icons/${size}.png %{buildroot}%{_datadir}/icons/hicolor/${size}x${size}/apps/uk.co.solarflareit.Superlion.png
done

%check
desktop-file-validate %{buildroot}%{_datadir}/applications/uk.co.solarflareit.Superlion.desktop

%files
%license LICENSE
%doc README.md
%{_bindir}/superlion
%{_datadir}/%{name}/
%{_datadir}/applications/uk.co.solarflareit.Superlion.desktop
%{_metainfodir}/uk.co.solarflareit.Superlion.metainfo.xml
%{_datadir}/icons/hicolor/*/apps/uk.co.solarflareit.Superlion*
%{_datadir}/dnf5/repos.override.d/50-superlion.repo

%changelog
* Mon Oct 19 2026 Tom <tom@solarflareit.co.uk> - 0.9.7-1
- Add programs to Steam from Files with a new Add to Steam script, turned on in Preferences. Each program gets a name and compatibility tool, and Flatpak Steam can be given access to its folder.

* Mon Oct 19 2026 Tom <tom@solarflareit.co.uk> - 0.9.6-1
- Add games to the cart from their store pages, choosing an edition or bundle, and see, count and change the cart in the Store sidebar. Check Out opens Steam's own checkout for payment.

* Mon Oct 19 2026 Tom <tom@solarflareit.co.uk> - 0.9.5-1
- Check the Superlion repository for updates every 4 hours instead of every 2 days.

* Mon Oct 19 2026 Tom <tom@solarflareit.co.uk> - 0.9.4-1
- Give the store sidebar and each genre their own icons. Keep store capsules in shape in grids. Fix adding to and removing from the wishlist once the store sign-in is more than a day old.

* Mon Oct 19 2026 Tom <tom@solarflareit.co.uk> - 0.9.3-1
- Widen Preferences so every page title fits.

* Mon Oct 19 2026 Tom <tom@solarflareit.co.uk> - 0.9.2-1
- Simplify setup: lead with the Steam installation found and its package type, rename Steam's folder to the Steam Data Folder, explain what to do before anyone has signed in to Steam, and show Sunshine's status like the other pages. Move streaming settings to a Streaming page in Preferences. Start Steam only when needed for new installs, and say in Downloads when updates are paused because Steam is closed.
- Group launch options more finely, warn about settings that conflict, rename misspelt and old names such as PROTON_ENABLE_HDR, and name games outside the library. Global Settings lists every setting by category with search and warnings. Edit DLL overrides and other lists one item per row, and choose audio outputs and other known values from drop-downs.
- Share one game menu between the library and game pages, with a Manage submenu. Offer Update and Play when an update is waiting, and Check for Updates in Downloads.
- Add a Store sidebar with lists, genres, the wishlist and the cart, a wishlist view, and adding to and removing from the wishlist without opening the web page.

* Mon Oct 19 2026 Tom <tom@solarflareit.co.uk> - 0.9.1-1
- Add While Streaming settings: stream on the main monitor or a dummy plug, which is turned off between streams; make a dummy plug act as a 4K, 1440p or 1080p HDR display with generated display information, kept after restarting; fix the resolution or match Moonlight; play sound straight to Sunshine or through EasyEffects; hide the dock and notifications while streaming. Prefer modes that reach the client's frame rate.

* Mon Oct 19 2026 Tom <tom@solarflareit.co.uk> - 0.9.0-1
- Add games to Sunshine from their ⋮ menu to stream them to Moonlight. Each stream switches the main monitor to the client's resolution, refresh rate and HDR or SDR, plays games straight into Sunshine's surround sound with EasyEffects quit, and puts everything back when the game is quit. Setup and Preferences show whether Sunshine is installed, running and able to stream HDR. Remove the Steam Remote Play streaming option.

* Mon Oct 19 2026 Tom <tom@solarflareit.co.uk> - 0.8.5-1
- List every game's launch option warnings in Preferences, fix or ignore each one, and turn a setting on or off for all installed games. Ignored warnings are left off a game's page but still shown in its launch options. Shorten the Steam Client setting descriptions.

* Mon Oct 19 2026 Tom <tom@solarflareit.co.uk> - 0.8.4-1
- Warn about launch options that are not needed on this computer or that cause problems, such as LD_PRELOAD="" stopping the Steam overlay and Steam Link's picture on Wayland, in the launch options editor and on a game's page.

* Sun Oct 18 2026 Tom <tom@solarflareit.co.uk> - 0.8.3-1
- Start Steam with PipeWire screen capture for Remote Play streaming, asked about in setup and changeable in Preferences.

* Sun Oct 18 2026 Tom <tom@solarflareit.co.uk> - 0.8.2-1
- Offer over 100 common launch settings, including FSR, grouped with NVIDIA-only and AMD-only settings kept apart, and add search to the launch options editor.

* Sun Oct 18 2026 Tom <tom@solarflareit.co.uk> - 0.8.1-1
- Start Steam hidden when Superlion opens, and whenever Superlion starts or restarts Steam, so its window only appears when one of its own pages is opened.

* Sun Oct 18 2026 Tom <tom@solarflareit.co.uk> - 0.8-1
- Install games from Superlion: choose the library folder, see the download size and free space, and Steam starts downloading without its own install dialog.

* Sun Oct 18 2026 Tom <tom@solarflareit.co.uk> - 0.7.6-1
- Show screenshots and links to the project in GNOME Software.

* Sun Oct 18 2026 Tom <tom@solarflareit.co.uk> - 0.7.5-1
- Add a development mode that runs separately from the installed app, with its own settings and keys.

* Sun Oct 18 2026 Tom <tom@solarflareit.co.uk> - 0.7.4-2
- Include the licence text in the package.

* Sun Oct 18 2026 Tom <tom@solarflareit.co.uk> - 0.7.4-1
- Use a floppy disk icon for Save as Preset, and a tick for games already saved as a preset.

* Sun Oct 18 2026 Tom <tom@solarflareit.co.uk> - 0.7.3-1
- Use bookmark icons for saving launch options as a preset, instead of an icon that looked like a download.

* Sun Oct 18 2026 Tom <tom@solarflareit.co.uk> - 0.7.2-1
- Name and describe the NVIDIA CUDA, DLSS 5 Vulkan Layer and Keep Mouse in Window launch settings.

* Sun Oct 18 2026 Tom <tom@solarflareit.co.uk> - 0.7.1-1
- Show launch options by setting name instead of truncated text, and open them in the editor from Preferences.
- Split the Steam Account preferences into Steam API and Steam Store.

* Sun Oct 18 2026 Tom <tom@solarflareit.co.uk> - 0.7-1
- Bring launch options together: one editor for typing and switching settings, with presets, and a Launch Options tab in Preferences.

* Sun Oct 18 2026 Tom <tom@solarflareit.co.uk> - 0.6-1
- Let settings be added to the launch options builder: suggestions Superlion knows, or the user's own variables, programs and game arguments.

* Sun Oct 18 2026 Tom <tom@solarflareit.co.uk> - 0.5-1
- Add a launch options builder, with settings gathered from the launch options of all your games.

* Sat Oct 17 2026 Tom <tom@solarflareit.co.uk> - 0.4-1
- Add launch option presets, with a preset manager and presets made from games' existing launch options.

* Sat Oct 17 2026 Tom <tom@solarflareit.co.uk> - 0.3-1
- Number the current release 0.3; version 1.0 is reserved for the finished product.

* Sat Oct 17 2026 Tom <tom@solarflareit.co.uk> - 0.1.0-3
- Connect to Steam with the user's own Steam Web API key instead of QR sign-in.
- Remove the stored sign-in token and store cookie left by earlier versions.

* Fri Oct 16 2026 Tom <tom@solarflareit.co.uk> - 0.1.0-2
- Ship the application icon as PNGs only, so it shows where SVG icons cannot be drawn.

* Fri Oct 16 2026 Tom <tom@solarflareit.co.uk> - 0.1.0-1
- First package.
