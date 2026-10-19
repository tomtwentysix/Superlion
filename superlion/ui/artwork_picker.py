"""Choosing artwork from SteamGridDB inside the app, or from a file."""

from gi.repository import Adw, Gio, GLib, GObject, Gtk, Pango

from .. import auth, library, sgdb
from . import images
from .sgdb_setup import SgdbKeySetup

THUMBS = {"cover": (120, 180), "header": (230, 108), "hero": (320, 103), "logo": (240, 96)}
PAGE_SIZE = 50  # SteamGridDB returns up to 50 images per page.


def choose_file(parent, kind, callback):
    """Ask for an image file of artwork; callback(path) once one is chosen."""
    image_filter = Gtk.FileFilter(name="Images")
    for mime in ("image/png", "image/jpeg"):
        image_filter.add_mime_type(mime)
    filters = Gio.ListStore.new(Gtk.FileFilter)
    filters.append(image_filter)
    dialog = Gtk.FileDialog(title=f"Choose {library.ART_LABELS[kind]}", filters=filters, default_filter=image_filter)

    def done(dlg, result):
        try:
            path = dlg.open_finish(result).get_path()
        except GLib.Error:
            return  # Cancelled.
        callback(path)

    dialog.open(parent, None, done)


class ArtworkPicker(Adw.Dialog):
    """Shows SteamGridDB artwork of one kind, and offers a file instead; emits "chosen" with the image's path."""

    __gsignals__ = {"chosen": (GObject.SignalFlags.RUN_FIRST, None, (str,))}

    def __init__(self, window, game, kind):
        label = library.ART_LABELS[kind]
        super().__init__(title=f"Choose {label}", content_width=860, content_height=700)
        self.window = window
        self.game = game
        self.kind = kind
        self.key = sgdb.load_key()
        self.sgdb_game_id = None
        self.page = 0
        self._serial = 0

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.stack.add_named(self._build_key_page(), "key")
        self.stack.add_named(self._build_results_page(), "results")
        self.stack.add_named(Adw.Spinner(), "loading")
        self.message = Adw.StatusPage(icon_name="image-missing-symbolic")
        self.stack.add_named(self.message, "message")

        header = Adw.HeaderBar()
        from_file = Gtk.Button(label="From File…")
        from_file.connect("clicked", lambda *_: choose_file(
            window, kind, lambda path: (self.emit("chosen", path), self.close())))
        header.pack_start(from_file)
        menu = Gtk.MenuButton(icon_name="open-menu-symbolic", tooltip_text="More Options")
        popover_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_top=6, margin_bottom=6,
                              margin_start=6, margin_end=6)
        for text, callback in (
            ("Open on SteamGridDB Website", lambda: window.open_website(library.steamgriddb_url(game.props.name))),
            ("Change API Key…", lambda: self.stack.set_visible_child_name("key")),
        ):
            button = Gtk.Button(label=text)
            button.add_css_class("flat")
            button.connect("clicked", lambda _b, cb=callback: (menu.popdown(), cb()))
            popover_box.append(button)
        menu.set_popover(Gtk.Popover(child=popover_box))
        header.pack_end(menu)

        toolbar = Adw.ToolbarView(content=self.stack)
        toolbar.add_top_bar(header)
        self.set_child(toolbar)

        if self.key:
            self._start()
        else:
            self.stack.set_visible_child_name("key")

    def _build_key_page(self):
        setup = SgdbKeySetup(self.window)
        setup.connect("saved", lambda *_: (setattr(self, "key", sgdb.load_key()), self._start()))
        box = Adw.Clamp(child=setup, maximum_size=560, margin_top=12, margin_bottom=24,
                        margin_start=12, margin_end=12)
        return Gtk.ScrolledWindow(child=box, hscrollbar_policy=Gtk.PolicyType.NEVER)

    def _build_results_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        # Non-Steam games are found by name; the right match can be chosen if the first is wrong.
        self.search_bar = Gtk.Box(spacing=12, margin_top=12, margin_bottom=6, margin_start=12, margin_end=12)
        self.search_entry = Gtk.SearchEntry(
            text=library.artwork_search_term(self.game.props.name), hexpand=True,
            placeholder_text="Search SteamGridDB",
        )
        self.search_entry.connect("activate", lambda *_: self._search())
        self.search_bar.append(self.search_entry)
        self.matches = Gtk.DropDown(model=Gtk.StringList(), visible=False)
        self.matches.connect("notify::selected", self._on_match_selected)
        self.search_bar.append(self.matches)
        self.search_bar.set_visible(self.game.props.non_steam)
        box.append(self.search_bar)

        self.flow = Gtk.FlowBox(
            selection_mode=Gtk.SelectionMode.NONE, homogeneous=True, max_children_per_line=8,
            min_children_per_line=1, column_spacing=6, row_spacing=6,
            margin_top=6, margin_bottom=12, margin_start=12, margin_end=12, valign=Gtk.Align.START,
        )
        self.more_button = Gtk.Button(label="Show More", halign=Gtk.Align.CENTER, margin_bottom=24, visible=False)
        self.more_button.add_css_class("pill")
        self.more_button.connect("clicked", lambda *_: self._load_images(more=True))
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content.append(self.flow)
        content.append(self.more_button)
        box.append(Gtk.ScrolledWindow(child=content, vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER))
        return box

    def _show_message(self, title, description, icon="image-missing-symbolic"):
        self.message.set_title(title)
        self.message.set_description(description)
        self.message.set_icon_name(icon)
        self.stack.set_visible_child_name("message")

    def _start(self):
        if self.game.props.non_steam:
            self._search()
        else:
            self._load_images()

    def _search(self):
        term = self.search_entry.get_text().strip()
        if not term:
            return
        self.stack.set_visible_child_name("loading")
        self._serial += 1
        serial = self._serial

        def done(results, error):
            if serial != self._serial:
                return
            if self._handle_error(error):
                return
            self.match_results = results[:12]
            names = [
                r.get("name", "") + (" (verified)" if r.get("verified") else "") for r in self.match_results
            ]
            self.matches.set_model(Gtk.StringList.new(names))
            self.matches.set_visible(bool(names))
            if not names:
                self.stack.set_visible_child_name("results")
                self._show_message("No Games Found", f"SteamGridDB has no game called “{term}”. Try a different name.")
                return
            self.matches.set_selected(0)
            self._on_match_selected()

        auth.run_async(lambda: sgdb.search(term, self.key), done)

    def _on_match_selected(self, *_):
        index = self.matches.get_selected()
        if getattr(self, "match_results", None) and 0 <= index < len(self.match_results):
            self.sgdb_game_id = self.match_results[index]["id"]
            self._load_images()

    def _load_images(self, more=False):
        self.page = self.page + 1 if more else 0
        if not more:
            while child := self.flow.get_first_child():
                self.flow.remove(child)
            self.stack.set_visible_child_name("loading")
        self._serial += 1
        serial = self._serial
        steam_appid = None if self.game.props.non_steam else self.game.props.appid

        def done(items, error):
            if serial != self._serial:
                return
            if self._handle_error(error):
                return
            for item in items:
                self.flow.append(self._thumbnail(item))
            self.more_button.set_visible(len(items) >= PAGE_SIZE)
            if not more and not items:
                self._show_message(
                    "No Artwork Found",
                    f"SteamGridDB has no {library.ART_LABELS[self.kind].lower()} for this game yet.",
                )
                return
            self.stack.set_visible_child_name("results")

        auth.run_async(
            lambda: sgdb.images(self.kind, self.key, game_id=self.sgdb_game_id, steam_appid=steam_appid, page=self.page),
            done,
        )

    def _handle_error(self, error):
        if isinstance(error, sgdb.ApiKeyError):
            self.stack.set_visible_child_name("key")
            return True
        if error:
            self._show_message(
                "SteamGridDB Could Not Be Reached", "Check your internet connection and try again.",
                "network-offline-symbolic",
            )
            return True
        return False

    def _thumbnail(self, item):
        width, height = THUMBS[self.kind]
        picture = Gtk.Picture(content_fit=Gtk.ContentFit.CONTAIN, can_shrink=True)
        picture.set_size_request(width, height)
        frame = Gtk.Overlay(child=picture, overflow=Gtk.Overflow.HIDDEN)
        frame.add_css_class("card")
        images.load(item.get("thumb") or item.get("url", ""), width * 2, height * 2, picture.set_paintable)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.append(frame)
        author = (item.get("author") or {}).get("name", "")
        caption = Gtk.Label(label=f"{item.get('width', '?')} × {item.get('height', '?')}" + (f" · {author}" if author else ""),
                            ellipsize=Pango.EllipsizeMode.END, max_width_chars=1, hexpand=True)
        caption.add_css_class("caption")
        caption.add_css_class("dim-label")
        box.append(caption)

        button = Gtk.Button(child=box, tooltip_text="Use This Image")
        button.add_css_class("flat")
        button.connect("clicked", lambda *_: self._choose(item, button))
        return button

    def _choose(self, item, button):
        button.set_sensitive(False)

        def done(path, error):
            button.set_sensitive(True)
            if error:
                self.window.toast("The image could not be downloaded. Try again.")
                return
            self.emit("chosen", str(path))
            self.close()

        auth.run_async(lambda: sgdb.download(item["url"]), done)
