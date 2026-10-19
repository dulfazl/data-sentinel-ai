"""Auto-detect cloud sync folders: Google Drive for desktop, OneDrive, Dropbox, iCloud Drive and Box.

detect_sync_folders() only looks at folder names - it never opens or lists files inside them.
``home``/``system``/``env`` can be passed in so tests run against a fake home folder.
"""
import json
import os
import platform
import string


def _provider_for(name):
    low = name.lower()
    if low.startswith(("googledrive", "google drive", "google drive-")) or low == "my drive":
        return "Google Drive"
    if low.startswith("onedrive"):
        return "OneDrive"
    if low.startswith("dropbox"):
        return "Dropbox"
    if low.startswith("box"):
        return "Box"
    if low.startswith("icloud"):
        return "iCloud Drive"
    return None


def _label(provider, folder_name):
    """'OneDrive - Contoso' / 'OneDrive-Personal' -> 'OneDrive (Contoso)'; plain names stay plain."""
    rest = folder_name[len(provider.replace(" ", "")):] if folder_name.lower().startswith(
        provider.replace(" ", "").lower()) else ""
    rest = rest.strip(" -_")
    if provider == "Google Drive" or not rest or rest.lower() in ("personal", "box"):
        return provider
    return f"{provider} ({rest})"


def _dropbox_info(paths):
    found = []
    for p in paths:
        try:
            with open(p) as fh:
                info = json.load(fh)
        except (OSError, ValueError):
            continue
        for kind, data in info.items():
            if isinstance(data, dict) and data.get("path"):
                found.append(("Dropbox" if kind == "personal" else f"Dropbox ({kind})", data["path"]))
    return found


def detect_sync_folders(home=None, system=None, env=None):
    """Return a list of (device_name, path) for sync folders that exist."""
    home = os.path.abspath(home or os.path.expanduser("~"))
    system = system or platform.system()
    env = os.environ if env is None else env
    candidates = []

    if system == "Darwin":
        cloud = os.path.join(home, "Library", "CloudStorage")
        if os.path.isdir(cloud):
            for name in sorted(os.listdir(cloud)):
                provider = _provider_for(name)
                if provider:
                    candidates.append((_label(provider, name), os.path.join(cloud, name)))
        candidates.append(("iCloud Drive", os.path.join(home, "Library", "Mobile Documents", "com~apple~CloudDocs")))
        candidates += _dropbox_info([os.path.join(home, ".dropbox", "info.json")])
        for name in ("Google Drive", "Dropbox", "OneDrive", "Box", "Box Sync"):
            candidates.append((_provider_for(name), os.path.join(home, name)))

    elif system == "Windows":
        for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
            if env.get(var):
                candidates.append(("OneDrive" if var != "OneDriveCommercial" else "OneDrive (Business)", env[var]))
        if os.path.isdir(home):
            for name in sorted(os.listdir(home)):
                provider = _provider_for(name)
                if provider and provider != "iCloud Drive":
                    candidates.append((_label(provider, name), os.path.join(home, name)))
        candidates.append(("iCloud Drive", os.path.join(home, "iCloudDrive")))
        candidates += _dropbox_info([os.path.join(env.get("APPDATA", ""), "Dropbox", "info.json"),
                                     os.path.join(env.get("LOCALAPPDATA", ""), "Dropbox", "info.json")])
        # Google Drive for desktop mounts a virtual drive (G: by default) with a "My Drive" folder.
        for letter in string.ascii_uppercase[3:]:
            my_drive = f"{letter}:\\My Drive"
            if os.path.isdir(my_drive):
                candidates.append(("Google Drive", my_drive))

    else:  # Linux and others
        for name in ("Dropbox", "OneDrive", "Google Drive", "GoogleDrive", "gdrive", "Box"):
            provider = _provider_for(name) or "Google Drive"
            candidates.append((provider, os.path.join(home, name)))
        candidates += _dropbox_info([os.path.join(home, ".dropbox", "info.json")])

    seen, result = set(), []
    for device, path in candidates:
        if not device or not path or not os.path.isdir(path):
            continue
        real = os.path.realpath(path)
        if real in seen:
            continue
        seen.add(real)
        result.append((device, path))
    return result
