"""Building launch options by switching settings on and off instead of typing them."""

from gi.repository import Adw, GLib, GObject, Gtk, Pango

from .. import launch_options as lo
from .. import launch_presets
from .add_launch_setting import AddLaunchSettingDialog


def _usage(setting):
    if setting.games == 0:
        return "Not used in your games yet"
    return f"Used in {setting.games} game{'s' if setting.games != 1 else ''}"


class LaunchOptionsBuilder(Adw.Dialog):
    """Settings from all the user's games, switched on to match the given launch options.

    Emits "chosen" with the launch options when Use is pressed.
    """

    __gsignals__ = {"chosen": (GObject.SignalFlags.RUN_FIRST, None, (str,))}

    def __init__(self, window, options, game_name=""):
        super().__init__(title="Build Launch Options", content_width=680, content_height=780)
        config = window.config
        others = launch_presets.configured_games(config).values() if config else []
        self.settings = lo.baseline(others)
        self.state = {}  # (kind, key) -> {"enabled": bool, "value": str}

        current = lo.parse(options, lo.custom_programs())
        # Variables the game already has keep their order; new ones follow.
        self.order = {name: i for i, (name, _value) in enumerate(current.env)}
        for kind, items in (
            (lo.ENV, current.env),
            (lo.WRAPPER, current.wrappers.items()),
            (lo.ARGUMENT, [(a, "") for a in current.arguments]),
        ):
            for key, value in items:
                self.settings.setdefault((kind, key), lo.setting_for(kind, key))
                self.state[(kind, key)] = {"enabled": True, "value": value}
        for key, setting in self.settings.items():
            self.state.setdefault(key, {"enabled": False, "value": setting.common_value})

        self.preview = Gtk.Label(
            wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR, selectable=True, xalign=0,
            margin_start=18, margin_end=18, margin_top=6, margin_bottom=12,
        )
        self.preview.add_css_class("monospace")
        preview_title = Gtk.Label(
            label=f"Launch options for {game_name}" if game_name else "Launch options",
            xalign=0, margin_start=18, margin_end=18, margin_top=6,
        )
        preview_title.add_css_class("heading")
        preview_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        preview_box.append(preview_title)
        preview_box.append(self.preview)

        self.page = Adw.PreferencesPage()
        self.category_groups = []
        self.own_group = self._build_own(current)
        self._fill_page()

        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda *_: self.close())
        use = Gtk.Button(label="Use")
        use.add_css_class("suggested-action")
        use.connect("clicked", self._on_use)
        add = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="Add Setting")
        add.connect("clicked", lambda *_: self._open_add())
        header = Adw.HeaderBar(show_start_title_buttons=False, show_end_title_buttons=False)
        header.pack_start(cancel)
        header.pack_end(use)
        header.pack_end(add)

        toolbar = Adw.ToolbarView(content=self.page, top_bar_style=Adw.ToolbarStyle.RAISED)
        toolbar.add_top_bar(header)
        toolbar.add_top_bar(preview_box)
        self.set_child(toolbar)
        self._update_preview()

    # Rows ------------------------------------------------------------------

    def _fill_page(self):
        """(Re)build the setting rows, keeping Your Own and its text at the end."""
        for group in self.category_groups:
            self.page.remove(group)
        if self.own_group.get_parent():
            self.page.remove(self.own_group)
        self.category_groups = [g for g in map(self._build_category, lo.CATEGORIES) if g]
        for group in self.category_groups:
            self.page.add(group)
        self.page.add(self.own_group)

    def _build_category(self, category):
        settings = [s for s in self.settings.values() if s.category == category]
        if not settings:
            return None
        settings.sort(key=lambda s: (-s.games, s.title.casefold()))
        descriptions = {
            "Tools": "Programs that start the game.",
            "Game Arguments": "Passed to the game itself, after %command%.",
        }
        group = Adw.PreferencesGroup(title=category, description=descriptions.get(category))
        for setting in settings:
            group.add(self._build_row(setting))
        return group

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
            row.connect("notify::active", lambda r, _p: self._set(key, enabled=r.get_active()))
            self._add_remove_button(row, setting)
            return row

        row = Adw.ExpanderRow(
            title=title, subtitle=self._subtitle(setting), show_enable_switch=True,
            enable_expansion=state["enabled"], expanded=False,
        )
        row.connect("notify::enable-expansion", lambda r, _p: self._set(key, enabled=r.get_enable_expansion()))
        entry = Adw.EntryRow(title="Options" if setting.kind == lo.WRAPPER else "Value", text=state["value"])
        entry.connect("changed", lambda e: self._set(key, value=e.get_text().strip()))
        values = [v for v, _n in setting.values.most_common()]
        if len(values) > 1 or (values and values[0] != state["value"]):
            entry.add_suffix(self._values_button(entry, values))
        row.add_row(entry)
        self._add_remove_button(row, setting)
        return row

    def _add_remove_button(self, row, setting):
        if not setting.custom:
            return
        button = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text="Remove from Builder", valign=Gtk.Align.CENTER)
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

    def _build_own(self, current):
        group = Adw.PreferencesGroup(
            title="Your Own",
            description=(
                "Anything else, typed as it would appear in Steam's launch options. To switch "
                "a setting on and off here for every game, add it with Add Setting."
            ),
        )
        add = Gtk.Button(child=Adw.ButtonContent(icon_name="list-add-symbolic", label="Add Setting"),
                         valign=Gtk.Align.CENTER)
        add.add_css_class("flat")
        add.connect("clicked", lambda *_: self._open_add())
        group.set_header_suffix(add)
        self.extra_env = Adw.EntryRow(title="Extra Variables, such as NAME=value")
        self.extra_commands = Adw.EntryRow(title="Other Commands Before %command%", text=" ".join(current.other))
        self.extra_arguments = Adw.EntryRow(title="Extra Game Arguments")
        for row in (self.extra_env, self.extra_commands, self.extra_arguments):
            row.connect("changed", lambda *_: self._update_preview())
            group.add(row)
        return group

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
        self.state[key] = {"enabled": True, "value": setting.common_value}
        self._fill_page()
        self._update_preview()

    def _remove(self, setting):
        key = (setting.kind, setting.key)
        lo.remove_custom(*key)
        if setting.games or self.state[key]["enabled"]:
            # Still used, so it stays, described as Superlion would without the user's entry.
            replacement = lo.setting_for(*key, custom={})
            replacement.values, replacement.games = setting.values, setting.games
            self.settings[key] = replacement
        else:
            del self.settings[key]
            del self.state[key]
        self._fill_page()
        self._update_preview()

    # State -----------------------------------------------------------------

    def _set(self, key, enabled=None, value=None):
        if enabled is not None:
            self.state[key]["enabled"] = enabled
        if value is not None:
            self.state[key]["value"] = value
        self._update_preview()

    def options(self):
        env, wrappers, arguments = [], {}, []
        for category in lo.CATEGORIES:
            settings = sorted(
                (s for s in self.settings.values() if s.category == category),
                key=lambda s: (-s.games, s.title.casefold()),
            )
            for setting in settings:
                state = self.state[(setting.kind, setting.key)]
                if not state["enabled"]:
                    continue
                if setting.kind == lo.ENV:
                    env.append((setting.key, state["value"]))
                elif setting.kind == lo.WRAPPER:
                    wrappers[setting.key] = state["value"]
                else:
                    arguments.append(setting.key)
        env.sort(key=lambda item: self.order.get(item[0], len(self.order)))
        # Typed variables are read like launch options so their quotes are kept.
        for word in lo.tokenize(self.extra_env.get_text()):
            match = lo.VARIABLE.match(word)
            if match:
                env.append((match.group(1), match.group(2)))
        other = lo.tokenize(self.extra_commands.get_text())
        arguments += lo.tokenize(self.extra_arguments.get_text())
        return lo.compose(env, wrappers, other, arguments)

    def _update_preview(self):
        options = self.options()
        self.preview.set_label(options or "None. The game starts normally.")

    def _on_use(self, _button):
        self.emit("chosen", self.options())
        self.close()
