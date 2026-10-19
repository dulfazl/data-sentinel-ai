import threading

import pytest

from conftest import PAYROLL
from data_sentinel import audit, config, scenarios
from data_sentinel.db import Database
from data_sentinel.engine import Engine, Payload

WORK = scenarios.WORK_TIME


def run(engine, sid):
    s = {x[0]: x for x in scenarios.SCENARIOS}[sid]
    _, _, user, device, dest, channel, name, content = s
    return engine.process(user, Payload.from_bytes(name, content.encode()), device, dest, channel, ts=WORK,
                          trust=scenarios.DEFAULT_TRUST.get(device, "unknown"))


def test_scenarios_a_b_c(engine):
    a, b, c = run(engine, "A"), run(engine, "B"), run(engine, "C")
    assert (a.decision, a.score, a.level) == ("ALLOW", 4.0, "LOW")
    assert (b.decision, b.score, b.level) == ("WARN", 41.2, "MEDIUM")
    assert (c.decision, c.level, c.sensitivity) == ("BLOCK", "CRITICAL", "Restricted")
    assert c.score == pytest.approx(74.5, abs=3)
    assert "role 'contractor'" in c.reasons and "device 'Unknown-USB-77' is untrusted" in c.reasons


def test_all_scenarios_match_review_document(db):
    """Full simulate run (uses the saved Isolation Forest when present, like the CLI)."""
    engine = Engine(db)
    results = scenarios.run(engine, verbose=False)
    review = {"A": 4.0, "B": 41.2, "C": 74.5, "D": 59.2, "E": 50.3, "F": 67.8, "G": 55.3, "H": 11.0,
              "I": 65.6, "J": 74.3}
    for sid, d in results.items():
        assert d.decision == scenarios.EXPECTED[sid], sid
        assert d.score == pytest.approx(review[sid], abs=3), sid
    assert audit.verify(db).ok


def test_alert_raised_on_block(engine, db):
    c = run(engine, "C")
    rows = db.query("SELECT * FROM alerts WHERE event_id = ?", (c.event_id,))
    assert len(rows) == 1 and rows[0]["status"] == "OPEN" and rows[0]["severity"] == "CRITICAL"
    assert "blocked usb transfer by 'carol'" in rows[0]["message"]
    assert run(engine, "A").alert is None
    assert db.scalar("SELECT COUNT(*) FROM alerts") == 1


def test_restricted_to_untrusted_always_blocked(engine, db):
    # Even if someone relaxes the policy table, the hard rule still blocks Restricted data.
    db.execute("UPDATE policies SET action = 'WARN' WHERE level IN ('HIGH', 'CRITICAL')")
    d = engine.process("bob", Payload.from_text("k.txt", "password = hunter22"), "SanDisk-USB-01", "usb", ts=WORK)
    assert d.level == "HIGH" and d.decision == "BLOCK"
    assert any(r.startswith("hard rule: Restricted data") for r in d.reasons)


def test_public_data_never_warned(engine):
    d = engine.process("carol", Payload.from_text("notice.txt", "Picnic on Friday"), "Unknown-USB-77", "usb", ts=WORK)
    assert (d.score, d.level, d.decision) == (37.5, "MEDIUM", "ALLOW")


def test_admin_on_trusted_device_gets_warn_instead_of_block(engine):
    p = Payload.from_text("keys.txt", "password = hunter22")
    p.size = 80_000_000                                      # > 50 MB
    night = WORK.replace(hour=17)                            # 22:30 IST
    d = engine.process("bob", p, "Corp-EncryptedUSB", "usb", ts=night)
    assert (d.score, d.level, d.decision) == (55.5, "HIGH", "WARN")
    assert any(r.startswith("exception: admin") for r in d.reasons)


def test_audit_detects_edit_delete_and_truncation():
    db = Database(url="", sqlite_path=":memory:")
    db.init_schema()
    engine = Engine(db, use_saved_model=False)
    for sid in ("A", "B", "C", "E"):
        run(engine, sid)
    assert audit.verify(db).ok
    # append-only at database level
    with pytest.raises(Exception):
        db.execute("UPDATE audit_log SET record = 'x' WHERE id = 1")
    with pytest.raises(Exception):
        db.execute("DELETE FROM audit_log WHERE id = 1")
    # an attacker who drops the triggers is still caught
    db.execute("DROP TRIGGER audit_no_update")
    db.execute("DROP TRIGGER audit_no_delete")
    db.execute("UPDATE audit_log SET record = replace(record, 'BLOCK', 'ALLOW') WHERE id = 3")
    r = audit.verify(db)
    assert not r.ok and r.bad_id == 3


@pytest.mark.parametrize("victim", ["middle", "last"])
def test_audit_detects_deleted_rows(victim):
    db = Database(url="", sqlite_path=":memory:")
    db.init_schema()
    engine = Engine(db, use_saved_model=False)
    for sid in ("A", "B", "C"):
        run(engine, sid)
    db.execute("DROP TRIGGER audit_no_delete")
    target = 2 if victim == "middle" else db.scalar("SELECT MAX(id) FROM audit_log")
    db.execute("DELETE FROM audit_log WHERE id = ?", (target,))
    assert not audit.verify(db).ok


def test_audit_detects_changed_event_decision(engine, db):
    c = run(engine, "C")
    db.execute("UPDATE transfer_events SET decision = 'ALLOW' WHERE id = ?", (c.event_id,))
    r = audit.verify(db)
    assert not r.ok and "decision changed" in r.problem


def test_matched_values_never_stored(engine, db):
    for sid in ("C", "E", "F", "G"):
        run(engine, sid)
    dump = "\n".join(db.conn.iterdump())
    for secret in ("4111 1111 1111 1111", "4111111111111111", "sk_live_51HxTestKeyOnly", "customer01@example.com",
                   "120000", "90000"):
        assert secret not in dump, secret
    files = db.query("SELECT matches FROM files")
    assert any('"credit card number": 1' in f["matches"] for f in files)


def test_name_only_payload(engine):
    d = engine.process("alice", Payload.name_only("customer_data_export.zip", 300_000_000), "drive.google.com",
                       "cloud", "browser", ts=WORK)
    assert not d.inspected and d.sensitivity == "Confidential"
    assert any("judged by file name and size" in r for r in d.reasons)
    assert any("large file" in r for r in d.reasons)
    assert d.features["size_mb"] == 300.0


def test_dry_run_does_not_enforce(dry_engine):
    d = dry_engine.process("carol", Payload.from_text("p.csv", PAYROLL), "Unknown-USB-77", "usb", ts=WORK)
    assert d.decision == "BLOCK" and not d.enforce and "dry-run" in d.alert


def test_engine_is_thread_safe(engine, db):
    def worker(n):
        for i in range(20):
            engine.process(f"user{n}", Payload.from_text(f"f{i}.txt", "Internal use only"), "SanDisk-USB-01", "usb")
    threads = [threading.Thread(target=worker, args=(n,)) for n in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert db.event_count() == 100
    assert audit.verify(db).ok


def test_model_trains_on_database_after_50_events(engine, db):
    assert engine.anomaly.model is None
    for i in range(config.MIN_TRAIN_ROWS + 1):
        engine.process("alice", Payload.from_text(f"n{i}.txt", "hello"), "corp-laptop", "internal", ts=WORK)
    assert engine.anomaly.model is not None and "trained on" in engine.anomaly.source
