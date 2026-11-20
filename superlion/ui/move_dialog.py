"""Moving a game to another Steam library, or a non-Steam game's folder anywhere."""

import os
import shutil
from pathlib import Path

from gi.repository import Adw, Gio, GLib, Gtk

from .. import auth, downloads, library, moving, steam_control, steam_paths
from .mover import Job
from .wizard import short_path


def _free(path):
    return shutil.disk_usage(path).free


def _libraries(config):
    return [Path(folder) for folder, _count in steam_paths.find_libraries(config.root)]


def _same(a, b):
    return Path(a).resolve() == Path(b).resolve()


def _blocked(config):
    folders = _libraries(config) + [Path(f) for f in config.library_folders()]
    return [folder / "steamapps" for folder in folders]


def _kept():
    folders = (GLib.get_user_special_dir(d) for d in GLib.UserDirectory if d != GLib.UserDirectory.N_DIRECTORIES)
    return [Path(f) for f in folders if f]


def blocker(window, game):
    config, appid = window.config, game.props.appid
    if window.moving:
        return f"Wait until the {window.mover.what} under way finishes."
    if appid in steam_control.running_games():
        return f"{game.props.name} is running. Quit it first."
    if game.props.non_steam:
        entries = library.read_shortcuts(config)
        exe = moving.shortcut_exe(entries[appid]) if appid in entries else None
        if exe is None:
            return "Its executable is not a file path, so Superlion cannot tell which folder holds the game."
        if moving.suggest_folder(entries, appid, _blocked(config), keep=_kept()) is None:
            folder = short_path(exe.parent)
            return (f"Its executable is in {folder}, which is a drive, your home folder, "
                    "a folder such as Downloads or part of a Steam library.")
        return None
    others = moving.folder_sharers(game.props.library, appid, Path(game.props.install_dir).name)
    if others:
        return f"It shares its folder with {', '.join(others)}, so it cannot be moved on its own."
    item = downloads.state_for(config, appid)
    if downloads.is_busy(item, True):
        if item.status == "paused":
            return "Its update is paused. Let Steam finish the update first."
        return "Steam is updating it. Wait until the update finishes."
    if not any(not _same(folder, game.props.library) for folder in _libraries(config)):
        return "There is no other Steam library to move it to."
    return None


def progress_text(mover, label, done, total):
    if mover.what != "move" or not total:
        return label  # An uninstall counts parts, not bytes.
    done_text, total_text = GLib.format_size(done), GLib.format_size(total)
    # format_size puts a no-break space before the unit; "4.2 of 12.0 GB" names it once.
    number, _space, unit = done_text.rpartition("\xa0")
    if number and unit == total_text.rpartition("\xa0")[2]:
        done_text = number
    return f"{label} {done_text} of {total_text}"


def _alert(parent, heading, body):
    dialog = Adw.AlertDialog(heading=heading, body=body)
    dialog.add_response("close", "Close")
    dialog.present(parent)


def move_game(window, game):
    reason = blocker(window, game)
    if reason:
        _alert(window, f"{game.props.name} Cannot Be Moved", reason)
    elif game.props.non_steam:
        _move_shortcut(window, game)
    else:
        choose_library(window, [game], lambda dest: window.mover.start([steam_job(game, dest)], window, "Move"))


def steam_job(game, dest):
    source, appid = Path(game.props.library), game.props.appid
    installdir = Path(game.props.install_dir).name
    return Job(
        "move", game.props.name,
        lambda progress: moving.move_steam_game(source, dest, appid, installdir, progress),
        game.props.size, appids=[appid], dest=dest,
    )


def choose_library(window, games, on_chosen):
    # Measured rather than taken from SizeOnDisk, which some games leave far too low (Star Trek
    # Online's launcher downloads 23 GB that Steam never counts).
    found = [(g.props.library, g.props.appid, Path(g.props.install_dir).name) for g in games]

    def measure():
        return [moving.parts_size(moving.steam_parts(*game)) for game in found]

    def done(sizes, error):
        if error:
            _alert(window, "Games Cannot Be Moved" if len(games) > 1 else f"{games[0].props.name} Cannot Be Moved",
                   str(error))
            return
        _present_libraries(window, games, sizes, on_chosen)

    auth.run_async(measure, done)


def _present_libraries(window, games, sizes, on_chosen):
    total = sum(sizes)
    sources = [Path(game.props.library) for game in games]
    folders = [f for f in _libraries(window.config) if not any(_same(f, s) for s in sources)]
    if len(games) == 1:
        heading = f"Move {games[0].props.name}"
        body = f"{games[0].props.name} uses {GLib.format_size(total)}. Choose the library to move it to."
    else:
        heading = f"Move {len(games)} Games"
        body = f"They use {GLib.format_size(total)}. Choose the library to move them to."
    dialog = Adw.AlertDialog(heading=heading, body=body)
    chosen = {}

    rows = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
    rows.add_css_class("boxed-list")
    group = None
    for folder in folders:
        # Games on the same drive are renamed, so only the rest need room.
        needed = sum(size for size, source in zip(sizes, sources)
                     if not moving.same_drive(source / "steamapps", folder / "steamapps"))
        try:
            free = _free(folder / "steamapps")
        except OSError:
            free = None
        if free is None:
            subtitle, usable = "Not available", False
        elif free < needed:
            subtitle, usable = f"{GLib.format_size(free)} free · Not enough space", False
        else:
            subtitle, usable = f"{GLib.format_size(free)} free", True
        check = Gtk.CheckButton(valign=Gtk.Align.CENTER)
        if group is None:
            group = check
        else:
            check.set_group(group)
        row = Adw.ActionRow(
            title=GLib.markup_escape_text(short_path(folder)), subtitle=subtitle,
            activatable_widget=check, sensitive=usable,
        )
        row.add_prefix(check)
        check.connect("toggled", lambda c, f=folder: c.get_active() and pick(f))
        rows.append(row)
    dialog.set_extra_child(rows)

    def pick(folder):
        chosen["folder"] = folder
        dialog.set_response_enabled("move", True)

    dialog.add_response("cancel", "Cancel")
    dialog.add_response("move", "Move")
    dialog.set_response_appearance("move", Adw.ResponseAppearance.SUGGESTED)
    dialog.set_response_enabled("move", False)
    dialog.set_close_response("cancel")
    dialog.connect("response", lambda _d, response: response == "move" and on_chosen(chosen["folder"]))
    dialog.present(window)


def _choose_folder(parent, title, initial, on_chosen):
    chooser = Gtk.FileDialog(title=title)
    if initial:
        chooser.set_initial_folder(Gio.File.new_for_path(str(initial)))

    def done(dlg, result):
        try:
            folder = dlg.select_folder_finish(result)
        except GLib.Error:  # Cancelled.
            return
        if folder and folder.get_path():
            on_chosen(Path(folder.get_path()))

    chooser.select_folder(parent.get_root(), None, done)


def _move_shortcut(window, game):
    config, appid, name = window.config, game.props.appid, game.props.name
    entries = library.read_shortcuts(config)
    blocked = _blocked(config)
    exe = moving.shortcut_exe(entries[appid])
    kept = _kept()
    folder, _shared = moving.suggest_folder(entries, appid, blocked, keep=kept)
    state = {"folder": folder, "target": None}

    dialog = Adw.AlertDialog(heading=f"Move {name}")
    rows = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
    rows.add_css_class("boxed-list")
    folder_row = Adw.ActionRow(title="Folder to Move")
    shared_row = Adw.ActionRow(title="Also Moves", subtitle_lines=0)
    target_row = Adw.ActionRow(title="Move To", subtitle="Not chosen")
    for row in (folder_row, shared_row, target_row):
        row.add_css_class("property")
        rows.append(row)
    dialog.set_extra_child(rows)

    def show_folder():
        folder = state["folder"]
        folder_row.set_subtitle(GLib.markup_escape_text(short_path(folder)))
        others = moving.sharing(entries, appid, folder)
        names = [library.field(entries[other], "AppName") or str(other) for other in others]
        shared_row.set_subtitle(GLib.markup_escape_text(", ".join(sorted(names, key=str.casefold))))
        shared_row.set_visible(bool(names))
        target = state["target"]
        if target and (target.resolve().is_relative_to(folder.resolve()) or os.path.lexists(target / folder.name)):
            state["target"] = None
            target_row.set_subtitle("Not chosen")
        dialog.set_response_enabled("move", state["target"] is not None)

    def folder_chosen(picked):
        home = Path.home()
        if not exe.parent.is_relative_to(picked):
            _alert(dialog, "Folder Cannot Be Moved", f"Choose a folder that holds {exe.name}.")
        elif picked == home or picked in kept or os.path.ismount(picked) or any(
            picked.is_relative_to(b) or b.is_relative_to(picked) for b in blocked
        ):
            _alert(dialog, "Folder Cannot Be Moved",
                   "Drives, your home folder, folders such as Downloads and folders holding a Steam library "
                   "cannot be moved.")
        else:
            state["folder"] = picked
            show_folder()

    def target_chosen(picked):
        folder = state["folder"]
        if picked.resolve().is_relative_to(folder.resolve()):
            _alert(dialog, "Folder Cannot Be Used", f"{short_path(picked)} is inside the folder being moved.")
        elif os.path.lexists(picked / folder.name):
            _alert(dialog, "Folder Cannot Be Used", f"{short_path(picked)} already holds a folder named {folder.name}.")
        else:
            state["target"] = picked
            target_row.set_subtitle(GLib.markup_escape_text(short_path(picked)))
            dialog.set_response_enabled("move", True)

    choose = Gtk.Button(label="Choose…", valign=Gtk.Align.CENTER)
    choose.connect("clicked", lambda b: _choose_folder(b, "Folder to Move", state["folder"], folder_chosen))
    folder_row.add_suffix(choose)
    pick_target = Gtk.Button(label="Choose…", valign=Gtk.Align.CENTER)
    pick_target.connect("clicked", lambda b: _choose_folder(b, "Move To", state["target"], target_chosen))
    target_row.add_suffix(pick_target)

    dialog.add_response("cancel", "Cancel")
    dialog.add_response("move", "Move")
    dialog.set_response_appearance("move", Adw.ResponseAppearance.SUGGESTED)
    dialog.set_close_response("cancel")
    show_folder()

    def on_response(_dialog, response):
        if response != "move":
            return
        folder, target = state["folder"], state["target"]
        moved = [appid, *moving.sharing(entries, appid, folder)]
        now = steam_control.running_games()
        running = [library.field(entries[a], "AppName") or str(a) for a in moved if a in now]
        if running:
            verb, them = ("is", "it") if len(running) == 1 else ("are", "them")
            _alert(window, f"{name} Cannot Be Moved", f"{' and '.join(running)} {verb} running. Quit {them} first.")
            return
        new = target / folder.name
        job = Job(
            "move", name, lambda progress: moving.move_folder(folder, target, progress),
            0, shortcut_moves={a: (folder, new) for a in moved}, appids=moved, dest=target,
        )
        window.mover.start([job], window, "Move")

    dialog.connect("response", on_response)
    dialog.present(window)
