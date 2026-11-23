import gc
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from . import config as config_mod  # noqa: E402
from . import steam_control  # noqa: E402
from .ui.dedication import COMPANY, DEDICATION, KNOWN_FOR, NAME, TRIBUTE, YEARS  # noqa: E402

PACKAGE_DIR = Path(__file__).parent
ICON_DIRS = (PACKAGE_DIR / "icons", PACKAGE_DIR.parent / "data" / "icons")
VERSION = "0.11.1"
DEVELOPER = "SolarFlare Developments"


class SuperlionApplication(Adw.Application):
    def __init__(self):
        super().__init__(application_id=config_mod.APP_ID, flags=Gio.ApplicationFlags.HANDLES_OPEN)
        self._gc_ticks = 0
        self._add_action("quit", self._on_quit, ["<primary>q"])
        self._add_action("about", self._on_about)
        self._add_action("dedication", self._on_dedication)
        self._add_action("preferences", self._on_preferences, ["<primary>comma"])

    def _add_action(self, name, callback, accels=None):
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)
        if accels:
            self.set_accels_for_action(f"app.{name}", accels)

    def do_startup(self):
        Adw.Application.do_startup(self)
        # Python collects garbage in whichever thread is allocating, and a WebKit view freed
        # off the main thread aborts the app, so collection only runs from the main loop.
        gc.disable()
        GLib.timeout_add_seconds(1, self._collect_garbage)
        theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        for folder in ICON_DIRS:
            theme.add_search_path(str(folder))
        Gtk.Window.set_default_icon_name(config_mod.ICON_NAME)

    def _collect_garbage(self):
        self._gc_ticks += 1
        if self._gc_ticks % 60 == 0:
            gc.collect()
        elif gc.get_count()[0] > gc.get_threshold()[0]:
            gc.collect(0)
        return GLib.SOURCE_CONTINUE

    def do_activate(self):
        from .ui.window import SuperlionWindow

        window = self.props.active_window
        if window is None:
            window = SuperlionWindow(application=self)
            config_mod.seed_devel()
            config = config_mod.load()
            window.set_config(config)
            window.present()
            if config is None:
                window.run_setup(first_run=True)
            elif config.start_steam and not config.problems():
                steam_control.start_if_needed(config)
        window.present()

    def do_open(self, files, _n_files, _hint):
        self.activate()
        paths = [f.get_path() for f in files if f.get_path() and Path(f.get_path()).is_file()]
        if paths:
            self.props.active_window.add_to_steam(paths)
        else:
            self.props.active_window.toast("Only files on this computer can be added to Steam")

    def _on_quit(self, *_):
        window = next((w for w in self.get_windows() if getattr(w, "moving", False)), None)
        if window:
            window.ask_quit()
        else:
            self.quit()

    def _on_preferences(self, *_):
        window = self.props.active_window
        if window.config is None:
            window.run_setup(first_run=True)
            return
        from .ui.preferences import PreferencesDialog

        PreferencesDialog(window).present(window)

    def _on_about(self, *_):
        about = Adw.AboutDialog(
            application_name="Superlion",
            application_icon=config_mod.ICON_NAME,
            developer_name=DEVELOPER,
            copyright=f"© 2026 {DEVELOPER}",
            version=VERSION,
            comments=(
                "A native Linux app for your Steam library. "
                "Named after the Fowler B6 Super Lion traction engine. Its icon shows the "
                "flywheel of Supreme of S J Wharton Ltd in Witney.\n\n"
                f"{DEDICATION}\n{TRIBUTE}\n{KNOWN_FOR}"
            ),
            license_type=Gtk.License.GPL_3_0,
        )
        about.add_acknowledgement_section("Dedicated To", [f"{NAME}, {COMPANY} ({YEARS})"])
        about.present(self.props.active_window)

    def _on_dedication(self, *_):
        from .ui.dedication import DedicationDialog

        DedicationDialog().present(self.props.active_window)


def main():
    import sys

    return SuperlionApplication().run(sys.argv)
