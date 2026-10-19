"""Per-game details page."""

from gi.repository import Adw, Gio, GLib, Gtk

from .. import (
    auth, downloads, library, mod_managers, owned, pending, steam_control, steam_settings, store_api,
)
from . import images
from .. import launch_options as lo
from .artwork_picker import choose_file
from .launch_options_editor import LaunchOptionsEditor, describe_warning
from .library_view import collections_popover, game_menu
from .downloads_view import describe
from .media import MediaCarousel, description_widgets, news_group


def format_last_played(timestamp):
    if not timestamp:
        return "Never"
    return GLib.DateTime.new_from_unix_local(timestamp).format("%-d %B %Y, %H:%M")


def format_date(timestamp):
    return GLib.DateTime.new_from_unix_local(timestamp).format("%-d %B %Y")


def info_row(title, value):
    row = Adw.ActionRow(title=title, subtitle=value, subtitle_selectable=True)
    row.add_css_class("property")
    return row


def folder_row(title, path, on_open):
    row = info_row(title, str(path))
    button = Gtk.Button(icon_name="folder-open-symbolic", tooltip_text="Open Folder", valign=Gtk.Align.CENTER)
    button.add_css_class("flat")
    button.connect("clicked", lambda *_: on_open(path))
    row.add_suffix(button)
    return row


class GameDetailsPage(Adw.NavigationPage):
    def __init__(self, window, game):
        super().__init__(title=game.props.name)
        self.window = window
        self.game = game

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content.append(self._build_hero())

        body = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=24,
            margin_top=24,
            margin_bottom=24,
            margin_start=12,
            margin_end=12,
        )
        body.append(self._build_actions())
        body.append(self._build_warnings_note())
        body.append(self._build_download_progress())

        overview = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.store_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.news_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        overview.append(self.store_box)
        overview.append(self.news_box)

        information = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        information.append(self._build_info())
        information.append(self._build_artwork())

        self.tabs = Adw.ViewStack(vhomogeneous=False)
        # Non-Steam games get an Overview when they are matched to a store game.
        if game.props.store_appid:
            self.tabs.add_titled_with_icon(overview, "overview", "Overview", "view-grid-symbolic")
        self.tabs.add_titled_with_icon(information, "information", "Information", "dialog-information-symbolic")
        self.tabs.add_titled_with_icon(self._build_settings(), "settings", "Steam Settings", "emblem-system-symbolic")
        switcher = Adw.InlineViewSwitcher(stack=self.tabs, halign=Gtk.Align.CENTER)
        switcher.add_css_class("round")
        body.append(switcher)
        body.append(self.tabs)
        content.append(Adw.Clamp(child=body, maximum_size=860))
        self.media = None
        self.connect("hidden", lambda *_: self.media and self.media.pause())
        if game.props.store_appid:
            self._load_store_content()
        self._watch_downloads()

        toolbar = Adw.ToolbarView(
            content=Gtk.ScrolledWindow(child=content, hscrollbar_policy=Gtk.PolicyType.NEVER),
            extend_content_to_top_edge=True,
        )
        # Its own back button, so the start and end buttons can be coloured separately.
        self.header = Adw.HeaderBar(show_title=False, show_back_button=False)
        self.header.add_css_class("hero-header")
        back = Gtk.Button(icon_name="go-previous-symbolic", tooltip_text="Back")
        back.add_css_class("hero-back")
        back.connect("clicked", lambda *_: self.window.nav.pop())
        self.header.pack_start(back)
        toolbar.add_top_bar(self.header)
        self.set_child(toolbar)

    def _build_hero(self):
        game = self.game
        self.hero = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, can_shrink=True, height_request=280)
        overlay = Gtk.Overlay(child=self.hero, overflow=Gtk.Overflow.HIDDEN)

        self.logo = Gtk.Picture(
            can_shrink=True,
            halign=Gtk.Align.START,
            valign=Gtk.Align.END,
            margin_start=24,
            margin_bottom=20,
            height_request=110,
            width_request=320,
        )
        overlay.add_overlay(self.logo)
        self.title = Gtk.Label(
            label=game.props.name,
            wrap=True,
            halign=Gtk.Align.START,
            valign=Gtk.Align.END,
            margin_start=24,
            margin_bottom=20,
        )
        self.title.add_css_class("title-1")
        overlay.add_overlay(self.title)

        # Games that are not installed may need their artwork downloaded first.
        self._handlers = [
            game.connect(f"notify::{kind}", lambda *_: self._load_hero_art())
            for kind in ("hero", "logo", "header")
        ]
        self._load_hero_art()
        for kind in ("hero", "logo"):
            owned.ensure_art(game, kind)
        return overlay

    def _build_match_row(self):
        """Which Steam store game this non-Steam game is shown as, with ways to change it."""
        game = self.game
        if game.props.store_appid:
            subtitle = f"Store page, news and artwork from Steam app {game.props.store_appid}"
        else:
            subtitle = "Not matched. Choose the Steam game to show its store page and metadata."
        row = info_row("Steam Store Match", subtitle)
        change = Gtk.Button(
            label="Change…" if game.props.store_appid else "Match…", valign=Gtk.Align.CENTER
        )
        change.connect("clicked", lambda *_: self.window.open_match_dialog(game))
        row.add_suffix(change)
        if game.props.store_appid:
            remove = Gtk.Button(icon_name="edit-delete-symbolic", tooltip_text="Remove Match", valign=Gtk.Align.CENTER)
            remove.add_css_class("flat")
            remove.connect("clicked", lambda *_: self.window.set_store_match(game, 0))
            row.add_suffix(remove)
        return row

    def _on_name_changed(self, name_row):
        name = self.game.props.name
        name_row.set_subtitle(name)
        self.title.set_label(name)
        self.set_title(name)

    def _load_hero_art(self):
        game = self.game
        banner = game.props.hero or game.props.header
        images.load(banner, 1920, 620, self.hero.set_paintable)
        images.load(game.props.logo, 640, 220, self.logo.set_paintable)
        self.logo.set_visible(bool(game.props.logo))
        self.title.set_visible(not game.props.logo)
        if banner:
            auth.run_async(lambda: images.corners_are_light(banner), self._on_banner_measured)

    def _on_banner_measured(self, result, error):
        """Use dark header buttons on each side where the banner behind them is bright."""
        if error or result is None:
            return
        left, right = result
        for css, light in (("start-light", left), ("end-light", right)):
            if light:
                self.header.add_css_class(css)
            else:
                self.header.remove_css_class(css)

    def _build_download_progress(self):
        """Progress of a Steam update or install, shown below Play while there is one."""
        self.download_area = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=6, visible=False, halign=Gtk.Align.CENTER,
            width_request=360,
        )
        self.download_bar = Gtk.ProgressBar()
        self.download_text = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER)
        self.download_text.add_css_class("caption")
        self.download_text.add_css_class("dim-label")
        self.download_area.append(self.download_bar)
        self.download_area.append(self.download_text)
        return self.download_area

    def _watch_downloads(self):
        """Keep Play in step with Steam's downloads while the page is open."""
        self._download_timer = 0
        if self.game.props.non_steam:
            return  # Steam does not download non-Steam games.
        self._check_download()
        self._download_timer = GLib.timeout_add_seconds(2, self._check_download)

    def _check_download(self):
        config, appid = self.window.config, self.game.props.appid
        auth.run_async(
            lambda: (downloads.state_for(config, appid), downloads.current_rate(config)), self._show_download
        )
        return GLib.SOURCE_CONTINUE

    def _show_download(self, result, error):
        if error or not result or not hasattr(self, "primary"):
            return
        item, rate = result
        if item is None:
            self.primary.set_label(self.primary_label)
            self.primary.set_sensitive(True)
            self.primary.set_tooltip_text(None)
            self.download_area.set_visible(False)
            return
        # Waiting updates have nothing in progress, so only the button changes for them.
        self.download_area.set_visible(item.status != "waiting")
        self.download_bar.set_fraction(item.fraction)
        self.download_text.set_label(describe(item, rate))
        self.primary.set_label(downloads.play_label(item, self.game.props.installed))
        busy = downloads.is_busy(item, self.game.props.installed)
        # Greyed out like Steam's own button while the game cannot start; a waiting
        # update is downloaded by Steam when the game is played.
        self.primary.set_sensitive(not busy)
        self.primary.set_tooltip_text("Steam is handling this; see the Downloads tab for details" if busy else None)

    def release(self):
        if getattr(self, "_download_timer", 0):
            GLib.source_remove(self._download_timer)
            self._download_timer = 0
        for handler in self._handlers:
            self.game.disconnect(handler)
        self._handlers = []
        if self.media:
            self.media.stop()

    ART_HINTS = {
        "cover": "Portrait, 600 × 900",
        "hero": "Wide banner, 3840 × 1240",
        "logo": "PNG with a transparent background",
        "header": "Landscape, 920 × 430",
    }
    ART_THUMB = {"cover": (40, 60), "hero": (96, 31), "logo": (96, 40), "header": (96, 45)}

    def _build_artwork(self):
        group = Adw.PreferencesGroup(
            title="Artwork",
            description=(
                "Custom images are saved where Steam keeps its own custom artwork, "
                "so Steam uses them too after it restarts."
            ),
        )
        self.art_rows = {}
        for kind, label in library.ART_LABELS.items():
            row = Adw.ActionRow(title=label)
            width, height = self.ART_THUMB[kind]
            thumb = Gtk.Picture(
                content_fit=Gtk.ContentFit.CONTAIN, can_shrink=True,
                width_request=width, height_request=height,
                halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER,
            )
            # A wide picture asks for more width the taller its row is; the clamp
            # caps every thumbnail at the same width so the row titles line up.
            slot = Adw.Clamp(
                child=thumb, maximum_size=96, tightening_threshold=96,
                width_request=96, valign=Gtk.Align.CENTER,
            )
            row.add_prefix(slot)
            choices = Gio.Menu()
            choices.append("Choose from SteamGridDB…", f"art.steamgriddb::{kind}")
            choices.append("Choose File…", f"art.file::{kind}")
            choose = Gtk.MenuButton(
                icon_name="document-open-symbolic", tooltip_text="Choose Image", menu_model=choices,
                valign=Gtk.Align.CENTER,
            )
            choose.add_css_class("flat")
            reset = Gtk.Button(icon_name="edit-undo-symbolic", tooltip_text="Use Steam's Image", valign=Gtk.Align.CENTER)
            reset.add_css_class("flat")
            reset.connect("clicked", lambda _b, k=kind: self._reset_art(k))
            row.add_suffix(reset)
            row.add_suffix(choose)
            group.add(row)
            self.art_rows[kind] = (row, thumb, reset)
            self._refresh_art_row(kind)

        actions = Gio.SimpleActionGroup()
        for name, handler in (
            ("steamgriddb", lambda k: self.window.open_artwork_picker(self.game, k)),
            ("file", self._choose_art),
        ):
            action = Gio.SimpleAction.new(name, GLib.VariantType.new("s"))
            action.connect("activate", lambda _a, value, h=handler: h(value.get_string()))
            actions.add_action(action)
        group.insert_action_group("art", actions)
        return group

    def refresh_artwork(self, kind):
        if kind in getattr(self, "art_rows", {}):
            self._refresh_art_row(kind)

    def _refresh_art_row(self, kind):
        row, thumb, reset = self.art_rows[kind]
        config = self.window.config
        custom = library.custom_art(config, self.game.props.appid, kind)
        path = self.game.get_property(kind)
        if custom:
            state = "Custom image"
        elif path:
            state = "Steam's image"
        else:
            state = "None"
        row.set_subtitle(f"{state} · {self.ART_HINTS[kind]}")
        reset.set_visible(custom is not None)
        thumb.set_paintable(None)
        # Loaded at the slot's size so the picture never asks for more width than the slot.
        images.load(path, 96, 60, thumb.set_paintable)

    def _choose_art(self, kind):
        choose_file(self.window, kind, lambda path: self.window.set_artwork(self.game, kind, path))

    def _reset_art(self, kind):
        config = self.window.config
        library.clear_custom_art(config, self.game.props.appid, kind)
        steam_image = library.find_art(config.root, config.userdata, self.game.props.appid)[kind]
        self._apply_art(kind, steam_image)
        if not steam_image and not self.game.props.installed:
            owned.ensure_art(self.game, kind)
        self.window.toast(f"{library.ART_LABELS[kind]} reset to Steam's image")

    def _apply_art(self, kind, path):
        images.forget(path)
        # Clear first so the library tile and hero reload even if the path is unchanged.
        self.game.set_property(kind, "")
        self.game.set_property(kind, path)
        self._refresh_art_row(kind)

    def _build_actions(self):
        box = Adw.WrapBox(child_spacing=12, line_spacing=12, halign=Gtk.Align.CENTER, align=0.5)
        self.actions_box = box
        self._fill_actions()
        return box

    def _fill_actions(self):
        box = self.actions_box
        while child := box.get_first_child():
            box.remove(child)
        game = self.game
        if game.props.installed:
            primary = Gtk.Button(label="Update and Play" if game.props.update_available else "Play")
            primary.connect("clicked", self._on_play)
        else:
            primary = Gtk.Button(label="Install")
            primary.connect("clicked", self._on_install)
        primary.add_css_class("suggested-action")
        primary.add_css_class("pill")
        box.append(primary)
        self.primary = primary
        self.primary_label = primary.get_label()
        manager = mod_managers.linked(game.props.appid)
        if manager is not None:
            box.append(self._pill(
                "superlion-mod-manager-symbolic", "Launch Mod Manager", lambda: self.window.launch_mod_manager(manager),
                tooltip=f"Open {manager.name}",
            ))

        more = Gtk.MenuButton(icon_name="view-more-symbolic", tooltip_text="More", valign=Gtk.Align.CENTER)
        more.add_css_class("circular")
        more.set_create_popup_func(self._fill_menu)
        box.append(more)

    def _fill_menu(self, button):
        # Rebuilt each time, so check marks and Sunshine match the game's current state.
        menu, actions = game_menu(self.window, self.game, page=self)
        # On the button, as groups added to the page do not reach through the ToolbarView's ScrolledWindow.
        button.insert_action_group("game", actions)
        button.set_menu_model(menu)

    @staticmethod
    def _pill(icon, label, callback, tooltip=None):
        button = Gtk.Button(child=Adw.ButtonContent(icon_name=icon, label=label), tooltip_text=tooltip)
        button.add_css_class("pill")
        button.connect("clicked", lambda *_: callback())
        return button

    def _build_info(self):
        game = self.game
        group = Adw.PreferencesGroup(title="Information")
        if game.props.non_steam:
            name_row = info_row("Name", game.props.name)
            rename = Gtk.Button(icon_name="document-edit-symbolic", tooltip_text="Rename", valign=Gtk.Align.CENTER)
            rename.add_css_class("flat")
            rename.connect("clicked", lambda *_: self.window.rename_game(game))
            name_row.add_suffix(rename)
            group.add(name_row)
            self._handlers.append(
                game.connect("notify::name", lambda *_: self._on_name_changed(name_row))
            )
            group.add(info_row("Type", "Non-Steam game"))
            group.add(self._build_match_row())
        if game.props.installed:
            if not game.props.non_steam:
                group.add(info_row("Install Size", GLib.format_size(game.props.size)))
            group.add(folder_row("Location", game.props.install_dir, self._open_folder))
            if game.props.library:
                group.add(info_row("Library", game.props.library))
            prefix = library.prefix_path(self.window.config, game)
            if prefix:
                group.add(folder_row("Compatibility Files", prefix, self._open_folder))
            else:
                group.add(info_row("Compatibility Files", "None. The game has not been run with Proton."))
        if game.props.release_date:
            group.add(info_row("Release Date", format_date(game.props.release_date)))
        if game.props.genres:
            group.add(info_row("Genres", ", ".join(game.props.genres)))
        if game.props.vr:
            group.add(info_row("VR Support", "VR only" if game.props.vr == 2 else "VR supported"))
        group.add(self._build_collections_row())
        if game.props.non_steam:
            manager_switch = Adw.SwitchRow(
                title="Mod Manager",
                subtitle="List this under Mod Managers instead of with your games",
                active=game.props.appid in mod_managers.shortcut_ids(),
            )
            manager_switch.connect(
                "notify::active", lambda row, _p: self.window.set_mod_manager_shortcut(game, row.get_active())
            )
            group.add(manager_switch)
        if not (game.props.non_steam and game.props.appid in mod_managers.shortcut_ids()):
            group.add(self._build_mod_manager_link())
        group.add(info_row("Last Played", format_last_played(game.props.last_played)))
        group.add(info_row("App ID", str(game.props.appid)))
        return group

    def _build_settings(self):
        appid = self.game.props.appid
        config = self.window.config
        queued = pending.get(appid)
        try:
            saved_options = steam_settings.read_launch_options(config, appid)
            saved_tool = steam_settings.read_compat_tool(config, appid)
            self.tools = steam_settings.list_compat_tools(config)
        except OSError:
            saved_options, saved_tool = "", ""
            self.tools = [steam_settings.CompatTool("", "Default (Steam Setting)")]
        self.loaded = {
            "launch_options": queued.get("launch_options", saved_options),
            "compat_tool": queued.get("compat_tool", saved_tool),
        }
        if self.loaded["compat_tool"] not in {t.name for t in self.tools}:
            # Keep a mapping Superlion does not recognise rather than discarding it.
            name = self.loaded["compat_tool"]
            self.tools.append(steam_settings.CompatTool(name, f"{name} (Not Found)"))

        self.settings_group = Adw.PreferencesGroup(title="Steam Settings")
        self._update_settings_description()

        self.launch_options = self.loaded["launch_options"]
        self.options_row = Adw.ActionRow(title="Launch Options", activatable=True, subtitle_lines=0)
        self.options_row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
        self.options_row.connect("activated", lambda *_: self._edit_launch_options())
        self.settings_group.add(self.options_row)
        self._show_launch_options()

        self.tool_row = Adw.ComboRow(
            title="Compatibility Tool",
            model=Gtk.StringList.new([t.label for t in self.tools]),
        )
        names = [t.name for t in self.tools]
        self.tool_row.set_selected(names.index(self.loaded["compat_tool"]))
        self.tool_row.connect("notify::selected", self._on_settings_edited)
        self.settings_group.add(self.tool_row)

        self.apply_row = Adw.ButtonRow(title="Apply", sensitive=False)
        self.apply_row.add_css_class("suggested-action")
        self.apply_row.connect("activated", self._on_apply)
        self.settings_group.add(self.apply_row)
        return self.settings_group

    def _build_warnings_note(self):
        self.warnings_label = Gtk.Label()
        content = Gtk.Box(spacing=6)
        content.append(Gtk.Image(icon_name="dialog-warning-symbolic"))
        content.append(self.warnings_label)
        self.warnings_note = Gtk.Button(child=content, halign=Gtk.Align.CENTER, visible=False)
        self.warnings_note.add_css_class("flat")
        self.warnings_note.add_css_class("warning")
        self.warnings_note.connect("clicked", lambda *_: self._edit_launch_options())
        return self.warnings_note

    def _show_warnings(self):
        ignored = lo.ignored_warnings().get(self.game.props.appid, set())
        found = [w for w in lo.warnings(self.launch_options) if w.id not in ignored]
        self.warnings_note.set_visible(bool(found))
        if found:
            count = len(found)
            self.warnings_label.set_label(f"{count} launch option warning{'s' if count != 1 else ''}")
            self.warnings_note.set_tooltip_text("\n".join(describe_warning(w) for w in found))

    def _show_launch_options(self):
        if self.launch_options:
            text = lo.summary(self.launch_options)
        else:
            text = "None. Choose to set them up, or to use a preset."
        self.options_row.set_subtitle(GLib.markup_escape_text(text))
        self.options_row.set_tooltip_text(self.launch_options or None)
        self._show_warnings()

    def _edit_launch_options(self):
        editor = LaunchOptionsEditor(
            self.window, self.launch_options, game_name=self.game.props.name, warnings_appid=self.game.props.appid
        )
        editor.connect("done", self._on_launch_options_chosen)
        editor.connect("closed", lambda *_: self._show_warnings())  # Warnings may have been ignored.
        editor.present(self.window)

    def _on_launch_options_chosen(self, _editor, options):
        # Shown here only; Apply saves it to Steam with any other change.
        self.launch_options = options
        self._show_launch_options()
        self._on_settings_edited()

    def _update_settings_description(self):
        if pending.get(self.game.props.appid):
            text = "Changes are waiting for Steam to close."
        else:
            text = "Stored by Steam. Changes are written while Steam is closed."
        self.settings_group.set_description(text)

    def _current_settings(self):
        return {
            "launch_options": self.launch_options.strip(),
            "compat_tool": self.tools[self.tool_row.get_selected()].name,
        }

    def _changed_settings(self):
        current = self._current_settings()
        return {k: v for k, v in current.items() if v != self.loaded[k]}

    def _on_settings_edited(self, *_):
        self.apply_row.set_sensitive(bool(self._changed_settings()))

    def _on_apply(self, _row):
        changes = self._changed_settings()
        if changes:
            self.window.apply_game_settings(self.game.props.appid, changes, self._mark_applied)

    def _mark_applied(self, changes):
        self.loaded.update(changes)
        self.apply_row.set_sensitive(False)
        self._update_settings_description()

    def _on_play(self, _button):
        self._open(self.game.run_uri, f"Launching {self.game.props.name}")

    def _on_install(self, _button):
        self.window.install_game(self.game.props.appid, self.game.props.name)

    def _open(self, uri, message):
        try:
            steam_control.open_uri(self.window.config, uri)
            self.window.toast(message)
        except GLib.Error as error:
            self.window.toast(f"Steam could not be opened: {error.message}")

    def _build_mod_manager_link(self):
        """Which mod manager the Launch Mod Manager button opens for this game."""
        managers = [m for m in mod_managers.all_managers() if m.id != f"shortcut:{self.game.props.appid}"]
        row = Adw.ComboRow(
            title="Linked Mod Manager",
            subtitle="Adds a Launch Mod Manager button" if managers else "Add mod managers under Mod Managers in the sidebar",
            model=Gtk.StringList.new(["None"] + [m.name for m in managers]),
            sensitive=bool(managers),
        )
        current = mod_managers.linked(self.game.props.appid)
        ids = [m.id for m in managers]
        if current is not None and current.id in ids:
            row.set_selected(ids.index(current.id) + 1)

        def changed(combo, _pspec):
            index = combo.get_selected()
            mod_managers.link(self.game.props.appid, ids[index - 1] if index > 0 else None)
            self._fill_actions()

        row.connect("notify::selected", changed)
        return row

    def _build_collections_row(self):
        self.collections_row = info_row("Collections", "")
        button = Gtk.MenuButton(
            icon_name="list-add-symbolic", tooltip_text="Add to Collection", valign=Gtk.Align.CENTER
        )
        button.add_css_class("flat")
        button.set_create_popup_func(
            lambda b: b.set_popover(collections_popover(self.window, self.game))
        )
        self.collections_row.add_suffix(button)
        self._update_collections_row()
        return self.collections_row

    def _update_collections_row(self):
        appid = self.game.props.appid
        names = [c.name for c in self.window.library.collections.values() if appid in c.appids]
        self.collections_row.set_subtitle(", ".join(names) if names else "None")

    def _open_folder(self, path):
        launcher = Gtk.FileLauncher(file=Gio.File.new_for_path(str(path)))
        launcher.launch(self.window, None, None)

    def _load_store_content(self):
        appid = self.game.props.store_appid
        region = self.window.store_region
        spinner = Adw.Spinner(height_request=48)
        self.store_box.append(spinner)

        def done(data, _error):
            self.store_box.remove(spinner)
            if not data:
                return  # No store page (for example, a delisted game); local details still show.
            self.media = MediaCarousel(data)
            if not self.media.is_empty:
                self.store_box.append(self.media)
            for widget in description_widgets(data):
                self.store_box.append(widget)

        def news_done(items, _error):
            if items:
                self.news_box.append(news_group(items, self.window.open_web))

        auth.run_async(lambda: store_api.details(appid, region), done)
        auth.run_async(lambda: store_api.news(appid), news_done)
