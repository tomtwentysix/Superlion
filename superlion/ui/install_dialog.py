"""Choosing where to install a game, without Steam's install dialog."""

from gi.repository import Adw, GLib, Gtk

from .. import installer, pending, steam_control


def _size(size):
    return GLib.format_size(size) if size else "unknown"


def install_game(window, appid, name=""):
    """Ask where to install a game, then have Steam download it there.

    Falls back to Steam's own install dialog when Superlion does not know the
    game's install folder, or when the user prefers it.
    """
    config = window.config
    info = installer.install_info(config, appid)
    libraries = installer.libraries(config)
    if info is None or not libraries:
        window.launch(f"steam://install/{appid}", "Opening the Steam install dialog")
        return
    name = name or info["name"]
    size = info["download_size"]
    running = steam_control.is_running(config)

    dialog = Adw.AlertDialog(heading=f"Install {name}")
    body = [f"Download size: about {_size(size)}." if size else "Steam will work out the download size."]
    if running:
        body.append("Steam only notices new installs when it starts, so it will restart and begin downloading.")
    else:
        body.append("Steam will start and begin downloading.")
    dialog.set_body("\n".join(body))

    # One choice per library folder, starting with the one with the most free space.
    selected = {"index": max(range(len(libraries)), key=lambda i: libraries[i].free)}
    rows = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
    rows.add_css_class("boxed-list")
    group = None
    for index, lib in enumerate(libraries):
        check = Gtk.CheckButton(active=index == selected["index"], valign=Gtk.Align.CENTER)
        if group is None:
            group = check
        else:
            check.set_group(group)
        row = Adw.ActionRow(
            title=GLib.markup_escape_text(str(lib.path)),
            subtitle=f"{_size(lib.free)} free" if lib.free else "Free space unknown",
            activatable_widget=check,
        )
        row.add_prefix(check)
        check.connect("toggled", lambda c, i=index: c.get_active() and choose(i))
        rows.append(row)
    heading = Gtk.Label(label="Install To", xalign=0, margin_bottom=6)
    heading.add_css_class("heading")
    warning = Gtk.Label(wrap=True, xalign=0, visible=False, margin_top=6)
    warning.add_css_class("warning")
    warning.add_css_class("caption")
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    box.append(heading)
    box.append(rows)
    box.append(warning)
    dialog.set_extra_child(box)

    def choose(index):
        selected["index"] = index
        free = libraries[index].free
        short = size and free and size > free
        warning.set_label(f"This drive may not have enough space: {_size(free)} free." if short else "")
        warning.set_visible(bool(short))

    choose(selected["index"])

    dialog.add_response("cancel", "Cancel")
    dialog.add_response("steam", "Use Steam's Dialog")
    dialog.add_response("install", "Restart Steam and Install" if running else "Install")
    dialog.set_response_appearance("install", Adw.ResponseAppearance.SUGGESTED)
    dialog.set_default_response("install")
    dialog.set_close_response("cancel")

    def on_response(_dialog, response):
        if response == "steam":
            window.launch(f"steam://install/{appid}", "Opening the Steam install dialog")
        elif response == "install":
            library = str(libraries[selected["index"]].path)
            install = {"library": library, "name": name, "installdir": info["installdir"]}
            _start(window, appid, name, install)

    dialog.connect("response", on_response)
    dialog.present(window)


def _start(window, appid, name, install):
    config = window.config
    pending.add(appid, {"install": install})
    if steam_control.is_running(config):
        window.relaunch_steam(reload=True)
        return
    try:
        pending.apply_now(config)
    except OSError as error:
        window.toast(f"{name} could not be set up to install: {error.strerror}")
        window.update_pending()
        return
    window.update_pending()
    steam_control.start(config)
    window.toast(f"Steam is starting and will download {name}")
    window.reload()
