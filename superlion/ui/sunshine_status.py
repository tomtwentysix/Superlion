"""Whether Sunshine is ready to stream games to Moonlight, shown in setup and Preferences."""

from gi.repository import Adw, GLib, Gtk

from .. import sunshine

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
        super().__init__(
            title="Sunshine",
            description="Streams your games to Moonlight on a TV, phone or another computer.",
        )
        self._rows = []
        self.refresh()

    def refresh(self):
        for row in self._rows:
            self.remove(row)
        self._rows = []
        issues = sunshine.problems()
        if not issues:
            self._add("emblem-ok-symbolic", "Ready to Stream",
                      "Games stream in HDR and surround sound. Add one with Add to Sunshine in its ⋮ menu.")
            return
        for issue in issues:
            title, subtitle, action = PROBLEMS[issue]
            row = self._add("dialog-warning-symbolic", title, subtitle)
            if action == "start":
                button = Gtk.Button(label="Start", valign=Gtk.Align.CENTER)
                button.connect("clicked", self._on_start)
            else:
                button = Gtk.LinkButton(uri=COPR_URL, label="Get Sunshine", valign=Gtk.Align.CENTER)
            row.add_suffix(button)

    def _add(self, icon, title, subtitle):
        row = Adw.ActionRow(title=title, subtitle=subtitle)
        row.add_prefix(Gtk.Image(icon_name=icon))
        self.add(row)
        self._rows.append(row)
        return row

    def _on_start(self, button):
        button.set_sensitive(False)
        sunshine.start()
        # Sunshine's service waits a few seconds for the desktop before it starts.
        GLib.timeout_add_seconds(8, lambda: (self.refresh(), GLib.SOURCE_REMOVE)[-1])
