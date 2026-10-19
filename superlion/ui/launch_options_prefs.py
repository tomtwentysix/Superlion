"""The Launch Options page of Preferences: presets, global and custom settings, and games' launch options."""

from gi.repository import Adw, GLib, Gtk

from .. import appinfo, auth, game_names
from .. import launch_options as lo
from .. import launch_presets
from .add_launch_setting import AddLaunchSettingDialog
from .launch_options_editor import LaunchOptionsEditor, describe_warning, warning_row

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
        self.expanded = set()  # Games whose warnings are shown, kept open across refreshes.
        self.looked_up = set()  # App IDs whose names were asked of the store this time.
        self.open_categories = set()  # Global Settings categories kept open across refreshes.
        self.search_text = ""
        self.refresh()

    def refresh(self):
        for group in self.groups:
            self.remove(group)
        config = self.window.config
        self.configured = launch_presets.configured_games(config) if config else {}
        self.apps = appinfo.load(config.root) if config else {}
        self.unnamed = set()
        self.groups = [
            self._build_presets(), *self._build_warnings(), self._build_global(),
            self._build_settings(), *self._build_games(),
        ]
        for group in self.groups:
            self.add(group)
        if self.unnamed - self.looked_up:
            missing = self.unnamed - self.looked_up
            self.looked_up |= missing
            auth.run_async(lambda: game_names.look_up(sorted(missing)), lambda *_: self.refresh())

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
        editor.connect("closed", lambda *_: self.refresh())  # After saving, or ignoring warnings.
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
            title="Custom Settings",
            description="Your own settings, offered in the launch options editor for every game.",
        )
        group.set_header_suffix(self._header_button("Add Custom Setting", self._add_setting))
        added = sorted(
            lo.custom_settings().values(),
            key=lambda c: (lo.CATEGORIES.index(c.category) if c.category in lo.CATEGORIES else 99, c.title.casefold()),
        )
        if not added:
            group.add(Adw.ActionRow(title="No Custom Settings"))
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

    def _build_warnings(self):
        """The Warnings group, and one for games that are not installed."""
        group = Adw.PreferencesGroup(
            title="Warnings",
            description="Settings in your games' launch options that are not needed on this computer, or cause problems.",
        )
        elsewhere = Adw.PreferencesGroup(
            title="Not Installed", description="Warnings in launch options kept for games that are not installed.",
        )
        ignored = lo.ignored_warnings()
        entries = []
        for appid, options in self.configured.items():
            found = lo.warnings(options)
            if found:
                entries.append((self._game_name(appid), appid, options, found))
        if not any(self._installed(e[1]) for e in entries):
            group.add(Adw.ActionRow(title="No Warnings"))
        elsewhere.set_visible(not all(self._installed(e[1]) for e in entries))
        for name, appid, options, found in sorted(entries, key=lambda e: e[0].casefold()):
            game_ignored = ignored.get(appid, set())
            count = sum(w.id not in game_ignored for w in found)
            parts = [f"{count} warning{'s' if count != 1 else ''}"]
            if len(found) > count:
                parts.append(f"{len(found) - count} ignored")
            expander = Adw.ExpanderRow(
                title=GLib.markup_escape_text(name), subtitle=" · ".join(parts), expanded=appid in self.expanded,
            )
            expander.connect("notify::expanded", lambda r, _p, a=appid: self._remember_expanded(a, r.get_expanded()))
            for warning in found:
                expander.add_row(warning_row(
                    lo.setting_for(*warning.key).title, warning, warning.id in game_ignored,
                    lambda a=appid, o=options, w=warning: self._fix(a, o, w),
                    lambda ignore, a=appid, w=warning: (lo.set_ignored(a, w, ignore), self.refresh()),
                ))
            edit = Adw.ButtonRow(title="Edit Launch Options…")
            edit.connect("activated", lambda *_, a=appid, n=name, o=options: self._edit_game(a, n, o))
            expander.add_row(edit)
            (group if self._installed(appid) else elsewhere).add(expander)
        return group, elsewhere

    def _remember_expanded(self, appid, expanded):
        if expanded:
            self.expanded.add(appid)
        else:
            self.expanded.discard(appid)

    def _fix(self, appid, options, warning):
        changes = {"launch_options": lo.fix(options, warning)}
        self.window.apply_game_settings(appid, changes, lambda *_: self.refresh(), parent=self.dialog)

    def _build_global(self):
        group = Adw.PreferencesGroup(
            title="Global Settings",
            description="Turn a setting on or off for all your installed games at once.",
        )
        search = Gtk.SearchEntry(placeholder_text="Search settings", text=self.search_text, margin_bottom=12)
        group.add(search)
        problems = {}  # {(kind, key): [(app ID, launch options, warning)]}
        for appid, options in self.configured.items():
            for warning in lo.warnings(options):
                problems.setdefault(warning.key, []).append((appid, options, warning))
        ignored = lo.ignored_warnings()
        settings = lo.baseline(self.configured.values()).values()
        vendors = lo.graphics_vendors()
        searchable = []  # (expander, [(row, text to search)])
        for category in lo.CATEGORIES:
            members = sorted(
                (s for s in settings if s.category == category), key=lambda s: (-s.games, s.title.casefold()),
            )
            used = sum(1 for s in members if s.games)
            # Settings for a make of graphics card this PC does not have, unless a game uses them.
            if not members or (category in ("NVIDIA", "AMD") and vendors and category not in vendors and not used):
                continue
            expander = Adw.ExpanderRow(
                title=category, subtitle=f"{used} in use" if used else "None in use",
                expanded=category in self.open_categories,
            )
            expander.connect("notify::expanded", lambda r, _p, c=category: self._remember_category(c, r.get_expanded()))
            entries = []
            for setting in members:
                row = self._global_row(setting, problems.get((setting.kind, setting.key), []), ignored)
                expander.add_row(row)
                text = " ".join((setting.title, setting.key, setting.description, category)).casefold()
                entries.append((row, text))
            group.add(expander)
            searchable.append((expander, entries))

        def on_search(entry):
            self.search_text = entry.get_text()
            words = self.search_text.casefold().split()
            for expander, entries in searchable:
                shown = 0
                for row, text in entries:
                    row.set_visible(all(word in text for word in words))
                    shown += row.get_visible()
                expander.set_visible(bool(shown))
                if words:
                    expander.set_expanded(True)

        search.connect("search-changed", on_search)
        if self.search_text:
            on_search(search)
        return group

    def _remember_category(self, category, expanded):
        if self.search_text:
            return  # Searching opens every category with a match.
        if expanded:
            self.open_categories.add(category)
        else:
            self.open_categories.discard(category)

    def _global_row(self, setting, problems, ignored):
        """A setting's row, with any warnings about it across games and a menu for all games."""
        parts = [setting.key if setting.kind == lo.ENV and setting.title != setting.key else "",
                 f"Used in {setting.games} game{'s' if setting.games != 1 else ''}" if setting.games
                 else "Not used in your games yet"]
        active = [p for p in problems if p[2].id not in ignored.get(p[0], set())]
        if active:
            parts.insert(0, describe_warning(active[0][2]))
        skipped = len({p[0] for p in problems}) - len({p[0] for p in active})
        if skipped:
            parts.append(f"Ignored in {skipped} game{'s' if skipped != 1 else ''}")
        row = Adw.ActionRow(
            title=GLib.markup_escape_text(setting.title),
            subtitle=GLib.markup_escape_text(" · ".join(p for p in parts if p)),
        )
        if active:
            icon = Gtk.Image(icon_name="dialog-warning-symbolic", tooltip_text=describe_warning(active[0][2]))
            icon.add_css_class("warning")
            row.add_prefix(icon)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        popover = Gtk.Popover(child=box)
        popover.add_css_class("menu")
        actions = [("Turn On for All Games", lambda: self._confirm_all(setting, True)),
                   ("Turn Off for All Games", lambda: self._confirm_all(setting, False))]
        if active:
            fix = lo.fix_label(active[0][2])
            label = {"Remove": "Remove From All Games", "Rename": "Rename in All Games"}.get(fix, f"{fix} in All Games")
            actions.append((label, lambda: self._confirm_fix(setting, fix, active)))
        for label, callback in actions:
            button = Gtk.Button(child=Gtk.Label(label=label, xalign=0))
            button.add_css_class("flat")
            button.connect("clicked", lambda _b, c=callback: (popover.popdown(), c()))
            box.append(button)
        menu = Gtk.MenuButton(icon_name="view-more-symbolic", popover=popover, valign=Gtk.Align.CENTER,
                              tooltip_text="All Games")
        menu.add_css_class("flat")
        row.add_suffix(menu)
        return row

    def _confirm_fix(self, setting, fix, problems):
        """Apply each game's own fix for its warnings about the setting, in the games not ignoring them."""
        changes = {}
        for appid, options, warning in problems:
            current = changes.get(appid, {}).get("launch_options", options)
            changes[appid] = {"launch_options": lo.fix(current, warning)}
        count = f"{len(changes)} game{'s' if len(changes) != 1 else ''}"
        alert = Adw.AlertDialog(
            heading=f"{fix} “{setting.title}” in {count.title()}?",
            body=f"The launch options of {count} are changed as each game's warning suggests.",
        )
        alert.add_response("cancel", "Cancel")
        alert.add_response("apply", fix)
        alert.set_response_appearance("apply", Adw.ResponseAppearance.SUGGESTED)
        alert.set_close_response("cancel")
        alert.connect(
            "response",
            lambda _a, response: response == "apply"
            and self.window.apply_settings(changes, self.refresh, parent=self.dialog),
        )
        alert.present(self.dialog)

    def _confirm_all(self, setting, on):
        value = setting.common_value
        games = {g.props.appid for g in self.window.installed} | set(self.configured)
        changes = {}
        for appid in games:
            options = self.configured.get(appid, "")
            updated = lo.with_setting(options, setting.kind, setting.key, value, on)
            if updated != options:
                changes[appid] = {"launch_options": updated}
        if not changes:
            self.window.toast(f"“{setting.title}” is already {'on' if on else 'off'} for all your games")
            return
        written = f"{setting.key}={lo.quote(value)}" if setting.kind == lo.ENV else " ".join(
            p for p in (setting.key, value) if p
        )
        count = f"{len(changes)} game{'s' if len(changes) != 1 else ''}"
        alert = Adw.AlertDialog(
            heading=f"Turn {'On' if on else 'Off'} “{setting.title}” for All Games?",
            body=f"{written} will be {'added to' if on else 'removed from'} the launch options of {count}.",
        )
        alert.add_response("cancel", "Cancel")
        alert.add_response("apply", f"Turn {'On' if on else 'Off'}")
        alert.set_response_appearance("apply", Adw.ResponseAppearance.SUGGESTED)
        alert.set_close_response("cancel")
        alert.connect(
            "response",
            lambda _a, response: response == "apply"
            and self.window.apply_settings(changes, self.refresh, parent=self.dialog),
        )
        alert.present(self.dialog)

    def _add_setting(self):
        config = self.window.config
        present = lo.baseline(launch_presets.configured_games(config).values() if config else []).keys()
        dialog = AddLaunchSettingDialog(present, for_game=False)
        dialog.connect("added", lambda *_: self.refresh())
        dialog.present(self.dialog)

    def _build_games(self):
        """The Your Games group, and one for games that are not installed."""
        group = Adw.PreferencesGroup(
            title="Your Games",
            description="Launch options set for your games. Choose one to change it, or to save it as a preset.",
        )
        elsewhere = Adw.PreferencesGroup(
            title="Not Installed", description="Launch options Steam keeps for games that are not installed.",
        )
        entries = sorted(
            ((appid, self._game_name(appid), options) for appid, options in self.configured.items()),
            key=lambda entry: entry[1].casefold(),
        )
        if not any(self._installed(e[0]) for e in entries):
            group.add(Adw.ActionRow(title="No games have launch options set."))
        elsewhere.set_visible(not all(self._installed(e[0]) for e in entries))
        for appid, name, options in entries:
            row = _options_row(name, options, lambda a=appid, n=name, o=options: self._edit_game(a, n, o))
            existing = launch_presets.find_by_options(options)
            if existing:
                saved = Gtk.Image(icon_name="object-select-symbolic", tooltip_text=f"Saved as preset “{existing.name}”")
                saved.add_css_class("dim-label")
                row.add_suffix(saved)
            else:
                row.add_suffix(_icon_button(
                    "media-floppy-symbolic", "Save as Preset", lambda n=name, o=options: self._new_preset(o, n)
                ))
            _go_next(row)
            (group if self._installed(appid) else elsewhere).add(row)
        return group, elsewhere

    def _edit_game(self, appid, name, options):
        self._open_editor(LaunchOptionsEditor(self.window, options, game_name=name, appid=appid))

    def _installed(self, appid):
        game = self.window.find_game(appid)
        return bool(game and game.props.installed)

    def _game_name(self, appid):
        game = self.window.find_game(appid)
        if game:
            return game.props.name
        name = game_names.known(self.apps, appid)
        if name is None:
            self.unnamed.add(appid)
        return game_names.display_name(name, appid)
