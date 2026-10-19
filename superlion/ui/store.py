"""Native store: its sidebar, home, lists, genres, wishlist, cart and search, and store game pages."""

import json

from gi.repository import Adw, GLib, Gtk, Pango

from .. import auth, steam_control, store_account, store_api
from . import images
from .library_view import SidebarRow
from .media import MediaCarousel, description_widgets
from .webview import CART_SCRIPT, STATE_SCRIPT, WISHLIST_SCRIPT, SteamWebPage, run_in_store

CATEGORIES = [
    ("specials", "Specials", "superlion-sale-symbolic"),
    ("new_releases", "New and Trending", "superlion-trending-symbolic"),
    ("top_sellers", "Top Sellers", "superlion-top-sellers-symbolic"),
    ("coming_soon", "Coming Soon", "x-office-calendar-symbolic"),
]
GENRES = {
    "Action": "superlion-genre-action-symbolic",
    "Adventure": "superlion-genre-adventure-symbolic",
    "RPG": "superlion-genre-rpg-symbolic",
    "Strategy": "superlion-genre-strategy-symbolic",
    "Simulation": "superlion-genre-simulation-symbolic",
    "Racing": "superlion-genre-racing-symbolic",
    "Sports": "superlion-genre-sports-symbolic",
    "Indie": "superlion-genre-indie-symbolic",
    "VR": "superlion-vr-symbolic",
}
# After Hours: a store of games with explicit sexual content, opened by clicking the
# Browse heading five times quickly. Each view is store_api.after_hours()'s options.
AFTER_HOURS_LISTS = [
    ("after:top_sellers", "Top Sellers", "superlion-top-sellers-symbolic", {"sort": store_api.TOP_SELLERS}),
    ("after:trending", "New and Trending", "superlion-trending-symbolic", {"sort": store_api.TRENDING}),
    ("after:specials", "Specials", "superlion-sale-symbolic", {"discounted": True}),
    ("after:coming_soon", "Coming Soon", "x-office-calendar-symbolic", {"coming_soon": True}),
    ("after:free", "Free to Play", "superlion-free-symbolic", {"free": True}),
]
# (name, Steam tag ID, icon)
AFTER_HOURS_GENRES = [
    ("Visual Novel", 3799, "superlion-genre-visual-novel-symbolic"),
    ("Dating Sim", 9551, "superlion-genre-dating-symbolic"),
    ("RPG", 122, "superlion-genre-rpg-symbolic"),
    ("Adventure", 21, "superlion-genre-adventure-symbolic"),
    ("Action", 19, "superlion-genre-action-symbolic"),
    ("Simulation", 599, "superlion-genre-simulation-symbolic"),
    ("Puzzle", 1664, "superlion-genre-puzzle-symbolic"),
    ("Strategy", 9, "superlion-genre-strategy-symbolic"),
]
SECRET_CLICKS = 5
SECRET_WINDOW = 3_000_000  # microseconds
SECTION_TITLES = {"after": "After Hours", "you": "You", "browse": "Browse"}
WISHLIST_SORTS = [
    ("Your Order", None),
    ("Price", lambda item: item.get("final_cents", 0)),
    ("Discount", lambda item: -item.get("discount_percent", 0)),
    ("Release Date", lambda item: -item.get("release", 0)),
]
CAPSULE_W, CAPSULE_H = 292, 136
LOGIN_URL = f"{store_api.STORE}/login/"
# Payment happens only on Steam's own checkout page.
CHECKOUT_URL = "https://checkout.steampowered.com/checkout/?accountcart=1"


def price_text(final, original, currency, discount):
    """Price label text, or "" when the store has not published a price."""
    if original is None and not final:
        return ""
    text = store_api.format_price(final, currency)
    return f"−{discount}%  {text}" if discount else text


def item_price(item):
    """Price text for an item from store_api.featured() or store_api.items()."""
    discount = item.get("discount_percent", 0) if item.get("discounted") else 0
    if "price_text" in item:
        return f"−{discount}%  {item['price_text']}" if discount else item["price_text"]
    return price_text(item.get("final_price"), item.get("original_price"), item.get("currency", ""), discount)


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
        # Centred, so a grid's wider cells do not stretch the picture.
        super().__init__(halign=Gtk.Align.CENTER, valign=Gtk.Align.START)
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
        price = item_price(item)
        if price:
            label = Gtk.Label(label=price, xalign=0)
            label.add_css_class("caption")
            label.add_css_class("success" if item.get("discounted") else "dim-label")
            box.append(label)
        # Pictures ask for their image's size, which is twice the capsule's for sharpness.
        self.set_child(Adw.Clamp(child=box, maximum_size=CAPSULE_W, tightening_threshold=CAPSULE_W))
        self.set_size_request(CAPSULE_W, -1)
        self.connect("clicked", lambda *_: on_open(item["id"], item.get("name", "")))


def _scroller(child):
    return Gtk.ScrolledWindow(child=child, hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)


class StoreView(Gtk.Box):
    """The Store section. Its sidebar is self.sidebar, which the window shows beside it."""

    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.window = window
        self.loaded_region = None
        self.featured = {}
        self.view = "featured"
        self.wishlist_ids = None  # The wishlist's app IDs in order, once loaded.
        self.wishlist_items = {}
        self.cart = None  # The cart API's cart, {"line_items", "subtotal"}, once loaded.
        self.signed_in = False
        self._serial = 0
        self.genres = list(GENRES)
        self.after_hours = False
        self._secret_clicks = []
        self.sidebar = self._build_sidebar()

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
        self.stack.add_named(_scroller(self.home), "home")

        self.grid_title = Gtk.Label(xalign=0, margin_start=18, margin_top=12)
        self.grid_title.add_css_class("title-2")
        self.grid = Gtk.FlowBox(
            selection_mode=Gtk.SelectionMode.NONE, homogeneous=True, max_children_per_line=6,
            column_spacing=12, row_spacing=18, margin_top=12, margin_bottom=24, margin_start=12, margin_end=12,
            valign=Gtk.Align.START,
        )
        grid_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        grid_box.append(self.grid_title)
        grid_box.append(self.grid)
        self.stack.add_named(_scroller(grid_box), "grid")

        self.stack.add_named(self._build_wishlist_page(), "wishlist")
        self.stack.add_named(self._build_cart_page(), "cart")

        self.results = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.results.add_css_class("boxed-list")
        results_clamp = Adw.Clamp(child=self.results, maximum_size=720, margin_top=12, margin_bottom=24,
                                  margin_start=12, margin_end=12)
        self.stack.add_named(_scroller(results_clamp), "results")

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

    def _build_sidebar(self):
        self.sidebar_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.sidebar_list.add_css_class("navigation-sidebar")
        self.sidebar_list.set_header_func(self._sidebar_header)
        self._fill_sidebar()
        self.sidebar_list.connect("row-selected", self._on_row_selected)
        toolbar = Adw.ToolbarView(
            content=Gtk.ScrolledWindow(child=self.sidebar_list, hscrollbar_policy=Gtk.PolicyType.NEVER)
        )
        toolbar.add_top_bar(Adw.HeaderBar(show_title=False))
        return toolbar

    def _fill_sidebar(self):
        self.sidebar_list.remove_all()
        self.rows = {}
        if self.after_hours:
            entries = (
                [("after:featured", "Featured", "superlion-featured-symbolic", "after")]
                + [(key, title, icon, "after") for key, title, icon, _options in AFTER_HOURS_LISTS]
                + [(f"after:genre:{tag}", name, icon, "browse") for name, tag, icon in AFTER_HOURS_GENRES]
                + [("leave", "Back to the Store", "go-previous-symbolic", "leave")]
            )
        else:
            entries = (
                [("featured", "Featured", "superlion-featured-symbolic", "store")]
                + [(key, title, icon, "store") for key, title, icon in CATEGORIES]
                + [("genre:Free to Play", "Free to Play", "superlion-free-symbolic", "store"),
                   ("wishlist", "Wishlist", "starred-symbolic", "you"),
                   ("cart", "Cart", "superlion-cart-symbolic", "you")]
                + [(f"genre:{genre}", genre, GENRES[genre], "browse") for genre in self.genres]
            )
        for key, title, icon, section in entries:
            self.rows[key] = SidebarRow(key, title, icon, section)
            self.sidebar_list.append(self.rows[key])
        self._show_counts()

    def _show_counts(self):
        if "wishlist" in self.rows:
            self.rows["wishlist"].count.set_label(str(len(self.wishlist_ids)) if self.wishlist_ids else "")
            count = len((self.cart or {}).get("line_items", []))
            self.rows["cart"].count.set_label(str(count) if count else "")

    def sort_genres(self, games):
        """Put the genres most common among the user's games first."""
        counts = {genre: 0 for genre in self.genres}
        for game in games:
            for genre in game.props.genres or []:
                if genre in counts:
                    counts[genre] += 1
            if game.props.vr:
                counts["VR"] += 1
        self.genres.sort(key=lambda g: -counts[g])
        if not self.after_hours:
            selected = self.sidebar_list.get_selected_row()
            self._fill_sidebar()
            if selected is not None and selected.key in self.rows:
                self.sidebar_list.select_row(self.rows[selected.key])

    def _sidebar_header(self, row, before):
        if row.section in SECTION_TITLES and (before is None or before.section != row.section):
            label = Gtk.Label(label=SECTION_TITLES[row.section], xalign=0, margin_start=12, margin_top=12,
                              margin_bottom=6)
            label.add_css_class("heading")
            label.add_css_class("dim-label")
            if row.section == "browse" and not self.after_hours:
                click = Gtk.GestureClick()
                click.connect("pressed", lambda *_: self._on_secret_click())
                label.add_controller(click)
            row.set_header(label)
        else:
            row.set_header(None)

    def _on_secret_click(self):
        now = GLib.get_monotonic_time()
        self._secret_clicks = [t for t in self._secret_clicks if now - t < SECRET_WINDOW] + [now]
        if len(self._secret_clicks) < SECRET_CLICKS:
            return
        self._secret_clicks = []
        alert = Adw.AlertDialog(
            heading="Are You 18 or Older?",
            body="After Hours lists games with explicit sexual content. It is only for people aged 18 or older.",
        )
        alert.add_response("cancel", "Cancel")
        alert.add_response("enter", "I Am 18 or Older")
        alert.set_close_response("cancel")
        alert.connect("response", lambda _a, response: response == "enter" and self.set_after_hours(True))
        alert.present(self.window)

    def set_after_hours(self, on):
        """Switch the sidebar and views between the store and After Hours."""
        self.after_hours = on
        self.view = "after:featured" if on else "featured"
        self.search_entry.set_placeholder_text("Search After Hours" if on else "Search the store")
        self._fill_sidebar()
        self.sidebar_list.select_row(self.rows[self.view])

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
            self.featured = data
            if self.sidebar_list.get_selected_row() is None:
                self.sidebar_list.select_row(self.rows["featured"])
            else:
                self._show_view()

        auth.run_async(lambda: store_api.featured(region), done)
        self.refresh_counts()

    def refresh_counts(self):
        config = self.window.config
        if config is None or not config.account_id:
            return

        def done(ids, error):
            if error or ids is None:
                if self.view == "wishlist":
                    self.stack.set_visible_child_name("error")
                return
            self.wishlist_ids = ids
            self._show_counts()
            if self.view == "wishlist":
                self._show_wishlist()

        def with_state(state):
            state = state or {}
            self.signed_in, self.cart = state.get("signed_in", False), state.get("cart") or {}
            if self.view == "cart":
                self._show_cart()
            token = state.get("token", "")
            auth.run_async(lambda: store_account.wishlist(auth.steamid64(config), token), done)

        run_in_store(STATE_SCRIPT, {"country": self.window.store_region}, with_state)

    def _on_row_selected(self, _list, row):
        if row is None:
            return
        if row.key == "leave":
            GLib.idle_add(lambda: (self.set_after_hours(False), GLib.SOURCE_REMOVE)[-1])
            return
        self.view = row.key
        if self.search_entry.get_text():
            self.search_entry.set_text("")  # Shows the view.
        else:
            self._show_view()
        if self.window.split.get_collapsed():
            self.window.split.set_show_sidebar(False)

    def _show_view(self):
        self._serial += 1
        if not self.loaded_region:
            return
        if self.view.startswith("after:"):
            self._show_after_hours()
        elif self.view == "featured":
            self._show_sections([(title, self.featured.get(key, [])) for key, title, _icon in CATEGORIES])
        elif self.view == "wishlist":
            self._show_wishlist()
        elif self.view == "cart":
            self._show_cart()
        elif self.view.startswith("genre:"):
            self._show_genre(self.view.partition(":")[2])
        else:
            title = next(t for k, t, _i in CATEGORIES if k == self.view)
            self._show_grid(title, self.featured.get(self.view, []))

    def _show_sections(self, sections):
        """Each section as a heading and a row of capsules, as on the store's home page."""
        while child := self.home.get_first_child():
            self.home.remove(child)
        for title, items in sections:
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

    def _show_grid(self, title, items):
        self.grid_title.set_label(title)
        self.grid.remove_all()
        seen = set()
        for item in items:
            if item["id"] not in seen:
                seen.add(item["id"])
                self.grid.append(Capsule(item, self.window.open_store_app))
        self.stack.set_visible_child_name("grid")

    def _show_genre(self, genre):
        serial, region = self._serial, self.window.store_region
        self.stack.set_visible_child_name("loading")

        def work():
            lists = store_api.genre(genre, region)
            found = store_api.items([a for ids in lists.values() for a in ids], region)
            order = ["Top Sellers", "Specials", "New Releases", "Popular New Releases", "Coming Soon"]
            ordered = sorted(lists.items(), key=lambda tab: order.index(tab[0]) if tab[0] in order else len(order))
            return [(title, [found[a] for a in ids if a in found]) for title, ids in ordered]

        def done(sections, error):
            if serial != self._serial:
                return  # Another view was chosen meanwhile.
            if error:
                self.error_page.set_description("Check your internet connection and try again.")
                self.stack.set_visible_child_name("error")
                return
            self._show_sections(sections)

        auth.run_async(work, done)

    def _show_after_hours(self):
        """An After Hours view: its home and genres in sections like the store's, its lists as a grid."""
        serial, region, view = self._serial, self.window.store_region, self.view
        lists = {key: (title, options) for key, title, _icon, options in AFTER_HOURS_LISTS}
        self.stack.set_visible_child_name("loading")

        def sections(tagid=None):
            return [
                (title, store_api.after_hours(region, tagid=tagid, **options))
                for key, (title, options) in lists.items() if key != "after:free"
            ]

        def work():
            if view == "after:featured":
                return sections()
            if view.startswith("after:genre:"):
                return sections(int(view.rpartition(":")[2]))
            title, options = lists[view]
            return title, store_api.after_hours(region, **options)

        def done(result, error):
            if serial != self._serial:
                return  # Another view was chosen meanwhile.
            if error:
                self.error_page.set_description("Check your internet connection and try again.")
                self.stack.set_visible_child_name("error")
            elif view in lists:
                self._show_grid(*result)
            else:
                self._show_sections(result)

        auth.run_async(work, done)

    def _build_wishlist_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=12, margin_bottom=24,
                      margin_start=12, margin_end=12)
        header = Gtk.Box(spacing=12)
        title = Gtk.Label(label="Wishlist", xalign=0, hexpand=True)
        title.add_css_class("title-2")
        header.append(title)
        self.wishlist_sort = Gtk.DropDown(
            model=Gtk.StringList.new([label for label, _key in WISHLIST_SORTS]), valign=Gtk.Align.CENTER,
            tooltip_text="Sort By",
        )
        self.wishlist_sort.connect("notify::selected", lambda *_: self._fill_wishlist())
        header.append(self.wishlist_sort)
        box.append(header)
        self.wishlist_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.wishlist_list.add_css_class("boxed-list")
        box.append(self.wishlist_list)
        self.wishlist_status = Adw.StatusPage(icon_name="starred-symbolic", vexpand=True)
        self.wishlist_button = Gtk.Button(label="Sign In to the Store", halign=Gtk.Align.CENTER)
        self.wishlist_button.add_css_class("pill")
        self.wishlist_button.connect("clicked", lambda *_: self.window.open_web(LOGIN_URL, "Sign In"))
        self.wishlist_status.set_child(self.wishlist_button)
        box.append(self.wishlist_status)
        return _scroller(Adw.Clamp(child=box, maximum_size=860))

    def _show_wishlist(self):
        config = self.window.config
        if not config or not config.account_id:
            self._wishlist_message("No Steam Account", "Choose your Steam account in Preferences to see your wishlist.")
            return
        if self.wishlist_ids is None:
            self.stack.set_visible_child_name("loading")
            return  # refresh_counts() shows it once loaded.
        if not self.wishlist_ids:
            if self.signed_in:
                self._wishlist_message("Your Wishlist Is Empty", "Games you add to your wishlist appear here.")
            else:
                self._wishlist_message(
                    "No Wishlist Found", "Your wishlist is empty or private. Sign in to the store to see a private one.",
                    sign_in=True,
                )
            return
        missing = [a for a in self.wishlist_ids if a not in self.wishlist_items]
        if not missing:
            self._fill_wishlist()
            return
        serial, region = self._serial, self.window.store_region
        self.stack.set_visible_child_name("loading")

        def done(found, error):
            if serial != self._serial:
                return
            if error:
                self.stack.set_visible_child_name("error")
                return
            self.wishlist_items.update(found)
            self._fill_wishlist()

        auth.run_async(lambda: store_api.items(missing, region), done)

    def _wishlist_message(self, title, description, sign_in=False):
        self.wishlist_list.set_visible(False)
        self.wishlist_sort.set_visible(False)
        self.wishlist_status.set_visible(True)
        self.wishlist_status.set_title(title)
        self.wishlist_status.set_description(description)
        self.wishlist_button.set_visible(sign_in)
        self.stack.set_visible_child_name("wishlist")

    def _fill_wishlist(self):
        if not self.wishlist_ids:
            return
        self.wishlist_list.remove_all()
        items = [self.wishlist_items[a] for a in self.wishlist_ids if a in self.wishlist_items]
        sort_key = WISHLIST_SORTS[self.wishlist_sort.get_selected()][1]
        if sort_key:
            items.sort(key=sort_key)
        for item in items:
            row = Adw.ActionRow(title=GLib.markup_escape_text(item["name"]), activatable=True)
            if item.get("release"):
                row.set_subtitle(GLib.DateTime.new_from_unix_local(item["release"]).format("%-d %B %Y"))
            thumb = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, can_shrink=True,
                                width_request=120, height_request=45, valign=Gtk.Align.CENTER)
            thumb.add_css_class("card")
            images.load(item.get("tiny_image", ""), 240, 90, thumb.set_paintable)
            row.add_prefix(thumb)
            price = Gtk.Label(label=item_price(item), valign=Gtk.Align.CENTER)
            if item.get("discounted"):
                price.add_css_class("success")
                price.set_tooltip_text(f"On sale, was {item['original_text']}")
            row.add_suffix(price)
            remove = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text="Remove From Wishlist",
                                valign=Gtk.Align.CENTER)
            remove.add_css_class("flat")
            remove.connect("clicked", lambda _b, i=item: self.set_wishlisted(i["id"], i["name"], False))
            row.add_suffix(remove)
            row.connect("activated", lambda _r, i=item: self.window.open_store_app(i["id"], i["name"]))
            self.wishlist_list.append(row)
        self.wishlist_list.set_visible(True)
        self.wishlist_sort.set_visible(True)
        self.wishlist_status.set_visible(False)
        self.stack.set_visible_child_name("wishlist")

    def show_cart(self):
        """Open the Store at the cart."""
        if self.after_hours:
            self.set_after_hours(False)
        self.window.view_stack.set_visible_child_name("store")
        self.sidebar_list.select_row(self.rows["cart"])

    def _build_cart_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=12, margin_bottom=24,
                      margin_start=12, margin_end=12)
        title = Gtk.Label(label="Cart", xalign=0)
        title.add_css_class("title-2")
        box.append(title)
        self.cart_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.cart_list.add_css_class("boxed-list")
        box.append(self.cart_list)
        self.cart_footer = Gtk.Box(spacing=12)
        self.cart_total = Gtk.Label(xalign=0, hexpand=True)
        self.cart_total.add_css_class("title-3")
        self.cart_footer.append(self.cart_total)
        checkout = Gtk.Button(label="Check Out")
        checkout.add_css_class("pill")
        checkout.add_css_class("suggested-action")
        checkout.connect("clicked", lambda *_: self.window.open_web(CHECKOUT_URL, "Checkout"))
        self.cart_footer.append(checkout)
        box.append(self.cart_footer)
        self.cart_status = Adw.StatusPage(icon_name="superlion-cart-symbolic", vexpand=True)
        self.cart_button = Gtk.Button(label="Sign In to the Store", halign=Gtk.Align.CENTER)
        self.cart_button.add_css_class("pill")
        self.cart_button.connect("clicked", lambda *_: self.window.open_web(LOGIN_URL, "Sign In"))
        self.cart_status.set_child(self.cart_button)
        box.append(self.cart_status)
        return _scroller(Adw.Clamp(child=box, maximum_size=860))

    def _show_cart(self):
        if self.cart is None:
            self.stack.set_visible_child_name("loading")
            return  # refresh_counts() shows it once loaded.
        lines = self.cart.get("line_items", [])
        if not lines:
            if self.signed_in:
                self._cart_message("Your Cart Is Empty", "Games you add to your cart appear here.")
            else:
                self._cart_message("Not Signed In", "Sign in to the store to use your cart.", sign_in=True)
            return
        serial, region = self._serial, self.window.store_region
        self.stack.set_visible_child_name("loading")

        def done(found, error):
            if serial != self._serial:
                return
            if error:
                self.stack.set_visible_child_name("error")
                return
            self._fill_cart(found)

        auth.run_async(lambda: store_api.cart_items(lines, region), done)

    def _cart_message(self, title, description, sign_in=False):
        self.cart_list.set_visible(False)
        self.cart_footer.set_visible(False)
        self.cart_status.set_visible(True)
        self.cart_status.set_title(title)
        self.cart_status.set_description(description)
        self.cart_button.set_visible(sign_in)
        self.stack.set_visible_child_name("cart")

    def _fill_cart(self, found):
        self.cart_list.remove_all()
        for item in found:
            row = Adw.ActionRow(title=GLib.markup_escape_text(item["name"]))
            if item["gift"]:
                row.set_subtitle("Gift")
            thumb = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, can_shrink=True,
                                width_request=120, height_request=45, valign=Gtk.Align.CENTER)
            thumb.add_css_class("card")
            images.load(item["image"], 240, 90, thumb.set_paintable)
            row.add_prefix(thumb)
            price = Gtk.Label(label=item_price({**item, "discounted": bool(item["discount_percent"])}),
                              valign=Gtk.Align.CENTER)
            if item["discount_percent"]:
                price.add_css_class("success")
                price.set_tooltip_text(f"On sale, was {item['original_text']}")
            row.add_suffix(price)
            remove = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text="Remove From Cart",
                                valign=Gtk.Align.CENTER)
            remove.add_css_class("flat")
            remove.connect("clicked", lambda button, i=item: self._remove_from_cart(button, i))
            row.add_suffix(remove)
            self.cart_list.append(row)
        subtotal = (self.cart.get("subtotal") or {}).get("formatted_amount", "")
        self.cart_total.set_label(f"Total: {subtotal}" if subtotal else "")
        self.cart_list.set_visible(True)
        self.cart_footer.set_visible(True)
        self.cart_status.set_visible(False)
        self.stack.set_visible_child_name("cart")

    def _cart_call(self, method, request, done):
        """Call a cart API method; done(cart) gets the updated cart, or None if it failed or needs a sign-in."""
        def finished(result):
            if result is not None and not result.get("signed_in"):
                self.window.open_web(LOGIN_URL, "Sign In")
                self.window.toast("Sign in to the store to use your cart")
                done(None)
                return
            cart = ((result or {}).get("response") or {}).get("cart") if (result or {}).get("ok") else None
            if cart is not None:
                self.signed_in, self.cart = True, cart
                self._show_counts()
                if self.view == "cart" and self.stack.get_visible_child_name() == "cart":
                    self._show_cart()
            done(cart)

        run_in_store(CART_SCRIPT, {"method": method, "request": json.dumps(request)}, finished)

    def add_to_cart(self, option, done):
        """Add a purchase option from store_api.purchase_options() to the cart; done() afterwards."""
        item = {key: option[key] for key in ("packageid", "bundleid") if key in option}

        def added(cart):
            done()
            if cart is None:
                self.window.toast(f"{option['name']} could not be added to your cart")
            else:
                self.window.toast(f"{option['name']} added to your cart")

        self._cart_call("AddItemsToCart", {"user_country": self.window.store_region, "items": [item]}, added)

    def _remove_from_cart(self, button, item):
        button.set_sensitive(False)

        def removed(cart):
            if cart is None:
                button.set_sensitive(True)
                self.window.toast(f"{item['name']} could not be removed from your cart")

        request = {"line_item_id": item["line_item_id"], "user_country": self.window.store_region}
        self._cart_call("RemoveItemFromCart", request, removed)

    def set_wishlisted(self, appid, name, add, done=None):
        """Add a game to the wishlist or remove it, signing in first if needed; done() after a change."""

        def finished(result):
            if result is not None and not result.get("signed_in"):
                self.window.open_web(LOGIN_URL, "Sign In")
                self.window.toast("Sign in to the store to change your wishlist")
                return
            if not (result and result.get("success")):
                self.window.toast("Your wishlist could not be changed")
                return
            self.signed_in = True
            ids = self.wishlist_ids if self.wishlist_ids is not None else []
            self.wishlist_ids = [a for a in ids if a != appid] + ([appid] if add else [])
            self._show_counts()
            self.window.toast(f"{name} {'added to' if add else 'removed from'} your wishlist")
            if self.view == "wishlist" and self.stack.get_visible_child_name() == "wishlist":
                self._show_wishlist()
            if done:
                done()

        action = "addtowishlist" if add else "removefromwishlist"
        run_in_store(WISHLIST_SCRIPT, {"appid": appid, "action": action}, finished)

    def _on_search_changed(self, entry):
        term = entry.get_text().strip()
        self._search_serial += 1
        serial = self._search_serial
        if not term:
            if self.loaded_region:
                self._show_view()
            else:
                self.stack.set_visible_child_name("loading")
            return
        region = self.window.store_region

        def done(items, error):
            if serial != self._search_serial:
                return  # A newer search has started.
            if error:
                self.stack.set_visible_child_name("error")
                return
            self._show_results(items)

        search = store_api.after_hours_search if self.after_hours else store_api.search
        auth.run_async(lambda: search(term, region), done)

    def _show_results(self, items):
        self.results.remove_all()
        for item in items:
            row = Adw.ActionRow(
                title=GLib.markup_escape_text(item.get("name", "")),
                subtitle=item_price(item) if "price_text" in item else search_price(item),
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
        cart.connect("clicked", lambda *_: (window.nav.pop_to_tag("main"), window.store_view.show_cart()))
        header.pack_end(cart)
        toolbar.add_top_bar(header)
        self.set_child(toolbar)

        region = window.store_region

        def load():
            data = store_api.details(appid, region)
            summary, options = None, []
            if data:
                try:
                    summary = store_api.reviews(appid)
                except Exception:  # The review summary is optional.
                    summary = None
                try:
                    options = store_api.purchase_options(appid, region)
                except Exception:  # Buying falls back to Steam's page.
                    options = []
            return data, summary, options

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

    def _build(self, data, summary, options):
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

        self.content.append(self._build_buttons(data, options))

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

    def _build_buttons(self, data, options):
        box = Gtk.Box(spacing=12)
        game = self.window.find_game(self.appid)
        page_url = f"{store_api.STORE}/app/{self.appid}/"
        if game is not None and game.props.installed:
            primary = Gtk.Button(label="Play")
            primary.connect("clicked", lambda *_: self._open_uri(f"steam://rungameid/{self.appid}"))
        elif game is not None:
            primary = Gtk.Button(label="Install")
            primary.connect("clicked", lambda *_: self.window.install_game(self.appid, game.props.name))
        elif len(options) == 1:
            primary = Gtk.Button(label="Add to Cart")
            primary.connect("clicked", lambda *_: self._add_to_cart(options[0]))
        elif options:
            primary = Gtk.MenuButton(label="Add to Cart", popover=self._options_popover(options),
                                     always_show_arrow=True)
        else:
            primary = Gtk.Button(label="Buy")
            primary.connect("clicked", lambda *_: self.window.open_web(page_url, data.get("name", "Store")))
        primary.add_css_class("suggested-action")
        primary.add_css_class("pill")
        box.append(primary)
        self.add_button = primary

        if game is None:
            self.wishlist_button = Gtk.Button()
            self.wishlist_button.add_css_class("pill")
            self.wishlist_button.connect("clicked", lambda *_: self._toggle_wishlist(data.get("name", "")))
            self._show_wishlisted()
            box.append(self.wishlist_button)

        client = Gtk.Button(label="Open in Steam Client")
        client.add_css_class("pill")
        client.add_css_class("flat")
        client.connect("clicked", lambda *_: self._open_uri(f"steam://store/{self.appid}"))
        box.append(client)
        return box

    def _options_popover(self, options):
        """A menu of a game's editions and bundles, each with its price."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        popover = Gtk.Popover(child=box)
        popover.add_css_class("menu")
        for option in options:
            content = Gtk.Box(spacing=24)
            content.append(Gtk.Label(label=option["name"], xalign=0, hexpand=True))
            price = Gtk.Label(label=item_price({**option, "discounted": bool(option["discount_percent"])}))
            price.add_css_class("success" if option["discount_percent"] else "dim-label")
            content.append(price)
            button = Gtk.Button(child=content)
            button.add_css_class("flat")
            button.connect("clicked", lambda _b, o=option: (popover.popdown(), self._add_to_cart(o)))
            box.append(button)
        return popover

    def _add_to_cart(self, option):
        self.add_button.set_sensitive(False)
        self.window.store_view.add_to_cart(option, lambda: self.add_button.set_sensitive(True))

    def _on_wishlist(self):
        ids = self.window.store_view.wishlist_ids
        return ids is not None and self.appid in ids

    def _show_wishlisted(self):
        if self._on_wishlist():
            self.wishlist_button.set_child(Adw.ButtonContent(icon_name="object-select-symbolic", label="On Wishlist"))
            self.wishlist_button.set_tooltip_text("Remove From Wishlist")
        else:
            self.wishlist_button.set_child(Adw.ButtonContent(icon_name="starred-symbolic", label="Add to Wishlist"))
            self.wishlist_button.set_tooltip_text(None)

    def _toggle_wishlist(self, name):
        self.window.store_view.set_wishlisted(self.appid, name, not self._on_wishlist(), self._show_wishlisted)

    def _open_uri(self, uri):
        try:
            steam_control.open_uri(self.window.config, uri)
        except GLib.Error as error:
            self.window.toast(f"Steam could not be opened: {error.message}")


def open_web(window, url, title):
    window.nav.push(SteamWebPage(window, url, title))
