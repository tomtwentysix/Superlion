"""Adding a setting to the launch options builder: a suggestion, or one of the user's own."""

from gi.repository import Adw, GLib, GObject, Gtk

from .. import launch_options as lo

KINDS = [
    (lo.ENV, "Environment Variable", "Variable Name", "Value"),
    (lo.WRAPPER, "Program", "Program", "Options"),
    (lo.ARGUMENT, "Game Argument", "Argument", ""),
]


class AddLaunchSettingDialog(Adw.Dialog):
    """Emits "added" with the new lo.Custom once it is saved."""

    __gsignals__ = {"added": (GObject.SignalFlags.RUN_FIRST, None, (object,))}

    def __init__(self, present):
        super().__init__(title="Add Setting", content_width=600, content_height=720)
        self.present_keys = set(present)
        self.add_button = Gtk.Button(label="Add", sensitive=False)
        self.add_button.add_css_class("suggested-action")
        self.add_button.connect("clicked", lambda *_: self._add_custom())

        page = Adw.PreferencesPage()
        page.add(self._build_custom())
        suggestions = self._build_suggestions()
        if suggestions:
            page.add(suggestions)

        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda *_: self.close())
        header = Adw.HeaderBar(show_start_title_buttons=False, show_end_title_buttons=False)
        header.pack_start(cancel)
        header.pack_end(self.add_button)
        toolbar = Adw.ToolbarView(content=page)
        toolbar.add_top_bar(header)
        self.set_child(toolbar)
        self.set_focus(self.key_row)

    # Your own --------------------------------------------------------------

    def _build_custom(self):
        group = Adw.PreferencesGroup(
            title="Your Own Setting",
            description="It is added to the builder for every game, and switched on for this one.",
        )
        self.kind_row = Adw.ComboRow(title="Type", model=Gtk.StringList.new([k[1] for k in KINDS]))
        self.key_row = Adw.EntryRow()
        self.value_row = Adw.EntryRow()
        self.title_row = Adw.EntryRow(title="Display Name (Optional)")
        self.category_row = Adw.ComboRow(title="Group", model=Gtk.StringList.new(lo.CATEGORIES))
        self.description_row = Adw.EntryRow(title="Description (Optional)")
        self.status = Gtk.Label(xalign=0, wrap=True, visible=False, margin_top=6)
        self.status.add_css_class("error")
        self.status.add_css_class("caption")
        for row in (self.kind_row, self.key_row, self.value_row, self.title_row, self.category_row,
                    self.description_row):
            group.add(row)
        group.add(self.status)

        self.kind_row.connect("notify::selected", lambda *_: self._on_kind_changed())
        self.key_row.connect("changed", lambda *_: self._validate())
        self.key_row.connect("entry-activated", lambda *_: self._add_custom())
        self._on_kind_changed()
        return group

    @property
    def kind(self):
        return KINDS[self.kind_row.get_selected()][0]

    def _on_kind_changed(self):
        _kind, _label, key_title, value_title = KINDS[self.kind_row.get_selected()]
        self.key_row.set_title(key_title)
        self.value_row.set_title(f"{value_title} (Optional)" if self.kind == lo.WRAPPER else value_title)
        self.value_row.set_visible(bool(value_title))
        if self.kind == lo.ENV and not self.value_row.get_text():
            self.value_row.set_text("1")
        elif self.kind == lo.WRAPPER and self.value_row.get_text() == "1":
            self.value_row.set_text("")
        self.category_row.set_selected(lo.CATEGORIES.index(lo.default_category(self.kind)))
        self._validate()

    def _validate(self):
        key = self.key_row.get_text().strip()
        error = ""
        if key and not lo.is_valid_key(self.kind, key):
            error = {
                lo.ENV: "A variable name uses only letters, numbers and underscores, and does not start with a number.",
                lo.WRAPPER: "A program name has no spaces. Put its options in Options.",
                lo.ARGUMENT: "An argument cannot contain %command%.",
            }[self.kind]
        elif (self.kind, key) in self.present_keys:
            error = "This setting is already in the builder."
        self.status.set_label(error)
        self.status.set_visible(bool(error))
        self.add_button.set_sensitive(bool(key) and not error)

    def _add_custom(self):
        if not self.add_button.get_sensitive():
            return
        kind, key = self.kind, self.key_row.get_text().strip()
        custom = lo.Custom(
            kind=kind,
            key=key,
            title=self.title_row.get_text().strip() or key,
            category=lo.CATEGORIES[self.category_row.get_selected()],
            description=self.description_row.get_text().strip(),
            default=self.value_row.get_text().strip() if kind != lo.ARGUMENT else "",
        )
        self._finish(custom)

    # Suggestions -----------------------------------------------------------

    def _build_suggestions(self):
        settings = lo.suggestions(self.present_keys)
        if not settings:
            return None
        group = Adw.PreferencesGroup(
            title="Suggestions",
            description="Settings Superlion knows that are not in the builder yet.",
        )
        settings.sort(key=lambda s: (lo.CATEGORIES.index(s.category), s.title.casefold()))
        for setting in settings:
            row = Adw.ActionRow(
                title=GLib.markup_escape_text(setting.title),
                subtitle=GLib.markup_escape_text(" · ".join(p for p in (setting.key, setting.description) if p)),
                activatable=True,
            )
            button = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="Add", valign=Gtk.Align.CENTER)
            button.add_css_class("flat")
            row.add_suffix(button)
            row.set_activatable_widget(button)
            button.connect("clicked", lambda _b, s=setting: self._finish(lo.Custom(
                s.kind, s.key, s.title, s.category, s.description, s.default,
            )))
            group.add(row)
        return group

    def _finish(self, custom):
        lo.add_custom(custom)
        self.emit("added", custom)
        self.close()
