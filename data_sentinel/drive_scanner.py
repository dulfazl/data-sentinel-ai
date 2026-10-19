"""Scan files already in Google Drive for risky sharing (Drive API v3, OAuth).

Finds files shared "anyone with the link", public on the web, or with people/domains outside
SENTINEL_COMPANY_DOMAINS. Google Docs/Sheets/Slides are exported as text; other files are
downloaded (up to 20 MB) or judged by name. Each risky file goes through the pipeline as a
cloud_share transfer: public -> "gdrive:public-link" (untrusted), external -> "gdrive:external" (unknown).
With --fix, a BLOCK removes only the risky permissions; owners and internal shares are kept.

Setup (one time): see README "Google Drive scanner". Needs credentials.json (OAuth client of type
"Desktop app") and:  pip install google-api-python-client google-auth-oauthlib
"""
import io
import os

from . import config
from .destinations import is_company_domain
from .engine import Payload

GOOGLE_EXPORTS = {
    "application/vnd.google-apps.document": ("text/plain", ".txt"),
    "application/vnd.google-apps.spreadsheet": ("text/csv", ".csv"),
    "application/vnd.google-apps.presentation": ("text/plain", ".txt"),
}
SCOPE_READ = "https://www.googleapis.com/auth/drive.readonly"
SCOPE_FULL = "https://www.googleapis.com/auth/drive"


def risky_permissions(file, domains=None):
    """Return (kind, [permissions]) where kind is 'public', 'external' or None."""
    public, external = [], []
    for p in file.get("permissions", []):
        ptype = p.get("type")
        if p.get("role") == "owner":
            continue
        if ptype == "anyone":
            public.append(p)
        elif ptype == "domain" and not is_company_domain(p.get("domain", ""), domains):
            external.append(p)
        elif ptype in ("user", "group"):
            addr = p.get("emailAddress", "")
            if "@" in addr and not is_company_domain(addr.rsplit("@", 1)[1], domains):
                external.append(p)
    if public:
        return "public", public + external
    if external:
        return "external", external
    return None, []


def describe(perm):
    if perm.get("type") == "anyone":
        return "anyone with the link" + (" (public on the web)" if perm.get("allowFileDiscovery") else "")
    if perm.get("type") == "domain":
        return f"domain {perm.get('domain')}"
    return perm.get("emailAddress", perm.get("id", "?"))


class DriveScanner:
    def __init__(self, engine, client, default_user="drive-owner", fix=False, out=print):
        self.engine = engine
        self.client = client
        self.default_user = default_user
        self.fix = fix
        self.out = out

    def _user_for(self, file):
        for owner in file.get("owners", []):
            addr = owner.get("emailAddress", "")
            if "@" in addr:
                return addr.split("@", 1)[0].lower()
        return self.default_user

    def _payload(self, file):
        mime = file.get("mimeType", "")
        name = file.get("name", "untitled")
        if mime in GOOGLE_EXPORTS:
            export_mime, ext = GOOGLE_EXPORTS[mime]
            text = self.client.export_text(file["id"], export_mime)
            return Payload.from_text(name if name.lower().endswith(ext) else name + ext, text)
        size = int(file.get("size") or 0)
        if mime.startswith("application/vnd.google-apps"):
            return Payload.name_only(name, size, "Google file type without a text export")
        if size > config.MAX_INSPECT_BYTES:
            return Payload.name_only(name, size, f"Drive file of {size / 1e6:.1f} MB judged by name and size")
        return Payload.from_bytes(name, self.client.download(file["id"]))

    def scan(self):
        results = []
        for file in self.client.list_files():
            kind, perms = risky_permissions(file)
            if not kind:
                continue
            device = "gdrive:public-link" if kind == "public" else "gdrive:external"
            trust = "untrusted" if kind == "public" else "unknown"
            d = self.engine.process(self._user_for(file), self._payload(file), device, "cloud_share", "drive",
                                    trust=trust)
            shared = ", ".join(describe(p) for p in perms)
            self.out(f"\n[{d.decision}] {file.get('name')} - shared with {shared}")
            self.out(f"    {d.sensitivity}, risk {d.score} ({d.level})")
            removed = []
            if d.decision == "BLOCK":
                if self.fix and not self.engine.dry_run:
                    for p in perms:
                        self.client.delete_permission(file["id"], p["id"])
                        removed.append(describe(p))
                    action = "removed sharing: " + ", ".join(removed)
                    self.out(f"    FIXED: {action}")
                elif self.fix:
                    action = "dry-run: sharing left unchanged"
                    self.out(f"    dry-run: would remove {shared}")
                else:
                    action = "report only: run scan-drive --fix to remove the risky sharing"
                    self.out(f"    -> {action}")
                self.engine.record_response(d.event_id, action)
            results.append({"file": file.get("name"), "id": file["id"], "kind": kind, "decision": d,
                            "removed": removed})
        if not results:
            self.out("No files shared publicly or outside the company were found.")
        return results


# --------------------------------------------------------------------------- real client
class GoogleDriveClient:
    """Thin wrapper over Drive API v3 (google-api-python-client)."""

    FIELDS = ("nextPageToken, files(id, name, mimeType, size, owners(emailAddress), webViewLink, "
              "permissions(id, type, role, emailAddress, domain, allowFileDiscovery))")

    def __init__(self, credentials_file="credentials.json", token_file=None, write=False):
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise SystemExit("Google API libraries missing. Install them with:\n"
                             "  pip install google-api-python-client google-auth-oauthlib") from exc
        scopes = [SCOPE_FULL if write else SCOPE_READ]
        token_file = token_file or str(config.HOME / (".drive_token_rw.json" if write else ".drive_token.json"))
        creds = Credentials.from_authorized_user_file(token_file, scopes) if os.path.exists(token_file) else None
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not os.path.exists(credentials_file):
                    raise SystemExit(f"{credentials_file} not found. See README 'Google Drive scanner' for setup.")
                creds = InstalledAppFlow.from_client_secrets_file(credentials_file, scopes).run_local_server(port=0)
            with open(token_file, "w") as fh:
                fh.write(creds.to_json())
        self.service = build("drive", "v3", credentials=creds, cache_discovery=False)

    def list_files(self):
        token = None
        while True:
            resp = self.service.files().list(q="trashed = false", fields=self.FIELDS, pageSize=100,
                                             pageToken=token, supportsAllDrives=True,
                                             includeItemsFromAllDrives=True).execute()
            for f in resp.get("files", []):
                if "permissions" not in f:              # shared-drive items: ask separately
                    f["permissions"] = self.service.permissions().list(
                        fileId=f["id"], supportsAllDrives=True,
                        fields="permissions(id, type, role, emailAddress, domain, allowFileDiscovery)"
                    ).execute().get("permissions", [])
                yield f
            token = resp.get("nextPageToken")
            if not token:
                break

    def export_text(self, file_id, mime):
        data = self.service.files().export(fileId=file_id, mimeType=mime).execute()
        return data.decode("utf-8", "ignore") if isinstance(data, bytes) else str(data)

    def download(self, file_id):
        from googleapiclient.http import MediaIoBaseDownload
        buf = io.BytesIO()
        req = self.service.files().get_media(fileId=file_id, supportsAllDrives=True)
        dl = MediaIoBaseDownload(buf, req)
        done = False
        while not done:
            _, done = dl.next_chunk()
        return buf.getvalue()

    def delete_permission(self, file_id, permission_id):
        self.service.permissions().delete(fileId=file_id, permissionId=permission_id,
                                          supportsAllDrives=True).execute()


# --------------------------------------------------------------------------- fake client
class FakeDriveClient:
    """In-memory Drive used by the tests and by `scan-drive --demo` (synthetic files only)."""

    def __init__(self, files=None, contents=None):
        self.files = files if files is not None else demo_files()
        self.contents = contents if contents is not None else DEMO_CONTENTS
        self.deleted = []

    def list_files(self):
        return [dict(f, permissions=[dict(p) for p in f["permissions"]]) for f in self.files]

    def export_text(self, file_id, mime):
        return self.contents[file_id]

    def download(self, file_id):
        c = self.contents[file_id]
        return c.encode() if isinstance(c, str) else c

    def delete_permission(self, file_id, permission_id):
        for f in self.files:
            if f["id"] == file_id:
                f["permissions"] = [p for p in f["permissions"] if p["id"] != permission_id]
        self.deleted.append((file_id, permission_id))


DEMO_CONTENTS = {
    "f-payroll": "RESTRICTED\nname,card,salary\nTest User,4111 1111 1111 1111,90000\n",
    "f-picnic": "Join us for the annual picnic on Friday!",
    "f-roadmap": "Internal use only. Product roadmap draft.",
    "f-partner": "Meeting notes with our partner about the launch date.",
}


def demo_files():
    company = (config.company_domains() or ["company.com"])[0]
    return [
        {"id": "f-payroll", "name": "customer_payroll_confidential", "mimeType": "application/vnd.google-apps.spreadsheet",
         "owners": [{"emailAddress": f"bob@{company}"}],
         "permissions": [{"id": "p-owner", "type": "user", "role": "owner", "emailAddress": f"bob@{company}"},
                         {"id": "p-team", "type": "user", "role": "reader", "emailAddress": f"alice@{company}"},
                         {"id": "p-anyone", "type": "anyone", "role": "reader", "allowFileDiscovery": False}]},
        {"id": "f-picnic", "name": "picnic_notice", "mimeType": "application/vnd.google-apps.document",
         "owners": [{"emailAddress": f"alice@{company}"}],
         "permissions": [{"id": "p-owner2", "type": "user", "role": "owner", "emailAddress": f"alice@{company}"},
                         {"id": "p-anyone2", "type": "anyone", "role": "reader", "allowFileDiscovery": False}]},
        {"id": "f-roadmap", "name": "roadmap_draft", "mimeType": "application/vnd.google-apps.document",
         "owners": [{"emailAddress": f"alice@{company}"}],
         "permissions": [{"id": "p-owner3", "type": "user", "role": "owner", "emailAddress": f"alice@{company}"},
                         {"id": "p-team3", "type": "domain", "role": "reader", "domain": company}]},
        {"id": "f-partner", "name": "partner_meeting.txt", "mimeType": "text/plain", "size": "52",
         "owners": [{"emailAddress": f"carol@{company}"}],
         "permissions": [{"id": "p-owner4", "type": "user", "role": "owner", "emailAddress": f"carol@{company}"},
                         {"id": "p-ext4", "type": "user", "role": "writer", "emailAddress": "partner@example.org"}]},
    ]
