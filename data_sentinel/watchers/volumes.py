"""Discover removable (USB) volumes and network shares with psutil, per operating system.

macOS   : /Volumes/* checked with `diskutil info -plist` (external / removable, not disk images)
Windows : partitions flagged "removable"; named by volume label + serial
Linux   : /sys/block/<disk>/removable or a USB bus path, or mounted under /media, /run/media
"""
import ctypes
import os
import platform
import plistlib
import subprocess
from dataclasses import dataclass

import psutil

NETWORK_FS = {"smbfs", "cifs", "smb", "smb2", "smb3", "nfs", "nfs4", "afpfs", "webdav", "davfs", "fuse.davfs",
              "fuse.sshfs", "9p"}


@dataclass(frozen=True)
class Volume:
    mountpoint: str
    name: str
    kind: str          # "usb" or "network_share"


# --------------------------------------------------------------------------- macOS
_diskutil_cache = {}


def _diskutil_info(target):
    if target not in _diskutil_cache:
        try:
            out = subprocess.run(["diskutil", "info", "-plist", target], capture_output=True, timeout=10).stdout
            _diskutil_cache[target] = plistlib.loads(out) if out else {}
        except (OSError, subprocess.SubprocessError, plistlib.InvalidFileException):
            _diskutil_cache[target] = {}
    return _diskutil_cache[target]


def mac_is_removable(info):
    if not info or info.get("Internal", True):
        return False
    if info.get("BusProtocol") in ("Disk Image", "Virtual Interface"):
        return False
    return bool(info.get("RemovableMedia") or info.get("Removable") or info.get("Ejectable")
                or info.get("BusProtocol") in ("USB", "Secure Digital", "Thunderbolt"))


def mac_volume_name(info, mountpoint):
    label = info.get("VolumeName") or os.path.basename(mountpoint)
    uid = (info.get("VolumeUUID") or info.get("DiskUUID") or "").replace("-", "")[:8]
    return f"USB:{label}-{uid}" if uid else f"USB:{label}"


def _mac_removable():
    vols = []
    for p in psutil.disk_partitions(all=False):
        if not p.mountpoint.startswith("/Volumes/"):
            continue
        info = _diskutil_info(p.device or p.mountpoint)
        if mac_is_removable(info):
            vols.append(Volume(p.mountpoint, mac_volume_name(info, p.mountpoint), "usb"))
    return vols


# --------------------------------------------------------------------------- Windows
def _win_label_serial(root):
    label = ctypes.create_unicode_buffer(261)
    fs = ctypes.create_unicode_buffer(261)
    serial = ctypes.c_uint32()
    ok = ctypes.windll.kernel32.GetVolumeInformationW(ctypes.c_wchar_p(root), label, 261, ctypes.byref(serial),
                                                      None, None, fs, 261)
    return (label.value or "NO_LABEL", f"{serial.value:08X}") if ok else ("NO_LABEL", "00000000")


def _win_removable():
    vols = []
    for p in psutil.disk_partitions(all=False):
        if "removable" in p.opts and os.path.exists(p.mountpoint):
            label, serial = _win_label_serial(p.mountpoint)
            vols.append(Volume(p.mountpoint, f"USB:{label}-{serial}", "usb"))
    return vols


# --------------------------------------------------------------------------- Linux
def linux_is_removable(device, mountpoint, sys_block="/sys/block"):
    disk = os.path.basename(device or "")
    while disk and not os.path.exists(os.path.join(sys_block, disk)) and disk[-1].isdigit():
        disk = disk[:-1]                                  # sdb1 -> sdb
    if disk.startswith("nvme") or disk.startswith("mmcblk"):
        disk = disk.split("p")[0] if "p" in disk[4:] else disk
    base = os.path.join(sys_block, disk)
    try:
        if open(os.path.join(base, "removable")).read().strip() == "1":
            return True
    except OSError:
        pass
    try:
        if "/usb" in os.path.realpath(base):
            return True
    except OSError:
        pass
    return mountpoint.startswith(("/media/", "/run/media/"))


def _linux_label(device):
    by_label = "/dev/disk/by-label"
    try:
        for name in os.listdir(by_label):
            if os.path.realpath(os.path.join(by_label, name)) == os.path.realpath(device):
                return name.replace("\\x20", " ")
    except OSError:
        pass
    return None


def _linux_removable():
    vols = []
    for p in psutil.disk_partitions(all=False):
        if p.mountpoint in ("/", "/boot", "/boot/efi") or not p.device.startswith("/dev/"):
            continue
        if linux_is_removable(p.device, p.mountpoint):
            label = _linux_label(p.device) or os.path.basename(p.mountpoint)
            vols.append(Volume(p.mountpoint, f"USB:{label}-{os.path.basename(p.device)}", "usb"))
    return vols


# --------------------------------------------------------------------------- public API
def removable_volumes():
    system = platform.system()
    try:
        if system == "Darwin":
            return _mac_removable()
        if system == "Windows":
            return _win_removable()
        return _linux_removable()
    except Exception as exc:                                # never crash the agent on discovery
        print(f"  [usb] volume discovery failed: {exc}")
        return []


def network_shares():
    vols = []
    try:
        parts = psutil.disk_partitions(all=True)
    except Exception:
        return vols
    for p in parts:
        fstype = (p.fstype or "").lower()
        remote = fstype in NETWORK_FS or (platform.system() == "Windows" and "remote" in p.opts)
        if remote and os.path.isdir(p.mountpoint):
            vols.append(Volume(p.mountpoint, f"share:{p.device or p.mountpoint}", "network_share"))
    return vols
