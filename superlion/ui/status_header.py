"""A status page's icon, title and description, for pages that scroll already.

Adw.StatusPage scrolls on its own, so inside an Adw.PreferencesPage it gets a
second scrollbar and is clipped.
"""

from gi.repository import Gtk


class StatusHeader(Gtk.Box):
    def __init__(self, icon_name, title, description="", icon_size=96):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=12, margin_bottom=12)
        self.icon = Gtk.Image(pixel_size=icon_size, margin_bottom=12)
        self.icon.add_css_class("dim-label")
        self.title = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER)
        self.title.add_css_class("title-1")
        self.description = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER)
        for widget in (self.icon, self.title, self.description):
            self.append(widget)
        self.update(icon_name, title, description)

    def update(self, icon_name, title, description=""):
        self.icon.set_from_icon_name(icon_name)
        self.title.set_label(title)
        self.description.set_label(description)
        self.description.set_visible(bool(description))
