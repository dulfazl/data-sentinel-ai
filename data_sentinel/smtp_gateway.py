"""SMTP gateway for desktop e-mail clients (aiosmtpd) on 127.0.0.1:1025.

Point the mail client's outgoing (SMTP) server at 127.0.0.1 port 1025, no TLS, no auth.
Subject + body and every attachment are scanned.
* All recipients in SENTINEL_COMPANY_DOMAINS -> email_internal, trusted ("mail:internal").
* Any outside recipient -> email, unknown trust, named after the riskiest outside domain.
BLOCK -> "550 5.7.1 Blocked by Data Sentinel: sensitive content in <file>".
Otherwise an X-Data-Sentinel header is added and the message is relayed to
SENTINEL_SMTP_UPSTREAM (host:port), or saved as .eml in outbox/ when no upstream is set.
"""
import asyncio
import email
import email.policy
import os
import re
import smtplib
import uuid
from datetime import datetime

from . import config
from .destinations import classify_recipients, is_company_domain
from .engine import Payload

RANK = config.RANK


def _ascii(text):
    return re.sub(r"[^\x20-\x7e]", "?", text)[:120]


def split_message(raw):
    """Return (body_text, [(attachment_name, bytes), ...]) for an RFC 822 message."""
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    texts = [f"Subject: {msg.get('Subject', '')}"]
    attachments = []
    for part in msg.walk():
        if part.is_multipart():
            continue
        filename = part.get_filename()
        disposition = part.get_content_disposition()
        if filename or disposition == "attachment":
            attachments.append((os.path.basename(filename or "attachment.bin"), part.get_payload(decode=True) or b""))
        elif part.get_content_maintype() == "text":
            try:
                text = part.get_content()
            except (LookupError, ValueError):
                text = (part.get_payload(decode=True) or b"").decode("utf-8", "ignore")
            if part.get_content_subtype() == "html":
                text = re.sub(r"<[^>]+>", " ", text)
            texts.append(text)
    return "\n".join(texts), attachments


class SentinelHandler:
    def __init__(self, gateway):
        self.gw = gateway

    async def handle_DATA(self, server, session, envelope):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.gw.handle_message, envelope.mail_from,
                                          list(envelope.rcpt_tos), envelope.original_content or envelope.content)


class SMTPGateway:
    def __init__(self, engine, default_user, host=config.SMTP_HOST, port=config.SMTP_PORT, upstream=None,
                 outbox=None, role="employee", on_decision=None):
        self.engine = engine
        self.default_user = default_user
        self.role = role
        self.host, self.port = host, port
        self.upstream = upstream if upstream is not None else config.SMTP_UPSTREAM
        self.outbox = str(outbox or config.OUTBOX_DIR)
        self.on_decision = on_decision
        self.controller = None

    def sender_user(self, mail_from):
        local, _, domain = (mail_from or "").partition("@")
        if local and domain and is_company_domain(domain):
            return local.lower()
        return self.default_user

    def handle_message(self, mail_from, rcpt_tos, raw):
        user = self.sender_user(mail_from)
        device, dest_type, trust = classify_recipients(rcpt_tos)
        body, attachments = split_message(raw)
        items = [Payload.from_text("message body", body)] + [Payload.from_bytes(n, d) for n, d in attachments]
        decisions = []
        for p in items:
            d = self.engine.process(user, p, device, dest_type, "email", role=self.role, trust=trust)
            decisions.append(d)
        worst = max(decisions, key=lambda d: (RANK[d.decision], d.score))
        blocked = [d for d in decisions if d.decision == "BLOCK"]

        if blocked and not self.engine.dry_run:
            for d in blocked:
                self.engine.record_response(d.event_id, "e-mail refused with SMTP 550")
            reply = f"550 5.7.1 Blocked by Data Sentinel: sensitive content in {_ascii(blocked[0].file_name)}"
            self._report(decisions, reply, device)
            return reply

        header = (f"X-Data-Sentinel: {worst.decision}; score={worst.score}; level={worst.level}; "
                  f"events={','.join(str(d.event_id) for d in decisions)}"
                  + ("; dry-run" if blocked else "") + "\r\n").encode()
        for d in blocked:
            self.engine.record_response(d.event_id, "dry-run: e-mail delivered")
        try:
            where = self.deliver(mail_from, rcpt_tos, header + raw)
        except (OSError, smtplib.SMTPException) as exc:
            reply = f"451 4.4.1 Data Sentinel could not relay the message ({type(exc).__name__})"
            self._report(decisions, reply, device)
            return reply
        reply = f"250 Message accepted by Data Sentinel ({where})"
        self._report(decisions, reply, device)
        return reply

    def deliver(self, mail_from, rcpt_tos, data):
        if self.upstream:
            host, _, port = self.upstream.partition(":")
            with smtplib.SMTP(host, int(port or 25), timeout=30) as smtp:
                if os.environ.get("SENTINEL_SMTP_STARTTLS") == "1":
                    smtp.starttls()
                if os.environ.get("SENTINEL_SMTP_USER"):
                    smtp.login(os.environ["SENTINEL_SMTP_USER"], os.environ.get("SENTINEL_SMTP_PASSWORD", ""))
                smtp.sendmail(mail_from, rcpt_tos, data)
            return f"relayed to {self.upstream}"
        os.makedirs(self.outbox, exist_ok=True)
        name = f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}.eml"
        with open(os.path.join(self.outbox, name), "wb") as fh:
            fh.write(data)
        return f"saved to outbox/{name}"

    def _report(self, decisions, reply, device):
        if self.on_decision:
            self.on_decision(decisions, reply, device)

    def start(self):
        from aiosmtpd.controller import Controller
        self.controller = Controller(SentinelHandler(self), hostname=self.host, port=self.port,
                                     data_size_limit=50 * 1024 * 1024)
        self.controller.start()
        return self.controller

    def stop(self):
        if self.controller:
            self.controller.stop()
