"""Drive scanner against the fake Drive client - no Google account, no network."""
from data_sentinel.drive_scanner import DriveScanner, FakeDriveClient, risky_permissions


def perms(client, file_id):
    return {p["id"] for f in client.files if f["id"] == file_id for p in f["permissions"]}


def scan(engine, fix):
    client = FakeDriveClient()
    results = DriveScanner(engine, client, fix=fix, out=lambda *a: None).scan()
    return client, {r["id"]: r for r in results}


def test_flags_public_payroll_file(engine):
    client, res = scan(engine, fix=False)
    payroll = res["f-payroll"]["decision"]
    assert payroll.decision == "BLOCK" and payroll.device == "gdrive:public-link" and payroll.trust == "untrusted"
    assert payroll.dest_type == "cloud_share" and payroll.sensitivity == "Restricted"
    assert res["f-picnic"]["decision"].decision == "ALLOW"           # public but harmless
    assert res["f-partner"]["decision"].device == "gdrive:external"  # shared with an outside person
    assert "f-roadmap" not in res                                    # internal sharing only: not scanned


def test_report_only_changes_nothing(engine):
    before = FakeDriveClient()
    client, _ = scan(engine, fix=False)
    assert client.deleted == []
    assert [f["permissions"] for f in client.files] == [f["permissions"] for f in before.files]


def test_fix_removes_only_the_anyone_permission(engine, db):
    client, res = scan(engine, fix=True)
    assert client.deleted == [("f-payroll", "p-anyone")]
    assert perms(client, "f-payroll") == {"p-owner", "p-team"}
    assert perms(client, "f-picnic") == {"p-owner2", "p-anyone2"}     # ALLOW: left alone
    ev = db.one("SELECT action_taken FROM transfer_events WHERE id = ?", (res["f-payroll"]["decision"].event_id,))
    assert ev["action_taken"] == "removed sharing: anyone with the link"


def test_fix_in_dry_run_changes_nothing(dry_engine):
    client = FakeDriveClient()
    DriveScanner(dry_engine, client, fix=True, out=lambda *a: None).scan()
    assert client.deleted == []


def test_risky_permission_rules():
    f = {"permissions": [{"id": "1", "type": "user", "role": "owner", "emailAddress": "x@gmail.com"},
                         {"id": "2", "type": "domain", "role": "reader", "domain": "company.com"},
                         {"id": "3", "type": "domain", "role": "reader", "domain": "other.org"},
                         {"id": "4", "type": "group", "role": "reader", "emailAddress": "team@company.com"}]}
    kind, risky = risky_permissions(f)
    assert kind == "external" and [p["id"] for p in risky] == ["3"]
    assert risky_permissions({"permissions": []}) == (None, [])
