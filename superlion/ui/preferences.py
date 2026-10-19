"""The Preferences window, used once setup has been completed."""

import copy

from gi.repository import Adw, Gtk

from .. import config as config_mod
from .. import sgdb, steam_paths
from .launch_options_prefs import LaunchOptionsPage
from .sgdb_setup import SgdbKeySetup
from .sunshine_status import StreamOptions, SunshineGroup
from .webview import clear_sign_in
from .wizard import (
    account_choice, apply_account, apply_install, install_choices, library_groups, region_choice,
)


class PreferencesDialog(Adw.PreferencesDialog):
    """Settings from the setup wizard, plus sign-ins, applied when the window closes."""

    def __init__(self, window):
        super().__init__(title="Preferences", search_enabled=False, content_width=760)
        self.window = window
        self.state = copy.deepcopy(window.config)

        steam = Adw.PreferencesPage(title="Steam", icon_name="applications-games-symbolic")
        self.folder, self.command = install_choices(steam.add, self.state)
        steam.add(self._build_client_group())
        self.account = account_choice(steam.add, self.state)
        self.collect_libraries = library_groups(steam.add, self.state, lambda: self)
        self.add(steam)

        streaming = Adw.PreferencesPage(title="Streaming", icon_name="tv-symbolic")
        streaming.add(SunshineGroup())
        streaming.add(StreamOptions(self.state, lambda text: self.add_toast(Adw.Toast(title=text))))
        self.add(streaming)

        accounts = Adw.PreferencesPage(title="Accounts", icon_name="system-users-symbolic")
        self.region = region_choice(accounts.add, self.state)
        self.sign_in_group = Adw.PreferencesGroup(title="Steam API")
        accounts.add(self.sign_in_group)
        accounts.add(self._build_store_group())
        self.sgdb_group = Adw.PreferencesGroup(title="SteamGridDB")
        accounts.add(self.sgdb_group)
        setup_group = Adw.PreferencesGroup(title="Setup")
        rerun = Adw.ButtonRow(title="Run Setup Wizard Again", start_icon_name="view-refresh-symbolic")
        rerun.connect("activated", lambda *_: self._run_wizard())
        setup_group.add(rerun)
        accounts.add(setup_group)
        self.add(accounts)
        self.add(LaunchOptionsPage(self, window))

        self._skip_apply = False
        self._sign_in_rows = []
        self._sgdb_rows = []
        self._show_sign_in()
        self._show_sgdb()
        self.connect("closed", lambda *_: self._apply())

    def _build_client_group(self):
        group = Adw.PreferencesGroup(title="Steam Client")
        row = Adw.SwitchRow(
            title="Start Steam With Superlion",
            subtitle="Keep Steam running in the background, so games stay updated and start faster",
            active=self.state.start_steam,
        )
        row.connect("notify::active", lambda r, _p: setattr(self.state, "start_steam", r.get_active()))
        group.add(row)
        return group

    def _show_sign_in(self):
        for row in self._sign_in_rows:
            self.sign_in_group.remove(row)
        rows = []
        if self.window.api_key:
            row = Adw.ActionRow(
                title="Connected",
                subtitle="Your Steam Web API key lists the games you own and sets store prices.",
            )
            change = Gtk.Button(label="Change Key…", valign=Gtk.Align.CENTER)
            change.connect("clicked", lambda *_: self._connect())
            disconnect = Gtk.Button(label="Disconnect", valign=Gtk.Align.CENTER)
            disconnect.add_css_class("destructive-action")
            disconnect.connect("clicked", lambda *_: (self.window.sign_out(), self._show_sign_in()))
            row.add_suffix(change)
            row.add_suffix(disconnect)
        else:
            row = Adw.ActionRow(
                title="Not Connected",
                subtitle="Connect to see games you own but have not installed, with prices in your currency.",
            )
            button = Gtk.Button(label="Connect…", valign=Gtk.Align.CENTER)
            button.add_css_class("suggested-action")
            button.connect("clicked", lambda *_: self._connect())
            row.add_suffix(button)
        rows.append(row)
        for row in rows:
            self.sign_in_group.add(row)
        self._sign_in_rows = rows

    def _build_store_group(self):
        group = Adw.PreferencesGroup(title="Steam Store")
        website = Adw.ActionRow(
            title="Store Sign-In",
            subtitle="Used for buying, the cart and the wishlist, and by the key page inside Superlion.",
        )
        sign_out = Gtk.Button(label="Sign Out", valign=Gtk.Align.CENTER)
        sign_out.connect("clicked", lambda *_: (clear_sign_in(), self.window.toast("Signed out of the Steam store")))
        website.add_suffix(sign_out)
        group.add(website)
        return group

    def _connect(self):
        dialog = self.window.sign_in(parent=self)
        dialog.connect("signed-in", lambda *_: self._show_sign_in())

    def _show_sgdb(self):
        for row in self._sgdb_rows:
            self.sgdb_group.remove(row)
        rows = []
        if sgdb.load_key():
            row = Adw.ActionRow(title="Connected", subtitle="Artwork can be chosen from SteamGridDB.")
            change = Gtk.Button(label="Change Key…", valign=Gtk.Align.CENTER)
            change.connect("clicked", lambda *_: self._open_key_setup())
            remove = Gtk.Button(label="Remove Key", valign=Gtk.Align.CENTER)
            remove.add_css_class("destructive-action")
            remove.connect("clicked", lambda *_: (sgdb.clear_key(), self._show_sgdb()))
            row.add_suffix(change)
            row.add_suffix(remove)
        else:
            row = Adw.ActionRow(
                title="Not Connected",
                subtitle="Connect a free SteamGridDB account to choose covers, backgrounds and logos.",
            )
            button = Gtk.Button(label="Set Up…", valign=Gtk.Align.CENTER)
            button.add_css_class("suggested-action")
            button.connect("clicked", lambda *_: self._open_key_setup())
            row.add_suffix(button)
        rows.append(row)
        for row in rows:
            self.sgdb_group.add(row)
        self._sgdb_rows = rows

    def _open_key_setup(self):
        page = Adw.NavigationPage(title="Connect SteamGridDB")
        setup = SgdbKeySetup(self.window)
        setup.connect("saved", lambda *_: (self._show_sgdb(), self.pop_subpage()))
        content = Adw.Clamp(child=setup, maximum_size=560, margin_top=12, margin_bottom=24,
                            margin_start=12, margin_end=12)
        toolbar = Adw.ToolbarView(content=Gtk.ScrolledWindow(child=content, hscrollbar_policy=Gtk.PolicyType.NEVER))
        toolbar.add_top_bar(Adw.HeaderBar())
        page.set_child(toolbar)
        self.push_subpage(page)

    def _apply(self):
        """Save valid changes once, when the window closes, so the library reloads only once."""
        if self._skip_apply:
            return
        if any(choice.error for choice in (self.folder, self.command, self.region)):
            self.window.toast("Some preferences were not valid, so they were not saved.")
            return
        folder_changed = self.folder.value != self.state.steam_root
        apply_install(self.state, self.folder, self.command)
        if folder_changed:
            # The account list shown belonged to the previous installation.
            accounts = steam_paths.find_accounts(self.state.steam_root)
            self.state.account_id = accounts[0].account_id if accounts else 0
            apply_account(self.state, None, self.region)
        else:
            if self.account.error:
                self.window.toast("The selected account is not valid, so preferences were not saved.")
                return
            apply_account(self.state, self.account, self.region)
            self.collect_libraries(self.state)
        if self.state != self.window.config:
            config_mod.save(self.state)
            self.window.set_config(self.state)

    def _run_wizard(self):
        # The wizard starts from the saved settings; unsaved changes here are dropped.
        self._skip_apply = True
        self.close()
        self.window.run_setup()
