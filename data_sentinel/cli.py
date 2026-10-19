"""Command line:  python -m data_sentinel <command>   (run with -h for help)."""
import argparse
import getpass
import os
import sqlite3
import sys
import tempfile
import time
from datetime import datetime

from . import audit, config
from .db import Database

ROLES = list(config.ROLE_RISK)
TRUST = list(config.TRUST_RISK)
DESTS = list(config.DEST_RISK)


def default_user():
    return os.environ.get("SENTINEL_USER") or getpass.getuser()


def open_db(args):
    if getattr(args, "db", None):
        return Database(url="", sqlite_path=args.db)
    return Database()


# --------------------------------------------------------------------------- commands
def cmd_init_db(args):
    db = open_db(args)
    if args.reset:
        db.reset()
        print(f"Database reset and seeded: {db.location}")
    else:
        db.init_schema(seed=True)
        print(f"Database initialised and demo users/devices seeded: {db.location}")


def _backup_sqlite(db):
    if db.pg or db.location == ":memory:" or not db.event_count():
        return None
    target = f"{db.location}.bak-{datetime.now():%Y%m%d-%H%M%S}"
    dst = sqlite3.connect(target)
    with db.lock:
        db.conn.backup(dst)
    dst.close()
    return target


def cmd_simulate(args):
    from . import scenarios
    from .engine import Engine
    db = open_db(args)
    if not args.no_reset:
        backup = _backup_sqlite(db)
        if backup:
            print(f"Existing events backed up to {backup}")
        db.reset()
        print(f"Database reset for a clean scenario run: {db.location}")
    else:
        db.init_schema(seed=True)
    engine = Engine(db)
    print(f"Anomaly model: {engine.anomaly.source}")
    results, check = scenarios.simulate(engine)
    wrong = [s for s, d in results.items() if d.decision != scenarios.EXPECTED[s]]
    if wrong or not check.ok:
        sys.exit(1)


def cmd_report(args):
    db = open_db(args)
    db.init_schema(seed=False)
    rows = db.query(
        "SELECT e.id, e.ts, e.channel, u.name AS usr, d.name AS dev, f.name AS file, f.sensitivity, "
        "r.score, r.level, e.decision, e.action_taken FROM transfer_events e "
        "JOIN users u ON u.id = e.user_id JOIN devices d ON d.id = e.device_id "
        "JOIN files f ON f.id = e.file_id JOIN risk_assessments r ON r.event_id = e.id "
        "ORDER BY e.id DESC LIMIT ?", (args.limit,))
    print(f"{'ID':>4} {'TIME (IST)':<16} {'CHANNEL':<11} {'USER':<8} {'DESTINATION':<20} {'FILE':<30} "
          f"{'SENS':<12} {'SCORE':>5} {'LEVEL':<8} DECISION")
    for r in reversed(rows):
        t = datetime.fromisoformat(r["ts"]).astimezone(config.IST).strftime("%d %b %H:%M")
        print(f"{r['id']:>4} {t:<16} {r['channel'] or '':<11} {r['usr'][:8]:<8} {r['dev'][:20]:<20} "
              f"{r['file'][:30]:<30} {r['sensitivity']:<12} {r['score']:>5} {r['level']:<8} {r['decision']}")
    total = db.event_count()
    by = {row["decision"]: row["n"] for row in
          db.query("SELECT decision, COUNT(*) AS n FROM transfer_events GROUP BY decision")}
    alerts = db.scalar("SELECT COUNT(*) AS n FROM alerts WHERE status = 'OPEN'") or 0
    print(f"\nEvents: {total}   ALLOW {by.get('ALLOW', 0)}   WARN {by.get('WARN', 0)}   BLOCK {by.get('BLOCK', 0)}"
          f"   Open alerts: {alerts}")
    print(audit.verify(db))


def cmd_verify(args):
    db = open_db(args)
    db.init_schema(seed=False)
    result = audit.verify(db)
    print(result)
    sys.exit(0 if result.ok else 1)


def cmd_tamper_demo(args):
    """Copy the database, secretly edit one audit record in the COPY, and show verify-audit catching it."""
    db = open_db(args)
    if db.pg:
        sys.exit("tamper-demo works with the SQLite database only.")
    rows = db.query("SELECT id, record FROM audit_log WHERE record LIKE '%\"decision\": \"BLOCK\"%' ORDER BY id LIMIT 1")
    if not rows:
        sys.exit("No BLOCK record to tamper with - run simulate first.")
    copy = os.path.join(tempfile.mkdtemp(prefix="sentinel_tamper_"), "copy.db")
    dst = sqlite3.connect(copy)
    with db.lock:
        db.conn.backup(dst)
    row = rows[0]
    forged = row["record"].replace('"decision": "BLOCK"', '"decision": "ALLOW"')
    dst.execute("DROP TRIGGER IF EXISTS audit_no_update")          # an attacker with file access
    dst.execute("UPDATE audit_log SET record = ? WHERE id = ?", (forged, row["id"]))
    dst.commit()
    dst.close()
    print(f"Working on a copy: {copy}  (the real database is not touched)")
    print(f"Changed audit row {row['id']}: decision BLOCK -> ALLOW, hash left as it was.")
    print("Real database :", audit.verify(db))
    print("Tampered copy :", audit.verify(Database(url="", sqlite_path=copy)))


def cmd_check(args):
    from .engine import Engine, Payload, format_decision
    engine = Engine(open_db(args))
    payload = Payload.from_path(args.file)
    d = engine.process(args.user, payload, args.device, args.dest, args.channel, trust=args.trust)
    print(format_decision(d, os.path.basename(args.file)))


def cmd_watch(args):
    from .agent import show
    from .engine import Engine
    from .watchers import FolderWatcher
    engine = Engine(open_db(args), dry_run=args.dry_run)
    os.makedirs(args.folder, exist_ok=True)
    w = FolderWatcher(engine, args.folder, args.device, args.user, dest_type=args.dest, channel=args.dest,
                      trust=args.trust, on_decision=lambda d, action, _w: show(d, action, args.device))
    n = w.baseline()
    print(f"Watching '{args.folder}' as {args.dest} '{args.device}' ({args.trust}) - {n} existing file(s) baselined."
          + ("  [DRY-RUN]" if args.dry_run else "") + "  Ctrl+C to stop.")
    try:
        while True:
            time.sleep(w.interval(args.interval))
            w.poll()
    except KeyboardInterrupt:
        print("\nStopped.")


def cmd_agent(args):
    from .agent import Agent
    from .engine import Engine
    engine = Engine(open_db(args), dry_run=args.dry_run)
    agent = Agent(args.user, mail=args.mail, watch=args.watch or [], watch_device=args.watch_device,
                  watch_trust=args.watch_trust, usb=not args.no_usb, cloud=not args.no_cloud,
                  shares=not args.no_shares, browser=not args.no_browser, engine=engine,
                  api_port=args.api_port, smtp_port=args.smtp_port)
    try:
        agent.run_forever()
    except OSError as exc:
        sys.exit(f"Could not start the agent: {exc}\n(Is another agent already running on these ports?)")


def cmd_monitor(args):
    db = open_db(args)
    db.init_schema(seed=False)
    last = max(0, (db.scalar("SELECT MAX(id) AS m FROM transfer_events") or 0) - args.last)
    last_alert = db.scalar("SELECT MAX(id) AS m FROM alerts") or 0
    print("Live monitor - new transfer events and alerts (Ctrl+C to stop)")
    try:
        while True:
            for r in db.query(
                    "SELECT e.id, e.ts, e.channel, u.name AS usr, d.name AS dev, f.name AS file, f.sensitivity, "
                    "r.score, r.level, e.decision FROM transfer_events e JOIN users u ON u.id = e.user_id "
                    "JOIN devices d ON d.id = e.device_id JOIN files f ON f.id = e.file_id "
                    "JOIN risk_assessments r ON r.event_id = e.id WHERE e.id > ? ORDER BY e.id", (last,)):
                t = datetime.fromisoformat(r["ts"]).astimezone(config.IST).strftime("%d %b %H:%M:%S")
                print(f"{t}  #{r['id']:<4} {r['decision']:<5} {r['score']:>5} {r['level']:<8} {r['channel']:<11} "
                      f"{r['usr']} -> {r['dev']}: {r['file']} ({r['sensitivity']})", flush=True)
                last = r["id"]
            for a in db.query("SELECT id, message FROM alerts WHERE id > ? ORDER BY id", (last_alert,)):
                print(f"           ALERT #{a['id']}: {a['message']}", flush=True)
                last_alert = a["id"]
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopped.")


def cmd_device(args):
    db = open_db(args)
    db.init_schema(seed=False)
    if args.action == "add":
        if not args.name:
            sys.exit("device add needs a NAME")
        row = db.upsert_device(args.name, args.type, args.trust)
        print(f"Device '{row['name']}' saved: type {row['device_type']}, {row['trust_status']}")
    else:
        rows = db.query("SELECT name, device_type, trust_status FROM devices ORDER BY name")
        print(f"{'DEVICE / DESTINATION':<34} {'TYPE':<15} TRUST")
        for r in rows:
            print(f"{r['name']:<34} {r['device_type']:<15} {r['trust_status']}")


def cmd_user(args):
    db = open_db(args)
    db.init_schema(seed=False)
    if args.action == "add":
        if not args.name:
            sys.exit("user add needs a NAME")
        row = db.upsert_user(args.name, args.role)
        print(f"User '{row['name']}' saved with role {row['role']}")
    else:
        print(f"{'USER':<20} ROLE")
        for r in db.query("SELECT name, role FROM users ORDER BY name"):
            print(f"{r['name']:<20} {r['role']}")


def cmd_scan_drive(args):
    from .drive_scanner import DriveScanner, FakeDriveClient, GoogleDriveClient
    from .engine import Engine
    engine = Engine(open_db(args), dry_run=args.dry_run)
    if args.demo:
        print("DEMO MODE: scanning a built-in fake Drive with synthetic files (no Google account used).")
        client = FakeDriveClient()
    else:
        client = GoogleDriveClient(args.credentials, write=args.fix)
    results = DriveScanner(engine, client, default_user=args.user, fix=args.fix).scan()
    blocked = sum(1 for r in results if r["decision"].decision == "BLOCK")
    print(f"\n{len(results)} risky shared file(s) checked, {blocked} blocked.")


# --------------------------------------------------------------------------- parser
def build_parser():
    ap = argparse.ArgumentParser(prog="python -m data_sentinel",
                                 description="Data Sentinel AI - AI-powered multi-channel Data Loss Prevention")
    ap.add_argument("--db", help="use this SQLite file instead of the default database")
    sub = ap.add_subparsers(dest="cmd", required=True, metavar="command")

    p = sub.add_parser("init-db", help="create tables and seed demo users, devices and policies")
    p.add_argument("--reset", action="store_true", help="drop all data first")
    p.set_defaults(func=cmd_init_db)

    p = sub.add_parser("simulate", help="run test scenarios A-J and D (resets the database)")
    p.add_argument("--no-reset", action="store_true", help="keep existing data (scores will differ)")
    p.set_defaults(func=cmd_simulate)

    p = sub.add_parser("report", help="recent events, totals and audit status")
    p.add_argument("--limit", type=int, default=30)
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("verify-audit", help="check the hash-chained audit log")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("tamper-demo", help="show verify-audit catching an edit (on a copy of the database)")
    p.set_defaults(func=cmd_tamper_demo)

    p = sub.add_parser("agent", help="run all channels: browser API, USB, sync folders, shares, mail gateway")
    p.add_argument("--mail", action="store_true", help="start the SMTP gateway on 127.0.0.1:1025")
    p.add_argument("--watch", action="append", metavar="FOLDER", help="treat a folder as a USB drive (repeatable)")
    p.add_argument("--watch-device", default="Demo-USB", help="device name for --watch folders")
    p.add_argument("--watch-trust", default="untrusted", choices=TRUST, help="trust for --watch folders")
    p.add_argument("--no-usb", action="store_true", help="do not watch real removable drives")
    p.add_argument("--no-cloud", action="store_true", help="do not watch cloud sync folders")
    p.add_argument("--no-shares", action="store_true", help="do not watch network shares")
    p.add_argument("--no-browser", action="store_true", help="do not start the browser scan API")
    p.add_argument("--dry-run", action="store_true", help="decide, log and alert, but never move/drop/refuse")
    p.add_argument("--user", default=default_user(), help="user the agent reports as (default: OS login)")
    p.add_argument("--api-port", type=int, default=config.API_PORT)
    p.add_argument("--smtp-port", type=int, default=config.SMTP_PORT)
    p.set_defaults(func=cmd_agent)

    p = sub.add_parser("check", help="run one file through the pipeline")
    p.add_argument("file")
    p.add_argument("--dest", choices=DESTS, help="destination type (default: the device's registered type)")
    p.add_argument("--device", default="SanDisk-USB-01")
    p.add_argument("--user", default="alice")
    p.add_argument("--trust", default="unknown", choices=TRUST, help="used only if the device is new")
    p.add_argument("--channel", default="manual")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("watch", help="watch one folder as if it were a USB drive")
    p.add_argument("folder")
    p.add_argument("--device", default="Demo-USB")
    p.add_argument("--trust", default="untrusted", choices=TRUST)
    p.add_argument("--user", default=default_user())
    p.add_argument("--dest", default="usb", choices=DESTS)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--interval", type=float, default=config.POLL_SECONDS)
    p.set_defaults(func=cmd_watch)

    p = sub.add_parser("monitor", help="live view of new events and alerts")
    p.add_argument("--interval", type=float, default=1.0)
    p.add_argument("--last", type=int, default=10, help="show this many recent events first")
    p.set_defaults(func=cmd_monitor)

    p = sub.add_parser("device", help="add or list devices / destinations")
    p.add_argument("action", choices=["add", "list"])
    p.add_argument("name", nargs="?")
    p.add_argument("--trust", default="unknown", choices=TRUST)
    p.add_argument("--type", default="usb", choices=DESTS)
    p.set_defaults(func=cmd_device)

    p = sub.add_parser("user", help="add or list users")
    p.add_argument("action", choices=["add", "list"])
    p.add_argument("name", nargs="?")
    p.add_argument("--role", default="employee", choices=ROLES)
    p.set_defaults(func=cmd_user)

    p = sub.add_parser("scan-drive", help="find risky sharing in Google Drive")
    p.add_argument("--fix", action="store_true", help="remove the risky permissions of BLOCKed files")
    p.add_argument("--demo", action="store_true", help="use a built-in fake Drive (no Google account)")
    p.add_argument("--credentials", default=str(config.HOME / "credentials.json"))
    p.add_argument("--user", default=default_user(), help="user when the file owner is unknown")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_scan_drive)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
