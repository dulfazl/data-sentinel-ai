"""Test scenarios A-J and D from the review document (synthetic data only).

All run on Monday 5 Oct 2026: A-C and E-J at 11:30 IST, then D (12 copies) from 22:30 IST.
"""
from datetime import datetime, timedelta, timezone

from . import audit
from .engine import Payload, format_decision

WORK_TIME = datetime(2026, 10, 5, 6, 0, tzinfo=timezone.utc)      # Mon 11:30 IST
NIGHT_TIME = datetime(2026, 10, 5, 17, 0, tzinfo=timezone.utc)    # Mon 22:30 IST

PAYROLL_NAME = "customer_payroll_confidential.csv"
PAYROLL = "RESTRICTED\nname,card,salary\nTest User,4111 1111 1111 1111,90000\n"
CUSTOMER_LIST = "name,email\n" + "".join(f"Customer {i:02d},customer{i:02d}@example.com\n" for i in range(1, 26))

# id, title, user, device, dest_type, channel, file name, content
SCENARIOS = [
    ("A", "public file -> trusted corporate device", "alice", "corp-laptop", "internal", "internal",
     "company_picnic_notice.txt", "Join us for the annual picnic on Friday!"),
    ("B", "internal file -> unknown USB", "alice", "SanDisk-USB-01", "usb", "usb",
     "team_memo.txt", "Internal use only. Sprint planning notes for next week."),
    ("C", "restricted file -> untrusted USB", "carol", "Unknown-USB-77", "usb", "usb", PAYROLL_NAME, PAYROLL),
    ("E", "customer list uploaded to Google Drive", "bob", "drive.google.com", "cloud", "browser",
     "customer_list.csv", CUSTOMER_LIST),
    ("F", "API key pasted into ChatGPT", "alice", "chatgpt.com", "genai", "browser",
     "deploy_notes.txt", "Deployment notes for staging\napi_key = sk_live_51HxTestKeyOnly\n"),
    ("G", "salary sheet e-mailed to personal Gmail", "carol", "mail:gmail.com", "email", "email",
     "q3_salaries.xlsx.csv", "Confidential\nemployee,salary\nA,120000\n"),
    ("H", "lunch e-mail to a colleague", "alice", "mail:internal", "email_internal", "email",
     "lunch_menu.txt", "Paneer butter masala and rice on Wednesday."),
    ("I", "restricted file saved in OneDrive sync folder", "bob", "OneDrive", "cloud_sync", "cloud_sync",
     PAYROLL_NAME, PAYROLL),
    ("J", "payroll file shared publicly in Google Drive", "bob", "gdrive:public-link", "cloud_share", "drive",
     PAYROLL_NAME, PAYROLL),
]
EXPECTED = {"A": "ALLOW", "B": "WARN", "C": "BLOCK", "D": "BLOCK", "E": "BLOCK", "F": "BLOCK",
            "G": "BLOCK", "H": "ALLOW", "I": "BLOCK", "J": "BLOCK"}
# Trust used when a destination is not registered yet (seeded devices keep their own trust).
DEFAULT_TRUST = {"mail:internal": "trusted", "gdrive:public-link": "untrusted"}


def run(engine, verbose=True):
    """Run every scenario on the given engine. Returns {id: Decision}."""
    out = {}
    say = print if verbose else (lambda *a, **k: None)
    for sid, title, user, device, dest, channel, name, content in SCENARIOS:
        d = engine.process(user, Payload.from_bytes(name, content.encode()), device, dest, channel,
                           ts=WORK_TIME, trust=DEFAULT_TRUST.get(device, "unknown"))
        out[sid] = d
        say(format_decision(d, f"{sid}: {title}"))

    say("\n--- D: 12 ordinary transfers at 22:30 by the same user ---")
    memo = "Internal use only. Weekly status report."
    for i in range(12):
        d = engine.process("alice", Payload.from_bytes("weekly_report.txt", memo.encode()), "SanDisk-USB-01",
                           "usb", "usb", ts=NIGHT_TIME + timedelta(minutes=i))
        say(f"  copy {i + 1:2d} at {22}:{30 + i}: {d.score:5.1f} {d.level:<8} {d.decision}")
    out["D"] = d
    say(format_decision(d, "D: 12th transfer (frequency + off-hours raise the score)"))
    return out


def summary_table(results):
    lines = [f"\n{'ID':<3} {'Sensitivity':<13} {'Score':>6}  {'Level':<9} {'Decision':<8} Expected",
             "-" * 52]
    for sid in sorted(results):
        d = results[sid]
        ok = "ok" if d.decision == EXPECTED[sid] else "MISMATCH"
        lines.append(f"{sid:<3} {d.sensitivity:<13} {d.score:>6}  {d.level:<9} {d.decision:<8} "
                     f"{EXPECTED[sid]} {ok}")
    return "\n".join(lines)


def simulate(engine, verbose=True):
    results = run(engine, verbose)
    print(summary_table(results))
    result = audit.verify(engine.db)
    print(f"\n{result}")
    return results, result
