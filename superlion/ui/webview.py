"""Embedded Steam store pages for buying, the cart and the wishlist."""

from urllib.parse import urlparse

import gi

gi.require_version("WebKit", "6.0")
import json  # noqa: E402

from gi.repository import Adw, GLib, Gtk, WebKit  # noqa: E402

from .. import config as config_mod  # noqa: E402

STEAM_DOMAINS = ("steampowered.com", "steamcommunity.com")

_network_session = None


def network_session():
    """One persistent session shared by every store page, so sign-in is kept."""
    global _network_session
    if _network_session is None:
        _network_session = WebKit.NetworkSession.new(
            str(config_mod.data_dir() / "webkit"), str(config_mod.cache_dir() / "webkit")
        )
        _network_session.get_cookie_manager().set_persistent_storage(
            str(config_mod.data_dir() / "webkit" / "cookies.sqlite"),
            WebKit.CookiePersistentStorage.SQLITE,
        )
    return _network_session


def is_steam_host(host):
    host = (host or "").lower()
    return any(host == d or host.endswith("." + d) for d in STEAM_DOMAINS)


def clear_sign_in(callback=None):
    manager = network_session().get_website_data_manager()
    manager.clear(
        WebKit.WebsiteDataTypes.COOKIES,
        0,
        None,
        lambda m, r: (m.clear_finish(r), callback and callback()),
    )


# The store's sign-in and data for Superlion: whether the user is signed in, the
# Web API token Steam's own pages use, and the wishlist and cart counts.
STATE_SCRIPT = """
const config = document.getElementById("application_config");
const user = config ? JSON.parse(config.dataset.store_user_config || "{}") : {};
const cart = user.shoppingcart || {};
return JSON.stringify({
    signed_in: Boolean(window.g_AccountID),
    token: user.webapi_token || "",
    cart: cart.line_items ? cart.line_items.length : cart.line_item_count || 0,
});
"""
WISHLIST_SCRIPT = """
if (!window.g_AccountID) return JSON.stringify({signed_in: false});
const body = new URLSearchParams({sessionid: g_sessionID, appid});
const response = await fetch(`/api/${action}`, {method: "POST", body, credentials: "same-origin"});
return JSON.stringify({signed_in: true, success: Boolean((await response.json()).success)});
"""


def run_in_store(script, args, callback):
    """Run script, the body of an async function given args (strings), in a hidden store page.

    Steam's sign-in token, the steamLoginSecure cookie, expires after about a
    day, and the store's pages renew it as they load, so requests made with the
    saved cookie alone are refused. callback(result) gets the script's JSON
    result decoded, or None if the page or script failed.
    """
    view = WebKit.WebView(network_session=network_session())

    def done(view, result):
        try:
            value = json.loads(view.call_async_javascript_function_finish(result).to_string())
        except (GLib.Error, ValueError):
            value = None
        _running.discard(view)
        callback(value)

    def loaded(view, event):
        if event == WebKit.LoadEvent.FINISHED:
            view.disconnect(handler)
            variant = GLib.Variant("a{sv}", {key: GLib.Variant("s", str(v)) for key, v in args.items()})
            view.call_async_javascript_function(script, -1, variant, None, None, None, done)

    handler = view.connect("load-changed", loaded)
    _running.add(view)  # Kept alive until the script finishes.
    view.load_uri("https://store.steampowered.com/cart/")


_running = set()


class SteamWebPage(Adw.NavigationPage):
    def __init__(self, window, url, title="Steam Store"):
        super().__init__(title=title)
        self.window = window
        self.in_checkout = False

        self.webview = WebKit.WebView(network_session=network_session(), vexpand=True)
        settings = self.webview.get_settings()
        settings.set_enable_developer_extras(False)
        self.webview.connect("decide-policy", self._on_decide_policy)
        self.webview.connect("notify::uri", self._on_uri_changed)
        self.webview.connect("notify::title", self._on_title_changed)

        header = Adw.HeaderBar(show_back_button=False)
        back = Gtk.Button(icon_name="go-previous-symbolic", tooltip_text="Back")
        back.connect("clicked", self._on_back)
        header.pack_start(back)

        self.window_title = Adw.WindowTitle(title=title)
        header.set_title_widget(self.window_title)

        browser = Gtk.Button(icon_name="superlion-external-link-symbolic", tooltip_text="Open in Browser")
        browser.connect("clicked", self._on_open_in_browser)
        header.pack_end(browser)
        reload_button = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Reload")
        reload_button.connect("clicked", lambda *_: self.webview.reload())
        header.pack_end(reload_button)

        self.progress = Gtk.ProgressBar(visible=False)
        self.progress.add_css_class("osd")
        self.webview.connect("notify::estimated-load-progress", self._on_progress)
        overlay = Gtk.Overlay(child=self.webview)
        self.progress.set_valign(Gtk.Align.START)
        overlay.add_overlay(self.progress)

        toolbar = Adw.ToolbarView(content=overlay)
        toolbar.add_top_bar(header)
        self.set_child(toolbar)

        self._load_signed_in(url)

    def _load_signed_in(self, url):
        self.webview.load_uri(url)

    def _on_decide_policy(self, _view, decision, decision_type):
        if decision_type not in (
            WebKit.PolicyDecisionType.NAVIGATION_ACTION,
            WebKit.PolicyDecisionType.NEW_WINDOW_ACTION,
        ):
            return False
        action = decision.get_navigation_action()
        uri = action.get_request().get_uri()
        host = urlparse(uri).hostname
        clicked = action.get_navigation_type() == WebKit.NavigationType.LINK_CLICKED
        # Checkout may redirect to a payment provider; only links the user clicks
        # to other sites outside checkout are sent to the browser.
        if clicked and not is_steam_host(host) and not self.in_checkout:
            decision.ignore()
            self._open_external(uri)
            return True
        if decision_type == WebKit.PolicyDecisionType.NEW_WINDOW_ACTION:
            decision.ignore()
            if is_steam_host(host):
                self.webview.load_uri(uri)
            else:
                self._open_external(uri)
            return True
        return False

    def _on_uri_changed(self, view, _pspec):
        uri = view.get_uri() or ""
        host = urlparse(uri).hostname or ""
        if host == "checkout.steampowered.com":
            self.in_checkout = True
        elif is_steam_host(host):
            self.in_checkout = False
        self.window_title.set_subtitle(uri)

    def _on_title_changed(self, view, _pspec):
        self.window_title.set_title(view.get_title() or "Steam Store")

    def _on_progress(self, view, _pspec):
        value = view.get_estimated_load_progress()
        self.progress.set_fraction(value)
        self.progress.set_visible(0 < value < 1)

    def _on_back(self, _button):
        if self.webview.can_go_back():
            self.webview.go_back()
        else:
            self.window.nav.pop()

    def _on_open_in_browser(self, _button):
        uri = self.webview.get_uri()
        if uri:
            self._open_external(uri)

    def _open_external(self, uri):
        Gtk.UriLauncher(uri=uri).launch(self.window, None, None)
