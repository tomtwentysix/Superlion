"""The Downloads section: Steam's active, paused and waiting downloads."""

from gi.repository import Adw, GLib, Gtk

from .. import auth, downloads, library, steam_control
from . import images

GROUPS = {
    "downloading": ("Downloading", ""),
    "paused": ("Paused", "Resume these in Steam."),
    "waiting": ("Updates Waiting", "Steam downloads these at the scheduled time, or when you play the game."),
}
VISIBLE_REFRESH = 2  # seconds while the section is open
HIDDEN_REFRESH = 30  # seconds otherwise, to keep the badge up to date


def describe(item, rate):
    size = GLib.format_size
    parts = [item.detail]
    if item.total and not item.downloaded:
        parts.append(f"{size(item.total)} to download")
    elif item.total:
        parts.append(f"{size(item.downloaded)} of {size(item.total)}")
    elif item.stage_total:
        parts.append(f"{size(item.staged)} of {size(item.stage_total)}")
    if item.status == "downloading" and rate:
        parts.append(f"{rate:.1f} Mbps")
    if item.status == "waiting" and item.scheduled:
        when = GLib.DateTime.new_from_unix_local(item.scheduled).format("%-d %B, %H:%M")
        parts.append(f"scheduled for {when}")
    return " · ".join(parts)


class DownloadRow(Adw.ActionRow):
    def __init__(self, window, item):
        super().__init__(title=GLib.markup_escape_text(item.name))
        thumb = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, can_shrink=True,
                            width_request=92, height_request=43, valign=Gtk.Align.CENTER)
        thumb.add_css_class("card")
        config = window.config
        art = library.find_art(config.root, config.userdata, item.appid)
        images.load(art["header"] or art["cover"], 184, 86, thumb.set_paintable)
        self.add_prefix(Adw.Clamp(child=thumb, maximum_size=92, tightening_threshold=92, width_request=92))
        self.progress = Gtk.ProgressBar(valign=Gtk.Align.CENTER, width_request=160)
        self.add_suffix(self.progress)

    def update(self, item, rate):
        self.set_subtitle(GLib.markup_escape_text(describe(item, rate)))
        self.progress.set_visible(item.status != "waiting")
        self.progress.set_fraction(item.fraction)


class DownloadsView(Gtk.Box):
    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.window = window
        self.page = None  # The view stack page, for its badge.
        self.visible = False
        self.rows = {}
        self._timer = 0
        self._busy = False

        self.closed_banner = Adw.Banner(title="Steam isn't running, so updates are paused", button_label="Start Steam")
        self.closed_banner.connect("button-clicked", self._on_start_steam)
        self.append(self.closed_banner)
        self.stack = Gtk.Stack(vexpand=True)
        self.prefs = Adw.PreferencesPage()
        self.groups = {}
        for status, (title, description) in GROUPS.items():
            group = Adw.PreferencesGroup(title=title, description=description, visible=False)
            self.groups[status] = group
            self.prefs.add(group)
        open_group = Adw.PreferencesGroup()
        check = Adw.ButtonRow(title="Check for Updates", start_icon_name="view-refresh-symbolic")
        check.connect("activated", lambda *_: self.check_for_updates())
        open_group.add(check)
        open_steam = Adw.ButtonRow(title="Open Downloads in Steam", end_icon_name="superlion-external-link-symbolic")
        open_steam.connect("activated", lambda *_: window.launch("steam://open/downloads", "Opening Steam's downloads"))
        open_group.add(open_steam)
        self.prefs.add(open_group)
        self.stack.add_named(self.prefs, "list")

        empty = Adw.StatusPage(
            icon_name="folder-download-symbolic", title="No Downloads",
            description="Games you install or update in Steam appear here while they download.",
        )
        buttons = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, halign=Gtk.Align.CENTER)
        check_button = Gtk.Button(label="Check for Updates")
        check_button.add_css_class("pill")
        check_button.add_css_class("suggested-action")
        check_button.connect("clicked", lambda *_: self.check_for_updates())
        open_button = Gtk.Button(label="Open Downloads in Steam")
        open_button.add_css_class("pill")
        open_button.connect("clicked", lambda *_: window.launch("steam://open/downloads", "Opening Steam's downloads"))
        buttons.append(check_button)
        buttons.append(open_button)
        empty.set_child(buttons)
        self.stack.add_named(empty, "empty")
        self.append(self.stack)

    def set_visible_section(self, visible):
        """Refresh quickly while the section is open or something downloads, slowly otherwise."""
        self.visible = visible
        self._schedule(fast=visible)
        self.refresh()

    def _schedule(self, fast):
        interval = VISIBLE_REFRESH if fast else HIDDEN_REFRESH
        if self._timer and getattr(self, "_interval", None) == interval:
            return
        if self._timer:
            GLib.source_remove(self._timer)
        self._interval = interval
        self._timer = GLib.timeout_add_seconds(interval, self._tick)

    def _tick(self):
        self.refresh()
        return GLib.SOURCE_CONTINUE

    def refresh(self):
        config = self.window.config
        if config is None or self._busy:
            return
        self._busy = True
        auth.run_async(
            lambda: (downloads.scan(config), downloads.current_rate(config), steam_control.is_running(config)),
            self._show,
        )

    def check_for_updates(self):
        """Steam checks for updates when it starts and while it runs, so start it if needed."""
        config = self.window.config
        if steam_control.start_if_needed(config):
            self.closed_banner.set_revealed(False)
            self.window.toast("Starting Steam, which checks for updates")
            # Steam's app database is updated a little after it starts.
            GLib.timeout_add_seconds(60, lambda: (self.window.refresh_updates(), self.refresh(), GLib.SOURCE_REMOVE)[-1])
        else:
            self.window.toast("Steam checks for updates while it runs. Updates it finds are listed here.")
        self.window.refresh_updates()
        self.refresh()

    def _on_start_steam(self, banner):
        banner.set_revealed(False)
        steam_control.start(self.window.config)

    def _update_games(self, items):
        states = {item.appid: item for item in items}
        store = self.window.library.store
        for index in range(store.get_n_items()):
            game = store.get_item(index)
            item = states.get(game.props.appid) if not game.props.non_steam else None
            if item:
                label = downloads.cover_label(item, game.props.installed)
            else:
                label = "Update Available" if game.props.update_available else ""
            progress = item.fraction if item and item.status != "waiting" else -1.0
            if game.props.download_label != label:
                game.props.download_label = label
            if game.props.download_progress != progress:
                game.props.download_progress = progress

    def _show(self, result, error):
        self._busy = False
        if error or result is None:
            return
        items, rate, running = result
        self.closed_banner.set_revealed(not running)
        self._update_games(items)
        # Games with a newer build that Steam has not marked yet.
        listed = {item.appid for item in items}
        items += [
            downloads.Download(g.props.appid, g.props.name, "waiting", "Update available", 0, 0, 0, 0, 0)
            for g in self.window.installed if g.props.update_available and g.props.appid not in listed
        ]
        # Covers in the library show live progress, so check often while downloading.
        self._schedule(fast=self.visible or any(i.status == "downloading" for i in items))
        if self.page is not None:
            self.page.set_badge_number(len(items))
            self.page.set_needs_attention(any(i.status == "downloading" for i in items))
        if not self.visible:
            return
        seen = set()
        for item in items:
            key = (item.appid, item.status)
            seen.add(key)
            row = self.rows.get(key)
            if row is None:
                row = DownloadRow(self.window, item)
                self.rows[key] = row
                self.groups[item.status].add(row)
            row.update(item, rate)
        for key in [k for k in self.rows if k not in seen]:
            row = self.rows.pop(key)
            self.groups[key[1]].remove(row)
        for status, group in self.groups.items():
            group.set_visible(any(k[1] == status for k in self.rows))
        self.stack.set_visible_child_name("list" if items else "empty")
