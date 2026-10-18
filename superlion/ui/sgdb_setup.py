"""Guided setup of a SteamGridDB API key, used by the setup wizard and the artwork picker."""

from gi.repository import Adw, Gdk, GLib, GObject, Gtk

from .. import auth, sgdb

LOGIN_PAGE = "https://www.steamgriddb.com/login"


class SgdbKeySetup(Gtk.Box):
    """Numbered steps that take the user from no account to a checked, saved key.

    Emits "saved" once a key has been checked with SteamGridDB and stored.
    """

    __gsignals__ = {"saved": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        self.window = window

        intro = Gtk.Label(
            label=(
                "SteamGridDB is a free, community-run collection of game artwork. "
                "Connecting it lets you choose covers, backgrounds and logos inside "
                "Superlion. It needs a free API key, which takes about a minute to create."
            ),
            wrap=True,
            xalign=0,
        )
        self.append(intro)

        steps = Adw.PreferencesGroup(title="Get Your Key")
        steps.add(
            self._step(
                "1", "Sign in to SteamGridDB",
                "You can sign in with your Steam account, so no new password is needed.",
                "Open Sign-In Page", LOGIN_PAGE,
            )
        )
        steps.add(
            self._step(
                "2", "Open your API key page",
                "If no key is shown yet, create one on that page.",
                "Open API Key Page", sgdb.KEY_PAGE,
            )
        )
        steps.add(
            self._step(
                "3", "Copy the key",
                "Select the key on that page and copy it, then come back here.",
                None, None,
            )
        )
        self.append(steps)

        key_group = Adw.PreferencesGroup(title="Paste Your Key")
        self.entry = Adw.PasswordEntryRow(title="SteamGridDB API Key")
        self.entry.set_text(sgdb.load_key())
        paste = Gtk.Button(icon_name="edit-paste-symbolic", tooltip_text="Paste", valign=Gtk.Align.CENTER)
        paste.add_css_class("flat")
        paste.connect("clicked", self._on_paste)
        self.entry.add_suffix(paste)
        self.entry.connect("changed", lambda *_: self._set_status(""))
        self.entry.connect("entry-activated", lambda *_: self._on_save())
        key_group.add(self.entry)
        self.append(key_group)

        self.status = Gtk.Label(wrap=True, xalign=0, visible=False)
        self.append(self.status)

        self.save_button = Gtk.Button(label="Check and Save Key", halign=Gtk.Align.CENTER)
        self.save_button.add_css_class("pill")
        self.save_button.add_css_class("suggested-action")
        self.save_button.connect("clicked", lambda *_: self._on_save())
        self.append(self.save_button)

    def _step(self, number, title, subtitle, button_label, url):
        row = Adw.ActionRow(title=title, subtitle=subtitle)
        badge = Gtk.Label(label=number, valign=Gtk.Align.CENTER, width_chars=2)
        badge.add_css_class("numeric")
        badge.add_css_class("heading")
        row.add_prefix(badge)
        if url:
            button = Gtk.Button(label=button_label, valign=Gtk.Align.CENTER)
            button.connect("clicked", lambda *_: self.window.open_website(url))
            row.add_suffix(button)
        return row

    def _on_paste(self, _button):
        clipboard = Gdk.Display.get_default().get_clipboard()

        def done(cb, result):
            try:
                text = cb.read_text_finish(result)
            except GLib.Error:
                text = None
            if text:
                self.entry.set_text(text.strip())
                self.entry.grab_focus()
            else:
                self._set_status("The clipboard does not contain text. Copy the key and try again.", error=True)

        clipboard.read_text_async(None, done)

    def _set_status(self, text, error=False):
        self.status.set_label(text)
        self.status.set_visible(bool(text))
        for css in ("error", "success"):
            self.status.remove_css_class(css)
        if text:
            self.status.add_css_class("error" if error else "success")

    def _on_save(self):
        key = self.entry.get_text().strip()
        if not key:
            self._set_status("Paste your API key first.", error=True)
            return
        self.save_button.set_sensitive(False)
        self._set_status("Checking the key with SteamGridDB…")

        def done(_result, error):
            self.save_button.set_sensitive(True)
            if isinstance(error, sgdb.ApiKeyError):
                self._set_status("SteamGridDB did not accept this key. Check it was copied in full.", error=True)
                return
            if error:
                self._set_status("SteamGridDB could not be reached. Check your connection and try again.", error=True)
                return
            try:
                sgdb.save_key(key)
            except GLib.Error as exc:
                self._set_status(f"The key could not be saved to your keyring: {exc.message}", error=True)
                return
            self._set_status("Connected to SteamGridDB.")
            self.emit("saved")

        auth.run_async(lambda: sgdb.search("Portal", key), done)
