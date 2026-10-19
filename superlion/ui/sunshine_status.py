"""Whether Sunshine is ready to stream games to Moonlight, shown in setup and Preferences."""

from gi.repository import Adw, GLib, Gtk

from .. import audio, display, edid, sunshine
from .status_header import StatusHeader

COPR_URL = "https://copr.fedorainfracloud.org/coprs/lizardbyte/stable/"

# Each problem from sunshine.problems(): title, explanation, and its button ("start" or "get").
PROBLEMS = {
    "missing": (
        "Sunshine Not Installed",
        "Install Sunshine from LizardByte's COPR to stream your games to Moonlight.",
        "get",
    ),
    "stopped": (
        "Sunshine Not Running",
        "Moonlight cannot connect to this PC until Sunshine starts.",
        "start",
    ),
    "no-hdr": (
        "HDR Not Available",
        "The Flatpak and AppImage versions of Sunshine cannot capture HDR. Install it from LizardByte's COPR instead.",
        "get",
    ),
}


class SunshineGroup(Adw.PreferencesGroup):
    def __init__(self):
        super().__init__(margin_bottom=12)
        self.header = StatusHeader("tv-symbolic", "", icon_size=64)
        self.button = Gtk.Button(halign=Gtk.Align.CENTER)
        self.button.add_css_class("pill")
        self.button.add_css_class("suggested-action")
        self.button.connect("clicked", self._on_button)
        self.header.append(self.button)
        self.add(self.header)
        self._rows = []
        self.refresh()

    def refresh(self):
        for row in self._rows:
            self.remove(row)
        self._rows = []
        self.button.set_sensitive(True)
        issues = sunshine.problems()
        if not issues:
            self.header.update("tv-symbolic", "Sunshine Is Ready",
                               "Add a game with Add to Sunshine in its menu, then play it in Moonlight.")
            self.button.set_visible(False)
            return
        title, description, action = PROBLEMS[issues[0]]
        self.header.update("dialog-warning-symbolic", title, description)
        self._action = action
        self.button.set_label("Start Sunshine" if action == "start" else "Get Sunshine")
        self.button.set_visible(True)
        for issue in issues[1:]:
            title, subtitle, action = PROBLEMS[issue]
            row = Adw.ActionRow(title=title, subtitle=subtitle)
            row.add_prefix(Gtk.Image(icon_name="dialog-warning-symbolic"))
            if action == "get":
                row.add_suffix(Gtk.LinkButton(uri=COPR_URL, label="Get Sunshine", valign=Gtk.Align.CENTER))
            self.add(row)
            self._rows.append(row)

    def _on_button(self, button):
        if self._action == "get":
            Gtk.UriLauncher(uri=COPR_URL).launch(self.get_root(), None, None)
            return
        button.set_sensitive(False)
        sunshine.start()
        # Sunshine's service waits a few seconds for the desktop before it starts.
        GLib.timeout_add_seconds(8, lambda: (self.refresh(), GLib.SOURCE_REMOVE)[-1])


def status_text():
    issues = sunshine.problems()
    return PROBLEMS[issues[0]][0] if issues else "Ready"


def display_label(connector):
    """How a Stream Display choice is named, such as "Main Monitor" or "Dummy Plug (HDMI-1)"."""
    if not connector:
        return "Main Monitor"
    try:
        others = display.monitors()
    except GLib.Error:
        others = {}
    if connector not in others:
        return f"{connector} (Not Connected)"
    return f"{'Dummy Plug' if edid.override(connector) else others[connector]} ({connector})"


RESOLUTIONS = [
    ("", "Match Moonlight"),
    ("3840x2160", "4K (3840 × 2160)"),
    ("2560x1440", "1440p (2560 × 1440)"),
    ("1920x1080", "1080p (1920 × 1080)"),
    ("1280x720", "720p (1280 × 720)"),
]
SOUND = [
    ("direct", "Surround"),
    ("easyeffects", "Stereo with EasyEffects"),
]


def _combo(title, subtitle, choices, value, on_change):
    keys = [key for key, _label in choices]
    row = Adw.ComboRow(
        title=title, subtitle=subtitle, model=Gtk.StringList.new([label for _key, label in choices]),
        selected=keys.index(value) if value in keys else 0,
    )
    row.connect("notify::selected", lambda r, _p: on_change(keys[r.get_selected()]))
    return row


class StreamOptions(Adw.PreferencesGroup):
    """Settings for Sunshine streams, kept in step with state; toast(text) reports results."""

    def __init__(self, state, toast):
        super().__init__(title="While Streaming")
        self.state = state
        self.toast = toast
        try:
            others = display.monitors()
        except GLib.Error:
            others = {}
        displays = [(c, display_label(c)) for c in ["", *others]]
        if state.stream_display and state.stream_display not in others:
            displays.append((state.stream_display, display_label(state.stream_display)))
        self.add(_combo(
            "Stream Display",
            "A dummy plug gives streams a display of their own" if others
            else "Connect a dummy plug to give streams a display of their own",
            displays, state.stream_display, self._on_display,
        ))
        self.capabilities = Adw.ActionRow(title="Dummy Plug Can Show", subtitle_selectable=True)
        self.add(self.capabilities)
        self.act_as = Adw.ComboRow(
            title="Act As",
            subtitle="Changes what the dummy plug tells this PC it can show. Needs your password.",
            model=Gtk.StringList.new(["Its Own Display"] + [label for label, *_ in edid.PROFILES.values()]),
        )
        self.apply_button = Gtk.Button(label="Apply", valign=Gtk.Align.CENTER)
        self.apply_button.add_css_class("suggested-action")
        self.apply_button.connect("clicked", self._on_apply)
        self.act_as.add_suffix(self.apply_button)
        self.act_as.connect("notify::selected", lambda *_: self._update_apply())
        self.add(self.act_as)
        self.add(_combo(
            "Resolution", "The resolution games run at while streaming",
            RESOLUTIONS, state.stream_resolution, lambda v: setattr(state, "stream_resolution", v),
        ))
        if audio.installed():
            self.add(_combo(
                "Sound", "Surround leaves out EasyEffects, so games reach Moonlight unchanged",
                SOUND, state.stream_audio, lambda v: setattr(state, "stream_audio", v),
            ))
        quiet = Adw.SwitchRow(
            title="Hide Dock and Notifications",
            subtitle="Hides the dock and pop-up notifications while a game is streaming",
            active=state.stream_quiet,
        )
        quiet.connect("notify::active", lambda row, _p: setattr(state, "stream_quiet", row.get_active()))
        self.add(quiet)
        self._show_dummy()

    def _on_display(self, connector):
        self.state.stream_display = connector
        self._show_dummy()

    def _show_dummy(self):
        connector = self.state.stream_display
        for row in (self.capabilities, self.act_as):
            row.set_visible(bool(connector))
        if not connector:
            return
        try:
            self.capabilities.set_subtitle(display.capabilities(connector))
        except GLib.Error:
            self.capabilities.set_subtitle("Unknown")
        profile = edid.override(connector)
        keys = [None, *edid.PROFILES]
        self._applied = profile if profile in keys else None
        self.act_as.set_selected(keys.index(self._applied))
        self._update_apply()

    def _selected_profile(self):
        return [None, *edid.PROFILES][self.act_as.get_selected()]

    def _update_apply(self):
        self.apply_button.set_sensitive(self._selected_profile() != getattr(self, "_applied", None))

    def _on_apply(self, button):
        button.set_sensitive(False)
        profile = self._selected_profile()

        def done(error):
            if error:
                self.toast(f"The dummy plug was not changed: {error}")
                self._update_apply()
                return
            self.toast("Dummy plug changed. It keeps this after restarting.")

            # The desktop takes a moment to read the new display information, and
            # turns the plug on as if it were a new monitor.
            def reread():
                display.turn_off(self.state.stream_display)
                self._show_dummy()
                return GLib.SOURCE_REMOVE

            GLib.timeout_add_seconds(3, reread)

        edid.apply(self.state.stream_display, profile, done)
