"""A library folder's games, selected and acted on together."""

import shutil
from pathlib import Path

from gi.repository import Adw, Gio, GLib, Gtk

from .. import game_collections, library, moving, steam_settings
from . import move_dialog
from .wizard import short_path


def _games(count):
    return f"{count} game{'s' if count != 1 else ''}"


class LibraryFolderPage(Adw.NavigationPage):
    def __init__(self, window, folder):
        super().__init__(title=short_path(folder))
        self.window = window
        self.folder = Path(folder)
        self.items = []  # (check button, Game, is a tool)
        self.groups = []
        self._handlers = []
        self._syncing = False

        header = Adw.HeaderBar()
        self.select_all = Gtk.ToggleButton(icon_name="edit-select-all-symbolic", tooltip_text="Select All")
        self.select_all.connect("toggled", self._on_select_all)
        header.pack_end(self.select_all)

        self.body = Adw.PreferencesPage()

        self.progress_area = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=6, visible=False,
            margin_top=6, margin_bottom=6, margin_start=12, margin_end=12,
        )
        self.progress_bar = Gtk.ProgressBar()
        self.progress_text = Gtk.Label(wrap=True, xalign=0)
        self.progress_text.add_css_class("caption")
        self.progress_text.add_css_class("dim-label")
        self.progress_area.append(self.progress_bar)
        self.progress_area.append(self.progress_text)

        self.action_bar = Gtk.ActionBar()
        self.selection_label = Gtk.Label()
        self.action_bar.pack_start(self.selection_label)
        self.menu_button = Gtk.MenuButton(icon_name="view-more-symbolic", tooltip_text="More Actions")
        self.action_bar.pack_end(self.menu_button)
        move = Gtk.Button(label="Move To…")
        move.connect("clicked", lambda *_: self._move())
        self.action_bar.pack_end(move)
        self.uninstall_button = Gtk.Button(label="Uninstall…")
        self.uninstall_button.add_css_class("destructive-action")
        self.action_bar.pack_end(self.uninstall_button)

        bottom = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        bottom.append(self.progress_area)
        bottom.append(self.action_bar)
        toolbar = Adw.ToolbarView(content=self.body)
        toolbar.add_top_bar(header)
        toolbar.add_bottom_bar(bottom)
        self.set_child(toolbar)

        actions = Gio.SimpleActionGroup()
        for name, callback in (("hide", self._hide), ("proton", self._choose_proton)):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda *_, c=callback: c())
            actions.add_action(action)
        collection = Gio.SimpleAction.new("collection", GLib.VariantType.new("s"))
        collection.connect("activate", lambda _a, cid: self._add_to_collection(cid.get_string()))
        actions.add_action(collection)
        self.insert_action_group("folder", actions)

        # Unhooked from the mover while unmapped, so a closed page is not kept alive by it.
        self.connect("map", lambda *_: self._watch() and self.refresh())
        self.connect("unmap", lambda *_: self._unwatch())
        self._watch()
        self.refresh()

    def _watch(self):
        if self._handlers:
            return False
        mover = self.window.mover
        self._handlers = [
            mover.connect("progress", self._on_progress),
            mover.connect("finished", lambda *_: self.refresh()),
            mover.connect("notify::busy", lambda *_: self._update()),
        ]
        return True

    def _unwatch(self):
        for handler in self._handlers:
            self.window.mover.disconnect(handler)
        self._handlers = []

    def refresh(self):
        for group in self.groups:
            self.body.remove(group)
        self.groups, self.items = [], []
        steamapps = self.folder / "steamapps"
        contents = sorted(moving.library_contents(self.folder), key=lambda e: e["name"].casefold())
        games = [e for e in contents if not e["tool"]]
        tools = [e for e in contents if e["tool"]]
        for title, entries in ((None, games), ("Tools", tools)):
            if not entries:
                continue
            group = Adw.PreferencesGroup(title=title)
            for entry in entries:
                game = library.Game(
                    appid=entry["appid"], name=entry["name"], installed=True, size=entry["size"],
                    install_dir=str(steamapps / "common" / entry["installdir"]), library=str(self.folder),
                )
                check = Gtk.CheckButton(valign=Gtk.Align.CENTER)
                check.connect("toggled", lambda *_: self._update())
                row = Adw.ActionRow(title=GLib.markup_escape_text(entry["name"]), activatable_widget=check)
                row.add_prefix(check)
                size = Gtk.Label(label=GLib.format_size(entry["size"]))
                size.add_css_class("dim-label")
                row.add_suffix(size)
                group.add(row)
                self.items.append((check, game, entry["tool"]))
            self.body.add(group)
            self.groups.append(group)

        try:
            free = f" · {GLib.format_size(shutil.disk_usage(steamapps).free)} free"
        except OSError:
            free = ""
        used = GLib.format_size(sum(e["size"] for e in contents))
        self.body.set_description(f"{_games(len(games))} · {used} used{free}")
        self.menu_button.set_menu_model(self._menu())
        self.progress_area.set_visible(False)
        self._update()

    def chosen(self):
        return [game for check, game, _tool in self.items if check.get_active()]

    def _update(self):
        chosen = self.chosen()
        if chosen:
            size = GLib.format_size(sum(game.props.size for game in chosen))
            self.selection_label.set_label(f"{len(chosen)} selected · {size}")
        else:
            self.selection_label.set_label("Nothing selected")
        self.action_bar.set_sensitive(bool(chosen) and not self.window.moving)
        games = [check for check, _game, tool in self.items if not tool]
        self._syncing = True
        self.select_all.set_active(bool(games) and all(check.get_active() for check in games))
        self._syncing = False

    def _on_select_all(self, button):
        if self._syncing:
            return
        active = button.get_active()
        for check, _game, tool in self.items:
            if not tool or not active:
                check.set_active(active)
        self._update()

    def _clear(self):
        for check, _game, _tool in self.items:
            check.set_active(False)

    def _on_progress(self, mover, label, done, total):
        self.progress_area.set_visible(True)
        self.progress_bar.set_fraction(done / total if total else 0)
        self.progress_text.set_label(move_dialog.progress_text(mover, label, done, total))

    def _menu(self):
        menu = Gio.Menu()
        collections = [c for c in self.window.library.collections.values() if not game_collections.is_fixed(c)]
        if collections:
            submenu = Gio.Menu()
            for collection in sorted(collections, key=lambda c: (c.source != "steam", c.name.casefold())):
                item = Gio.MenuItem.new(collection.name, None)
                item.set_action_and_target_value("folder.collection", GLib.Variant.new_string(collection.id))
                submenu.append_item(item)
            menu.append_submenu("Add to Collection", submenu)
        menu.append("Hide", "folder.hide")
        menu.append("Set Proton Version…", "folder.proton")
        return menu

    def _alert(self, heading, body):
        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.add_response("close", "Close")
        dialog.present(self)

    def _move(self):
        games = self.chosen()
        reasons = [(game.props.name, move_dialog.blocker(self.window, game)) for game in games]
        reasons = [(name, reason) for name, reason in reasons if reason]
        if reasons:
            if len(games) == 1:
                self._alert(f"{games[0].props.name} Cannot Be Moved", reasons[0][1])
            else:
                self._alert("Games Cannot Be Moved", "\n".join(f"{name}: {reason}" for name, reason in reasons))
            return

        def chosen(dest):
            self._clear()
            self.window.mover.start([move_dialog.steam_job(game, dest) for game in games], self, "Move")

        move_dialog.choose_library(self.window, games, chosen)

    def _hide(self):
        self.window.hide_games(self.chosen())
        self._clear()

    def _add_to_collection(self, collection_id):
        self.window.add_games_to_collection(self.chosen(), collection_id)
        self._clear()

    def _choose_proton(self):
        games = self.chosen()
        try:
            tools = steam_settings.list_compat_tools(self.window.config)
        except OSError:
            tools = [steam_settings.CompatTool("", "Default (Steam Setting)")]
        what = games[0].props.name if len(games) == 1 else _games(len(games))
        dialog = Adw.AlertDialog(
            heading="Set Proton Version", body=f"Choose the compatibility tool Steam uses for {what}.",
        )
        dropdown = Gtk.DropDown.new_from_strings([tool.label for tool in tools])
        dialog.set_extra_child(dropdown)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("set", "Set")
        dialog.set_response_appearance("set", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("set")
        dialog.set_close_response("cancel")

        def on_response(_dialog, response):
            if response != "set":
                return
            name = tools[dropdown.get_selected()].name
            self.window.apply_settings({game.props.appid: {"compat_tool": name} for game in games}, parent=self)
            self._clear()

        dialog.connect("response", on_response)
        dialog.present(self)
