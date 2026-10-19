"""Adding programs chosen in Files to Steam as non-Steam games."""

import os

from gi.repository import Adw, GObject, Gtk

from .. import shortcuts, steam_settings


class AddShortcutDialog(Adw.Dialog):
    """Names each file and picks its compatibility tool; emits "add" with {app ID: changes}."""

    __gsignals__ = {"add": (GObject.SignalFlags.RUN_FIRST, None, (object,))}

    def __init__(self, window, paths):
        super().__init__(title="Add to Steam", content_width=560)
        self.window = window
        config = window.config
        try:
            self.tools = steam_settings.list_compat_tools(config)
        except OSError:
            self.tools = [steam_settings.CompatTool("", "Default (Steam Setting)")]
        self.items = []

        self.toasts = Adw.ToastOverlay()
        page = Adw.PreferencesPage()
        self.toasts.set_child(page)
        for path in paths:
            page.add(self._build_group(config, path))

        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda *_: self.close())
        self.add_button = Gtk.Button(label="Add")
        self.add_button.add_css_class("suggested-action")
        self.add_button.connect("clicked", lambda *_: self._on_add())
        header = Adw.HeaderBar(show_start_title_buttons=False, show_end_title_buttons=False)
        header.pack_start(cancel)
        header.pack_end(self.add_button)
        toolbar = Adw.ToolbarView(content=self.toasts, top_bar_style=Adw.ToolbarStyle.RAISED)
        toolbar.add_top_bar(header)
        self.set_child(toolbar)

    def _build_group(self, config, path):
        group = Adw.PreferencesGroup(title=os.path.basename(path), description=os.path.dirname(path))
        name = Adw.EntryRow(title="Name", text=shortcuts.default_name(path))
        name.connect("changed", lambda *_: self._update_add())
        group.add(name)
        tool = Adw.ComboRow(
            title="Compatibility Tool",
            model=Gtk.StringList.new([t.label for t in self.tools]),
        )
        group.add(tool)
        if not shortcuts.steam_can_read(config, path):
            group.add(self._build_access_row(os.path.dirname(path)))
        self.items.append((path, name, tool))
        return group

    def _build_access_row(self, folder):
        row = Adw.ActionRow(
            title="Steam Cannot See This Folder",
            subtitle="Flatpak Steam can only start programs in folders it has been given access to.",
        )
        row.add_prefix(Gtk.Image(icon_name="dialog-warning-symbolic"))
        button = Gtk.Button(label="Give Access", valign=Gtk.Align.CENTER)

        def grant(_button):
            error = shortcuts.grant_flatpak_access(folder)
            if error:
                self.toasts.add_toast(Adw.Toast(title=error))
                return
            row.set_title("Access Given")
            row.set_subtitle(f"Steam can read {folder} once it restarts.")
            button.set_visible(False)

        button.connect("clicked", grant)
        row.add_suffix(button)
        return row

    def _update_add(self):
        self.add_button.set_sensitive(all(name.get_text().strip() for _p, name, _t in self.items))

    def _on_add(self):
        changes = {}
        for path, name, tool in self.items:
            entry = shortcuts.entry(path, name.get_text().strip())
            item = {"shortcut": entry}
            if self.tools[tool.get_selected()].name:
                item["compat_tool"] = self.tools[tool.get_selected()].name
            changes[entry["appid"]] = item
        self.close()
        self.emit("add", changes)
