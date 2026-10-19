"""Append-only, hash-chained audit log (tamper-evident).

Each row stores hash = SHA-256(previous hash + JSON record). verify() recomputes the chain
from "GENESIS", and also checks that no row is missing at the end and that every
transfer event still has its audit record.
"""
import hashlib
import json
from dataclasses import dataclass

GENESIS = "GENESIS"


def append(db, record, ts, event_id=None):
    """Must be called inside db.transaction() so the chain cannot fork."""
    last = db.one("SELECT hash FROM audit_log ORDER BY id DESC LIMIT 1")
    prev = last["hash"] if last else GENESIS
    body = json.dumps(record, sort_keys=True, default=str)
    digest = hashlib.sha256((prev + body).encode()).hexdigest()
    return db.insert("INSERT INTO audit_log (ts, event_id, record, prev_hash, hash) VALUES (?, ?, ?, ?, ?)",
                     (ts, event_id, body, prev, digest))


@dataclass
class VerifyResult:
    ok: bool
    rows: int
    bad_id: int = None
    problem: str = ""

    def __str__(self):
        if self.ok:
            return f"Audit chain intact ({self.rows} records verified)."
        where = f" at audit row {self.bad_id}" if self.bad_id is not None else ""
        return f"TAMPERING detected{where}: {self.problem}"


def verify(db):
    prev = GENESIS
    rows = db.query("SELECT id, event_id, record, prev_hash, hash FROM audit_log ORDER BY id")
    decided = {}
    for row in rows:
        expected = hashlib.sha256((prev + row["record"]).encode()).hexdigest()
        if row["prev_hash"] != prev:
            return VerifyResult(False, len(rows), row["id"], "previous-hash link broken (a row was deleted or edited)")
        if row["hash"] != expected:
            return VerifyResult(False, len(rows), row["id"], "record content does not match its hash (row edited)")
        prev = row["hash"]
        try:
            rec = json.loads(row["record"])
        except ValueError:
            rec = {}
        if rec.get("type", "decision") == "decision" and row["event_id"] is not None:
            decided[row["event_id"]] = rec

    # A deleted *last* row leaves the chain valid, so check the id counter too.
    if not db.pg:
        seq = db.scalar("SELECT seq FROM sqlite_sequence WHERE name = 'audit_log'")
        last_id = rows[-1]["id"] if rows else 0
        if seq is not None and seq > last_id:
            return VerifyResult(False, len(rows), last_id + 1, f"{seq - last_id} audit row(s) missing at the end")

    # Every transfer event must still have its (unchanged) decision record.
    for ev in db.query("SELECT id, decision FROM transfer_events ORDER BY id"):
        rec = decided.get(ev["id"])
        if rec is None:
            return VerifyResult(False, len(rows), None, f"transfer event {ev['id']} has no audit record (deleted)")
        if rec.get("decision") != ev["decision"]:
            return VerifyResult(False, len(rows), None,
                                f"transfer event {ev['id']} decision changed ({rec.get('decision')} in audit log, "
                                f"{ev['decision']} in events table)")
    return VerifyResult(True, len(rows))
