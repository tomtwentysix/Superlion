"""Managing launch option presets, and making them from games' existing launch options."""

from gi.repository import Adw, GLib, GObject, Gtk, Pango

from .. import launch_presets


def edit_preset(parent, heading, confirm, name, options, callback):
    """Ask for a preset's name and launch options; callback(name, options) when confirmed."""
    dialog = Adw.AlertDialog(heading=heading)
    name_row = Adw.EntryRow(title="Name", text=name, activates_default=True)
    options_row = Adw.EntryRow(title="Launch Options", text=options, activates_default=True)
    rows = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
    rows.add_css_class("boxed-list")
    rows.append(name_row)
    rows.append(options_row)
    dialog.set_extra_child(rows)
    dialog.add_response("cancel", "Cancel")
    dialog.add_response("confirm", confirm)
    dialog.set_response_appearance("confirm", Adw.ResponseAppearance.SUGGESTED)
    dialog.set_default_response("confirm")
    dialog.set_close_response("cancel")

    def update(*_):
        dialog.set_response_enabled(
            "confirm", bool(name_row.get_text().strip() and options_row.get_text().strip())
        )

    name_row.connect("changed", update)
    options_row.connect("changed", update)
    update()

    def on_response(_dialog, response):
        if response == "confirm":
            callback(name_row.get_text().strip(), options_row.get_text().strip())

    dialog.connect("response", on_response)
    dialog.present(parent)
    dialog.set_focus(name_row)
    return dialog


def save_as_preset(parent, options, game_name, on_saved=None):
    """Offer to save launch options as a new preset, with a suggested name."""
    existing = launch_presets.find_by_options(options)
    if existing:
        if hasattr(parent, "toast"):
            parent.toast(f"These launch options are already saved as “{existing.name}”")
        return

    def save(name, new_options):
        preset = launch_presets.add(name, new_options)
        if on_saved:
            on_saved(preset)

    name = launch_presets.unique_name(launch_presets.suggest_name(options, game_name))
    edit_preset(parent, "Save as Preset", "Save", name, options, save)


class LaunchPresetsDialog(Adw.Dialog):
    """Lists presets for editing, and games whose launch options can become presets."""

    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self, window):
        super().__init__(title="Launch Option Presets", content_width=640, content_height=680)
        self.window = window
        self.page = Adw.PreferencesPage()
        toolbar = Adw.ToolbarView(content=self.page)
        toolbar.add_top_bar(Adw.HeaderBar())
        self.set_child(toolbar)
        self.groups = []
        self._refresh()

    def _refresh(self):
        for group in self.groups:
            self.page.remove(group)
        self.groups = [self._build_presets(), self._build_games()]
        for group in self.groups:
            self.page.add(group)

    def _changed(self, *_):
        self._refresh()
        self.emit("changed")

    def _build_presets(self):
        group = Adw.PreferencesGroup(
            title="Presets",
            description="Choose a preset from the menu beside a game's launch options to use it.",
        )
        add = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="New Preset", valign=Gtk.Align.CENTER)
        add.add_css_class("flat")
        add.connect("clicked", lambda *_: edit_preset(
            self, "New Preset", "Create", "", "",
            lambda name, options: self._changed(launch_presets.add(name, options)),
        ))
        group.set_header_suffix(add)

        presets = launch_presets.all_presets()
        if not presets:
            group.add(Adw.ActionRow(
                title="No Presets",
                subtitle="Create one with the + button, or save a game's launch options below.",
            ))
        for preset in presets:
            row = Adw.ActionRow(
                title=GLib.markup_escape_text(preset.name),
                subtitle=GLib.markup_escape_text(preset.options),
                subtitle_lines=2,
            )
            row.add_css_class("property")
            edit = Gtk.Button(icon_name="document-edit-symbolic", tooltip_text="Edit", valign=Gtk.Align.CENTER)
            edit.add_css_class("flat")
            edit.connect("clicked", lambda *_, p=preset: edit_preset(
                self, "Edit Preset", "Save", p.name, p.options,
                lambda name, options, pid=p.id: self._changed(launch_presets.update(pid, name, options)),
            ))
            delete = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text="Delete", valign=Gtk.Align.CENTER)
            delete.add_css_class("flat")
            delete.connect("clicked", lambda *_, p=preset: self._confirm_delete(p))
            row.add_suffix(edit)
            row.add_suffix(delete)
            group.add(row)
        return group

    def _confirm_delete(self, preset):
        dialog = Adw.AlertDialog(
            heading="Delete Preset?",
            body=f"“{preset.name}” will be deleted. Games already using its launch options keep them.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("delete", "Delete")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_close_response("cancel")
        dialog.connect(
            "response",
            lambda _d, response: response == "delete" and self._changed(launch_presets.remove(preset.id)),
        )
        dialog.present(self)

    def _build_games(self):
        group = Adw.PreferencesGroup(
            title="From Your Games",
            description="Launch options already set for your games. Save any of them as a preset.",
        )
        config = self.window.config
        configured = launch_presets.configured_games(config) if config else {}
        entries = sorted(
            ((self._game_name(appid), options) for appid, options in configured.items()),
            key=lambda entry: entry[0].casefold(),
        )
        if not entries:
            group.add(Adw.ActionRow(title="No games have launch options set."))
        for name, options in entries:
            row = Adw.ActionRow(
                title=GLib.markup_escape_text(name),
                subtitle=GLib.markup_escape_text(options),
                subtitle_lines=2,
            )
            row.add_css_class("property")
            existing = launch_presets.find_by_options(options)
            if existing:
                saved = Gtk.Label(label=f"Saved as “{existing.name}”", valign=Gtk.Align.CENTER, ellipsize=Pango.EllipsizeMode.END,
                                  max_width_chars=18)
                saved.add_css_class("dim-label")
                row.add_suffix(saved)
            else:
                button = Gtk.Button(label="Save as Preset", valign=Gtk.Align.CENTER)
                button.connect("clicked", lambda *_, n=name, o=options: save_as_preset(self, o, n, self._changed))
                row.add_suffix(button)
            group.add(row)
        return group

    def _game_name(self, appid):
        game = self.window.find_game(appid)
        return game.props.name if game else f"App {appid}"
