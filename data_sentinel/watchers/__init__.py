"""File-copy channels: USB drives, cloud sync folders and network shares share one folder watcher."""
import threading

from .. import config
from .folder import FolderWatcher, start_thread  # noqa: F401
from .sync import detect_sync_folders  # noqa: F401
from .volumes import network_shares, removable_volumes  # noqa: F401


class VolumeMonitor:
    """Polls a discovery function (USB volumes or network shares) every 2 s and watches each volume.

    A new volume is baselined when it appears; a removed volume is forgotten.
    """

    def __init__(self, discover, make_watcher, label, interval=config.POLL_SECONDS):
        self.discover = discover
        self.make_watcher = make_watcher
        self.label = label
        self.interval = interval
        self.watchers = {}                    # mountpoint -> FolderWatcher

    def tick(self):
        current = {v.mountpoint: v for v in self.discover()}
        for mp in [m for m in self.watchers if m not in current]:
            print(f"  [{self.label}] {self.watchers[mp].device} removed ({mp})", flush=True)
            del self.watchers[mp]
        for mp, vol in current.items():
            if mp not in self.watchers:
                w = self.make_watcher(vol)
                n = w.baseline()
                self.watchers[mp] = w
                print(f"  [{self.label}] {vol.name} connected at {mp} - {n} existing file(s) baselined", flush=True)
        for w in list(self.watchers.values()):
            try:
                w.poll()
            except Exception as exc:
                print(f"  [{self.label}] error scanning {w.root}: {exc}", flush=True)

    def run(self, stop_event):
        while not stop_event.is_set():
            self.tick()
            slowest = max([w.last_walk_seconds for w in self.watchers.values()] or [0])
            stop_event.wait(max(self.interval, 3 * slowest))

    def start(self, stop_event):
        t = threading.Thread(target=self.run, args=(stop_event,), daemon=True, name=f"monitor:{self.label}")
        t.start()
        return t
