"""Custom Proton builds in Preferences: installed builds, their updates, and installing more."""

import threading
from datetime import datetime

import requests
from gi.repository import Adw, GLib, Gtk

from .. import pending, proton, steam_control
from ..auth import run_async

STAGES = {"download": "Downloading", "check": "Checking the download", "unpack": "Unpacking"}
VARIANT_NOTES = {
    "x86_64_v3": "The x86-64-v3 build is used, which suits this processor",
    "x86_64": "The x86-64 build is used, which suits every processor",
}


class Job:
    def __init__(self, title):
        self.title = title
        self.stage = "download"
        self.fraction = 0.0
        self.cancel = threading.Event()


# The install running now; it outlives Preferences if that is closed.
_job = None


def _reason(error):
    if isinstance(error, requests.RequestException):
        return "GitHub could not be reached"
    if isinstance(error, OSError) and error.strerror:
        return error.strerror
    return str(error)


def _tools_changed(window, message, toast):
    if steam_control.is_running(window.config):
        pending.add_tools_restart()
        window.update_pending()
        message += ". Steam will show the change once it restarts"
    toast(message)


def start_install(window, source, release, variant, toast, replace=None):
    global _job
    job = _job = Job(f"Installing {source.version(release.tag)}")
    config = window.config

    def progress(stage, fraction):
        job.stage, job.fraction = stage, fraction

    def finished(_path, error):
        global _job
        _job = None
        version = source.version(release.tag)
        if isinstance(error, proton.Cancelled):
            toast(f"{version} was not installed")
        elif error:
            toast(f"{version} could not be installed: {_reason(error)}")
        elif replace:
            toast(f"{replace.label} updated to {version}")
        else:
            _tools_changed(window, f"{version} installed", toast)

    run_async(lambda: proton.install(config, source, release, variant, progress, job.cancel.is_set, replace),
              finished)


class ProtonGroup(Adw.PreferencesGroup):
    def __init__(self, dialog, window):
        super().__init__(
            title="Proton Builds",
            description="Custom versions of Proton that Steam can run Windows games with",
        )
        self.dialog = dialog
        self.window = window
        self.releases = {}
        self.errors = {}
        self._rows = []
        self._watch = 0
        self._install_page = None

        install = Gtk.Button(label="Install…", valign=Gtk.Align.CENTER)
        install.connect("clicked", lambda *_: self._open_install())
        self.set_header_suffix(install)
        self.refresh()
        for source in proton.SOURCES:
            run_async(lambda s=source: proton.releases(s), lambda r, e, s=source: self._got_releases(s, r, e))

    def toast(self, text):
        if self.dialog.get_mapped():
            self.dialog.add_toast(Adw.Toast(title=text))
        else:
            self.window.toast(text)

    def _got_releases(self, source, found, error):
        self.releases[source.name] = found or []
        if error:
            self.errors[source.name] = _reason(error)
        self.refresh()
        if self._install_page:
            self._fill_install_page()

    def refresh(self):
        for row in self._rows:
            self.remove(row)
        self._rows = []
        if _job:
            self._add(self._job_row(_job))
        builds = proton.installed(self.window.config)
        for build in builds:
            self._add(self._build_row(build, builds))
        if not builds and not _job:
            self._add(Adw.ActionRow(
                title="No Custom Proton Builds",
                subtitle="GE-Proton and Proton-CachyOS can fix games that Valve's Proton cannot run well",
            ))

    def _add(self, row):
        self.add(row)
        self._rows.append(row)

    def _job_row(self, job):
        row = Adw.ActionRow(title=job.title)
        bar = Gtk.ProgressBar(valign=Gtk.Align.CENTER, width_request=120)
        cancel = Gtk.Button(icon_name="process-stop-symbolic", tooltip_text="Cancel", valign=Gtk.Align.CENTER)
        cancel.add_css_class("flat")
        cancel.connect("clicked", lambda *_: (job.cancel.set(), cancel.set_sensitive(False)))
        row.add_suffix(bar)
        row.add_suffix(cancel)

        def tick():
            if _job is not job:
                self._watch = 0
                self.refresh()
                return GLib.SOURCE_REMOVE
            percent = f" {round(job.fraction * 100)}%" if job.stage == "download" else ""
            row.set_subtitle(STAGES[job.stage] + percent)
            if job.stage == "download":
                bar.set_fraction(job.fraction)
            else:
                bar.pulse()
            return GLib.SOURCE_CONTINUE

        tick()
        if self._watch:
            GLib.source_remove(self._watch)
        self._watch = GLib.timeout_add(300, tick)
        return row

    def _build_row(self, build, builds):
        source = build.source
        if source:
            subtitle = source.version(build.tag)
            if len(source.variants) > 1:
                subtitle += f", {build.variant.replace('_', '-')}"
        else:
            subtitle = "Not managed by Superlion"
        update = proton.update_for(build, builds, self.releases.get(source.name, [])) if source else None
        if update:
            subtitle += f". {source.version(update.tag)} is available"
        row = Adw.ActionRow(title=build.label, subtitle=subtitle)
        if update:
            button = Gtk.Button(label="Update", valign=Gtk.Align.CENTER, sensitive=not _job)
            button.add_css_class("suggested-action")
            button.connect("clicked", lambda *_: self._install(
                source, update, build.variant, build if build.rolling else None))
            row.add_suffix(button)
        remove = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text="Remove", valign=Gtk.Align.CENTER,
                            sensitive=not _job)
        remove.add_css_class("flat")
        remove.connect("clicked", lambda *_: self._confirm_remove(build))
        row.add_suffix(remove)
        return row

    def _install(self, source, release, variant, replace=None):
        if _job:
            return
        start_install(self.window, source, release, variant, self.toast, replace)
        if self._install_page:
            self.dialog.pop_subpage()
        self.refresh()

    def _confirm_remove(self, build):
        body = "Its files will be deleted from Steam's compatibility tools folder."
        using = len(proton.games_using(self.window.config, build))
        if using:
            body += f" {using} game{'s' if using != 1 else ''} set to use it will need another compatibility tool."
        dialog = Adw.AlertDialog(heading=f"Remove {build.label}?", body=body)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("remove", "Remove")
        dialog.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_close_response("cancel")

        def on_response(_dialog, response):
            if response != "remove":
                return
            try:
                proton.remove(build)
            except OSError as error:
                self.toast(f"{build.label} could not be removed: {error.strerror}")
            else:
                _tools_changed(self.window, f"{build.label} removed", self.toast)
            self.refresh()

        dialog.connect("response", on_response)
        dialog.present(self.dialog)

    def _open_install(self):
        self._install_page = Adw.PreferencesPage()
        self._install_groups = []
        self._fill_install_page()
        toolbar = Adw.ToolbarView(content=self._install_page)
        toolbar.add_top_bar(Adw.HeaderBar())
        page = Adw.NavigationPage(title="Install Proton", child=toolbar)
        page.connect("hidden", lambda *_: setattr(self, "_install_page", None))
        self.dialog.push_subpage(page)

    def _fill_install_page(self):
        for group in self._install_groups:
            self._install_page.remove(group)
        self._install_groups = [self._source_group(source) for source in proton.SOURCES]
        for group in self._install_groups:
            self._install_page.add(group)

    def _source_group(self, source):
        variant = source.default_variant()
        description = source.description
        if variant in VARIANT_NOTES:
            description += f". {VARIANT_NOTES[variant]}"
        group = Adw.PreferencesGroup(title=source.name, description=description)
        if source.name not in self.releases:
            row = Adw.ActionRow(title="Looking for Versions…")
            row.add_suffix(Adw.Spinner())
            group.add(row)
            return group
        if source.name in self.errors:
            group.add(Adw.ActionRow(title="Versions Not Available", subtitle=self.errors[source.name]))
            return group
        have = {b.tag for b in proton.installed(self.window.config) if b.source == source and b.variant == variant}
        for release in self.releases[source.name]:
            archive = release.archive(source, variant)
            if not archive:
                continue
            published = datetime.fromisoformat(release.published.replace("Z", "+00:00")).strftime("%-d %B %Y")
            row = Adw.ActionRow(
                title=source.version(release.tag),
                subtitle=f"Released {published}, {GLib.format_size(archive['size'])} download",
            )
            if release.tag in have:
                label = Gtk.Label(label="Installed", valign=Gtk.Align.CENTER)
                label.add_css_class("dim-label")
                row.add_suffix(label)
            else:
                button = Gtk.Button(label="Install", valign=Gtk.Align.CENTER, sensitive=not _job)
                button.connect("clicked", lambda *_, r=release: self._install(source, r, variant))
                row.add_suffix(button)
            group.add(row)
        return group
