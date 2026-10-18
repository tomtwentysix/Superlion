"""The launch options editor, used for games and for presets.

The launch options are shown as text that can be typed into directly, above
every setting found across the user's games as a switch. Typing updates the
switches, and switching settings on and off rewrites the text, so either way
of working can be used at any time.
"""

from gi.repository import Adw, GLib, GObject, Gtk, Pango

from .. import launch_options as lo
from .. import launch_presets
from .add_launch_setting import AddLaunchSettingDialog

PARSE_DELAY = 300  # milliseconds after the last keystroke

CATEGORY_DESCRIPTIONS = {
    "Tools": "Programs that start the game.",
    "Game Arguments": "Passed to the game itself, after %command%.",
}


def _usage(setting):
    if setting.games == 0:
        return "Not used in your games yet"
    return f"Used in {setting.games} game{'s' if setting.games != 1 else ''}"


def ask_preset_name(parent, options, game_name, callback):
    """Ask for the name of a new preset, suggesting one; callback(name) when confirmed."""
    dialog = Adw.AlertDialog(heading="Save as Preset", body=options)
    entry = Gtk.Entry(
        text=launch_presets.unique_name(launch_presets.suggest_name(options, game_name)),
        activates_default=True,
    )
    dialog.set_extra_child(entry)
    dialog.add_response("cancel", "Cancel")
    dialog.add_response("save", "Save")
    dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
    dialog.set_default_response("save")
    dialog.set_close_response("cancel")
    entry.connect("changed", lambda e: dialog.set_response_enabled("save", bool(e.get_text().strip())))
    dialog.connect(
        "response",
        lambda _d, response: response == "save" and entry.get_text().strip() and callback(entry.get_text().strip()),
    )
    dialog.present(parent)
    dialog.set_focus(entry)
    entry.select_region(0, -1)


class LaunchOptionsEditor(Adw.Dialog):
    """Edits launch options for a game (game_name) or a preset (preset, or new_preset for a new one).

    For a game, emits "done" with the launch options when Done is pressed. For a
    preset, saves it and emits "done" with its launch options.
    """

    __gsignals__ = {"done": (GObject.SignalFlags.RUN_FIRST, None, (str,))}

    def __init__(self, window, options="", game_name="", preset=None, new_preset=False):
        self.window = window
        self.game_name = game_name
        self.preset = preset
        self.for_preset = preset is not None or new_preset
        if self.for_preset:
            title = f"Edit “{preset.name}”" if preset else "New Preset"
        else:
            title = "Launch Options"
        super().__init__(title=title, content_width=700, content_height=820)

        config = window.config
        self.settings = lo.baseline(launch_presets.configured_games(config).values() if config else [])
        self.programs = lo.custom_programs()
        self.state = {key: {"enabled": False, "value": s.common_value} for key, s in self.settings.items()}
        self.order = {}
        self.other = []
        self.rows = {}
        self._syncing = False
        self._parse_timer = 0

        self.toasts = Adw.ToastOverlay()
        self.page = Adw.PreferencesPage()
        self.category_groups = []
        self.top_group = self._build_top_group(options)
        self.toasts.set_child(self.page)

        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda *_: self.close())
        self.done_button = Gtk.Button(label="Save" if self.for_preset else "Done")
        self.done_button.add_css_class("suggested-action")
        self.done_button.connect("clicked", lambda *_: self._on_done())
        add = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="Add Setting")
        add.connect("clicked", lambda *_: self._open_add())
        header = Adw.HeaderBar(show_start_title_buttons=False, show_end_title_buttons=False)
        header.pack_start(cancel)
        header.pack_end(self.done_button)
        header.pack_end(add)

        toolbar = Adw.ToolbarView(content=self.toasts, top_bar_style=Adw.ToolbarStyle.RAISED)
        toolbar.add_top_bar(header)
        toolbar.add_top_bar(self._build_text_area(options))
        self.set_child(toolbar)

        self._read_text(options, rebuild=True)
        self.connect("closed", lambda *_: self._parse_timer and GLib.source_remove(self._parse_timer))

    # Text ------------------------------------------------------------------

    def _build_text_area(self, options):
        self.buffer = Gtk.TextBuffer(text=options)
        self.buffer.connect("changed", self._on_text_changed)
        view = Gtk.TextView(
            buffer=self.buffer, wrap_mode=Gtk.WrapMode.WORD_CHAR, monospace=True,
            top_margin=8, bottom_margin=8, left_margin=10, right_margin=10,
            accepts_tab=False,
        )
        view.update_property([Gtk.AccessibleProperty.LABEL], ["Launch options"])
        scroller = Gtk.ScrolledWindow(
            child=view, hscrollbar_policy=Gtk.PolicyType.NEVER,
            propagate_natural_height=True, min_content_height=48, max_content_height=140,
        )
        scroller.add_css_class("card")
        heading = Gtk.Label(
            label=f"Launch options for {self.game_name}" if self.game_name and not self.for_preset else "Launch options",
            xalign=0,
        )
        heading.add_css_class("heading")
        self.hint = Gtk.Label(xalign=0, wrap=True)
        self.hint.add_css_class("dim-label")
        self.hint.add_css_class("caption")
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=6,
            margin_start=18, margin_end=18, margin_top=6, margin_bottom=12,
        )
        box.append(heading)
        box.append(scroller)
        box.append(self.hint)
        clamp = Adw.Clamp(child=box, maximum_size=640)
        return clamp

    def text(self):
        return self.buffer.get_text(self.buffer.get_start_iter(), self.buffer.get_end_iter(), False).strip()

    def _set_text(self, options):
        self._syncing = True
        self.buffer.set_text(options)
        self._syncing = False
        self._update_hint()

    def _update_hint(self):
        text = self.text()
        if not text:
            self.hint.set_label("Empty: the game starts normally. Type here, or switch settings on below.")
        elif lo.COMMAND not in text:
            self.hint.set_label("Without %command%, Steam passes all of this to the game as arguments.")
        else:
            self.hint.set_label("Type here, or switch settings on below. Each changes the other.")
        if self.for_preset:
            self._validate_preset()

    def _on_text_changed(self, _buffer):
        if self._syncing:
            return
        self._update_hint()
        if self._parse_timer:
            GLib.source_remove(self._parse_timer)
        self._parse_timer = GLib.timeout_add(PARSE_DELAY, self._on_parse_timer)

    def _on_parse_timer(self):
        self._parse_timer = 0
        self._read_text(self.text())
        return GLib.SOURCE_REMOVE

    def _read_text(self, options, rebuild=False):
        """Switch settings on and off to match typed launch options."""
        parsed = lo.parse(options, self.programs)
        found = (
            [((lo.ENV, k), v) for k, v in parsed.env]
            + [((lo.WRAPPER, k), v) for k, v in parsed.wrappers.items()]
            + [((lo.ARGUMENT, a), "") for a in parsed.arguments]
        )
        for state in self.state.values():
            state["enabled"] = False
        for key, value in found:
            if key not in self.settings:
                self.settings[key] = lo.setting_for(*key)
                rebuild = True
            self.state[key] = {"enabled": True, "value": value or self.state.get(key, {}).get("value", "")}
            row = self.rows.get(key)
            if row and row[1] is None and value not in ("", "1"):
                rebuild = True  # A switch cannot show this value, so it needs a value row.
        # What was typed keeps its order when the text is next rewritten.
        self.order = {key: i for i, (key, _value) in enumerate(found)}
        self.other = parsed.other
        if rebuild:
            self._fill_page()
        else:
            self._refresh_rows()

    def _write_text(self):
        """Rewrite the text from the settings switched on."""
        env, wrappers, arguments = [], {}, []
        enabled = [s for s in self._ordered_settings() if self.state[(s.kind, s.key)]["enabled"]]
        enabled.sort(key=lambda s: self.order.get((s.kind, s.key), len(self.order)))
        for setting in enabled:
            value = self.state[(setting.kind, setting.key)]["value"]
            if setting.kind == lo.ENV:
                env.append((setting.key, value))
            elif setting.kind == lo.WRAPPER:
                wrappers[setting.key] = value
            else:
                arguments.append(setting.key)
        self._set_text(lo.compose(env, wrappers, self.other, arguments))

    # Rows ------------------------------------------------------------------

    def _ordered_settings(self):
        return sorted(
            self.settings.values(),
            key=lambda s: (lo.CATEGORIES.index(s.category), -s.games, s.title.casefold()),
        )

    def _fill_page(self):
        for group in [self.top_group, *self.category_groups]:
            if group.get_parent():
                self.page.remove(group)
        self.rows = {}
        self.page.add(self.top_group)
        self.category_groups = []
        for category in lo.CATEGORIES:
            settings = [s for s in self._ordered_settings() if s.category == category]
            if not settings:
                continue
            group = Adw.PreferencesGroup(title=category, description=CATEGORY_DESCRIPTIONS.get(category))
            for setting in settings:
                group.add(self._build_row(setting))
            self.category_groups.append(group)
        more = Adw.PreferencesGroup()
        add = Adw.ButtonRow(title="Add Setting…", start_icon_name="list-add-symbolic")
        add.connect("activated", lambda *_: self._open_add())
        more.add(add)
        self.category_groups.append(more)
        for group in self.category_groups:
            self.page.add(group)

    def _subtitle(self, setting):
        parts = [setting.description, _usage(setting)]
        if setting.kind == lo.ENV and setting.title != setting.key:
            parts.insert(0, setting.key)
        return GLib.markup_escape_text(" · ".join(p for p in parts if p))

    def _build_row(self, setting):
        key = (setting.kind, setting.key)
        state = self.state[key]
        title = GLib.markup_escape_text(setting.title)
        if not (setting.takes_value or (setting.kind == lo.ENV and state["value"] != "1")):
            row = Adw.SwitchRow(title=title, subtitle=self._subtitle(setting), active=state["enabled"])
            row.connect("notify::active", lambda r, _p: self._on_row_changed(key, enabled=r.get_active()))
            self._add_remove_button(row, setting)
            self.rows[key] = (row, None)
            return row

        row = Adw.ExpanderRow(
            title=title, subtitle=self._subtitle(setting), show_enable_switch=True,
            enable_expansion=state["enabled"], expanded=False,
        )
        row.connect(
            "notify::enable-expansion", lambda r, _p: self._on_row_changed(key, enabled=r.get_enable_expansion())
        )
        entry = Adw.EntryRow(title="Options" if setting.kind == lo.WRAPPER else "Value", text=state["value"])
        entry.connect("changed", lambda e: self._on_row_changed(key, value=e.get_text().strip()))
        values = [v for v, _n in setting.values.most_common()]
        if len(values) > 1 or (values and values[0] != state["value"]):
            entry.add_suffix(self._values_button(entry, values))
        row.add_row(entry)
        self._add_remove_button(row, setting)
        self.rows[key] = (row, entry)
        return row

    def _refresh_rows(self):
        self._syncing = True
        for key, (row, entry) in self.rows.items():
            state = self.state[key]
            if entry is None:
                row.set_active(state["enabled"])
            else:
                row.set_enable_expansion(state["enabled"])
                if entry.get_text() != state["value"]:
                    entry.set_text(state["value"])
        self._syncing = False

    def _on_row_changed(self, key, enabled=None, value=None):
        if self._syncing:
            return
        if enabled is not None:
            self.state[key]["enabled"] = enabled
        if value is not None:
            self.state[key]["value"] = value
        self._write_text()

    def _add_remove_button(self, row, setting):
        if not setting.custom:
            return
        button = Gtk.Button(
            icon_name="user-trash-symbolic", tooltip_text="Remove from Every Game's List", valign=Gtk.Align.CENTER
        )
        button.add_css_class("flat")
        button.connect("clicked", lambda *_: self._remove(setting))
        row.add_suffix(button)

    def _values_button(self, entry, values):
        """A menu of the values the user's games use, which fills the entry."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        popover = Gtk.Popover(child=box)
        popover.add_css_class("menu")
        heading = Gtk.Label(label="Used in Your Games", xalign=0, margin_start=12, margin_top=6, margin_bottom=6)
        heading.add_css_class("dim-label")
        heading.add_css_class("caption-heading")
        box.append(heading)
        for value in values:
            label = Gtk.Label(label=value, xalign=0, ellipsize=Pango.EllipsizeMode.MIDDLE, max_width_chars=48)
            label.add_css_class("monospace")
            button = Gtk.Button(child=label)
            button.add_css_class("flat")
            button.connect("clicked", lambda _b, v=value: (entry.set_text(v), popover.popdown()))
            box.append(button)
        button = Gtk.MenuButton(
            icon_name="pan-down-symbolic", tooltip_text="Values Used in Your Games",
            valign=Gtk.Align.CENTER, popover=popover,
        )
        button.add_css_class("flat")
        return button

    # Presets ---------------------------------------------------------------

    def _build_top_group(self, options):
        if self.for_preset:
            group = Adw.PreferencesGroup(title="Preset")
            self.name_row = Adw.EntryRow(
                title="Name",
                text=self.preset.name if self.preset else launch_presets.unique_name(
                    launch_presets.suggest_name(options, self.game_name or "New")
                ),
            )
            self.name_row.connect("changed", lambda *_: self._validate_preset())
            group.add(self.name_row)
            return group

        group = Adw.PreferencesGroup(
            title="Presets",
            description="Presets are managed in Preferences, under Launch Options.",
        )
        presets = launch_presets.all_presets()
        use = Adw.ActionRow(
            title="Use a Preset",
            subtitle="Replaces the launch options above" if presets else "No presets yet",
        )
        if presets:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            popover = Gtk.Popover(child=box)
            popover.add_css_class("menu")
            for preset in presets:
                button = Gtk.Button(child=Gtk.Label(label=preset.name, xalign=0))
                button.add_css_class("flat")
                button.set_tooltip_text(preset.options)
                button.connect("clicked", lambda _b, p=preset: (popover.popdown(), self._use_preset(p)))
                box.append(button)
            menu = Gtk.MenuButton(label="Choose", popover=popover, valign=Gtk.Align.CENTER)
            use.add_suffix(menu)
            use.set_activatable_widget(menu)
        group.add(use)
        save = Adw.ButtonRow(title="Save as Preset…", start_icon_name="document-save-symbolic")
        save.connect("activated", lambda *_: self._save_as_preset())
        group.add(save)
        return group

    def _use_preset(self, preset):
        self._set_text(preset.options)
        self._read_text(preset.options)
        self.toasts.add_toast(Adw.Toast(title=f"Using “{preset.name}”"))

    def _save_as_preset(self):
        options = self.text()
        if not options:
            self.toasts.add_toast(Adw.Toast(title="There are no launch options to save"))
            return
        existing = launch_presets.find_by_options(options)
        if existing:
            self.toasts.add_toast(Adw.Toast(title=f"Already saved as “{existing.name}”"))
            return

        def save(name):
            launch_presets.add(name, options)
            self.toasts.add_toast(Adw.Toast(title=f"Saved as “{name}”"))

        ask_preset_name(self, options, self.game_name, save)

    def _validate_preset(self):
        self.done_button.set_sensitive(bool(self.name_row.get_text().strip() and self.text()))

    # Adding and removing settings ------------------------------------------

    def _open_add(self):
        dialog = AddLaunchSettingDialog(self.settings.keys())
        dialog.connect("added", lambda _d, custom: self._on_added(custom))
        dialog.present(self)

    def _on_added(self, custom):
        key = (custom.kind, custom.key)
        setting = lo.setting_for(custom.kind, custom.key)
        old = self.settings.get(key)
        if old:  # Keep what the user's games already use.
            setting.values, setting.games = old.values, old.games
        self.settings[key] = setting
        self.programs = lo.custom_programs()
        self.state[key] = {"enabled": True, "value": setting.common_value}
        self._fill_page()
        self._write_text()

    def _remove(self, setting):
        key = (setting.kind, setting.key)
        lo.remove_custom(*key)
        self.programs = lo.custom_programs()
        if setting.games or self.state[key]["enabled"]:
            # Still used, so it stays, described as Superlion would without the user's entry.
            replacement = lo.setting_for(*key, custom={})
            replacement.values, replacement.games = setting.values, setting.games
            self.settings[key] = replacement
        else:
            del self.settings[key]
            del self.state[key]
        self._fill_page()

    # Finishing -------------------------------------------------------------

    def _on_done(self):
        options = self.text()
        if self.for_preset:
            name = self.name_row.get_text().strip()
            if not (name and options):
                return
            if self.preset:
                launch_presets.update(self.preset.id, name, options)
            else:
                launch_presets.add(name, options)
        self.emit("done", options)
        self.close()
