"""Choosing an installed Linux application to use as a mod manager."""

from gi.repository import Adw, GLib, GObject, Gtk

from .. import mod_managers


class AppChooser(Adw.Dialog):
    """Lists installed applications; emits "chosen" with the desktop ID and display name."""

    __gsignals__ = {"chosen": (GObject.SignalFlags.RUN_FIRST, None, (str, str))}

    def __init__(self):
        super().__init__(title="Add Mod Manager", content_width=480, content_height=600)
        self.search = Gtk.SearchEntry(placeholder_text="Search applications", hexpand=True)
        self.search.connect("search-changed", lambda *_: self.list.invalidate_filter())

        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.list.add_css_class("boxed-list")
        self.list.set_filter_func(self._filter)
        self.rows = []
        for app in mod_managers.installed_apps():
            row = Adw.ActionRow(
                title=GLib.markup_escape_text(app.get_display_name()),
                subtitle=GLib.markup_escape_text(app.get_description() or ""),
                activatable=True,
            )
            icon = Gtk.Image(pixel_size=32)
            if app.get_icon() is not None:
                icon.set_from_gicon(app.get_icon())
            row.add_prefix(icon)
            row.app = app
            row.connect("activated", self._on_activated)
            self.list.append(row)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=6, margin_bottom=18,
                      margin_start=18, margin_end=18)
        hint = Gtk.Label(
            label="Choose the application you use to manage mods, such as a mod manager installed from Flathub.",
            wrap=True, xalign=0,
        )
        hint.add_css_class("dim-label")
        box.append(hint)
        box.append(self.search)
        box.append(Gtk.ScrolledWindow(child=self.list, vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER))
        toolbar = Adw.ToolbarView(content=box)
        toolbar.add_top_bar(Adw.HeaderBar())
        self.set_child(toolbar)
        self.set_focus(self.search)

    def _filter(self, row):
        text = self.search.get_text().strip().casefold()
        return not text or text in row.app.get_display_name().casefold()

    def _on_activated(self, row):
        self.emit("chosen", row.app.get_id(), row.app.get_display_name())
        self.close()
