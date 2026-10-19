"""Polling folder watcher shared by the USB, cloud-sync and network-share channels.

* Files already present when watching starts are the baseline and are not scanned.
* A new (or changed) file is scanned once its size and mtime stop changing between polls.
* Temp/lock files and OS folders are ignored.
* On an enforced BLOCK the file is moved into quarantine/ (with a small JSON note - no content).
"""
import fnmatch
import json
import os
import re
import shutil
import threading
import time
from datetime import datetime

from .. import config
from ..engine import Payload

IGNORE_FILES = ["~$*", "*.tmp", "*.part", "*.crdownload", ".DS_Store", "desktop.ini",
                # extra OS / sync-client noise
                "._*", "Thumbs.db", ".~lock.*#", "*.icloud", "*.download", "*.partial", "*.swp",
                ".dropbox", ".dropbox.attr", "Icon\r", "*.sentinel.json"]
IGNORE_DIRS = {"System Volume Information", "$RECYCLE.BIN", ".Trashes", ".Spotlight-V100", ".fseventsd",
               ".TemporaryItems", ".DocumentRevisions-V100", ".Trash", ".dropbox.cache",
               ".tmp.drivedownload", ".tmp.driveupload", "$Recycle.Bin"}


def ignored_file(name):
    low = name.lower()
    return any(fnmatch.fnmatchcase(low, p.lower()) for p in IGNORE_FILES)


def _safe(text):
    return re.sub(r"[^\w.-]+", "_", text).strip("_")[:60] or "device"


class FolderWatcher:
    def __init__(self, engine, root, device, user, *, dest_type="usb", channel="usb", trust="unknown",
                 role="employee", response="quarantine", quarantine_dir=None, on_decision=None):
        self.engine = engine
        self.root = os.path.abspath(root)
        self.device = device
        self.user = user
        self.role = role
        self.dest_type = dest_type
        self.channel = channel
        self.trust = trust
        self.response = response            # "quarantine" (USB/share) or "move_out" (sync folder)
        self.quarantine_dir = os.path.abspath(quarantine_dir or config.QUARANTINE_DIR)
        self.on_decision = on_decision
        self.known = {}                     # path -> (size, mtime_ns) already handled / baseline
        self.pending = {}                   # path -> signature seen on the previous poll
        self.last_walk_seconds = 0.0

    # ------------------------------------------------------------------ scanning
    def snapshot(self):
        start = time.monotonic()
        snap = {}
        for dirpath, dirnames, filenames in os.walk(self.root, onerror=lambda e: None):
            dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS
                           and os.path.join(dirpath, d) != self.quarantine_dir]
            for name in filenames:
                if ignored_file(name):
                    continue
                path = os.path.join(dirpath, name)
                try:
                    st = os.lstat(path)
                except OSError:
                    continue
                if not os.path.isfile(path) or os.path.islink(path):
                    continue
                snap[path] = (st.st_size, st.st_mtime_ns)
        self.last_walk_seconds = time.monotonic() - start
        return snap

    def baseline(self):
        self.known = self.snapshot()
        self.pending = {}
        return len(self.known)

    def poll(self):
        """One polling pass. Returns the decisions made in this pass."""
        snap = self.snapshot()
        decisions = []
        for path, sig in snap.items():
            if self.known.get(path) == sig:
                continue                                    # baseline or already handled
            if self.pending.get(path) != sig:
                self.pending[path] = sig                    # new or still growing: wait one poll
                continue
            del self.pending[path]
            self.known[path] = sig
            d = self.handle(path)
            if d is not None:
                decisions.append(d)
        for path in [p for p in self.pending if p not in snap]:
            del self.pending[path]
        for path in [p for p in self.known if p not in snap]:
            del self.known[path]                            # so a re-copied file is scanned again
        return decisions

    def handle(self, path):
        try:
            payload = Payload.from_path(path)
        except OSError as exc:                              # locked or vanished: retry on next poll
            self.known.pop(path, None)
            print(f"  [watch] cannot read {path}: {exc}")
            return None
        d = self.engine.process(self.user, payload, self.device, self.dest_type, self.channel,
                                role=self.role, trust=self.trust)
        action = None
        if d.enforce:
            action = self.quarantine(path, d)
        elif d.decision == "BLOCK":
            action = "dry-run: file left in place"
        if action:
            self.engine.record_response(d.event_id, action)
        if self.on_decision:
            self.on_decision(d, action, self)
        return d

    def quarantine(self, path, d):
        os.makedirs(self.quarantine_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = os.path.join(self.quarantine_dir, f"{stamp}_{_safe(self.device)}_{os.path.basename(path)}")
        n = 1
        while os.path.exists(target):
            root, ext = os.path.splitext(target)
            target = f"{root}-{n}{ext}"
            n += 1
        try:
            shutil.move(path, target)
        except OSError as exc:
            print(f"  [watch] could not move {path} to quarantine: {exc}")
            return f"quarantine FAILED: {exc}"
        self.known.pop(path, None)
        note = {"event_id": d.event_id, "original_path": path, "device": self.device, "user": d.user,
                "decision": d.decision, "score": d.score, "level": d.level, "sensitivity": d.sensitivity,
                "reasons": d.reasons, "quarantined_at": datetime.now().isoformat(timespec="seconds")}
        with open(target + ".sentinel.json", "w") as fh:
            json.dump(note, fh, indent=2)
        where = os.path.relpath(target, os.path.dirname(self.quarantine_dir))
        verb = "moved out of the sync folder to" if self.response == "move_out" else "quarantined to"
        return f"{verb} {where}"

    # ------------------------------------------------------------------ loop
    def run(self, stop_event, interval=config.POLL_SECONDS):
        self.baseline()
        while not stop_event.wait(self.interval(interval)):
            try:
                self.poll()
            except Exception as exc:                        # keep watching whatever happens
                print(f"  [watch] error while scanning {self.root}: {exc}")

    def interval(self, base):
        # Back off on very large folders so polling never eats the CPU.
        return max(base, 3 * self.last_walk_seconds)


def start_thread(watcher, stop_event, interval=config.POLL_SECONDS):
    t = threading.Thread(target=watcher.run, args=(stop_event, interval), daemon=True,
                         name=f"watch:{watcher.device}")
    t.start()
    return t
