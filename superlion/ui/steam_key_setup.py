"""Guided setup of the user's own Steam Web API key.

The key page is Valve's own (steamcommunity.com/dev/apikey), shown inside
Superlion. If the user is not signed in to the Steam website, Steam's own
sign-in page appears there. Superlion fills in the domain field and reads the
key from the page once it is shown; agreeing to Valve's terms, registering and
any phone confirmation are left to the user.
"""

from urllib.parse import urlparse

from gi.repository import Adw, Gdk, GLib, GObject, Gtk

from .. import auth
from .webview import network_session

DOMAIN_NAME = "Superlion"
WATCH_INTERVAL = 1500  # milliseconds between looks at the page for the key

# Fills in the domain field if it is empty, and returns the key if the page shows one.
PAGE_SCRIPT = """
(function () {
    var domain = document.getElementById('domain');
    if (domain && !domain.value) { domain.value = '%s'; }
    var text = (document.body && document.body.innerText) || '';
    var match = text.match(/Key:\\s*([0-9A-Fa-f]{32})/);
    return match ? match[1] : '';
})();
""" % DOMAIN_NAME


class KeyCaptureDialog(Adw.Dialog):
    """Valve's key page, watched for the key; emits "found" with it."""

    __gsignals__ = {"found": (GObject.SignalFlags.RUN_FIRST, None, (str,))}

    def __init__(self):
        super().__init__(title="Get Your Steam Web API Key", content_width=900, content_height=760)
        import gi

        gi.require_version("WebKit", "6.0")
        from gi.repository import WebKit

        self.webview = WebKit.WebView(network_session=network_session(), vexpand=True)
        self.webview.connect("notify::uri", self._on_uri)
        self._timer = GLib.timeout_add(WATCH_INTERVAL, self._look_for_key)
        self.connect("closed", lambda *_: self._stop())

        steps = Gtk.Label(
            label=(
                "1. Sign in to Steam if asked.   "
                "2. Tick the box to agree to Valve's terms.   "
                "3. Press Register, and approve on your phone if Steam asks.\n"
                "The domain name is filled in for you, and your key is picked up automatically."
            ),
            wrap=True, justify=Gtk.Justification.CENTER, margin_top=6, margin_bottom=6,
            margin_start=12, margin_end=12,
        )
        banner_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        banner_box.add_css_class("toolbar")
        banner_box.append(steps)

        self.title = Adw.WindowTitle(title="Get Your Steam Web API Key", subtitle=auth.KEY_PAGE)
        header = Adw.HeaderBar(title_widget=self.title)
        toolbar = Adw.ToolbarView(content=self.webview)
        toolbar.add_top_bar(header)
        toolbar.add_top_bar(banner_box)
        self.set_child(toolbar)
        self.webview.load_uri(auth.KEY_PAGE)

    def _on_uri(self, view, _pspec):
        # The address is shown so it is clear this is Steam's own site.
        self.title.set_subtitle(view.get_uri() or "")

    def _look_for_key(self):
        host = urlparse(self.webview.get_uri() or "").hostname or ""
        if host == "steamcommunity.com":
            self.webview.evaluate_javascript(PAGE_SCRIPT, -1, None, None, None, self._on_result)
        return GLib.SOURCE_CONTINUE

    def _on_result(self, view, result):
        try:
            value = view.evaluate_javascript_finish(result).to_string()
        except GLib.Error:
            return  # The page was changing; try again on the next look.
        if value and len(value) == 32:
            self._stop()
            self.emit("found", value.upper())
            self.close()

    def _stop(self):
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0


class SteamKeySetup(Gtk.Box):
    """Connect Superlion to the user's Steam account; emits "saved" when a key is stored."""

    __gsignals__ = {"saved": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        self.window = window

        intro = Gtk.Label(
            label=(
                "Superlion lists the games you own but have not installed using your own "
                "Steam Web API key, which Valve provides free to every Steam account for "
                "apps like this. No password is shared with Superlion."
            ),
            wrap=True, xalign=0,
        )
        self.append(intro)

        auto = Gtk.Button(label="Get My Key Automatically", halign=Gtk.Align.CENTER)
        auto.add_css_class("pill")
        auto.add_css_class("suggested-action")
        auto.connect("clicked", lambda *_: self._open_capture())
        self.append(auto)
        hint = Gtk.Label(
            label="Opens Steam's key page here. You only tick Valve's terms and press Register.",
            wrap=True, justify=Gtk.Justification.CENTER,
        )
        hint.add_css_class("dim-label")
        hint.add_css_class("caption")
        self.append(hint)

        manual = Adw.PreferencesGroup(
            title="Or Paste a Key",
            description="If you already have a key, or prefer to copy it yourself.",
        )
        self.entry = Adw.PasswordEntryRow(title="Steam Web API Key")
        self.entry.set_text(auth.load_key())
        paste = Gtk.Button(icon_name="edit-paste-symbolic", tooltip_text="Paste", valign=Gtk.Align.CENTER)
        paste.add_css_class("flat")
        paste.connect("clicked", self._on_paste)
        self.entry.add_suffix(paste)
        self.entry.connect("entry-activated", lambda *_: self._check_and_save(self.entry.get_text()))
        self.entry.connect("changed", lambda *_: self._set_status(""))
        manual.add(self.entry)
        open_page = Adw.ButtonRow(title="Open Key Page in Browser", end_icon_name="superlion-external-link-symbolic")
        open_page.connect("activated", lambda *_: window.open_website(auth.KEY_PAGE))
        manual.add(open_page)
        self.append(manual)

        self.status = Gtk.Label(wrap=True, xalign=0, visible=False, use_markup=True)
        self.append(self.status)
        self.privacy_button = Gtk.Button(label="Open Steam Privacy Settings", halign=Gtk.Align.START, visible=False)
        self.privacy_button.connect("clicked", lambda *_: window.open_website(auth.PRIVACY_PAGE))
        self.append(self.privacy_button)

        self.save_button = Gtk.Button(label="Check and Save Key", halign=Gtk.Align.CENTER)
        self.save_button.add_css_class("pill")
        self.save_button.connect("clicked", lambda *_: self._check_and_save(self.entry.get_text()))
        self.append(self.save_button)

    def _open_capture(self):
        dialog = KeyCaptureDialog()
        dialog.connect("found", lambda _d, key: (self.entry.set_text(key), self._check_and_save(key)))
        dialog.present(self.get_root())

    def _on_paste(self, _button):
        clipboard = Gdk.Display.get_default().get_clipboard()

        def done(cb, result):
            try:
                text = cb.read_text_finish(result)
            except GLib.Error:
                text = None
            if text:
                self.entry.set_text(text.strip())
            else:
                self._set_status("The clipboard does not contain text.", error=True)

        clipboard.read_text_async(None, done)

    def _set_status(self, text, error=False, privacy=False):
        self.status.set_markup(GLib.markup_escape_text(text))
        self.status.set_visible(bool(text))
        for css in ("error", "success", "warning"):
            self.status.remove_css_class(css)
        if text:
            self.status.add_css_class("error" if error else "warning" if privacy else "success")
        self.privacy_button.set_visible(privacy)

    def _check_and_save(self, key):
        key = key.strip()
        if len(key) != 32:
            self._set_status("A Steam Web API key is 32 letters and numbers. Check it was copied in full.", error=True)
            return
        config = self.window.config
        if config is None:
            self._set_status("Finish choosing your Steam account first.", error=True)
            return
        steamid = auth.steamid64(config)
        self.save_button.set_sensitive(False)
        self._set_status("Checking the key with Valve…")

        def done(result, error):
            self.save_button.set_sensitive(True)
            if isinstance(error, auth.AuthError):
                self._set_status("Valve did not accept this key. Check it was copied in full.", error=True)
                return
            if error:
                self._set_status("Steam could not be reached. Check your connection and try again.", error=True)
                return
            try:
                auth.save_key(key)
            except GLib.Error as exc:
                self._set_status(f"The key could not be saved to your keyring: {exc.message}", error=True)
                return
            name = result["name"] or "your account"
            if result["games"]:
                self._set_status(f"Connected to {name}. {result['games']} owned games found.")
                self.emit("saved")
                return
            # Private game details: use the store's list for this sign-in instead.
            self._set_status(f"Connected to {name}. Your game details are private, so checking the Steam store instead…")
            self._try_store_list(name)

        auth.run_async(lambda: auth.check_key(key, steamid), done)

    def _try_store_list(self, name):
        from .store_owned import fetch_owned_appids, owned_entries

        def done(appids):
            entries = owned_entries(appids, self.window.config.root) if appids else []
            if entries:
                self._set_status(
                    f"Connected to {name}. Your game details stay private; {len(entries)} owned "
                    "games were found through your Steam store sign-in."
                )
            else:
                self._set_status(
                    f"Connected to {name}. Your game details are private and this window is not "
                    "signed in to the Steam store, so only installed games will show. Use Get My "
                    "Key Automatically to sign in, or, if you prefer, make Game details visible "
                    "in your Steam privacy settings.",
                    privacy=True,
                )
            self.emit("saved")

        fetch_owned_appids(done)


class SteamKeyDialog(Adw.Dialog):
    """The setup as a dialog, used from the main menu and Preferences; emits "signed-in"."""

    __gsignals__ = {"signed-in": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self, window):
        super().__init__(title="Connect Steam Account", content_width=560, content_height=640)
        setup = SteamKeySetup(window)
        setup.connect("saved", lambda *_: self.emit("signed-in"))
        content = Adw.Clamp(child=setup, maximum_size=520, margin_top=12, margin_bottom=24,
                            margin_start=12, margin_end=12)
        toolbar = Adw.ToolbarView(content=Gtk.ScrolledWindow(child=content, hscrollbar_policy=Gtk.PolicyType.NEVER))
        toolbar.add_top_bar(Adw.HeaderBar())
        self.set_child(toolbar)
