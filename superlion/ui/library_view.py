"""The Library section: sidebar of views and collections, and the game grid."""

from gi.repository import Adw, Gio, GLib, Gtk, Pango

from .. import downloads, game_collections, library, mod_managers, owned, steam_control
from . import images

COVER_W, COVER_H = 150, 225
GROUP_TITLES = {"genre": "Genre", "year": "Release Year", "installed": "Installed"}
BUILT_IN_VIEWS = [
    ("all", "All Games", "applications-games-symbolic"),
    ("installed", "Installed", "drive-harddisk-symbolic"),
    ("not_installed", "Not Installed", "folder-download-symbolic"),
    ("vr", "VR Games", "superlion-vr-symbolic"),
    ("non_steam", "Non-Steam Games", "application-x-executable-symbolic"),
    ("mod_managers", "Mod Managers", "superlion-mod-manager-symbolic"),
]
# Views from which non-Steam games marked as mod managers are left out.
MANAGER_FREE_VIEWS = {"all", "installed", "not_installed", "non_steam"}


# Tiles ---------------------------------------------------------------------


class LibraryTile(Gtk.Box):
    """A game cover with its name; uninstalled games get an Install button."""

    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.window = window
        self.add_css_class("game-tile")
        self.game = None
        self._cover_handler = 0
        self._name_handler = 0
        self._download_handlers = []

        self.placeholder = Gtk.Image(icon_name="applications-games-symbolic", pixel_size=48)
        self.placeholder.add_css_class("dim-label")
        self.picture = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, can_shrink=True)
        overlay = Gtk.Overlay(child=self.placeholder, overflow=Gtk.Overflow.HIDDEN)
        overlay.add_overlay(self.picture)
        overlay.set_size_request(COVER_W, COVER_H)
        for css in ("cover-frame", "cover-placeholder", "card"):
            overlay.add_css_class(css)

        self.install_button = Gtk.Button(
            label="Install", halign=Gtk.Align.CENTER, valign=Gtk.Align.END, margin_bottom=12
        )
        self.install_button.add_css_class("pill")
        self.install_button.add_css_class("suggested-action")
        self.install_button.connect("clicked", self._on_install)
        overlay.add_overlay(self.install_button)

        # Steam download state, such as "Updating 42%", along the bottom of the cover.
        self.download_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=6, valign=Gtk.Align.END,
            margin_start=8, margin_end=8, margin_bottom=8, visible=False,
        )
        self.download_box.add_css_class("osd")
        self.download_box.add_css_class("download-badge")
        self.download_label = Gtk.Label(ellipsize=Pango.EllipsizeMode.END)
        self.download_label.add_css_class("caption-heading")
        self.download_bar = Gtk.ProgressBar()
        self.download_box.append(self.download_label)
        self.download_box.append(self.download_bar)
        overlay.add_overlay(self.download_box)
        self.append(overlay)

        self.label = Gtk.Label(ellipsize=Pango.EllipsizeMode.END, max_width_chars=1, hexpand=True)
        self.append(self.label)

        # Right-click, or press and hold on a touch screen, to manage collections.
        click = Gtk.GestureClick(button=3)
        click.connect("pressed", lambda *_: self._show_menu())
        self.add_controller(click)
        hold = Gtk.GestureLongPress()
        hold.connect("pressed", lambda *_: self._show_menu())
        self.add_controller(hold)

    def bind(self, game):
        if self.game is not None and self._cover_handler:
            self.game.disconnect(self._cover_handler)
            self.game.disconnect(self._name_handler)
            for handler in self._download_handlers:
                self.game.disconnect(handler)
        self.game = game
        self._show_name()
        self._name_handler = game.connect("notify::name", lambda *_: self._show_name())
        self._download_handlers = [
            game.connect(f"notify::{prop}", lambda *_: self._show_download())
            for prop in ("download-label", "download-progress")
        ]
        self.picture.set_opacity(1.0 if game.props.installed else 0.6)
        self._show_download()
        # Artwork for games that are not installed may arrive after binding.
        self._cover_handler = game.connect("notify::cover", lambda *_: self._load_cover())
        self._load_cover()
        if not game.props.cover:
            owned.ensure_art(game, "cover")

    def _show_download(self):
        game = self.game
        busy = bool(game.props.download_label)
        self.download_box.set_visible(busy)
        self.download_label.set_label(game.props.download_label)
        self.download_bar.set_visible(game.props.download_progress >= 0)
        self.download_bar.set_fraction(max(0.0, game.props.download_progress))
        # Install would only queue what Steam is already doing.
        self.install_button.set_visible(not game.props.installed and not busy)

    def _show_name(self):
        self.label.set_label(self.game.props.name)
        self.set_tooltip_text(self.game.props.name)

    def _load_cover(self):
        self.picture.set_paintable(None)

        def apply(texture, expected=self.game):
            if self.game is expected:
                self.picture.set_paintable(texture)
                # Dimmed covers of uninstalled games would otherwise show the icon through them.
                self.placeholder.set_visible(texture is None)

        self.placeholder.set_visible(True)
        images.load(self.game.props.cover, COVER_W * 2, COVER_H * 2, apply)

    def _on_install(self, _button):
        try:
            steam_control.open_uri(self.window.config, f"steam://install/{self.game.props.appid}")
            self.window.toast(f"Opening the Steam install dialog for {self.game.props.name}")
        except GLib.Error as error:
            self.window.toast(f"Steam could not be opened: {error.message}")

    def _show_menu(self):
        if self.game is None:
            return
        menu, actions = game_menu(self.window, self.game)
        # Actions are rebuilt for each menu, so check marks match the game's current state.
        self.insert_action_group("game", actions)
        popover = Gtk.PopoverMenu(menu_model=menu, has_arrow=True)
        popover.set_parent(self)
        popover.connect("closed", lambda p: GLib.idle_add(p.unparent))
        popover.popup()


def game_menu(window, game):
    """The right-click menu for a game, and the "game" action group it uses."""
    actions = Gio.SimpleActionGroup()
    appid = game.props.appid

    def action(name, callback):
        act = Gio.SimpleAction.new(name, None)
        act.connect("activate", lambda *_: callback())
        actions.add_action(act)

    def toggle(name, state, callback):
        act = Gio.SimpleAction.new_stateful(name, None, GLib.Variant("b", state))
        act.connect("change-state", lambda a, v: (a.set_state(v), callback(v.get_boolean())))
        actions.add_action(act)

    menu = Gio.Menu()
    main = Gio.Menu()
    download = None if game.props.non_steam else downloads.state_for(window.config, appid)
    if download is not None:
        # Shown greyed out, as the game cannot start or install until Steam finishes.
        main.append(downloads.play_label(download, game.props.installed), "game.busy")
        busy = Gio.SimpleAction.new("busy", None)
        busy.set_enabled(False)
        actions.add_action(busy)
    elif game.props.installed:
        main.append("Play", "game.play")
        action("play", lambda: window.launch(game.run_uri, f"Launching {game.props.name}"))
    else:
        main.append("Install", "game.install")
        action("install", lambda: window.launch(f"steam://install/{appid}", "Opening the Steam install dialog"))
    main.append("Show Details", "game.details")
    action("details", lambda: window.open_game(game))
    if game.props.store_appid:
        main.append("View in Store", "game.store")
        action("store", lambda: window.open_store_app(game.props.store_appid, game.props.name))
    if game.props.non_steam:
        main.append("Rename…", "game.rename")
        action("rename", lambda: window.rename_game(game))
        main.append("Match to Steam Game…", "game.match")
        action("match", lambda: window.open_match_dialog(game))
    main.append("Choose Cover from SteamGridDB…", "game.steamgriddb")
    action("steamgriddb", lambda: window.open_artwork_picker(game, "cover"))
    menu.append_section(None, main)

    places = Gio.Menu()
    if game.props.installed and game.props.install_dir:
        places.append("Browse Game Files", "game.folder")
        action("folder", lambda: window.open_folder(game.props.install_dir))
        prefix = library.prefix_path(window.config, game)
        if prefix:
            places.append("Open Compatibility Files", "game.prefix")
            action("prefix", lambda: window.open_folder(prefix))
    if places.get_n_items():
        menu.append_section(None, places)

    organise = Gio.Menu()
    collections = window.library.collections.values()
    favourites = next((c for c in collections if c.steam_id == "favorite" and c.source == "steam"), None)
    organise.append("Favourite", "game.favourite")
    toggle("favourite", bool(favourites and appid in favourites.appids),
           lambda on: window.set_favourite(game, on))

    submenu = Gio.Menu()
    choices = [c for c in collections if not game_collections.is_fixed(c)]
    for index, collection in enumerate(sorted(choices, key=lambda c: (c.source != "steam", c.name.casefold()))):
        submenu.append(collection.name, f"game.collection-{index}")
        toggle(f"collection-{index}", appid in collection.appids,
               lambda on, cid=collection.id: window.set_collection_member(cid, appid, on))
    new = Gio.Menu()
    new.append("New Collection…", "game.new-collection")
    action("new-collection", lambda: window.new_collection(game))
    submenu.append_section(None, new)
    organise.append_submenu("Add to Collection", submenu)
    menu.append_section(None, organise)

    manager = mod_managers.linked(appid)
    if manager is not None:
        launch_section = Gio.Menu()
        launch_section.append(f"Launch {manager.name}", "game.mod-manager")
        action("mod-manager", lambda: window.launch_mod_manager(manager))
        menu.insert_section(1, None, launch_section)
    if game.props.non_steam:
        organise.append("Mod Manager", "game.is-manager")
        toggle("is-manager", appid in mod_managers.shortcut_ids(),
               lambda on: window.set_mod_manager_shortcut(game, on))

    visibility = Gio.Menu()
    hidden = appid in window.library.hidden_ids
    visibility.append("Unhide Game" if hidden else "Hide Game", "game.hide")
    action("hide", lambda: window.set_hidden(game, not hidden))
    menu.append_section(None, visibility)
    return menu, actions


def collections_popover(window, game):
    """Check boxes for adding a game to, or removing it from, the user's collections."""
    popover = Gtk.Popover()
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=6, margin_bottom=6,
                  margin_start=6, margin_end=6)
    heading = Gtk.Label(label="Add to Collection", xalign=0, margin_start=6)
    heading.add_css_class("heading")
    box.append(heading)
    choices = sorted(
        (c for c in window.library.collections.values() if c.steam_id != "hidden" or c.source != "steam"),
        key=lambda c: (c.source != "steam", c.steam_id != "favorite", c.name.casefold()),
    )
    for collection in choices:
        check = Gtk.CheckButton(label=collection.name, active=game.props.appid in collection.appids)
        check.connect(
            "toggled",
            lambda c, cid=collection.id: window.set_collection_member(cid, game.props.appid, c.get_active()),
        )
        box.append(check)
    new = Gtk.Button(label="New Collection…")
    new.add_css_class("flat")
    new.connect("clicked", lambda *_: (popover.popdown(), window.new_collection(game)))
    box.append(new)
    popover.set_child(box)
    return popover


# Sidebar -------------------------------------------------------------------


class SidebarRow(Gtk.ListBoxRow):
    def __init__(self, key, title, icon, section, collection=None):
        super().__init__()
        self.key = key
        self.section = section
        self.collection = collection
        box = Gtk.Box(spacing=12, margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)
        box.append(Gtk.Image(icon_name=icon))
        self.title = Gtk.Label(label=title, xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END)
        box.append(self.title)
        self.count = Gtk.Label()
        self.count.add_css_class("dim-label")
        self.count.add_css_class("numeric")
        box.append(self.count)
        self.set_child(box)


class LibraryView(Adw.Bin):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.view = "installed"
        self.sort_mode = "name"
        self.group_mode = "none"
        self.search_text = ""
        self.signed_in = False
        self.collections = {}  # id -> Collection, Steam's and Superlion's
        self.hidden_ids = set()
        self.manager_ids = set()
        self._manager_groups = []
        self._rebuild_source = 0

        self.store = Gio.ListStore(item_type=library.Game)
        self.filter = Gtk.CustomFilter.new(self._filter_func)
        self.sorter = Gtk.CustomSorter.new(self._sort_func)
        self.visible_games = Gtk.SortListModel(
            model=Gtk.FilterListModel(model=self.store, filter=self.filter), sorter=self.sorter
        )

        # The window places the sidebar in its split view, beside all page content.
        self.sidebar = self._build_sidebar()
        self.set_child(self._build_content())
        self.split = None

    # Sidebar ---------------------------------------------------------------

    def _build_sidebar(self):
        self.sidebar_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.sidebar_list.add_css_class("navigation-sidebar")
        self.sidebar_list.set_header_func(self._sidebar_header)
        self.sidebar_list.connect("row-selected", self._on_row_selected)
        click = Gtk.GestureClick(button=3)
        click.connect("pressed", self._on_sidebar_right_click)
        self.sidebar_list.add_controller(click)

        self.sync_button = Gtk.Button(label="Sync Collections to Steam", margin_top=6, margin_bottom=6,
                                      margin_start=6, margin_end=6)
        self.sync_button.add_css_class("pill")
        self.sync_button.connect("clicked", lambda *_: self.window.sync_collections())

        toolbar = Adw.ToolbarView(
            content=Gtk.ScrolledWindow(child=self.sidebar_list, hscrollbar_policy=Gtk.PolicyType.NEVER)
        )
        # Split header bars: the sidebar has its own, so it runs the full window height.
        toolbar.add_top_bar(Adw.HeaderBar(show_title=False))
        toolbar.add_bottom_bar(self.sync_button)
        return toolbar

    def _sidebar_header(self, row, before):
        if before is not None and before.section == row.section:
            row.set_header(None)
            return
        titles = {"steam": "Steam Collections", "own": "My Collections"}
        if row.section in titles:
            label = Gtk.Label(label=titles[row.section], xalign=0, margin_start=12, margin_top=12, margin_bottom=6)
            label.add_css_class("heading")
            label.add_css_class("dim-label")
            row.set_header(label)
        else:
            row.set_header(None)

    def refresh_sidebar(self):
        """Rebuild the sidebar from the current sign-in state and collections."""
        steam = game_collections.load_steam(self.window.config) if self.window.config else []
        own = game_collections.load_own()
        self.collections = {c.id: c for c in steam + own}
        hidden = next((c for c in steam if c.steam_id == "hidden"), None)
        self.hidden_ids = set(hidden.appids) if hidden else set()
        self.manager_ids = mod_managers.shortcut_ids()

        self.sidebar_list.remove_all()
        rows = []
        for key, title, icon in BUILT_IN_VIEWS:
            if key == "not_installed" and not self.signed_in:
                continue
            rows.append(SidebarRow(key, title, icon, "views"))
        for c in steam:
            icon = {"favorite": "starred-symbolic", "hidden": "view-conceal-symbolic"}.get(
                c.steam_id, "folder-symbolic"
            )
            rows.append(SidebarRow(c.id, c.name, icon, "steam", c))
        for c in own:
            rows.append(SidebarRow(c.id, c.name, "folder-symbolic", "own", c))
        rows.append(SidebarRow("new", "New Collection…", "list-add-symbolic", "own"))
        for row in rows:
            self.sidebar_list.append(row)

        self.sync_button.set_visible(bool(own) or game_collections.needs_sync())
        self.sync_button.set_sensitive(game_collections.needs_sync())
        if game_collections.needs_sync():
            self.sync_button.add_css_class("suggested-action")
        else:
            self.sync_button.remove_css_class("suggested-action")
        self.sync_button.set_tooltip_text(
            "Superlion's collections have changes that Steam does not have yet."
            if game_collections.needs_sync() else "Steam already has your latest collections."
        )
        if self.view not in {r.key for r in rows} or self.view == "new":
            self.view = "installed"
        self._select_row(self.view)
        self.update_counts()

    def _select_row(self, key):
        row = self.sidebar_list.get_first_child()
        while row is not None:
            if isinstance(row, SidebarRow) and row.key == key:
                self.sidebar_list.select_row(row)
                return
            row = row.get_next_sibling()

    def update_counts(self):
        games = [self.store.get_item(i) for i in range(self.store.get_n_items())]
        row = self.sidebar_list.get_first_child()
        while row is not None:
            if isinstance(row, SidebarRow) and row.key == "mod_managers":
                row.count.set_label(str(len(mod_managers.all_managers())))
            elif isinstance(row, SidebarRow) and row.key != "new":
                row.count.set_label(str(sum(1 for g in games if self._in_view(g, row.key))))
            row = row.get_next_sibling()

    def _on_row_selected(self, _list, row):
        if row is None:
            return
        if row.key == "new":
            self._select_row(self.view)
            self.window.new_collection()
            return
        self.view = row.key
        if self.group_mode == "installed" and self.view in ("installed", "not_installed"):
            self.group_mode = "none"
        self.window.on_library_view_changed()
        self.changed()
        if self.split is not None and self.split.get_collapsed():
            self.split.set_show_sidebar(False)

    def _on_sidebar_right_click(self, _gesture, _n, x, y):
        row = self.sidebar_list.get_row_at_y(int(y))
        if not isinstance(row, SidebarRow) or row.collection is None:
            return
        if game_collections.is_fixed(row.collection):
            return  # Favorites and Hidden are built into Steam.
        menu = Gio.Menu()
        menu.append("Rename…", f"win.rename-collection::{row.collection.id}")
        menu.append("Delete", f"win.delete-collection::{row.collection.id}")
        popover = Gtk.PopoverMenu(menu_model=menu, has_arrow=True)
        popover.set_parent(row)
        popover.connect("closed", lambda p: GLib.idle_add(p.unparent))
        popover.popup()

    # Content ---------------------------------------------------------------

    def _build_content(self):
        self.search_entry = Gtk.SearchEntry(placeholder_text="Search games", hexpand=True)
        self.search_entry.connect("search-changed", self._on_search_changed)
        self.search_bar = Gtk.SearchBar(child=Adw.Clamp(child=self.search_entry, maximum_size=480))
        self.search_bar.connect_entry(self.search_entry)

        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", lambda _f, item: item.set_child(LibraryTile(self.window)))
        factory.connect("bind", lambda _f, item: item.get_child().bind(item.get_item()))
        grid = Gtk.GridView(
            model=Gtk.NoSelection(model=self.visible_games),
            factory=factory, single_click_activate=True, max_columns=12, min_columns=2,
        )
        grid.add_css_class("navigation-sidebar")
        grid.connect("activate", lambda _g, pos: self.window.open_game(self.visible_games.get_item(pos)))

        self.groups_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_bottom=24)

        self.content_stack = Gtk.Stack(vexpand=True)
        self.content_stack.add_named(
            Gtk.ScrolledWindow(child=grid, hscrollbar_policy=Gtk.PolicyType.NEVER), "grid"
        )
        self.content_stack.add_named(
            Gtk.ScrolledWindow(child=self.groups_box, hscrollbar_policy=Gtk.PolicyType.NEVER), "groups"
        )
        self.content_stack.add_named(
            Adw.StatusPage(icon_name="system-search-symbolic", title="No Games Here",
                           description="Try a different search, view or collection."),
            "empty",
        )
        self.content_stack.add_named(
            Adw.StatusPage(icon_name="applications-games-symbolic", title="Steam Not Found",
                           description="Run setup from the main menu to choose your Steam folder."),
            "missing",
        )
        self.managers_page = Adw.PreferencesPage()
        self.content_stack.add_named(self.managers_page, "mod_managers")

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(self.search_bar)
        box.append(self.content_stack)
        return box

    def _show_mod_managers(self):
        """List of mod managers, with launch and remove buttons and a way to add apps."""
        for old in self._manager_groups:
            self.managers_page.remove(old)
        group = Adw.PreferencesGroup(
            title="Mod Managers",
            description=(
                "Linux applications or non-Steam games used to mod your games. Link a game to "
                "one in its Information tab to get a Launch Mod Manager button. To use a "
                "non-Steam game, turn on Mod Manager in its Information tab."
            ),
        )
        counts = mod_managers.link_counts()
        for manager in mod_managers.all_managers():
            linked = counts.get(manager.id, 0)
            kind = "Linux application" if manager.is_app else "Non-Steam game"
            row = Adw.ActionRow(
                title=GLib.markup_escape_text(manager.name),
                subtitle=f"{kind} · linked to {linked} game{'s' if linked != 1 else ''}",
            )
            app = mod_managers.app_info(manager)
            icon = Gtk.Image(pixel_size=32)
            if app is not None and app.get_icon() is not None:
                icon.set_from_gicon(app.get_icon())
            else:
                icon.set_from_icon_name("application-x-executable-symbolic")
            row.add_prefix(icon)
            launch = Gtk.Button(label="Launch", valign=Gtk.Align.CENTER)
            launch.add_css_class("suggested-action")
            launch.connect("clicked", lambda _b, m=manager: self.window.launch_mod_manager(m))
            remove = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text="Stop Using as Mod Manager",
                                valign=Gtk.Align.CENTER)
            remove.add_css_class("flat")
            remove.connect("clicked", lambda _b, m=manager: self._remove_manager(m))
            row.add_suffix(launch)
            row.add_suffix(remove)
            group.add(row)
        add = Adw.ButtonRow(title="Add Linux Application…", start_icon_name="list-add-symbolic")
        add.connect("activated", lambda *_: self.window.add_app_mod_manager())
        group.add(add)
        self.managers_page.add(group)
        self._manager_groups = [group]

    def _remove_manager(self, manager):
        mod_managers.remove(manager.id)
        self.refresh_sidebar()
        self.changed()

    def _in_view(self, game, view):
        appid = game.props.appid
        if view == "steam:hidden":
            return appid in self.hidden_ids
        if appid in self.hidden_ids:
            return False  # Steam hides these everywhere except the Hidden collection.
        if view in MANAGER_FREE_VIEWS and game.props.non_steam and appid in self.manager_ids:
            return False  # Listed under Mod Managers instead.
        if view == "all":
            return True
        if view == "installed":
            return game.props.installed
        if view == "not_installed":
            return not game.props.installed
        if view == "vr":
            return game.props.vr > 0
        if view == "non_steam":
            return game.props.non_steam
        collection = self.collections.get(view)
        return collection is not None and appid in collection.appids

    def _filter_func(self, game):
        if not self._in_view(game, self.view):
            return False
        return not self.search_text or library.game_matches(game, self.search_text)

    def _sort_func(self, a, b, _data=None):
        ka, kb = library.sort_key(a, self.sort_mode), library.sort_key(b, self.sort_mode)
        return (ka > kb) - (ka < kb)

    def _on_search_changed(self, entry):
        self.search_text = entry.get_text().strip()
        self.changed()

    def set_games(self, games):
        self.store.splice(0, self.store.get_n_items(), games)
        self.update_counts()
        self.changed()

    def changed(self):
        """Re-apply the view, search, sort and grouping."""
        self.filter.changed(Gtk.FilterChange.DIFFERENT)
        self.sorter.changed(Gtk.SorterChange.DIFFERENT)
        if self.group_mode != "none" and not self._rebuild_source:
            # Grouped pages are rebuilt once per burst of changes, such as typing.
            self._rebuild_source = GLib.timeout_add(150, self._rebuild_groups)
        self._update_page()

    def _update_page(self):
        config = self.window.config
        if self.view == "mod_managers":
            self._show_mod_managers()
            self.content_stack.set_visible_child_name("mod_managers")
        elif config is None or not config.root.is_dir():
            self.content_stack.set_visible_child_name("missing")
        elif self.visible_games.get_n_items() == 0:
            self.content_stack.set_visible_child_name("empty")
        else:
            self.content_stack.set_visible_child_name("grid" if self.group_mode == "none" else "groups")

    def _rebuild_groups(self):
        self._rebuild_source = 0
        while child := self.groups_box.get_first_child():
            self.groups_box.remove(child)
        groups = {}
        for i in range(self.visible_games.get_n_items()):
            game = self.visible_games.get_item(i)
            for key in library.group_keys(game, self.group_mode):
                groups.setdefault(key, []).append(game)
        for (_order, title), games in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1].casefold())):
            heading = Gtk.Box(spacing=12, margin_start=18, margin_top=12)
            label = Gtk.Label(label=title, xalign=0)
            label.add_css_class("title-3")
            heading.append(label)
            count = Gtk.Label(label=str(len(games)), valign=Gtk.Align.BASELINE_CENTER)
            count.add_css_class("dim-label")
            heading.append(count)
            self.groups_box.append(heading)

            flow = Gtk.FlowBox(
                homogeneous=True, selection_mode=Gtk.SelectionMode.NONE, activate_on_single_click=True,
                max_children_per_line=12, min_children_per_line=2, margin_start=6, margin_end=6,
            )
            flow.add_css_class("navigation-sidebar")
            for game in games:
                tile = LibraryTile(self.window)
                tile.bind(game)
                flow.append(tile)
            flow.connect("child-activated", lambda _f, child: self.window.open_game(child.get_child().game))
            self.groups_box.append(flow)
        return GLib.SOURCE_REMOVE
