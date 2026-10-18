"""Main window: navigation, banners and the library grid."""

from gi.repository import Adw, Gio, GLib, GObject, Gtk

from .. import appinfo, auth, game_collections, library, mod_managers, owned, pending, steam_control, steam_match
from .. import config as config_mod
from . import images
from .details import GameDetailsPage
from .downloads_view import DownloadsView
from .library_view import GROUP_TITLES, LibraryView
from .store import StoreAppPage, StoreView
from .steam_key_setup import SteamKeyDialog
from .webview import SteamWebPage, clear_sign_in
from .wizard import SetupWizard

CSS = """
.cover-frame { border-radius: 10px; }
.cover-placeholder { background-color: alpha(currentColor, 0.08); }
.game-tile { padding: 6px; }
.store-capsule { padding: 6px; }
.download-badge { padding: 8px 10px; border-radius: 10px; }
/* Adwaita gives progress bars a 150 px minimum, wider than the space on a cover. */
.download-badge progressbar trough, .download-badge progressbar progress { min-width: 0; }
/* Header buttons over a game's banner: light by default, dark over bright artwork. */
headerbar.hero-header button { color: white; }
headerbar.hero-header.start-light button.hero-back,
headerbar.hero-header.start-light windowcontrols.start button,
headerbar.hero-header.end-light windowcontrols.end button { color: rgba(0, 0, 0, 0.8); }
/* Menu items built from buttons use the normal weight of standard menu items. */
.icon-menu button label { font-weight: normal; }
"""


class SuperlionWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(default_width=1100, default_height=760, title="Superlion", **kwargs)
        if config_mod.DEVEL and not config_mod.SCREENSHOTS:
            self.add_css_class("devel")
        self.config = None
        self.api_key = ""  # The user's Steam Web API key, when connected.
        self.account_country = ""
        self.installed = []

        provider = Gtk.CssProvider()
        provider.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(
            self.get_display(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        self._build_actions()

        self.toasts = Adw.ToastOverlay()
        self.nav = Adw.NavigationView()
        self.toasts.set_child(self.nav)
        self.set_content(self.toasts)

        # Banners follow the visible page so they show under its header bar.
        self.setup_banner = Adw.Banner(
            title="Some saved Steam folders are missing.", button_label="Open Preferences"
        )
        self.setup_banner.connect(
            "button-clicked", lambda *_: self.get_application().activate_action("preferences", None)
        )
        self.pending_banner = Adw.Banner(button_label="Relaunch Steam")
        self.pending_banner.connect("button-clicked", lambda *_: self.relaunch_steam())
        self.banners = [self.setup_banner, self.pending_banner]
        self._pending_watch = 0
        self._relaunching = False
        self.nav.connect("notify::visible-page", self._attach_banners)
        self.nav.connect("popped", lambda _nav, page: getattr(page, "release", lambda: None)())

        self.nav.add(self._build_main_page())
        self._attach_banners()

    def _build_actions(self):
        for name, default, handler in (
            ("sort", "name", self._on_sort_changed),
            ("group", "none", self._on_group_changed),
        ):
            action = Gio.SimpleAction.new_stateful(
                name, GLib.VariantType.new("s"), GLib.Variant("s", default)
            )
            action.connect("change-state", handler)
            self.add_action(action)

        for name, callback in [
            ("refresh", lambda *_: self.reload()),
            ("sign-in", lambda *_: self.sign_in()),
            ("sign-out", lambda *_: self.sign_out()),
            ("client-store", lambda *_: self.open_client_store()),
        ]:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)

        for name, callback in [
            ("rename-collection", self.rename_collection),
            ("delete-collection", self.delete_collection),
        ]:
            action = Gio.SimpleAction.new(name, GLib.VariantType.new("s"))
            action.connect("activate", lambda _a, value, cb=callback: cb(value.get_string()))
            self.add_action(action)

    def _on_sort_changed(self, action, value):
        action.set_state(value)
        self.library.sort_mode = value.get_string()
        self.library.changed()

    def _on_group_changed(self, action, value):
        action.set_state(value)
        self.library.group_mode = value.get_string()
        self.library.changed()

    def on_library_view_changed(self):
        """Grouping by installed state only makes sense when both kinds are shown."""
        view = self.library.view
        self.lookup_action("group").set_state(GLib.Variant("s", self.library.group_mode))
        self._group_installed_item_allowed = view not in ("installed", "not_installed")
        self._rebuild_view_menu()

    def _build_main_page(self):
        header = Adw.HeaderBar()
        self.view_stack = Adw.ViewStack()
        switcher = Adw.ViewSwitcher(stack=self.view_stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(switcher)
        switcher_bar = Adw.ViewSwitcherBar(stack=self.view_stack)

        # Below 550 px the switcher moves from the header bar to the bottom.
        breakpoint = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 550sp"))
        breakpoint.add_setter(switcher, "visible", False)
        breakpoint.add_setter(switcher_bar, "reveal", True)
        self.add_breakpoint(breakpoint)

        self.search_button = Gtk.ToggleButton(
            icon_name="system-search-symbolic", tooltip_text="Search"
        )
        header.pack_start(self.search_button)
        self.cart_button = Gtk.Button(icon_name="superlion-cart-symbolic", tooltip_text="Cart", visible=False)
        self.cart_button.connect(
            "clicked", lambda *_: self.open_web("https://store.steampowered.com/cart", "Cart")
        )
        header.pack_start(self.cart_button)

        main_menu = Gio.Menu()
        section = Gio.Menu()
        section.append("Refresh", "win.refresh")
        section.append("Preferences", "app.preferences")
        main_menu.append_section(None, section)
        section = Gio.Menu()
        for label, action in [("Connect Steam Account…", "win.sign-in"), ("Disconnect Steam Account", "win.sign-out")]:
            item = Gio.MenuItem.new(label, action)
            item.set_attribute_value("hidden-when", GLib.Variant("s", "action-disabled"))
            section.append_item(item)
        main_menu.append_section(None, section)
        section = Gio.Menu()
        section.append("Open Store in Steam Client", "win.client-store")
        section.append("In Memory of John Wharton", "app.dedication")
        section.append("About Superlion", "app.about")
        main_menu.append_section(None, section)
        header.pack_end(
            Gtk.MenuButton(
                icon_name="open-menu-symbolic", menu_model=main_menu, tooltip_text="Main Menu"
            )
        )

        self.sort_button = Gtk.MenuButton(
            icon_name="view-sort-descending-symbolic", tooltip_text="Sort and Group"
        )
        header.pack_end(self.sort_button)
        self._group_installed_item_allowed = False

        self.library = LibraryView(self)
        self.search_bar = self.library.search_bar
        self.search_bar.set_key_capture_widget(self)
        self.search_bar.bind_property(
            "search-mode-enabled",
            self.search_button,
            "active",
            GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE,
        )
        self.sidebar_button = Gtk.ToggleButton(
            icon_name="sidebar-show-symbolic", tooltip_text="Show Sidebar"
        )
        self.split = Adw.OverlaySplitView(sidebar=self.library.sidebar)
        # Whether the user wants the sidebar open in the Library on a wide window.
        # Kept separately because the Store and narrow windows hide it temporarily.
        self._sidebar_wanted = True
        self._sidebar_changing = False
        self.split.connect("notify::show-sidebar", self._on_sidebar_toggled)
        self.library.split = self.split
        self.split.bind_property(
            "show-sidebar",
            self.sidebar_button,
            "active",
            GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE,
        )
        # The sidebar button goes first, so the search and cart buttons are re-packed after it.
        header.remove(self.search_button)
        header.remove(self.cart_button)
        for button in (self.sidebar_button, self.search_button, self.cart_button):
            header.pack_start(button)
        sidebar_breakpoint = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 760sp"))
        sidebar_breakpoint.add_setter(self.split, "collapsed", True)
        # Narrow windows start with the sidebar folded away; wide ones always show it.
        sidebar_breakpoint.connect("apply", lambda *_: self._show_sidebar(False))
        sidebar_breakpoint.connect("unapply", lambda *_: self._restore_sidebar())
        self.add_breakpoint(sidebar_breakpoint)
        self._rebuild_view_menu()

        self.view_stack.add_titled_with_icon(
            self.library, "library", "Library", "applications-games-symbolic"
        )

        self.store_view = StoreView(self)
        self.view_stack.add_titled_with_icon(
            self.store_view, "store", "Store", "superlion-store-symbolic"
        )
        self.downloads_view = DownloadsView(self)
        self.downloads_view.page = self.view_stack.add_titled_with_icon(
            self.downloads_view, "downloads", "Downloads", "folder-download-symbolic"
        )
        self.downloads_view.set_visible_section(False)  # Keeps the badge up to date.
        self.view_stack.connect("notify::visible-child-name", self._on_section_changed)

        toolbar = Adw.ToolbarView(content=self.view_stack)
        toolbar.add_top_bar(header)
        toolbar.add_bottom_bar(switcher_bar)
        self.split.set_content(toolbar)
        return Adw.NavigationPage(child=self.split, title="Superlion", tag="main")

    def _restore_sidebar(self):
        """Return the sidebar to the user's choice on wide windows, unless the Store is open."""
        self._show_sidebar(self._sidebar_wanted and self.view_stack.get_visible_child_name() == "library")

    def _show_sidebar(self, show):
        """Show or hide the sidebar without recording it as the user's choice."""
        self._sidebar_changing = True
        self.split.set_show_sidebar(show)
        self._sidebar_changing = False

    def _on_sidebar_toggled(self, split, _pspec):
        # Only the user's own toggles in the Library on a wide window count as a choice.
        in_library = self.view_stack.get_visible_child_name() == "library"
        if not self._sidebar_changing and in_library and not split.get_collapsed():
            self._sidebar_wanted = split.get_show_sidebar()

    def _on_section_changed(self, *_):
        section = self.view_stack.get_visible_child_name()
        in_library, in_store = section == "library", section == "store"
        self.search_button.set_visible(in_library)
        self.sort_button.set_visible(in_library)
        self.sidebar_button.set_visible(in_library)
        if not in_library:
            self._show_sidebar(False)
        elif not self.split.get_collapsed():
            self._show_sidebar(self._sidebar_wanted)
        self.cart_button.set_visible(in_store)
        # Typing searches the Library only; the Store has its own search entry.
        self.search_bar.set_key_capture_widget(self if in_library else None)
        if not in_library:
            self.search_bar.set_search_mode(False)
        if in_store:
            self.store_view.load()
        self.downloads_view.set_visible_section(section == "downloads")

    def _rebuild_view_menu(self):
        menu = Gio.Menu()
        sort = Gio.Menu()
        for label, mode in (("Name", "name"), ("Size", "size"), ("Last Played", "last_played"),
                            ("Release Date", "release_date")):
            sort.append(label, f"win.sort::{mode}")
        menu.append_section("Sort By", sort)
        group = Gio.Menu()
        group.append("None", "win.group::none")
        for mode, label in GROUP_TITLES.items():
            if mode == "installed" and not self._group_installed_item_allowed:
                continue
            group.append(label, f"win.group::{mode}")
        menu.append_section("Group By", group)
        self.sort_button.set_menu_model(menu)

    def open_game(self, game):
        self.nav.push(GameDetailsPage(self, game))

    def set_config(self, config):
        self.config = config
        self._remove_legacy_sign_in()
        self.api_key = auth.load_key() if config else ""
        self._update_sign_in_state()
        self.reload()

    def _remove_legacy_sign_in(self):
        """Delete what the QR sign-in of earlier versions left behind, once."""
        marker = config_mod.data_dir() / "legacy-sign-in-removed"
        if marker.exists():
            return
        auth.remove_legacy_sign_in()
        clear_sign_in()  # Clears the store cookie that sign-in created.
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()

    def reload(self):
        if self.config is None:
            self.library.set_games([])
            return
        self.setup_banner.set_revealed(bool(self.config.problems()))
        self._apply_pending_if_closed()
        self.library.refresh_sidebar()
        self.installed = (
            library.load_installed(self.config) + library.load_shortcuts(self.config)
            if self.config.root.is_dir()
            else []
        )
        if config_mod.SCREENSHOTS and not self.api_key:
            self._show_games(owned.SAMPLE_GAMES)
            return
        self._show_games(owned.load_cached() if self.api_key else [])
        if self.api_key:
            self._refresh_owned()

    def _show_games(self, owned_entries):
        installed_ids = {g.props.appid for g in self.installed}
        games = self.installed + owned.to_games(self.config, owned_entries, installed_ids)
        library.apply_metadata(games, appinfo.load(self.config.root))
        GLib.idle_add(lambda: (self.downloads_view.refresh(), GLib.SOURCE_REMOVE)[-1])  # Covers show download state.
        for game in games:
            # Names waiting for Steam to close are shown as if already written.
            waiting = pending.get(game.props.appid).get("name") if game.props.non_steam else None
            if waiting:
                game.props.name = waiting
        for game in games:
            if not game.props.non_steam:
                game.props.store_appid = game.props.appid
        self._match_shortcuts([g for g in games if g.props.non_steam])
        self.library.set_games(games)

    def _match_shortcuts(self, shortcuts):
        """Link non-Steam games to the same game on the Steam store, where there is one.

        A matched game gets that store entry's metadata, missing artwork, store
        page and news, so it looks like a Steam game in the library. Nothing is
        written to Steam, and custom artwork always takes priority.
        """
        if not shortcuts:
            return
        region = self.store_region
        known = appinfo.load(self.config.root)

        def work():
            matches = steam_match.match_games(shortcuts, region)
            metadata = {}
            for steam_appid in set(matches.values()) - {0}:
                if steam_appid in known:
                    metadata[steam_appid] = known[steam_appid]
                else:
                    try:
                        metadata[steam_appid] = steam_match.store_metadata(steam_appid, region)
                    except Exception:  # Offline or rate-limited; artwork and matching still apply.
                        pass
            return matches, metadata

        def done(result, error):
            if error or not result:
                return
            matches, metadata = result
            for game in shortcuts:
                self.apply_store_match(game, matches.get(game.props.appid, 0), metadata)
            self.library.changed()

        auth.run_async(work, done)

    def open_match_dialog(self, game):
        from .match_dialog import MatchDialog

        dialog = MatchDialog(self, game)
        dialog.connect("chosen", lambda _d, appid: self.set_store_match(game, appid))
        dialog.present(self)

    def set_store_match(self, game, steam_appid):
        steam_match.set_override(game.props.appid, steam_appid)
        # Drop artwork that came from the previous match; custom artwork is kept.
        art = library.find_art(self.config.root, self.config.userdata, game.props.appid)
        for kind in library.ART_LABELS:
            game.set_property(kind, art[kind])
        game.props.release_date, game.props.genres, game.props.vr = 0, [], 0
        region = self.store_region
        known = appinfo.load(self.config.root)

        def done(info, _error):
            self.apply_store_match(game, steam_appid, {steam_appid: info} if info else None)
            self.library.changed()
            if steam_appid:
                self._use_steam_artwork(game, steam_appid)
            page = self.nav.get_visible_page()
            if getattr(page, "game", None) is game:
                self.nav.pop()
                self.open_game(game)

        def fetch():
            if not steam_appid:
                return None
            return known.get(steam_appid) or steam_match.store_metadata(steam_appid, region)

        auth.run_async(fetch, done)
        self.toast("Match removed" if not steam_appid else "Matched to the Steam store")

    def _use_steam_artwork(self, game, steam_appid):
        """Save the matched Steam game's original artwork as this game's artwork.

        Kinds with no custom image are filled straight away. If some already have
        custom images, the user chooses whether Steam's should replace them.
        """

        def download():
            return {kind: owned.download_steam_art(steam_appid, kind) for kind in library.ART_LABELS}

        def done(paths, error):
            if error or not paths:
                return
            available = {kind: path for kind, path in paths.items() if path}
            custom = [k for k in available if library.custom_art(self.config, game.props.appid, k)]
            filled = [k for k in available if k not in custom]
            for kind in filled:
                self.set_artwork(game, kind, available[kind], quiet=True)
            if filled:
                self.toast(f"Steam artwork added to {game.props.name}")
            if custom:
                self._ask_replace_artwork(game, {k: available[k] for k in custom})

        auth.run_async(download, done)

    def _ask_replace_artwork(self, game, replacements):
        labels = [library.ART_LABELS[k].lower() for k in replacements]
        listed = labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + " and " + labels[-1]
        dialog = Adw.AlertDialog(
            heading="Replace Custom Artwork?",
            body=(
                f"“{game.props.name}” already has a custom {listed}. Replace "
                f"{'it' if len(labels) == 1 else 'them'} with the original Steam artwork?"
            ),
        )
        dialog.add_response("keep", "Keep Mine")
        dialog.add_response("replace", "Use Steam's")
        dialog.set_response_appearance("replace", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("replace")
        dialog.set_close_response("keep")

        def on_response(_dialog, response):
            if response == "replace":
                for kind, path in replacements.items():
                    self.set_artwork(game, kind, path, quiet=True)
                self.toast(f"Steam artwork used for {game.props.name}")

        dialog.connect("response", on_response)
        dialog.present(self)

    def apply_store_match(self, game, steam_appid, metadata=None):
        game.props.store_appid = steam_appid
        info = (metadata or {}).get(steam_appid)
        if info:
            game.props.release_date = info.get("release", 0)
            game.props.genres = info.get("genres", [])
            game.props.vr = info.get("vr", 0)
        if steam_appid:
            for kind in library.ART_LABELS:
                owned.ensure_art(game, kind, source_appid=steam_appid)

    def _refresh_owned(self):
        """Update owned games with the Web API key, or the store's list if that is empty."""
        key, steamid = self.api_key, auth.steamid64(self.config)

        def done(entries, error):
            if key != self.api_key:
                return  # Disconnected while loading.
            if isinstance(error, auth.AuthError):
                self.toast("Valve no longer accepts your Steam Web API key. Connect your Steam account again.")
                return
            if error:
                self.toast("Your owned games could not be updated. Showing saved results.")
                return
            if entries:
                self._show_games(entries)
            else:
                self._owned_from_store()

        auth.run_async(lambda: owned.fetch(key, steamid), done)

    def _owned_from_store(self):
        from .store_owned import fetch_owned_appids, owned_entries

        def done(appids):
            if not appids:
                return  # Not signed in to the Steam website here; installed games still show.
            entries = owned_entries(appids, self.config.root)
            owned.save_cache(entries)
            self._show_games(entries)

        fetch_owned_appids(done)

    @property
    def store_region(self):
        """Country for store prices: the chosen one, else the account's, else the UK."""
        if self.config is not None and not self.config.region_auto and self.config.region:
            return self.config.region
        return self.account_country or "GB"

    def _load_account_country(self):
        key = self.api_key
        if not key:
            self.account_country = ""
            return
        steamid = auth.steamid64(self.config)

        def done(country, error):
            if key == self.api_key and not error and country and country != self.account_country:
                self.account_country = country
                self.store_view.load(force=True)  # Show prices in the account's currency.

        auth.run_async(lambda: auth.account_country(key, steamid), done)

    def _update_sign_in_state(self):
        signed_in = bool(self.api_key)
        self.lookup_action("sign-in").set_enabled(not signed_in)
        self.lookup_action("sign-out").set_enabled(signed_in)
        self.library.signed_in = signed_in or config_mod.SCREENSHOTS
        self.library.refresh_sidebar()
        self._load_account_country()

    def sign_in(self, parent=None):
        dialog = SteamKeyDialog(self)
        dialog.connect("signed-in", lambda _d: self._on_connected())
        dialog.present(parent or self)
        return dialog

    def _on_connected(self):
        self.api_key = auth.load_key()
        self._update_sign_in_state()
        self.reload()

    def sign_out(self):
        """Forget the Web API key and owned games; the Steam website sign-in is separate."""
        auth.clear_key()
        owned.clear_cache()
        self.api_key = ""
        self._update_sign_in_state()
        self.reload()

    def _collections_changed(self):
        self.library.refresh_sidebar()
        self.library.changed()
        page = self.nav.get_visible_page()
        if hasattr(page, "_update_collections_row"):
            page._update_collections_row()

    def set_collection_member(self, collection_id, appid, member):
        collection = self.library.collections.get(collection_id)
        if collection is not None and collection.source == "steam":
            game_collections.set_steam_member(collection.steam_id, appid, member)
            self.queue_steam_sync()
        else:
            game_collections.set_member(collection_id, appid, member)
        self._collections_changed()

    def rename_game(self, game):

        def rename(name, steam_appid):
            game.props.name = name
            pending.add(game.props.appid, {"name": name})
            if steam_control.is_running(self.config):
                self.update_pending()
            else:
                try:
                    pending.apply_now(self.config)
                except (OSError, ValueError) as error:
                    self.toast(f"The new name could not be saved: {error}")
                self.update_pending()
            self.library.changed()  # Re-sort and re-filter under the new name.
            page = self.nav.get_visible_page()
            if getattr(page, "game", None) is game:
                page.set_title(name)
            if steam_appid and steam_appid != game.props.store_appid:
                self.set_store_match(game, steam_appid)

        from .rename_dialog import ask_game_name

        ask_game_name(self, game, rename)

    def set_hidden(self, game, hidden):
        game_collections.set_steam_member("hidden", game.props.appid, hidden)
        self.queue_steam_sync()
        self._collections_changed()
        self.toast(f"{game.props.name} {'hidden' if hidden else 'shown again'}")

    def set_favourite(self, game, favourite):
        game_collections.set_steam_member("favorite", game.props.appid, favourite)
        self.queue_steam_sync()
        self._collections_changed()

    def queue_steam_sync(self):
        """Write edits to Steam's collections now if Steam is closed, otherwise when it closes.

        Unlike the Sync button, this never sends Superlion's own collections, and it
        does not interrupt with a dialog: the pending changes banner offers a relaunch.
        """
        pending.add_collections_sync(include_own=False)
        if steam_control.is_running(self.config):
            self.update_pending()
            return
        try:
            pending.apply_now(self.config)
        except (OSError, ValueError) as error:
            self.toast(f"Steam's collections could not be updated: {error}")
        self.update_pending()

    def _ask_name(self, heading, body, confirm, initial, callback):
        dialog = Adw.AlertDialog(heading=heading, body=body)
        entry = Gtk.Entry(text=initial, activates_default=True)
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("confirm", confirm)
        dialog.set_response_appearance("confirm", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("confirm")
        dialog.set_close_response("cancel")
        entry.connect("changed", lambda e: dialog.set_response_enabled("confirm", bool(e.get_text().strip())))
        dialog.set_response_enabled("confirm", bool(initial.strip()))

        def on_response(_dialog, response):
            name = entry.get_text().strip()
            if response == "confirm" and name:
                callback(name)

        dialog.connect("response", on_response)
        dialog.present(self)
        dialog.set_focus(entry)
        entry.select_region(0, -1)

    def new_collection(self, game=None):

        def create(name):
            collection = game_collections.create(name)
            if game is not None:
                game_collections.set_member(collection.id, game.props.appid, True)
            self._collections_changed()
            self.toast(f"Created “{name}”")

        body = f"“{game.props.name}” will be added to it." if game else "Add games by right-clicking them."
        self._ask_name("New Collection", body, "Create", "", create)

    def rename_collection(self, collection_id):
        collection = self.library.collections.get(collection_id)
        if collection is None:
            return

        steam = collection.source == "steam"

        def rename(name):
            if steam:
                game_collections.rename_steam(collection.steam_id, name)
            else:
                game_collections.rename(collection_id, name)
            self.library.refresh_sidebar()
            if steam:
                self.queue_steam_sync()  # Steam's own collections change only through a sync.

        body = "The new name is written to Steam now, or when Steam next closes if it is running." if steam else ""
        self._ask_name("Rename Collection", body, "Rename", collection.name, rename)

    def delete_collection(self, collection_id):
        collection = self.library.collections.get(collection_id)
        if collection is None:
            return
        steam = collection.source == "steam"
        body = "The games stay in your library."
        if steam:
            body += " The collection is removed from Steam, and from your other devices, when it syncs."
        elif collection.steam_id:
            body += " The collection is also removed from Steam the next time collections are synced."
        dialog = Adw.AlertDialog(heading=f"Delete “{collection.name}”?", body=body)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("delete", "Delete")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_close_response("cancel")

        def on_response(_dialog, response):
            if response == "delete":
                if steam:
                    game_collections.delete_steam(collection.steam_id)
                else:
                    game_collections.delete(collection_id)
                self.library.refresh_sidebar()
                self.library.changed()
                if steam:
                    self.queue_steam_sync()

        dialog.connect("response", on_response)
        dialog.present(self)

    def sync_collections(self):
        """Copy Superlion's collections into Steam, which must be closed to accept them."""
        if not steam_control.is_running(self.config):
            try:
                pending.add_collections_sync()
                pending.apply_now(self.config)
            except (OSError, ValueError) as error:
                self.toast(f"Collections could not be synced: {error}")
                self.update_pending()
                return
            self.library.refresh_sidebar()
            self.update_pending()
            self.toast("Collections synced. Steam uploads them to Steam Cloud when it next starts.")
            return

        dialog = Adw.AlertDialog(
            heading="Steam Must Be Closed",
            body=(
                "Steam keeps collections in memory and overwrites changes made while it is "
                "running. Relaunch Steam now to sync them, or have them synced when Steam next closes."
            ),
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("later", "Sync When Steam Closes")
        dialog.add_response("relaunch", "Relaunch Steam Now")
        dialog.set_response_appearance("relaunch", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("relaunch")
        dialog.set_close_response("cancel")

        def on_response(_dialog, response):
            if response == "cancel":
                return
            pending.add_collections_sync()
            if response == "relaunch":
                self.relaunch_steam()
            else:
                self.update_pending()

        dialog.connect("response", on_response)
        dialog.present(self)

    def find_game(self, appid):
        store = self.library.store
        for i in range(store.get_n_items()):
            game = store.get_item(i)
            if game.props.appid == appid:
                return game
        return None

    def open_store_app(self, appid, name=""):
        self.nav.push(StoreAppPage(self, appid, name))

    def open_web(self, url, title="Steam Store"):
        self.nav.push(SteamWebPage(self, url, title))

    def launch(self, uri, message):
        try:
            steam_control.open_uri(self.config, uri)
            self.toast(message)
        except GLib.Error as error:
            self.toast(f"Steam could not be opened: {error.message}")

    def open_website(self, url):
        Gtk.UriLauncher(uri=url).launch(self, None, None)

    def open_artwork_picker(self, game, kind):
        from .artwork_picker import ArtworkPicker

        picker = ArtworkPicker(self, game, kind)
        picker.connect("chosen", lambda _p, path: self.set_artwork(game, kind, path))
        picker.present(self)

    def set_artwork(self, game, kind, source, quiet=False):
        try:
            target = str(library.set_custom_art(self.config, game.props.appid, kind, source))
        except OSError as error:
            self.toast(f"The image could not be saved: {error.strerror}")
            return
        images.forget(target)
        # Clear first so covers and banners reload even when the file name is unchanged.
        game.set_property(kind, "")
        game.set_property(kind, target)
        page = self.nav.get_visible_page()
        if getattr(page, "game", None) is game and hasattr(page, "refresh_artwork"):
            page.refresh_artwork(kind)
        if not quiet:
            self.toast(f"{library.ART_LABELS[kind]} updated")

    def launch_mod_manager(self, manager):
        """Start a mod manager: a Linux application directly, a non-Steam game through Steam."""
        if manager.is_app:
            app = mod_managers.app_info(manager)
            if app is None:
                self.toast(f"{manager.name} is no longer installed")
                return
            try:
                app.launch([], None)
                self.toast(f"Opening {manager.name}")
            except GLib.Error as error:
                self.toast(f"{manager.name} could not be opened: {error.message}")
            return
        game = self.find_game(manager.shortcut_appid)
        if game is None:
            self.toast(f"{manager.name} is no longer in your Steam library")
            return
        self.launch(game.run_uri, f"Opening {manager.name}")

    def add_app_mod_manager(self):
        from .app_chooser import AppChooser

        def chosen(_dialog, desktop_id, name):
            mod_managers.add(f"app:{desktop_id}", name)
            self.library.refresh_sidebar()
            self.library.changed()
            self.toast(f"{name} added as a mod manager")

        dialog = AppChooser()
        dialog.connect("chosen", chosen)
        dialog.present(self)

    def set_mod_manager_shortcut(self, game, is_manager):
        mod_managers.set_shortcut(game.props.appid, game.props.name, is_manager)
        self.library.refresh_sidebar()
        self.library.changed()

    def open_folder(self, path):
        Gtk.FileLauncher(file=Gio.File.new_for_path(str(path))).launch(self, None, None)

    def open_client_store(self):
        try:
            steam_control.open_uri(self.config, "steam://store")
        except GLib.Error as error:
            self.toast(f"Steam could not be opened: {error.message}")

    def toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=text))

    def run_setup(self, first_run=False):
        start = self.config or config_mod.detect()
        wizard = SetupWizard(start, self, first_run=first_run)
        wizard.connect("finished", self._on_setup_finished)
        wizard.present(self)

    def _on_setup_finished(self, wizard):
        config_mod.save(wizard.result)
        self.set_config(wizard.result)

    def update_pending(self):
        count = pending.count()
        if count:
            self.pending_banner.set_title(
                f"{count} change{'s' if count != 1 else ''} will be written to Steam when it closes"
            )
        self.pending_banner.set_revealed(bool(count))
        if count and not self._pending_watch:
            self._pending_watch = GLib.timeout_add_seconds(5, self._on_pending_watch)

    def _on_pending_watch(self):
        if self._relaunching:
            return GLib.SOURCE_CONTINUE
        self._apply_pending_if_closed()
        if pending.count():
            return GLib.SOURCE_CONTINUE
        self._pending_watch = 0
        return GLib.SOURCE_REMOVE

    def _apply_pending_if_closed(self):
        try:
            applied = pending.apply_if_closed(self.config)
        except OSError as error:
            self.toast(f"Waiting settings could not be saved: {error.strerror}")
            applied = 0
        if applied:
            self.toast("Steam closed, so your waiting changes were written to Steam")
            self.library.refresh_sidebar()
        self.update_pending()

    def apply_game_settings(self, appid, changes, on_applied=None, parent=None):
        """Save a game's settings to Steam, asking first when Steam must be closed.

        on_applied(changes) runs once they are saved or queued for when Steam closes.
        """
        if not steam_control.is_running(self.config):
            # Queue first so older queued values for this game cannot overwrite these.
            pending.add(appid, changes)
            try:
                pending.apply_now(self.config)
            except OSError as error:
                self.toast(f"The settings could not be saved: {error.strerror}")
                self.update_pending()
                return
            if on_applied:
                on_applied(changes)
            self.update_pending()
            self.toast("Settings saved")
            return

        dialog = Adw.AlertDialog(
            heading="Steam Must Be Closed",
            body=(
                "Steam keeps these settings in memory and overwrites any changes made "
                "while it is running. Relaunch Steam now to apply them, or have them "
                "applied automatically when Steam next closes."
            ),
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("later", "Apply When Steam Closes")
        dialog.add_response("relaunch", "Relaunch Steam Now")
        dialog.set_response_appearance("relaunch", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("relaunch")
        dialog.set_close_response("cancel")

        def on_response(_dialog, response):
            if response == "cancel":
                return
            pending.add(appid, changes)
            if on_applied:
                on_applied(changes)
            if response == "relaunch":
                self.relaunch_steam()
            else:
                self.update_pending()

        dialog.connect("response", on_response)
        dialog.present(parent or self)

    def relaunch_steam(self):
        if self._relaunching:
            return
        self._relaunching = True
        self.pending_banner.set_button_label("Relaunching…")
        self.toast("Closing Steam…")

        def done(error):
            self._relaunching = False
            self.pending_banner.set_button_label("Relaunch Steam")
            self.toast(error or "Changes written and Steam restarted")
            self.library.refresh_sidebar()
            self.update_pending()

        steam_control.relaunch(self.config, lambda: pending.apply_now(self.config), done)

    def _attach_banners(self, *_args):
        page = self.nav.get_visible_page()
        toolbar = page.get_child() if page else None
        if isinstance(toolbar, Adw.OverlaySplitView):
            toolbar = toolbar.get_content()  # Banners belong over the content, not the sidebar.
        if not isinstance(toolbar, Adw.ToolbarView):
            return
        for banner in self.banners:
            current = banner.get_ancestor(Adw.ToolbarView)
            if current is toolbar:
                continue
            if current is not None:
                current.remove(banner)
            toolbar.add_top_bar(banner)
