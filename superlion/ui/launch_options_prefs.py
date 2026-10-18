"""The Launch Options page of Preferences: presets, added settings, and games' launch options."""

from gi.repository import Adw, GLib, Gtk

from .. import launch_options as lo
from .. import launch_presets
from .add_launch_setting import AddLaunchSettingDialog
from .launch_options_editor import LaunchOptionsEditor

PAGE_NAME = "launch-options"


def _options_row(title, options, on_activate):
    """A row naming the settings in some launch options in full; it opens them in the editor."""
    row = Adw.ActionRow(
        title=GLib.markup_escape_text(title),
        subtitle=GLib.markup_escape_text(lo.summary(options)),
        subtitle_lines=0,
        activatable=True,
        tooltip_text=options,
    )
    row.connect("activated", lambda *_: on_activate())
    return row


def _go_next(row):
    row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))


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
            row = _options_row(preset.name, preset.options, lambda p=preset: self._edit_preset(p))
            row.add_suffix(_icon_button("user-trash-symbolic", "Delete", lambda p=preset: self._confirm_delete(p)))
            _go_next(row)
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

    def _build_games(self):
        group = Adw.PreferencesGroup(
            title="Your Games",
            description="Launch options set for your games. Choose one to change it, or to save it as a preset.",
        )
        config = self.window.config
        configured = launch_presets.configured_games(config) if config else {}
        entries = sorted(
            ((appid, self._game_name(appid), options) for appid, options in configured.items()),
            key=lambda entry: entry[1].casefold(),
        )
        if not entries:
            group.add(Adw.ActionRow(title="No games have launch options set."))
        for appid, name, options in entries:
            row = _options_row(name, options, lambda a=appid, n=name, o=options: self._edit_game(a, n, o))
            existing = launch_presets.find_by_options(options)
            if existing:
                saved = Gtk.Image(icon_name="emblem-ok-symbolic", tooltip_text=f"Saved as preset “{existing.name}”")
                saved.add_css_class("dim-label")
                row.add_suffix(saved)
            else:
                row.add_suffix(_icon_button(
                    "media-floppy-symbolic", "Save as Preset", lambda n=name, o=options: self._new_preset(o, n)
                ))
            _go_next(row)
            group.add(row)
        return group

    def _edit_game(self, appid, name, options):
        self._open_editor(LaunchOptionsEditor(self.window, options, game_name=name, appid=appid))

    def _game_name(self, appid):
        game = self.window.find_game(appid)
        return game.props.name if game else f"App {appid}"
