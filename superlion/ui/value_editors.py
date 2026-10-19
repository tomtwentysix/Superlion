"""Editors for a launch option's value, added to its row in the launch options editor.

Each has value and set_value(value), and calls on_change(value) when the user
changes it. Values are read with any quotes they were written with, and given
back without them; launch_options.compose() quotes them where needed.
"""

import re

from gi.repository import Adw, GLib, Gtk, Pango

from .. import audio
from .. import launch_options as lo


def _menu_button(icon, tooltip, heading, items, on_choose):
    """A menu of (value, label) items that calls on_choose(value)."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    popover = Gtk.Popover(child=box)
    popover.add_css_class("menu")
    if heading:
        label = Gtk.Label(label=heading, xalign=0, margin_start=12, margin_top=6, margin_bottom=6)
        label.add_css_class("dim-label")
        label.add_css_class("caption-heading")
        box.append(label)
    for value, text in items:
        label = Gtk.Label(label=text, xalign=0, ellipsize=Pango.EllipsizeMode.MIDDLE, max_width_chars=48)
        button = Gtk.Button(child=label)
        button.add_css_class("flat")
        button.connect("clicked", lambda _b, v=value: (popover.popdown(), on_choose(v)))
        box.append(button)
    button = Gtk.MenuButton(icon_name=icon, tooltip_text=tooltip, valign=Gtk.Align.CENTER, popover=popover)
    button.add_css_class("flat")
    return button


class TextValue:
    def __init__(self, expander, title, value, used, on_change):
        self.entry = Adw.EntryRow(title=title, text=value)
        self.entry.connect("changed", lambda *_: on_change(self.value))
        if len(used) > 1 or (used and used[0] != value):
            self.entry.add_suffix(_menu_button(
                "pan-down-symbolic", "Values Used in Your Games", "Used in Your Games",
                [(v, v) for v in used], self.entry.set_text,
            ))
        expander.add_row(self.entry)

    @property
    def value(self):
        return self.entry.get_text().strip()

    def set_value(self, value):
        if value != self.value:
            self.entry.set_text(value)


class ChoiceValue:
    """A drop-down of choices [(value, label)] ending with Other…, which shows an entry.

    With missing set, a value that is not among the choices, such as an audio
    output that is unplugged, is shown as "value (Not Connected)" instead of Other….
    """

    def __init__(self, expander, title, value, choices, on_change, missing=False):
        self.choices = list(choices)
        self.missing = missing
        self.on_change = on_change
        self.combo = Adw.ComboRow(title=title)
        self.other = Adw.EntryRow(title="Other Value")
        expander.add_row(self.combo)
        expander.add_row(self.other)
        self._setting = False
        self.set_value(value)
        self.combo.connect("notify::selected", lambda *_: self._changed())
        self.other.connect("changed", lambda *_: self._changed())

    @property
    def value(self):
        index = self.combo.get_selected()
        return self.choices[index][0] if index < len(self.choices) else self.other.get_text().strip()

    def set_value(self, value):
        value = value.strip("\"'")
        if value == self.value and self.combo.get_model():
            return
        values = [v for v, _label in self.choices]
        if value and value not in values and self.missing:
            self.choices.append((value, f"{value} (Not Connected)"))
            values.append(value)
        self._setting = True
        self.combo.set_model(Gtk.StringList.new([label for _v, label in self.choices] + ["Other…"]))
        if value in values or not value:
            self.combo.set_selected(values.index(value) if value in values else 0)
        else:
            self.other.set_text(value)
            self.combo.set_selected(len(self.choices))
        self._setting = False
        self.other.set_visible(self.combo.get_selected() >= len(self.choices))

    def _changed(self):
        self.other.set_visible(self.combo.get_selected() >= len(self.choices))
        if not self._setting:
            self.on_change(self.value)


class ListValue:
    """One row per item, each with a remove button, then an entry that adds items.

    Enter adds what was typed and leaves the entry ready for the next; pasting
    a list adds every item in it. For DLL overrides, each DLL has a load order.
    """

    def __init__(self, expander, value, separator, known, on_change, dlls=False):
        self.expander = expander
        self.separator = separator
        self.dlls = dlls
        self.on_change = on_change
        self.items = []
        self.rows = []
        self.add_row = Adw.EntryRow(title="Add a DLL, Such as dxgi" if dlls else "Add a Value")
        self.add_row.connect("entry-activated", lambda *_: self._add_typed())
        add = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="Add", valign=Gtk.Align.CENTER)
        add.add_css_class("flat")
        add.connect("clicked", lambda *_: self._add_typed())
        self.add_row.add_suffix(add)
        if known:
            self.add_row.add_suffix(_menu_button(
                "pan-down-symbolic", "Known Values", "Known Values", [(k, k) for k in known], self._add_text,
            ))
        expander.add_row(self.add_row)
        self.set_value(value)

    @property
    def value(self):
        if self.dlls:
            return lo.join_dll_overrides(self.items)
        return self.separator.join(name for name, _order in self.items)

    def set_value(self, value):
        if self.rows and value.strip("\"'") == self.value:
            return
        self.items = self._split(value)
        self._show()

    def _split(self, text):
        if self.dlls:
            return lo.split_dll_overrides(text)
        # A pasted comma list may use semicolons instead.
        separators = re.escape(self.separator) + (";" if self.separator == "," else "")
        return [(item.strip(), None) for item in re.split(f"[{separators}]", text.strip("\"'")) if item.strip()]

    def _show(self):
        for row in self.rows:
            self.expander.remove(row)
        self.expander.remove(self.add_row)
        self.rows = [self._item_row(i, name, order) for i, (name, order) in enumerate(self.items)]
        for row in self.rows:
            self.expander.add_row(row)
        self.expander.add_row(self.add_row)

    def _item_row(self, index, name, order):
        title = GLib.markup_escape_text(name)
        if self.dlls:
            orders = [o for o, _label in lo.DLL_ORDERS]
            row = Adw.ComboRow(title=title, model=Gtk.StringList.new([label for _o, label in lo.DLL_ORDERS]))
            if order not in orders:
                orders.append(order)
                row.get_model().append(order)
            row.set_selected(orders.index(order))
            row.connect("notify::selected", lambda r, _p: self._set_order(index, orders[r.get_selected()]))
        else:
            row = Adw.ActionRow(title=title)
        remove = Gtk.Button(icon_name="window-close-symbolic", tooltip_text="Remove", valign=Gtk.Align.CENTER)
        remove.add_css_class("flat")
        remove.connect("clicked", lambda *_: self._remove(index))
        row.add_suffix(remove)
        return row

    def _set_order(self, index, order):
        self.items[index] = (self.items[index][0], order)
        self.on_change(self.value)

    def _remove(self, index):
        del self.items[index]
        self._show()
        self.on_change(self.value)

    def _add_typed(self):
        self._add_text(self.add_row.get_text())
        self.add_row.set_text("")
        self.add_row.grab_focus()

    def _add_text(self, text):
        names = {name for name, _order in self.items}
        added = [item for item in self._split(text) if item[0] not in names]
        if added:
            self.items += added
            self._show()
            self.on_change(self.value)


def value_editor(expander, setting, value, on_change):
    title = "Options" if setting.kind == lo.WRAPPER else "Value"
    if setting.kind == lo.ENV and setting.key == "WINEDLLOVERRIDES":
        return ListValue(expander, value, ";", [], on_change, dlls=True)
    if setting.kind == lo.ENV and setting.key in lo.LISTS:
        separator, known = lo.LISTS[setting.key]
        return ListValue(expander, value, separator, known, on_change)
    if setting.kind == lo.ENV and setting.key == "PULSE_SINK":
        return ChoiceValue(expander, "Output", value, [(n, d) for n, d in audio.outputs()], on_change, missing=True)
    if setting.kind == lo.ENV and setting.key in lo.CHOICES:
        return ChoiceValue(expander, title, value, lo.CHOICES[setting.key], on_change)
    return TextValue(expander, title, value, [v for v, _n in setting.values.most_common()], on_change)
