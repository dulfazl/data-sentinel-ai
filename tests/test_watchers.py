"""Folder watcher, volume discovery and sync-folder detection - temp folders only."""
import os

from conftest import PAYROLL
from data_sentinel.watchers import VolumeMonitor, detect_sync_folders
from data_sentinel.watchers.folder import FolderWatcher, ignored_file
from data_sentinel.watchers.volumes import Volume, linux_is_removable, mac_is_removable, mac_volume_name


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


def make_watcher(engine, tmp_path, **kw):
    usb = tmp_path / "usb"
    usb.mkdir(exist_ok=True)
    return FolderWatcher(engine, str(usb), "Test-USB", "carol", trust="untrusted",
                         quarantine_dir=str(tmp_path / "quarantine"), **kw), usb


def test_baseline_then_quarantine(engine, db, tmp_path):
    w, usb = make_watcher(engine, tmp_path)
    write(usb / "old_payroll.csv", PAYROLL)                 # already on the drive -> baseline
    assert w.baseline() == 1
    write(usb / "sub" / "customer_payroll_confidential.csv", PAYROLL)
    assert w.poll() == []                                   # first sighting: wait for size to settle
    decisions = w.poll()
    assert [d.decision for d in decisions] == ["BLOCK"]
    assert not (usb / "sub" / "customer_payroll_confidential.csv").exists()
    q = os.listdir(tmp_path / "quarantine")
    assert any(n.endswith("customer_payroll_confidential.csv") for n in q)
    assert any(n.endswith(".sentinel.json") for n in q)
    assert (usb / "old_payroll.csv").exists()                # baseline file untouched
    row = db.one("SELECT action_taken FROM transfer_events WHERE id = ?", (decisions[0].event_id,))
    assert row["action_taken"].startswith("quarantined to quarantine")
    assert db.event_count() == 1


def test_allowed_file_stays_and_is_scanned_once(engine, db, tmp_path):
    w, usb = make_watcher(engine, tmp_path)
    w.baseline()
    write(usb / "notice.txt", "Join us for the annual picnic on Friday!")
    w.poll()
    assert [d.decision for d in w.poll()] == ["ALLOW"]
    assert w.poll() == [] and (usb / "notice.txt").exists()
    assert db.event_count() == 1


def test_dry_run_moves_nothing(dry_engine, db, tmp_path):
    w, usb = make_watcher(dry_engine, tmp_path)
    w.baseline()
    write(usb / "payroll.csv", PAYROLL)
    w.poll()
    d = w.poll()[0]
    assert d.decision == "BLOCK" and not d.enforce
    assert (usb / "payroll.csv").exists()
    assert not (tmp_path / "quarantine").exists()
    assert db.one("SELECT action_taken FROM transfer_events")["action_taken"].startswith("dry-run")
    assert db.scalar("SELECT COUNT(*) FROM alerts") == 1       # dry-run still alerts


def test_growing_file_waits_until_stable(engine, tmp_path):
    w, usb = make_watcher(engine, tmp_path)
    w.baseline()
    path = usb / "big.csv"
    write(path, "name,salary\n")
    assert w.poll() == []
    with open(path, "a") as fh:
        fh.write("A,1\n" * 100)                              # still being copied
    assert w.poll() == []
    assert len(w.poll()) == 1


def test_temp_files_and_os_folders_ignored(engine, db, tmp_path):
    w, usb = make_watcher(engine, tmp_path)
    w.baseline()
    for name in ["~$report.docx", "x.tmp", "movie.part", "file.crdownload", ".DS_Store", "desktop.ini", "._x.csv"]:
        write(usb / name, PAYROLL)
    write(usb / "System Volume Information" / "a.csv", PAYROLL)
    write(usb / ".Trashes" / "a.csv", PAYROLL)
    write(usb / "$RECYCLE.BIN" / "a.csv", PAYROLL)
    w.poll()
    assert w.poll() == [] and db.event_count() == 0
    assert ignored_file("~$Budget.xlsx") and not ignored_file("budget.xlsx")


def test_volume_monitor_handles_plug_and_unplug(engine, tmp_path):
    vols = []
    q = tmp_path / "quarantine"
    mon = VolumeMonitor(lambda: list(vols),
                        lambda v: FolderWatcher(engine, v.mountpoint, v.name, "alice", quarantine_dir=str(q)), "usb")
    stick = tmp_path / "STICK"
    write(stick / "existing.csv", PAYROLL)
    vols.append(Volume(str(stick), "USB:STICK-1234", "usb"))
    mon.tick()                                              # plugged in: baseline
    write(stick / "new_payroll.csv", PAYROLL)
    mon.tick()
    mon.tick()
    assert not (stick / "new_payroll.csv").exists() and (stick / "existing.csv").exists()
    vols.clear()
    mon.tick()
    assert mon.watchers == {}


def test_mac_diskutil_decision():
    usb = {"Internal": False, "BusProtocol": "USB", "RemovableMedia": True, "VolumeName": "KINGSTON",
           "VolumeUUID": "1A2B3C4D-0000-1111-2222-333344445555"}
    assert mac_is_removable(usb)
    assert mac_volume_name(usb, "/Volumes/KINGSTON") == "USB:KINGSTON-1A2B3C4D"
    assert not mac_is_removable({"Internal": True, "BusProtocol": "Apple Fabric"})
    assert not mac_is_removable({"Internal": False, "BusProtocol": "Disk Image", "Ejectable": True})
    assert not mac_is_removable({})


def test_linux_removable_detection(tmp_path):
    sysb = tmp_path / "sys_block"
    write(sysb / "sdb" / "removable", "1\n")
    write(sysb / "sda" / "removable", "0\n")
    assert linux_is_removable("/dev/sdb1", "/mnt/x", str(sysb))
    assert not linux_is_removable("/dev/sda2", "/home", str(sysb))
    assert linux_is_removable("/dev/sdc1", "/media/me/STICK", str(sysb))


def test_sync_folder_detection_macos(tmp_path):
    home = tmp_path / "home"
    for d in ["Library/CloudStorage/GoogleDrive-alice@example.com", "Library/CloudStorage/OneDrive-Personal",
              "Library/CloudStorage/Dropbox", "Library/CloudStorage/Box-Box",
              "Library/Mobile Documents/com~apple~CloudDocs", "Documents"]:
        os.makedirs(home / d)
    found = dict(detect_sync_folders(home=str(home), system="Darwin"))
    assert set(found) == {"Google Drive", "OneDrive", "Dropbox", "Box", "iCloud Drive"}


def test_sync_folder_detection_windows_and_linux(tmp_path):
    home = tmp_path / "home"
    for d in ["OneDrive - Contoso", "Dropbox", "iCloudDrive", "Box", "Pictures"]:
        os.makedirs(home / d)
    env = {"OneDriveCommercial": str(home / "OneDrive - Contoso")}
    found = dict(detect_sync_folders(home=str(home), system="Windows", env=env))
    assert set(found) == {"OneDrive (Business)", "Dropbox", "iCloud Drive", "Box"}
    lin = tmp_path / "lin"
    os.makedirs(lin / "Dropbox")
    assert dict(detect_sync_folders(home=str(lin), system="Linux")) == {"Dropbox": str(lin / "Dropbox")}
