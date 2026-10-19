"""The endpoint agent: every channel runs as a thread on one shared, thread-safe engine."""
import os
import threading
import time

from . import config
from .engine import Engine, format_decision
from .watchers import FolderWatcher, VolumeMonitor, detect_sync_folders, network_shares, removable_volumes
from .watchers.folder import start_thread

_print_lock = threading.Lock()


def say(text):
    with _print_lock:
        print(text, flush=True)


def show(d, action=None, where=None):
    if d.decision == "ALLOW":
        say(f"[{d.channel}] ALLOW  {d.file_name} -> {where or d.device}  ({d.sensitivity}, risk {d.score} {d.level})")
        return
    text = format_decision(d, f"[{d.channel}] {d.file_name} -> {where or d.device}")
    if action:
        text += f"\n  RESPONSE    : {action}"
    say(text)


class Agent:
    def __init__(self, user, *, dry_run=False, mail=False, watch=(), watch_device="Demo-USB",
                 watch_trust="untrusted", usb=True, cloud=True, shares=True, browser=True, engine=None,
                 api_port=config.API_PORT, smtp_port=config.SMTP_PORT):
        self.engine = engine or Engine(dry_run=dry_run)
        self.user = user
        self.mail, self.watch = mail, list(watch)
        self.watch_device, self.watch_trust = watch_device, watch_trust
        self.usb, self.cloud, self.shares, self.browser = usb, cloud, shares, browser
        self.api_port, self.smtp_port = api_port, smtp_port
        self.stop_event = threading.Event()
        self.api = self.gateway = None
        self.watchers = []

    # -------------------------------------------------------------- callbacks
    def _on_file(self, d, action, watcher):
        show(d, action, watcher.device)

    def _on_browser(self, d, action, host):
        show(d, action, host)

    def _on_mail(self, decisions, reply, device):
        for d in decisions:
            show(d, None, device)
        say(f"  [email] SMTP reply: {reply}")

    # -------------------------------------------------------------- start / stop
    def start(self):
        e = self.engine
        lines = [f"Data Sentinel agent - user '{self.user}'" + ("  [DRY-RUN: nothing is moved, dropped or refused]"
                                                              if e.dry_run else ""),
                 f"  database      : {e.db.location}",
                 f"  anomaly model : {e.anomaly.source}"]
        if self.browser:
            from .browser_api import ScanAPI
            self.api = ScanAPI(e, self.user, port=self.api_port, on_decision=self._on_browser)
            self.api.start()
            lines.append(f"  browser API   : http://127.0.0.1:{self.api.port}  (token in {config.TOKEN_PATH.name})")
        if self.mail:
            from .smtp_gateway import SMTPGateway
            self.gateway = SMTPGateway(e, self.user, port=self.smtp_port, on_decision=self._on_mail)
            self.gateway.start()
            target = self.gateway.upstream or f"outbox/ ({self.gateway.outbox})"
            lines.append(f"  mail gateway  : 127.0.0.1:{self.smtp_port} -> {target}")
        for i, folder in enumerate(self.watch):
            os.makedirs(folder, exist_ok=True)
            device = self.watch_device if len(self.watch) == 1 else f"{self.watch_device}-{i + 1}"
            w = FolderWatcher(e, folder, device, self.user, dest_type="usb", channel="usb", trust=self.watch_trust,
                              on_decision=self._on_file)
            self.watchers.append(w)
            start_thread(w, self.stop_event)
            lines.append(f"  watched folder: {os.path.abspath(folder)} as USB '{device}' ({self.watch_trust})")
        if self.usb:
            VolumeMonitor(removable_volumes, self._usb_watcher, "usb").start(self.stop_event)
            lines.append("  USB drives    : watching removable volumes (polling every 2 s)")
        if self.cloud:
            found = detect_sync_folders()
            for device, path in found:
                w = FolderWatcher(e, path, device, self.user, dest_type="cloud_sync", channel="cloud_sync",
                                  response="move_out", on_decision=self._on_file)
                self.watchers.append(w)
                start_thread(w, self.stop_event)
                lines.append(f"  sync folder   : {device} at {path}")
            if not found:
                lines.append("  sync folders  : none found")
        if self.shares:
            VolumeMonitor(network_shares, self._share_watcher, "share").start(self.stop_event)
            lines.append("  network shares: watching SMB/NFS/WebDAV mounts")
        say("\n".join(lines))
        say("Waiting for transfers... (Ctrl+C to stop)\n")

    def _usb_watcher(self, vol):
        return FolderWatcher(self.engine, vol.mountpoint, vol.name, self.user, dest_type="usb", channel="usb",
                             on_decision=self._on_file)

    def _share_watcher(self, vol):
        return FolderWatcher(self.engine, vol.mountpoint, vol.name, self.user, dest_type="network_share",
                             channel="network_share", on_decision=self._on_file)

    def stop(self):
        self.stop_event.set()
        if self.api:
            self.api.stop()
        if self.gateway:
            self.gateway.stop()

    def run_forever(self):
        self.start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            say("\nStopping agent...")
        finally:
            self.stop()
