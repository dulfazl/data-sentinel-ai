"""SMTP gateway on a free local port, outbox mode and a fake local upstream. No real mailbox."""
import os
import smtplib
from email.message import EmailMessage

import pytest

from conftest import free_port
from data_sentinel.destinations import classify_recipients
from data_sentinel.smtp_gateway import SMTPGateway


@pytest.fixture
def gateway(engine, tmp_path):
    gw = SMTPGateway(engine, "alice", port=free_port(), upstream="", outbox=tmp_path / "outbox")
    gw.start()
    yield gw
    gw.stop()


def message(to, subject, body, attachment=None):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = "alice@company.com", to, subject
    m.set_content(body)
    if attachment:
        name, data = attachment
        m.add_attachment(data.encode(), maintype="text", subtype="csv", filename=name)
    return m


def test_recipient_classification():
    assert classify_recipients(["bob@company.com", "carol@hr.company.com"]) == ("mail:internal", "email_internal",
                                                                                 "trusted")
    assert classify_recipients(["bob@company.com", "x@partner.org", "me@gmail.com"]) == ("mail:gmail.com", "email",
                                                                                          "unknown")
    assert classify_recipients(["x@partner.org"]) == ("mail:partner.org", "email", "unknown")


def test_internal_mail_delivered_with_header(gateway, db):
    with smtplib.SMTP("127.0.0.1", gateway.port, timeout=10) as s:
        s.send_message(message("bob@company.com", "Lunch", "Paneer butter masala and rice on Wednesday."))
    files = os.listdir(gateway.outbox)
    assert len(files) == 1 and files[0].endswith(".eml")
    raw = open(os.path.join(gateway.outbox, files[0]), "rb").read().decode()
    assert raw.startswith("X-Data-Sentinel: ALLOW; score=")
    ev = db.one("SELECT e.dest_type, d.name AS dev, u.name AS usr FROM transfer_events e "
                "JOIN devices d ON d.id = e.device_id JOIN users u ON u.id = e.user_id")
    assert ev == {"dest_type": "email_internal", "dev": "mail:internal", "usr": "alice"}


def test_external_mail_with_test_card_refused_550(gateway, db):
    msg = message("friend@gmail.com", "numbers", "see attached",
                  attachment=("cards.csv", "name,card\nTest User,4111 1111 1111 1111\n"))
    with smtplib.SMTP("127.0.0.1", gateway.port, timeout=10) as s:
        with pytest.raises(smtplib.SMTPDataError) as err:
            s.send_message(msg)
    assert err.value.smtp_code == 550
    assert b"Blocked by Data Sentinel: sensitive content in cards.csv" in err.value.smtp_error
    assert not os.path.exists(gateway.outbox) or os.listdir(gateway.outbox) == []
    row = db.one("SELECT d.name AS dev, e.decision, e.action_taken FROM transfer_events e "
                 "JOIN devices d ON d.id = e.device_id JOIN files f ON f.id = e.file_id WHERE f.name = 'cards.csv'")
    assert row == {"dev": "mail:gmail.com", "decision": "BLOCK", "action_taken": "e-mail refused with SMTP 550"}


def test_secret_in_body_is_refused(gateway):
    with smtplib.SMTP("127.0.0.1", gateway.port, timeout=10) as s:
        with pytest.raises(smtplib.SMTPDataError) as err:
            s.send_message(message("me@yahoo.com", "keys", "api_key = sk_live_51HxTestKeyOnly"))
    assert b"message body" in err.value.smtp_error


def test_relay_to_upstream(engine, tmp_path):
    from aiosmtpd.controller import Controller

    class Catcher:
        def __init__(self):
            self.got = []

        async def handle_DATA(self, server, session, envelope):
            self.got.append(envelope.content)
            return "250 OK"

    catcher = Catcher()
    up_port = free_port()
    upstream = Controller(catcher, hostname="127.0.0.1", port=up_port)
    upstream.start()
    gw = SMTPGateway(engine, "alice", port=free_port(), upstream=f"127.0.0.1:{up_port}", outbox=tmp_path / "o")
    gw.start()
    try:
        with smtplib.SMTP("127.0.0.1", gw.port, timeout=10) as s:
            s.send_message(message("bob@company.com", "Sprint", "Internal use only. Sprint notes."))
    finally:
        gw.stop()
        upstream.stop()
    assert len(catcher.got) == 1 and catcher.got[0].startswith(b"X-Data-Sentinel: ALLOW")


def test_dry_run_delivers_but_marks_header(dry_engine, tmp_path):
    gw = SMTPGateway(dry_engine, "alice", port=free_port(), upstream="", outbox=tmp_path / "outbox")
    gw.start()
    try:
        with smtplib.SMTP("127.0.0.1", gw.port, timeout=10) as s:
            s.send_message(message("me@gmail.com", "cards", "x", attachment=("cards.csv", "4111 1111 1111 1111")))
    finally:
        gw.stop()
    raw = open(os.path.join(tmp_path / "outbox", os.listdir(tmp_path / "outbox")[0])).read()
    assert raw.startswith("X-Data-Sentinel: BLOCK") and "dry-run" in raw.splitlines()[0]
