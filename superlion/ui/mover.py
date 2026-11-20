"""Runs moves and uninstalls with Steam closed, then starts it again."""

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from gi.repository import Adw, GLib, GObject

from .. import moving, pending, shortcuts, steam_control, steam_settings

ING = {"move": "Moving", "uninstall": "Uninstalling"}
DONE = {"move": "moved", "uninstall": "uninstalled"}


@dataclass
class Job:
    kind: str  # "move" or "uninstall"
    name: str
    run: Callable[[moving.Progress], None]
    size: int
    shortcut_moves: dict[int, tuple[Path, Path]] = field(default_factory=dict)
    appids: list[int] = field(default_factory=list)
    dest: Path | None = None


def _games(jobs):
    return jobs[0].name if len(jobs) == 1 else f"{len(jobs)} games"


class Mover(GObject.Object):
    # progress: label, bytes done, bytes total (parts deleted and parts in all for an uninstall).
    # finished: [(name, message)] for the jobs that failed.
    __gsignals__ = {
        "progress": (GObject.SignalFlags.RUN_FIRST, None, (str, GObject.TYPE_INT64, GObject.TYPE_INT64)),
        "finished": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }
    busy = GObject.Property(type=bool, default=False)

    def __init__(self, window):
        super().__init__()
        self.window = window
        self.jobs = []
        self.progress = moving.Progress()

    @property
    def what(self):
        return "uninstall" if self.jobs and self.jobs[0].kind == "uninstall" else "move"

    def busy_with(self, appid):
        return self.busy and any(appid in job.appids for job in self.jobs)

    def _refuse_if_busy(self):
        if self.window.relaunching:
            self.window.toast("Wait until Steam has restarted")
            return True
        if self.busy:
            kind = self.jobs[0].kind
            self.window.toast(f"Wait until {_games(self.jobs)} {'is' if len(self.jobs) == 1 else 'are'} {DONE[kind]}")
        return self.busy

    def cancel(self):
        self.progress.cancelled = True

    def start(self, jobs, parent, verb):
        from .window import will_close_text

        if not jobs or self._refuse_if_busy():
            return
        config = self.window.config
        if not steam_control.is_running(config):
            self._begin(jobs, verb, was_running=False)
            return
        running = steam_control.running_games()
        if not running:
            self._begin(jobs, verb, was_running=True)
            return
        dialog = Adw.AlertDialog(
            heading="Steam Must Be Closed",
            body=will_close_text(self.window.running_game_names(running)),
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("close", f"Close Steam and {verb}")
        dialog.set_response_appearance("close", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("close")
        dialog.set_close_response("cancel")
        dialog.connect(
            "response",
            lambda _d, response: response == "close" and self._begin(jobs, verb, was_running=True),
        )
        dialog.present(parent or self.window)

    def _begin(self, jobs, verb, was_running):
        if self._refuse_if_busy():
            return
        self.jobs = list(jobs)
        self.progress = moving.Progress()
        self.failures = []
        self.succeeded = []
        self.was_running = was_running
        self.busy = True
        self.window.toast(f"{ING[jobs[0].kind]} {_games(jobs)}…")
        if not was_running:
            self._run()
            return

        def closed(ok):
            if ok:
                self._run()
                return
            self.window.toast(f"Steam did not close within a minute, so nothing was {DONE[jobs[0].kind]}")
            self.busy = False
            self.emit("finished", [])

        steam_control.shutdown(self.window.config, closed)

    def _run(self):
        self._thread = threading.Thread(target=self._work)
        self._thread.start()
        GLib.timeout_add(250, self._poll)

    def _work(self):
        count = len(self.jobs)
        for index, job in enumerate(self.jobs, 1):
            progress = self.progress
            if progress.cancelled:
                break
            progress.done = progress.total = 0
            counter = f" ({index} of {count})" if count > 1 else ""
            progress.label = f"{ING[job.kind]} {job.name}{counter}…"
            try:
                job.run(progress)
            except moving.MoveError as error:
                self.failures.append((job.name, str(error)))
            except OSError as error:
                self.failures.append((job.name, error.strerror or str(error)))
            except Exception as error:  # A job must not stop the rest or leave Steam closed.
                self.failures.append((job.name, str(error)))
            else:
                self.succeeded.append(job)

    def _poll(self):
        progress = self.progress
        self.emit("progress", progress.label, progress.done, progress.total)
        if self._thread.is_alive():
            return GLib.SOURCE_CONTINUE
        self._finish()
        return GLib.SOURCE_REMOVE

    def _finish(self):
        config = self.window.config
        failures = list(self.failures)
        # Queued changes go first, so an old launch option cannot put a moved path back.
        try:
            pending.apply_now(config)
        except Exception as error:
            failures.append(("Waiting changes", getattr(error, "strerror", None) or str(error)))
        moves = {appid: paths for job in self.succeeded for appid, paths in job.shortcut_moves.items()}
        if moves:
            try:
                steam_settings.rewrite_shortcut_paths(config, moves)
            except Exception as error:
                failures.append(("Steam shortcuts", getattr(error, "strerror", None) or str(error)))
            for new in {new for _old, new in moves.values()}:
                if not shortcuts.steam_can_read(config, new):
                    error = shortcuts.grant_flatpak_access(new)
                    if error:
                        failures.append((str(new), error))
        self.busy = False
        try:
            self._report(failures)
        finally:
            # Started after the reload, so a retried pending write cannot race Steam starting up.
            try:
                if self.was_running:
                    steam_control.start(config)
            finally:
                self.emit("finished", failures)

    def _report(self, failures):
        self.window.reload()
        if self.succeeded:
            kind = self.succeeded[0].kind
            text = f"{_games(self.succeeded)} {DONE[kind]}"
            dests = {job.dest for job in self.succeeded}
            if kind == "move" and len(dests) == 1 and None not in dests:
                text += f" to {dests.pop()}"
            self.window.toast(text)
        if failures and not self.progress.cancelled:
            what = "Moved" if self.jobs[0].kind == "move" else "Uninstalled"
            if not self.failures:
                heading = "Some Changes Could Not Be Saved"
            elif len(self.jobs) == 1:
                heading = f"{self.jobs[0].name} Could Not Be {what}"
            else:
                heading = f"Some Games Could Not Be {what}"
            dialog = Adw.AlertDialog(
                heading=heading,
                body="\n".join(f"{name}: {message}" for name, message in failures),
            )
            dialog.add_response("close", "Close")
            dialog.present(self.window)
