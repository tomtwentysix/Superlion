"""Choosing which Steam store game a non-Steam game should be shown as."""

from gi.repository import Adw, GLib, GObject, Gtk

from .. import auth, library, store_api
from . import images
from .store import search_price


class MatchDialog(Adw.Dialog):
    """Searches the Steam store; emits "chosen" with an app ID, or 0 for "not on Steam"."""

    __gsignals__ = {"chosen": (GObject.SignalFlags.RUN_FIRST, None, (GObject.TYPE_INT64,))}

    def __init__(self, window, game):
        super().__init__(title="Match to Steam Game", content_width=560, content_height=620)
        self.window = window
        self._serial = 0

        self.entry = Gtk.SearchEntry(
            text=library.artwork_search_term(game.props.name), hexpand=True, placeholder_text="Search the Steam store"
        )
        self.entry.connect("search-changed", lambda *_: self._search())
        intro = Gtk.Label(
            label=(
                f"Choose the Steam game that “{game.props.name}” is, to show its store page, "
                "screenshots, news, release date, genres and artwork. Nothing is changed in Steam."
            ),
            wrap=True, xalign=0,
        )
        intro.add_css_class("dim-label")

        self.results = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.results.add_css_class("boxed-list")
        self.stack = Gtk.Stack(vexpand=True)
        self.stack.add_named(Gtk.ScrolledWindow(child=self.results, hscrollbar_policy=Gtk.PolicyType.NEVER), "results")
        self.stack.add_named(Adw.Spinner(), "loading")
        self.stack.add_named(
            Adw.StatusPage(icon_name="system-search-symbolic", title="No Matches",
                           description="Try a shorter or different name."), "empty")

        not_on_steam = Gtk.Button(label="Not on Steam", halign=Gtk.Align.CENTER)
        not_on_steam.add_css_class("pill")
        not_on_steam.set_tooltip_text("Show this game without store information, and stop matching it automatically")
        not_on_steam.connect("clicked", lambda *_: self._choose(0))

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=6, margin_bottom=18,
                      margin_start=18, margin_end=18)
        for widget in (intro, self.entry, self.stack, not_on_steam):
            box.append(widget)
        toolbar = Adw.ToolbarView(content=box)
        toolbar.add_top_bar(Adw.HeaderBar())
        self.set_child(toolbar)
        self._search()

    def _search(self):
        term = self.entry.get_text().strip()
        self._serial += 1
        serial = self._serial
        if not term:
            self.stack.set_visible_child_name("empty")
            return
        self.stack.set_visible_child_name("loading")
        region = self.window.store_region

        def done(items, error):
            if serial != self._serial:
                return  # A newer search has started.
            self.results.remove_all()
            for item in items or []:
                row = Adw.ActionRow(
                    title=GLib.markup_escape_text(item.get("name", "")),
                    subtitle=GLib.markup_escape_text(f"App {item['id']} · {search_price(item)}"),
                    activatable=True,
                )
                thumb = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, can_shrink=True,
                                    width_request=120, height_request=45, valign=Gtk.Align.CENTER)
                thumb.add_css_class("card")
                images.load(item.get("tiny_image", ""), 240, 90, thumb.set_paintable)
                row.add_prefix(thumb)
                row.connect("activated", lambda _r, appid=item["id"]: self._choose(appid))
                self.results.append(row)
            self.stack.set_visible_child_name("results" if items and not error else "empty")

        auth.run_async(lambda: store_api.search(term, region), done)

    def _choose(self, appid):
        self.emit("chosen", appid)
        self.close()
