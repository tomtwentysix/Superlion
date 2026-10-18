"""Renaming a non-Steam game, with Steam store suggestions for its proper name."""

from gi.repository import Adw, GLib, Gtk

from .. import auth, store_api

SEARCH_DELAY = 350  # milliseconds after the last keystroke
MAX_SUGGESTIONS = 6


def ask_game_name(window, game, callback):
    """Ask for a new name; callback(name, steam_appid or 0) when confirmed.

    Typing searches the Steam store. Choosing a suggestion fills in Steam's exact
    name and also matches the game to that store entry; editing the name
    afterwards keeps the text but drops the match.
    """
    dialog = Adw.AlertDialog(
        heading="Rename Game",
        body="Type a name, or choose a Steam game below to use its exact name and store information.",
    )
    entry = Gtk.Entry(text=game.props.name, activates_default=True)
    suggestions = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, visible=False)
    suggestions.add_css_class("boxed-list")
    status = Gtk.Label(xalign=0, wrap=True, visible=False)
    status.add_css_class("dim-label")
    status.add_css_class("caption")
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    box.append(entry)
    box.append(status)
    box.append(
        Gtk.ScrolledWindow(
            child=suggestions, hscrollbar_policy=Gtk.PolicyType.NEVER,
            propagate_natural_height=True, max_content_height=300,
        )
    )
    dialog.set_extra_child(box)
    dialog.add_response("cancel", "Cancel")
    dialog.add_response("rename", "Rename")
    dialog.set_response_appearance("rename", Adw.ResponseAppearance.SUGGESTED)
    dialog.set_default_response("rename")
    dialog.set_close_response("cancel")

    state = {"chosen": None, "timer": 0, "serial": 0, "filling": False}
    region = window.store_region

    def show_status(text):
        status.set_label(text)
        status.set_visible(bool(text))

    def choose(item):
        state["filling"] = True
        entry.set_text(item["name"])
        state["filling"] = False
        state["chosen"] = item
        entry.grab_focus()
        entry.set_position(-1)
        show_status(f"Will also match to Steam app {item['id']}, for its store page, news and artwork.")

    def search():
        state["timer"] = 0
        term = entry.get_text().strip()
        state["serial"] += 1
        serial = state["serial"]
        if len(term) < 2:
            suggestions.set_visible(False)
            return GLib.SOURCE_REMOVE

        def done(items, error):
            if serial != state["serial"]:
                return  # A newer search has started.
            suggestions.remove_all()
            for item in (items or [])[:MAX_SUGGESTIONS]:
                row = Adw.ActionRow(
                    title=GLib.markup_escape_text(item.get("name", "")),
                    subtitle=GLib.markup_escape_text(f"Steam app {item['id']}"),
                    activatable=True,
                )
                row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
                row.connect("activated", lambda _r, it=item: choose(it))
                suggestions.append(row)
            suggestions.set_visible(bool(items) and not error)

        auth.run_async(lambda: store_api.search(term, region), done)
        return GLib.SOURCE_REMOVE

    def on_changed(_entry):
        dialog.set_response_enabled("rename", bool(entry.get_text().strip()))
        if state["filling"]:
            return
        if state["chosen"] and entry.get_text() != state["chosen"]["name"]:
            state["chosen"] = None  # A hand-edited name no longer refers to that store game.
            show_status("")
        if state["timer"]:
            GLib.source_remove(state["timer"])
        state["timer"] = GLib.timeout_add(SEARCH_DELAY, search)

    entry.connect("changed", on_changed)

    def on_response(_dialog, response):
        if state["timer"]:
            GLib.source_remove(state["timer"])
        name = entry.get_text().strip()
        if response == "rename" and name:
            callback(name, state["chosen"]["id"] if state["chosen"] else 0)

    dialog.connect("response", on_response)
    dialog.present(window)
    dialog.set_focus(entry)
    entry.select_region(0, -1)
    search()  # Suggestions for the current name straight away.
    return dialog
