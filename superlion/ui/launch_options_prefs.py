"""The Launch Options page of Preferences: presets, added settings, and games' launch options."""

from gi.repository import Adw, GLib, Gtk, Pango

from .. import launch_options as lo
from .. import launch_presets
from .add_launch_setting import AddLaunchSettingDialog
from .launch_options_editor import LaunchOptionsEditor

PAGE_NAME = "launch-options"


def _options_row(title, options):
    row = Adw.ActionRow(
        title=GLib.markup_escape_text(title),
        subtitle=GLib.markup_escape_text(options),
        subtitle_lines=2,
    )
    row.add_css_class("property")
    return row


def _icon_button(icon, tooltip, callback):
    button = Gtk.Button(icon_name=icon, tooltip_text=tooltip, valign=Gtk.Align.CENTER)
    button.add_css_class("flat")
    button.connect("clicked", lambda *_: callback())
    return button


class LaunchOptionsPage(Adw.PreferencesPage):
    def __init__(self, dialog, window):
        super().__init__(title="Launch Options", icon_name="utilities-terminal-symbolic", name=PAGE_NAME)
        self.dialog = dialog
        self.window = window
        self.groups = []
        self.refresh()

    def refresh(self):
        for group in self.groups:
            self.remove(group)
        self.groups = [self._build_presets(), self._build_settings(), self._build_games()]
        for group in self.groups:
            self.add(group)

    # Presets ---------------------------------------------------------------

    def _build_presets(self):
        group = Adw.PreferencesGroup(
            title="Presets",
            description="Launch options to reuse. Choose one from Use a Preset when editing a game's launch options.",
        )
        group.set_header_suffix(self._header_button("New Preset", self._new_preset))
        presets = launch_presets.all_presets()
        if not presets:
            group.add(Adw.ActionRow(
                title="No Presets",
                subtitle="Create one, or save a game's launch options as a preset below.",
            ))
        for preset in presets:
            row = _options_row(preset.name, preset.options)
            row.add_suffix(_icon_button("document-edit-symbolic", "Edit", lambda p=preset: self._edit_preset(p)))
            row.add_suffix(_icon_button("user-trash-symbolic", "Delete", lambda p=preset: self._confirm_delete(p)))
            group.add(row)
        return group

    def _header_button(self, label, callback):
        button = Gtk.Button(child=Adw.ButtonContent(icon_name="list-add-symbolic", label=label),
                            valign=Gtk.Align.CENTER)
        button.add_css_class("flat")
        button.connect("clicked", lambda *_: callback())
        return button

    def _open_editor(self, editor):
        editor.connect("done", lambda *_: self.refresh())
        editor.present(self.dialog)

    def _new_preset(self, options="", game_name=""):
        self._open_editor(LaunchOptionsEditor(self.window, options, game_name=game_name, new_preset=True))

    def _edit_preset(self, preset):
        self._open_editor(LaunchOptionsEditor(self.window, preset.options, preset=preset))

    def _confirm_delete(self, preset):
        alert = Adw.AlertDialog(
            heading="Delete Preset?",
            body=f"“{preset.name}” will be deleted. Games already using its launch options keep them.",
        )
        alert.add_response("cancel", "Cancel")
        alert.add_response("delete", "Delete")
        alert.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        alert.set_close_response("cancel")

        def on_response(_alert, response):
            if response == "delete":
                launch_presets.remove(preset.id)
                self.refresh()

        alert.connect("response", on_response)
        alert.present(self.dialog)

    # Settings added to the editor --------------------------------------------

    def _build_settings(self):
        group = Adw.PreferencesGroup(
            title="Added Settings",
            description=(
                "Settings you added to the launch options editor. They are offered for every game, "
                "alongside those found in your games' launch options."
            ),
        )
        group.set_header_suffix(self._header_button("Add Setting", self._add_setting))
        added = sorted(
            lo.custom_settings().values(),
            key=lambda c: (lo.CATEGORIES.index(c.category) if c.category in lo.CATEGORIES else 99, c.title.casefold()),
        )
        if not added:
            group.add(Adw.ActionRow(title="No Added Settings"))
        for custom in added:
            written = custom.key if custom.kind != lo.ENV else f"{custom.key}={custom.default}"
            row = Adw.ActionRow(
                title=GLib.markup_escape_text(custom.title),
                subtitle=GLib.markup_escape_text(" · ".join(p for p in (custom.category, written, custom.description) if p)),
            )
            row.add_suffix(_icon_button(
                "user-trash-symbolic", "Remove", lambda c=custom: (lo.remove_custom(c.kind, c.key), self.refresh())
            ))
            group.add(row)
        return group

    def _add_setting(self):
        config = self.window.config
        present = lo.baseline(launch_presets.configured_games(config).values() if config else []).keys()
        dialog = AddLaunchSettingDialog(present, for_game=False)
        dialog.connect("added", lambda *_: self.refresh())
        dialog.present(self.dialog)

    # Games' launch options ---------------------------------------------------

    def _build_games(self):
        group = Adw.PreferencesGroup(
            title="Your Games",
            description="Launch options set for your games. Any of them can be saved as a preset.",
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
            row = _options_row(name, options)
            existing = launch_presets.find_by_options(options)
            if existing:
                saved = Gtk.Label(label=f"Saved as “{existing.name}”", valign=Gtk.Align.CENTER,
                                  ellipsize=Pango.EllipsizeMode.END, max_width_chars=18)
                saved.add_css_class("dim-label")
                row.add_suffix(saved)
            else:
                button = Gtk.Button(label="Save as Preset", valign=Gtk.Align.CENTER)
                button.connect("clicked", lambda *_, n=name, o=options: self._new_preset(o, n))
                row.add_suffix(button)
            group.add(row)
        return group

    def _game_name(self, appid):
        game = self.window.find_game(appid)
        return game.props.name if game else f"App {appid}"
