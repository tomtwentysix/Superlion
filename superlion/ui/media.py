"""Store media and text shared by the store page and the game details page."""

import html
import re

import gi
from gi.repository import Adw, GLib, Gtk, Pango

from . import images

MAX_TRAILERS = 4
MAX_SCREENSHOTS = 12
MEDIA_HEIGHT = 420


def plain_text(markup):
    """Store descriptions and news posts contain HTML or BBCode; keep the text only."""
    text = markup or ""
    text = re.sub(r"(?i)<br\s*/?>|</p>|</li>|\[/?(p|h\d|list|\*)(?:[= ][^\]]*)?\]", "\n", text)
    text = re.sub(r"(?s)\[img\].*?\[/img\]|\{STEAM_CLAN_IMAGE\}\S*", "", text)
    text = re.sub(r"(?i)<[^>]+>|\[/?[a-z0-9]+(?:[= ][^\]]*)?\]", "", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


class TrailerTile(Gtk.Overlay):
    """A trailer thumbnail that becomes a video player when Play is pressed.

    Steam serves trailers as HLS streams. They are played by GStreamer's
    playbin3 given the web address directly: GTK's own media file reads the
    playlist as a plain stream, which loses the address the playlist's relative
    segment paths depend on. Streams are only opened on demand.
    """

    def __init__(self, movie):
        super().__init__(height_request=MEDIA_HEIGHT, hexpand=True, overflow=Gtk.Overflow.HIDDEN)
        self.add_css_class("card")
        self.uri = movie.get("hls_h264") or movie.get("dash_h264") or ""
        self.pipeline = None

        self.poster = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, can_shrink=True)
        images.load(movie.get("thumbnail", ""), 1280, 720, self.poster.set_paintable)
        self.screen = Gtk.Picture(content_fit=Gtk.ContentFit.CONTAIN, can_shrink=True)
        self.screen.add_css_class("trailer-screen")
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.stack.add_named(self.poster, "poster")
        self.stack.add_named(self.screen, "video")
        self.set_child(self.stack)

        self.play_button = self._osd_button(
            "media-playback-start-symbolic", f"Play {movie.get('name', 'Trailer')}",
            Gtk.Align.CENTER, Gtk.Align.CENTER, 64,
        )
        self.play_button.connect("clicked", lambda *_: self.play())
        self.toggle_button = self._osd_button(
            "media-playback-pause-symbolic", "Pause", Gtk.Align.START, Gtk.Align.END, 40,
        )
        self.toggle_button.set_margin_start(12)
        self.toggle_button.set_margin_bottom(12)
        self.toggle_button.set_visible(False)
        self.toggle_button.connect("clicked", lambda *_: self._toggle())

        self.caption = Gtk.Label(
            label=movie.get("name", ""), halign=Gtk.Align.START, valign=Gtk.Align.END,
            margin_start=12, margin_bottom=12, ellipsize=Pango.EllipsizeMode.END,
        )
        self.caption.add_css_class("osd")
        self.caption.add_css_class("caption")
        self.add_overlay(self.caption)

    def _osd_button(self, icon, tooltip, halign, valign, size):
        button = Gtk.Button(
            icon_name=icon, tooltip_text=tooltip, halign=halign, valign=valign,
            width_request=size, height_request=size,
        )
        button.add_css_class("circular")
        button.add_css_class("osd")
        self.add_overlay(button)
        return button

    def play(self):
        if not self.uri or not _init_gstreamer():
            return
        if self.pipeline is None:
            self.pipeline = Gst.ElementFactory.make("playbin3")
            sink = Gst.ElementFactory.make("gtk4paintablesink")
            if self.pipeline is None or sink is None:
                self.pipeline = None
                return
            self.pipeline.set_property("video-sink", sink)
            self.pipeline.set_property("uri", self.uri)
            self.screen.set_paintable(sink.get_property("paintable"))
            bus = self.pipeline.get_bus()
            bus.add_signal_watch()
            bus.connect("message::eos", lambda *_: self.stop())
            bus.connect("message::error", lambda *_: self.stop())
        self.pipeline.set_state(Gst.State.PLAYING)
        self.stack.set_visible_child_name("video")
        self.play_button.set_visible(False)
        self.caption.set_visible(False)
        self.toggle_button.set_visible(True)
        self.toggle_button.set_icon_name("media-playback-pause-symbolic")
        self.toggle_button.set_tooltip_text("Pause")

    def pause(self):
        if self.pipeline is not None:
            self.pipeline.set_state(Gst.State.PAUSED)
            self.toggle_button.set_icon_name("media-playback-start-symbolic")
            self.toggle_button.set_tooltip_text("Play")

    def _toggle(self):
        _ok, state, _pending = self.pipeline.get_state(0)
        if state == Gst.State.PLAYING:
            self.pause()
        else:
            self.play()

    def stop(self):
        """Release the stream and show the thumbnail again."""
        if self.pipeline is not None:
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline.get_bus().remove_signal_watch()
            self.pipeline = None
        self.stack.set_visible_child_name("poster")
        self.play_button.set_visible(True)
        self.caption.set_visible(True)
        self.toggle_button.set_visible(False)


_gst_ready = None


def _init_gstreamer():
    """Load GStreamer on first use; False when it is unavailable."""
    global _gst_ready, Gst
    if _gst_ready is None:
        try:
            gi.require_version("Gst", "1.0")
            from gi.repository import Gst as _Gst

            _Gst.init(None)
            Gst = _Gst
            _gst_ready = True
        except (ValueError, ImportError):
            _gst_ready = False
    return _gst_ready


Gst = None


class MediaCarousel(Gtk.Box):
    """Trailers followed by screenshots, with arrows and page dots."""

    def __init__(self, data):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.carousel = Adw.Carousel(allow_scroll_wheel=False, spacing=12)
        self.trailers = []

        for movie in (data.get("movies") or [])[:MAX_TRAILERS]:
            tile = TrailerTile(movie)
            self.trailers.append(tile)
            self.carousel.append(tile)
        for shot in (data.get("screenshots") or [])[:MAX_SCREENSHOTS]:
            picture = Gtk.Picture(
                content_fit=Gtk.ContentFit.COVER, can_shrink=True,
                height_request=MEDIA_HEIGHT, hexpand=True,
            )
            picture.add_css_class("card")
            images.load(shot.get("path_full", ""), 1280, 720, picture.set_paintable)
            self.carousel.append(picture)

        # Leaving a trailer pauses it, so sound never plays from a hidden page.
        self.carousel.connect("page-changed", lambda *_: self.pause())

        overlay = Gtk.Overlay(child=self.carousel)
        for icon, align, delta in (
            ("go-previous-symbolic", Gtk.Align.START, -1),
            ("go-next-symbolic", Gtk.Align.END, 1),
        ):
            button = Gtk.Button(
                icon_name=icon, valign=Gtk.Align.CENTER, halign=align, margin_start=12, margin_end=12
            )
            button.add_css_class("circular")
            button.add_css_class("osd")
            button.connect("clicked", lambda _b, d=delta: self._step(d))
            overlay.add_overlay(button)
        self.append(overlay)
        self.append(Adw.CarouselIndicatorDots(carousel=self.carousel))

    @property
    def is_empty(self):
        return self.carousel.get_n_pages() == 0

    def pause(self):
        for tile in self.trailers:
            tile.pause()

    def stop(self):
        """Close every trailer stream; used when the page is closed."""
        for tile in self.trailers:
            tile.stop()

    def _step(self, delta):
        count = self.carousel.get_n_pages()
        if count:
            index = (round(self.carousel.get_position()) + delta) % count
            self.carousel.scroll_to(self.carousel.get_nth_page(index), True)


def description_widgets(data):
    """The short description, plus the full "About This Game" text in an expander."""
    widgets = []
    short = plain_text(data.get("short_description"))
    if short:
        widgets.append(Gtk.Label(label=short, wrap=True, xalign=0))
    about = plain_text(data.get("about_the_game"))
    if about and about != short:
        group = Adw.PreferencesGroup()
        expander = Adw.ExpanderRow(title="About This Game")
        body = Gtk.Label(
            label=about[:6000], wrap=True, xalign=0, selectable=True,
            margin_top=12, margin_bottom=12, margin_start=12, margin_end=12,
        )
        expander.add_row(body)
        group.add(expander)
        widgets.append(group)
    return widgets


def news_group(items, open_web):
    """Developer announcements as expandable rows with a link to the full post."""
    group = Adw.PreferencesGroup(title="Developer Updates")
    for item in items:
        date = GLib.DateTime.new_from_unix_local(int(item.get("date", 0))).format("%-d %B %Y")
        expander = Adw.ExpanderRow(
            title=GLib.markup_escape_text(item.get("title", "")),
            subtitle=GLib.markup_escape_text(date),
        )
        text = plain_text(item.get("contents"))
        if len(text) > 900:
            text = text[:900].rsplit(" ", 1)[0] + "…"
        body = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=12,
            margin_top=12, margin_bottom=12, margin_start=12, margin_end=12,
        )
        body.append(Gtk.Label(label=text or "No preview is available.", wrap=True, xalign=0, selectable=True))
        if item.get("url"):
            read = Gtk.Button(label="Read Full Post", halign=Gtk.Align.START)
            read.add_css_class("pill")
            read.connect("clicked", lambda _b, u=item["url"], t=item.get("title", "Update"): open_web(u, t))
            body.append(read)
        expander.add_row(body)
        group.add(expander)
    return group
