"""Native store home, search and store game pages."""

from gi.repository import Adw, GLib, Gtk, Pango

from .. import auth, steam_control, store_api
from . import images
from .media import MediaCarousel, description_widgets
from .webview import SteamWebPage

CATEGORIES = [
    ("specials", "Specials"),
    ("top_sellers", "Top Sellers"),
    ("new_releases", "New Releases"),
    ("coming_soon", "Coming Soon"),
]
CAPSULE_W, CAPSULE_H = 292, 136


def price_text(final, original, currency, discount):
    """Price label text, or "" when the store has not published a price."""
    if original is None and not final:
        return ""
    text = store_api.format_price(final, currency)
    return f"−{discount}%  {text}" if discount else text


def search_price(item):
    """Price text for a search result; results without a price are free."""
    price = item.get("price")
    if not price:
        return "Free"
    final, initial = price.get("final", 0), price.get("initial", 0)
    discount = round(100 - 100 * final / initial) if initial and final < initial else 0
    return price_text(final, initial, price.get("currency", ""), discount)


class Capsule(Gtk.Button):
    def __init__(self, item, on_open):
        super().__init__()
        self.add_css_class("flat")
        self.add_css_class("store-capsule")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        picture = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, can_shrink=True)
        frame = Gtk.Overlay(child=picture, overflow=Gtk.Overflow.HIDDEN)
        frame.set_size_request(CAPSULE_W, CAPSULE_H)
        frame.add_css_class("card")
        box.append(frame)
        images.load(item.get("large_capsule_image", ""), CAPSULE_W * 2, CAPSULE_H * 2, picture.set_paintable)

        name = Gtk.Label(
            label=item.get("name", ""), xalign=0, ellipsize=Pango.EllipsizeMode.END, max_width_chars=1
        )
        box.append(name)
        price = price_text(
            item.get("final_price"),
            item.get("original_price"),
            item.get("currency", ""),
            item.get("discount_percent", 0) if item.get("discounted") else 0,
        )
        if price:
            label = Gtk.Label(label=price, xalign=0)
            label.add_css_class("caption")
            if item.get("discounted"):
                label.add_css_class("success")
            else:
                label.add_css_class("dim-label")
            box.append(label)
        self.set_child(box)
        self.set_size_request(CAPSULE_W, -1)
        self.connect("clicked", lambda *_: on_open(item["id"], item.get("name", "")))


class StoreView(Gtk.Box):

    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.window = window
        self.loaded_region = None

        self.search_entry = Gtk.SearchEntry(placeholder_text="Search the store", hexpand=True)
        self.search_entry.connect("search-changed", self._on_search_changed)
        self.search_entry.connect("activate", self._on_search_changed)
        search_box = Adw.Clamp(
            child=self.search_entry, maximum_size=560, margin_top=12, margin_bottom=6,
            margin_start=12, margin_end=12,
        )
        self.append(search_box)

        self.stack = Gtk.Stack(vexpand=True)
        self.home = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24, margin_top=12, margin_bottom=24)
        self.stack.add_named(Gtk.ScrolledWindow(child=self.home, hscrollbar_policy=Gtk.PolicyType.NEVER), "home")

        self.results = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.results.add_css_class("boxed-list")
        results_clamp = Adw.Clamp(child=self.results, maximum_size=720, margin_top=12, margin_bottom=24,
                                  margin_start=12, margin_end=12)
        self.stack.add_named(Gtk.ScrolledWindow(child=results_clamp, hscrollbar_policy=Gtk.PolicyType.NEVER), "results")

        self.stack.add_named(Adw.Spinner(), "loading")
        self.error_page = Adw.StatusPage(
            icon_name="network-offline-symbolic", title="The Store Could Not Be Loaded"
        )
        retry = Gtk.Button(label="Try Again", halign=Gtk.Align.CENTER)
        retry.add_css_class("pill")
        retry.connect("clicked", lambda *_: self.load(force=True))
        self.error_page.set_child(retry)
        self.stack.add_named(self.error_page, "error")
        self.stack.add_named(
            Adw.StatusPage(icon_name="system-search-symbolic", title="No Results Found"), "empty"
        )
        self.append(self.stack)
        self._search_serial = 0

    def load(self, force=False):
        config = self.window.config
        if config is None or (self.loaded_region == self.window.store_region and not force):
            return
        self.stack.set_visible_child_name("loading")
        region = self.window.store_region

        def done(data, error):
            if error:
                self.error_page.set_description("Check your internet connection and try again.")
                self.stack.set_visible_child_name("error")
                return
            self.loaded_region = region
            self._show_home(data)

        auth.run_async(lambda: store_api.featured(region), done)

    def _show_home(self, data):
        while child := self.home.get_first_child():
            self.home.remove(child)
        for key, title in CATEGORIES:
            items = data.get(key, [])
            if not items:
                continue
            heading = Gtk.Label(label=title, xalign=0, margin_start=18)
            heading.add_css_class("title-3")
            self.home.append(heading)
            row = Gtk.Box(spacing=12, margin_start=12, margin_end=12)
            seen = set()
            for item in items:
                if item["id"] not in seen:
                    seen.add(item["id"])
                    row.append(Capsule(item, self.window.open_store_app))
            scroller = Gtk.ScrolledWindow(
                child=row, vscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True
            )
            self.home.append(scroller)
        self.stack.set_visible_child_name("home")

    def _on_search_changed(self, entry):
        term = entry.get_text().strip()
        self._search_serial += 1
        serial = self._search_serial
        if not term:
            self.stack.set_visible_child_name("home" if self.loaded_region else "loading")
            return
        region = self.window.store_region

        def done(items, error):
            if serial != self._search_serial:
                return  # A newer search has started.
            if error:
                self.stack.set_visible_child_name("error")
                return
            self._show_results(items)

        auth.run_async(lambda: store_api.search(term, region), done)

    def _show_results(self, items):
        self.results.remove_all()
        for item in items:
            row = Adw.ActionRow(
                title=GLib.markup_escape_text(item.get("name", "")),
                subtitle=search_price(item),
                activatable=True,
            )
            thumb = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, can_shrink=True,
                                width_request=120, height_request=45, valign=Gtk.Align.CENTER)
            thumb.add_css_class("card")
            images.load(item.get("tiny_image", ""), 240, 90, thumb.set_paintable)
            row.add_prefix(thumb)
            row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
            row.connect("activated", lambda _r, i=item: self.window.open_store_app(i["id"], i.get("name", "")))
            self.results.append(row)
        self.stack.set_visible_child_name("results" if items else "empty")


class StoreAppPage(Adw.NavigationPage):

    def __init__(self, window, appid, name=""):
        super().__init__(title=name or "Store")
        self.window = window
        self.appid = appid

        self.stack = Gtk.Stack()
        self.stack.add_named(Adw.Spinner(), "loading")
        self.content = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=24, margin_top=12, margin_bottom=24,
            margin_start=12, margin_end=12,
        )
        self.stack.add_named(
            Gtk.ScrolledWindow(
                child=Adw.Clamp(child=self.content, maximum_size=860),
                hscrollbar_policy=Gtk.PolicyType.NEVER,
            ),
            "page",
        )
        self.stack.add_named(
            Adw.StatusPage(
                icon_name="dialog-information-symbolic",
                title="No Store Page",
                description="Steam does not have a store page for this item in your region.",
            ),
            "missing",
        )

        toolbar = Adw.ToolbarView(content=self.stack)
        header = Adw.HeaderBar()
        cart = Gtk.Button(icon_name="superlion-cart-symbolic", tooltip_text="Cart")
        cart.connect("clicked", lambda *_: window.open_web(f"{store_api.STORE}/cart", "Cart"))
        header.pack_end(cart)
        toolbar.add_top_bar(header)
        self.set_child(toolbar)

        region = window.store_region

        def load():
            data = store_api.details(appid, region)
            summary = None
            if data:
                try:
                    summary = store_api.reviews(appid)
                except Exception:  # The review summary is optional.
                    summary = None
            return data, summary

        def done(result, error):
            if error or not result or not result[0]:
                self.stack.set_visible_child_name("missing")
                return
            self._build(*result)
            self.stack.set_visible_child_name("page")

        self.media = None
        self.connect("hidden", lambda *_: self.media and self.media.pause())
        auth.run_async(load, done)

    def release(self):
        if self.media:
            self.media.stop()

    def _build(self, data, summary):
        self.set_title(data.get("name", self.get_title()))
        self.media = MediaCarousel(data)
        if not self.media.is_empty:
            self.content.append(self.media)
        else:
            header_image = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, can_shrink=True, height_request=280)
            images.load(data.get("header_image", ""), 920, 430, header_image.set_paintable)
            self.content.append(header_image)

        title = Gtk.Label(label=data.get("name", ""), wrap=True, xalign=0)
        title.add_css_class("title-1")
        self.content.append(title)

        meta = Gtk.Box(spacing=12)
        price = data.get("price_overview")
        if data.get("is_free"):
            meta.append(Gtk.Label(label="Free to Play"))
        elif price:
            text = price.get("final_formatted") or store_api.format_price(price.get("final"), price.get("currency", ""))
            label = Gtk.Label(label=text)
            label.add_css_class("title-3")
            meta.append(label)
            if price.get("discount_percent"):
                badge = Gtk.Label(label=f"−{price['discount_percent']}%  (was {price.get('initial_formatted', '')})")
                badge.add_css_class("success")
                meta.append(badge)
        if summary:
            reviews = Gtk.Label(label=f"{summary[0]} ({summary[1]:,} reviews)")
            reviews.add_css_class("dim-label")
            meta.append(reviews)
        self.content.append(meta)

        self.content.append(self._build_buttons(data))

        for widget in description_widgets(data):
            self.content.append(widget)

        group = Adw.PreferencesGroup(title="Information")
        release = data.get("release_date") or {}
        platforms = data.get("platforms") or {}
        rows = [
            ("Developer", ", ".join(data.get("developers", []))),
            ("Publisher", ", ".join(data.get("publishers", []))),
            ("Release Date", ("Coming soon: " if release.get("coming_soon") else "") + release.get("date", "")),
            ("Genres", ", ".join(g.get("description", "") for g in data.get("genres", []))),
            ("Platforms", ", ".join(p.capitalize() if p != "mac" else "macOS" for p, ok in platforms.items() if ok)),
        ]
        for label, value in rows:
            if value:
                row = Adw.ActionRow(title=label, subtitle=GLib.markup_escape_text(value), subtitle_selectable=True)
                row.add_css_class("property")
                group.add(row)
        self.content.append(group)

    def _build_buttons(self, data):
        box = Gtk.Box(spacing=12)
        game = self.window.find_game(self.appid)
        page_url = f"{store_api.STORE}/app/{self.appid}/"
        if game is not None and game.props.installed:
            primary = Gtk.Button(label="Play")
            primary.connect("clicked", lambda *_: self._open_uri(f"steam://rungameid/{self.appid}"))
        elif game is not None:
            primary = Gtk.Button(label="Install")
            primary.connect("clicked", lambda *_: self.window.install_game(self.appid, game.props.name))
        else:
            primary = Gtk.Button(label="Buy")
            primary.connect("clicked", lambda *_: self.window.open_web(page_url, data.get("name", "Store")))
        primary.add_css_class("suggested-action")
        primary.add_css_class("pill")
        box.append(primary)

        if game is None:
            wishlist = Gtk.Button(label="Add to Wishlist")
            wishlist.add_css_class("pill")
            wishlist.connect("clicked", lambda *_: self.window.open_web(page_url, data.get("name", "Store")))
            box.append(wishlist)

        client = Gtk.Button(label="Open in Steam Client")
        client.add_css_class("pill")
        client.add_css_class("flat")
        client.connect("clicked", lambda *_: self._open_uri(f"steam://store/{self.appid}"))
        box.append(client)
        return box

    def _open_uri(self, uri):
        try:
            steam_control.open_uri(self.window.config, uri)
        except GLib.Error as error:
            self.window.toast(f"Steam could not be opened: {error.message}")


def open_web(window, url, title):
    window.nav.push(SteamWebPage(window, url, title))
