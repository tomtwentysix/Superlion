"""First-launch setup wizard."""

import copy
from pathlib import Path

from gi.repository import Adw, Gio, GObject, Gtk

from .. import auth, sgdb, steam_paths
from .sgdb_setup import SgdbKeySetup
from .steam_key_setup import SteamKeySetup

OTHER = "\0other"
AUTO_REGION = "auto"
AUTO_REGION_LABEL = "Automatic"

REGIONS = {
    "AU": "Australia",
    "BR": "Brazil",
    "CA": "Canada",
    "DE": "Germany",
    "ES": "Spain",
    "FR": "France",
    "GB": "United Kingdom",
    "IE": "Ireland",
    "IN": "India",
    "IT": "Italy",
    "JP": "Japan",
    "NL": "Netherlands",
    "NZ": "New Zealand",
    "PL": "Poland",
    "SE": "Sweden",
    "US": "United States",
}


def short_path(path):
    home = str(Path.home())
    text = str(path)
    return "~" + text[len(home):] if text.startswith(home + "/") else text


class Choice(GObject.Object):
    """A drop-down of detected options that always ends with "Other…".

    Choosing "Other…" reveals a row for a manual value: a folder picker when
    kind is "folder", otherwise a text entry. validate(value) returns an error
    message, or None when the value is acceptable.
    """

    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self, group, title, options, kind, validate, selected=None, other_title=None):
        super().__init__()
        self.options = list(options)
        self.kind = kind
        self.validate = validate
        self.other_value = ""

        labels = [label for label, _value in self.options] + ["Other…"]
        self.combo = Adw.ComboRow(title=title, model=Gtk.StringList.new(labels))
        group.add(self.combo)

        if kind == "folder":
            self.other_row = Adw.ActionRow(title=other_title or "Folder", subtitle="None chosen")
            button = Gtk.Button(label="Choose…", valign=Gtk.Align.CENTER)
            button.connect("clicked", self._on_choose_folder)
            self.other_row.add_suffix(button)
        else:
            self.other_row = Adw.EntryRow(title=other_title or "Value")
            self.other_row.connect("changed", self._on_entry_changed)
        group.add(self.other_row)

        self.error_label = Gtk.Label(xalign=0, wrap=True, margin_top=6, visible=False)
        self.error_label.add_css_class("error")
        self.error_label.add_css_class("caption")
        group.add(self.error_label)

        values = [value for _label, value in self.options]
        if selected is not None and selected not in values and selected != "":
            self.other_value = str(selected)
            if kind == "folder":
                self.other_row.set_subtitle(short_path(selected))
            else:
                self.other_row.set_text(str(selected))
            self.combo.set_selected(len(self.options))
        elif selected in values:
            self.combo.set_selected(values.index(selected))
        elif not self.options:
            self.combo.set_selected(0)  # Only "Other…" is available.

        self.combo.connect("notify::selected", lambda *_: self._refresh())
        self._refresh()

    @property
    def is_other(self):
        return self.combo.get_selected() >= len(self.options)

    @property
    def value(self):
        if self.is_other:
            return self.other_value
        return self.options[self.combo.get_selected()][1]

    @property
    def error(self):
        if self.is_other and not self.other_value:
            return "Enter a value or choose one of the detected options."
        return self.validate(self.value)

    def select_value(self, value):
        values = [v for _label, v in self.options]
        if value in values:
            self.combo.set_selected(values.index(value))

    def _on_choose_folder(self, _button):
        dialog = Gtk.FileDialog(title="Choose a Folder")
        if self.other_value:
            dialog.set_initial_folder(Gio.File.new_for_path(self.other_value))

        def done(dlg, result):
            try:
                folder = dlg.select_folder_finish(result)
            except Exception:  # Cancelled by the user.
                return
            self.other_value = folder.get_path()
            self.other_row.set_subtitle(short_path(self.other_value))
            self._refresh()

        dialog.select_folder(self.combo.get_root(), None, done)

    def _on_entry_changed(self, entry):
        self.other_value = entry.get_text().strip()
        self._refresh()

    def _refresh(self):
        # Long values are shortened in the row, so the full value is in the tooltip.
        selected = self.combo.get_selected_item()
        self.combo.set_tooltip_text(selected.get_string() if selected else None)
        self.other_row.set_visible(self.is_other)
        error = self.error if (not self.is_other or self.other_value) else None
        self.error_label.set_label(error or "")
        self.error_label.set_visible(bool(error))
        if self.kind != "folder":
            if error:
                self.other_row.add_css_class("error")
            else:
                self.other_row.remove_css_class("error")
        self.emit("changed")


# Setting builders shared with the Preferences window ------------------------


def install_choices(add_group, state):
    """Steam folder and Steam command choices; returns (folder, command)."""
    group = Adw.PreferencesGroup(
        title="Steam Installation",
        description="The Steam folder holds your settings, account data and artwork.",
    )
    add_group(group)
    folder = Choice(
        group,
        "Steam Folder",
        [
            (f"{'Flatpak' if i.kind == 'flatpak' else 'Native'}: {short_path(i.root)}", str(i.root))
            for i in steam_paths.find_installs()
        ],
        "folder",
        lambda v: None if steam_paths.is_steam_root(v) else "This folder does not contain a Steam installation.",
        selected=state.steam_root,
        other_title="Steam Folder",
    )
    command_group = Adw.PreferencesGroup(
        title="Steam Command", description="Used to start, close and restart Steam."
    )
    add_group(command_group)
    labels = {steam_paths.NATIVE_COMMAND: "Native Steam", steam_paths.FLATPAK_COMMAND: "Flatpak Steam"}
    command = Choice(
        command_group,
        "Command",
        [(f"{labels[c]} ({c})", c) for c in steam_paths.command_candidates()],
        "text",
        lambda v: None if steam_paths.is_valid_command(v) else "This command was not found.",
        selected=state.steam_command,
        other_title="Command",
    )

    def on_folder_changed(_choice):
        if not folder.error:
            kind = steam_paths.kind_for_root(folder.value)
            command.select_value(steam_paths.FLATPAK_COMMAND if kind == "flatpak" else steam_paths.NATIVE_COMMAND)

    folder.connect("changed", on_folder_changed)
    return folder, command


def apply_install(state, folder, command):
    if folder.value != state.steam_root:
        # A different installation has its own accounts and libraries.
        state.account_id = 0
        state.disabled_libraries = []
    state.steam_root = folder.value
    state.steam_command = command.value


def account_choice(add_group, state):
    root = state.steam_root
    group = Adw.PreferencesGroup(
        title="Steam Account", description="Launch options and play history are stored per account."
    )
    add_group(group)
    accounts = steam_paths.find_accounts(root)
    if not state.account_id and accounts:
        state.account_id = accounts[0].account_id

    def check_account(value):
        account_id = steam_paths.parse_account_id(str(value))
        if account_id is None:
            return "Enter a SteamID64 or an account ID (digits only)."
        if not steam_paths.userdata_dir(root, account_id).is_dir():
            return "This account has no data folder in the selected Steam installation."
        return None

    return Choice(
        group,
        "Account",
        [(a.label, str(a.account_id)) for a in accounts],
        "text",
        check_account,
        selected=str(state.account_id) if state.account_id else None,
        other_title="SteamID64 or Account ID",
    )


def region_choice(add_group, state):
    group = Adw.PreferencesGroup(
        title="Store Region",
        description=(
            "Sets the currency and prices shown in the store. Automatic uses your "
            "Steam account's country once you sign in, and the United Kingdom until then."
        ),
    )
    add_group(group)
    return Choice(
        group,
        "Region",
        [(AUTO_REGION_LABEL, AUTO_REGION)] + [(f"{REGIONS[c]} ({c})", c) for c in sorted(REGIONS, key=REGIONS.get)],
        "text",
        lambda v: None if v == AUTO_REGION or (len(v) == 2 and v.isalpha()) else "Enter a two-letter country code, such as GB.",
        selected=AUTO_REGION if state.region_auto else state.region,
        other_title="Country Code",
    )


def apply_account(state, account, region):
    if account is not None:
        state.account_id = steam_paths.parse_account_id(str(account.value))
    state.region_auto = region.value == AUTO_REGION
    if not state.region_auto:
        state.region = region.value.upper()


def library_groups(add_group, state, get_parent):
    """Library folder switches and extra folders; returns collect(state) to read them back."""
    group = Adw.PreferencesGroup(
        title="Library Folders", description="Games in folders that are turned off are hidden."
    )
    add_group(group)
    switches = {}
    for folder, count in steam_paths.find_libraries(state.steam_root):
        row = Adw.SwitchRow(
            title=short_path(folder),
            subtitle=f"{count} installed item{'s' if count != 1 else ''}",
            active=str(folder) not in state.disabled_libraries,
        )
        switches[str(folder)] = row
        group.add(row)

    extra_group = Adw.PreferencesGroup(
        title="Other Folders", description="Library folders that Steam does not list, such as an old drive."
    )
    add_group(extra_group)
    extras = list(state.extra_libraries)
    error_label = Gtk.Label(xalign=0, wrap=True, margin_top=6, visible=False)
    error_label.add_css_class("error")
    error_label.add_css_class("caption")
    rows = {}

    def add_extra_row(path):
        row = Adw.ActionRow(title=short_path(path), subtitle=f"{steam_paths.count_manifests(path)} installed items")
        remove = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text="Remove", valign=Gtk.Align.CENTER)
        remove.add_css_class("flat")

        def on_remove(*_):
            extras.remove(path)
            extra_group.remove(rows.pop(path))

        remove.connect("clicked", on_remove)
        row.add_suffix(remove)
        rows[path] = row
        extra_group.add(row)

    add_button = Adw.ButtonRow(title="Add Other Folder…", start_icon_name="list-add-symbolic")
    extra_group.add(add_button)
    extra_group.add(error_label)
    for path in extras:
        add_extra_row(path)

    def on_add(*_):
        dialog = Gtk.FileDialog(title="Choose a Library Folder")

        def done(dlg, result):
            try:
                path = dlg.select_folder_finish(result).get_path()
            except Exception:  # Cancelled by the user.
                return
            if not steam_paths.is_library_folder(path):
                error_label.set_label("This folder is not a Steam library: it has no steamapps folder.")
                error_label.set_visible(True)
                return
            error_label.set_visible(False)
            if path not in extras and path not in switches:
                extras.append(path)
                add_extra_row(path)

        dialog.select_folder(get_parent(), None, done)

    add_button.connect("activated", on_add)

    def collect(target):
        target.disabled_libraries = [p for p, row in switches.items() if not row.get_active()]
        target.extra_libraries = list(extras)

    return collect


class WizardPage(Adw.NavigationPage):
    def __init__(self, title, next_label="Next"):
        super().__init__(title=title)
        self.header = Adw.HeaderBar()
        self.next_button = Gtk.Button(label=next_label)
        self.next_button.add_css_class("suggested-action")
        self.header.pack_end(self.next_button)
        self.prefs = Adw.PreferencesPage()
        toolbar = Adw.ToolbarView(content=self.prefs)
        toolbar.add_top_bar(self.header)
        self.set_child(toolbar)

    def set_valid(self, valid):
        self.next_button.set_sensitive(valid)


class SetupWizard(Adw.Dialog):
    """Collects a Config; emits "finished" with the result in self.result."""

    __gsignals__ = {"finished": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self, start_config, window, first_run=False):
        super().__init__(title="Setup", content_width=600, content_height=680)
        self.state = copy.deepcopy(start_config)
        self.result = None
        self.first_run = first_run
        self.window = window
        self.set_can_close(not first_run)

        self.nav = Adw.NavigationView()
        self.set_child(self.nav)
        self.nav.add(self._welcome_page())

    def _push(self, builder):
        page = builder()
        if self.first_run:
            # Setup must be completed on first launch, so no close button is offered.
            page.header.set_show_end_title_buttons(False)
        self.nav.push(page)

    # Pages -----------------------------------------------------------------

    def _welcome_page(self):
        page = WizardPage("Welcome")
        page.header.set_show_end_title_buttons(not self.first_run)
        status = Adw.StatusPage(
            icon_name="applications-games-symbolic",
            title="Welcome to Superlion",
            description=(
                "Superlion shows your Steam library using Steam's own files on this computer. "
                "Your Steam installation, account and libraries have been detected "
                "automatically. The next pages let you confirm or change them."
            ),
        )
        page.prefs.add(self._status_group(status))
        page.next_button.connect("clicked", lambda *_: self._push(self._install_page))
        return page

    def _install_page(self):
        page = WizardPage("Steam Installation")
        folder, command = install_choices(page.prefs.add, self.state)

        def validate(*_):
            page.set_valid(not folder.error and not command.error)

        folder.connect("changed", validate)
        command.connect("changed", validate)
        validate()

        def next_page(*_):
            apply_install(self.state, folder, command)
            self._push(self._account_page)

        page.next_button.connect("clicked", next_page)
        return page

    def _account_page(self):
        page = WizardPage("Steam Account")
        account = account_choice(page.prefs.add, self.state)
        region = region_choice(page.prefs.add, self.state)

        def validate(*_):
            page.set_valid(not account.error and not region.error)

        account.connect("changed", validate)
        region.connect("changed", validate)
        validate()

        def next_page(*_):
            apply_account(self.state, account, region)
            self._push(self._libraries_page)

        page.next_button.connect("clicked", next_page)
        return page

    def _libraries_page(self):
        page = WizardPage("Libraries")
        collect = library_groups(page.prefs.add, self.state, self.get_root)

        def next_page(*_):
            collect(self.state)
            self._push(self._sign_in_page)

        page.next_button.connect("clicked", next_page)
        return page

    def _sign_in_page(self):
        page = WizardPage("Steam Account")
        setup = SteamKeySetup(self.window)
        setup.set_margin_top(12)
        setup.set_margin_bottom(24)
        clamp = Adw.Clamp(child=setup, maximum_size=520, margin_start=12, margin_end=12)
        page.prefs.add(self._status_group(clamp))

        def show_state(*_):
            # Optional: "Skip" until a key is saved.
            page.next_button.set_label("Next" if auth.load_key() else "Skip")

        setup.connect("saved", lambda *_: (self.window._on_connected(), show_state()))
        show_state()

        def next_page(*_):
            self.state.sign_in_skipped = not auth.load_key()
            self._push(self._artwork_page)

        page.next_button.connect("clicked", next_page)
        return page

    def _artwork_page(self):
        page = WizardPage("Artwork")
        setup = SgdbKeySetup(self.window)
        setup.set_margin_top(12)
        setup.set_margin_bottom(24)
        clamp = Adw.Clamp(child=setup, maximum_size=520, margin_start=12, margin_end=12)
        page.prefs.add(self._status_group(clamp))

        def show_state(*_):
            # Optional, like signing in: "Skip" until a working key is saved.
            page.next_button.set_label("Next" if sgdb.load_key() else "Skip")

        setup.connect("saved", show_state)
        show_state()
        page.next_button.connect("clicked", lambda *_: self._push(self._done_page))
        return page

    def _done_page(self):
        page = WizardPage("Ready", next_label="Start")
        status = Adw.StatusPage(
            icon_name="emblem-ok-symbolic",
            title="Setup Complete",
            description="You can change these settings later from Preferences in the main menu.",
        )
        page.prefs.add(self._status_group(status))

        group = Adw.PreferencesGroup(title="Summary")
        state = self.state
        accounts = {a.account_id: a.label for a in steam_paths.find_accounts(state.steam_root)}
        for title, value in [
            ("Steam Folder", short_path(state.steam_root)),
            ("Steam Command", state.steam_command),
            ("Account", accounts.get(state.account_id, str(state.account_id))),
            ("Store Region", AUTO_REGION_LABEL if state.region_auto
             else f"{REGIONS.get(state.region, state.region)} ({state.region})"),
            ("Library Folders", "\n".join(short_path(p) for p in state.library_folders()) or "None"),
        ]:
            row = Adw.ActionRow(title=title, subtitle=value)
            row.add_css_class("property")
            group.add(row)
        page.prefs.add(group)

        def finish(*_):
            self.result = self.state
            self.emit("finished")
            self.force_close()

        page.next_button.connect("clicked", finish)
        return page

    @staticmethod
    def _status_group(status):
        group = Adw.PreferencesGroup()
        group.add(status)
        return group
