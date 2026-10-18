"""The dedication page for John Wharton."""

from pathlib import Path

from gi.repository import Adw, Gtk

PHOTO = Path(__file__).resolve().parents[2] / "data" / "dedication" / "john-wharton.png"

NAME = "John Wharton"
COMPANY = "S J Wharton Ltd"
YEARS = "1953–2026"
TRIBUTE = "A fountain of knowledge, generosity, and a true, traditional English gentleman."
# "steam community" here means the traction engine community, not the Steam platform.
KNOWN_FOR = (
    "Best known for his Burrell, King George VI, and his contributions to the steam community, "
    "but fondly remembered by the creators of this app for his Fowler B6 Super Lion, Supreme."
)
DEDICATION = f"Dedicated to the memory of {NAME} of {COMPANY} ({YEARS})."


class DedicationDialog(Adw.Dialog):
    def __init__(self):
        super().__init__(title=f"In Memory of {NAME}", content_width=460)

        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=12,
            margin_top=12, margin_bottom=36, margin_start=24, margin_end=24,
        )
        if PHOTO.is_file():
            photo = Gtk.Picture.new_for_filename(str(PHOTO))
            photo.set_content_fit(Gtk.ContentFit.COVER)
            photo.set_size_request(280, 280)
            photo.set_halign(Gtk.Align.CENTER)
            photo.set_overflow(Gtk.Overflow.HIDDEN)
            photo.add_css_class("card")
            photo.set_alternative_text(f"Photograph of {NAME}")
            box.append(photo)

        name = Gtk.Label(label=NAME, margin_top=12)
        name.add_css_class("title-1")
        box.append(name)
        details = Gtk.Label(label=f"{COMPANY} · {YEARS}")
        details.add_css_class("dim-label")
        box.append(details)
        tribute = Gtk.Label(
            label=TRIBUTE, wrap=True, justify=Gtk.Justification.CENTER, margin_top=12, max_width_chars=40
        )
        box.append(tribute)
        known_for = Gtk.Label(
            label=KNOWN_FOR, wrap=True, justify=Gtk.Justification.CENTER, max_width_chars=40
        )
        box.append(known_for)
        dedication = Gtk.Label(label="Superlion is dedicated to his memory.", margin_top=6)
        dedication.add_css_class("dim-label")
        box.append(dedication)

        toolbar = Adw.ToolbarView(content=box)
        toolbar.add_top_bar(Adw.HeaderBar())
        self.set_child(toolbar)
