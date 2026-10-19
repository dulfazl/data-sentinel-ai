"""The Data Sentinel pipeline, shared by every channel.

detect -> metadata -> classify -> context -> anomaly -> risk score -> policy -> respond -> audit

Channels (USB, sync folders, shares, browser API, SMTP gateway, Drive scanner, CLI) build a
Payload and call Engine.process(). The channel then carries out the response (quarantine,
drop, SMTP 550, unshare) and reports it back with Engine.record_response().
"""
import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import timedelta

from . import alerts, audit, classifier, config
from .anomaly import AnomalyDetector
from .db import Database, ts_str, utcnow

LEVELS = config.LEVELS


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


@dataclass
class Payload:
    """What is being moved. Content stays in memory and is never stored."""
    name: str
    size: int = 0
    sha256: str = None
    data: bytes = None          # file content (may be only the first part of a big text file)
    text: str = None            # already-text content (paste, e-mail body, exported Google Doc)
    path: str = None
    note: str = ""              # why content is not available

    @classmethod
    def from_bytes(cls, name, data):
        return cls(name=name, size=len(data), sha256=sha256_bytes(data), data=data)

    @classmethod
    def from_text(cls, name, text):
        raw = text.encode("utf-8")
        return cls(name=name, size=len(raw), sha256=sha256_bytes(raw), text=text)

    @classmethod
    def name_only(cls, name, size, note="content not sent"):
        return cls(name=name, size=int(size or 0), note=note)

    @classmethod
    def from_path(cls, path):
        """Hash the whole file (streamed) and keep only what the classifier needs."""
        name = os.path.basename(path)
        size = os.path.getsize(path)
        readable = classifier.can_read(name)
        limit = classifier.read_limit(name)
        h = hashlib.sha256()
        head = bytearray()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
                if readable and len(head) < limit:
                    head.extend(chunk[: limit - len(head)])
        note = ""
        data = bytes(head) if readable else None
        if readable and os.path.splitext(name)[1].lower() in (".docx", ".pdf") and size > limit:
            data, note = None, f"document larger than {limit // 1_000_000} MB"
        return cls(name=name, size=size, sha256=h.hexdigest(), data=data, path=str(path), note=note)

    def content_text(self):
        if self.text is not None:
            return self.text, ""
        if self.data is not None:
            return classifier.extract_text(self.name, self.data)
        return None, self.note or "content not available"


@dataclass
class Decision:
    event_id: int
    user: str
    role: str
    device: str
    trust: str
    channel: str
    dest_type: str
    file_name: str
    size: int
    sha256: str
    level_idx: int
    score: float
    level: str
    decision: str
    reasons: list
    matches: dict = field(default_factory=dict)
    signals: dict = field(default_factory=dict)
    features: dict = field(default_factory=dict)
    alert: str = None
    dry_run: bool = False
    inspected: bool = True

    @property
    def sensitivity(self):
        return LEVELS[self.level_idx]

    @property
    def enforce(self):
        """True when the channel must actually stop the transfer."""
        return self.decision == "BLOCK" and not self.dry_run

    def user_message(self, destination=None):
        dest = destination or self.device
        if self.decision == "BLOCK":
            msg = f"Blocked by Data Sentinel: {self.file_name} ({self.sensitivity}) cannot be sent to {dest}."
            return msg + (" [dry-run: not enforced]" if self.dry_run else "")
        if self.decision == "WARN":
            return (f"Data Sentinel warning: {self.file_name} ({self.sensitivity}) is going to {dest}. "
                    "This transfer has been logged.")
        return ""

    def to_dict(self):
        return {"event_id": self.event_id, "user": self.user, "device": self.device, "trust": self.trust,
                "channel": self.channel, "dest_type": self.dest_type, "file": self.file_name,
                "size": self.size, "sensitivity": self.sensitivity, "score": self.score,
                "level": self.level, "decision": self.decision, "reasons": self.reasons,
                "matches": self.matches, "alert": self.alert, "dry_run": self.dry_run,
                "enforce": self.enforce}


def risk_level(score):
    for limit, name in config.THRESHOLDS:
        if score < limit:
            return name
    return "CRITICAL"


def format_decision(d, title=None):
    lines = [f"\n=== {title or d.file_name} ===",
             f"  Sensitivity : {d.sensitivity}",
             f"  Risk        : {d.score} ({d.level})",
             f"  DECISION    : {d.decision}" + ("  [dry-run]" if d.dry_run and d.decision == "BLOCK" else "")]
    lines += [f"    - {r}" for r in d.reasons]
    if d.alert:
        lines.append(f"  ALERT -> security team: {d.alert}")
    return "\n".join(lines)


class Engine:
    def __init__(self, db=None, dry_run=False, model_path=None, use_saved_model=True):
        self.db = db or Database()
        self.db.init_schema(seed=False)
        self.dry_run = dry_run
        self.anomaly = AnomalyDetector(self.db, model_path=model_path, use_saved_model=use_saved_model)

    # ------------------------------------------------------------ context signals
    def _user_risk(self, user, ts):
        base = config.ROLE_RISK.get(user["role"], config.UNKNOWN_ROLE_RISK)
        prior = self.db.scalar(
            "SELECT COUNT(*) AS n FROM transfer_events WHERE user_id = ? AND decision = 'BLOCK' "
            "AND ts >= ? AND ts <= ?", (user["id"], ts_str(ts - timedelta(days=30)), ts_str(ts))) or 0
        reasons = [f"role '{user['role']}'"]
        if prior:
            reasons.append(f"{prior} blocked transfer(s) in last 30 days")
        return min(1.0, base + 0.1 * min(prior, 3)), reasons

    @staticmethod
    def _context_risk(ts, size_bytes):
        local = ts.astimezone(config.IST)
        risk, reasons = 0.0, []
        if local.weekday() >= 5:
            risk += 0.6
            reasons.append(f"weekend transfer ({local:%A %H:%M} IST)")
        elif not config.WORK_HOURS[0] <= local.hour < config.WORK_HOURS[1]:
            risk += 0.6
            reasons.append(f"outside normal working hours ({local:%H:%M} IST)")
        if size_bytes / 1e6 > config.LARGE_FILE_MB:
            risk += 0.3
            reasons.append(f"large file (> {config.LARGE_FILE_MB} MB)")
        return min(1.0, risk), reasons, local.hour + local.minute / 60

    def _recent_count(self, user, ts):
        return self.db.scalar(
            "SELECT COUNT(*) AS n FROM transfer_events WHERE user_id = ? AND ts >= ? AND ts <= ?",
            (user["id"], ts_str(ts - timedelta(hours=1)), ts_str(ts))) or 0

    # ------------------------------------------------------------ policy
    def _decide(self, level, sens_idx, user, trust):
        action = self.db.policy_action(level)
        notes = [f"policy: {level} -> {action}"]
        # Hard rules, applied in this order.
        if sens_idx == 3 and trust != "trusted":
            if action != "BLOCK":
                notes.append("hard rule: Restricted data to a non-trusted destination -> BLOCK")
            action = "BLOCK"
        elif sens_idx == 0 and action == "WARN":
            action = "ALLOW"
            notes.append("rule: Public data is never warned about -> ALLOW")
        elif user["role"] == "admin" and trust == "trusted" and action == "BLOCK":
            action = "WARN"
            notes.append("exception: admin using a trusted device -> WARN instead of BLOCK")
        return action, notes

    # ------------------------------------------------------------ main entry point
    def process(self, user, payload, device, dest_type=None, channel="manual", ts=None,
                role="employee", trust="unknown"):
        """Run one transfer through the pipeline. ``role``/``trust`` apply only to new users/devices."""
        ts = ts or utcnow()
        text, note = payload.content_text()                      # outside the lock: may be slow
        cls = classifier.classify(payload.name, text, note)
        db = self.db
        with db.transaction():
            u = db.get_user(user, role)
            dev = db.get_device(device, dest_type or "other", trust)
            dest_type = dest_type or dev["device_type"]
            trust_status = dev["trust_status"]

            sens_idx = cls.level
            user_r, user_reasons = self._user_risk(u, ts)
            ctx_r, ctx_reasons, hour = self._context_risk(ts, payload.size)
            dev_r = config.TRUST_RISK.get(trust_status, 0.7)
            dest_r = config.DEST_RISK.get(dest_type, config.DEST_RISK["other"])
            count = self._recent_count(u, ts)
            feats = {"hour": round(hour, 3), "sensitivity": sens_idx, "size_mb": round(payload.size / 1e6, 3),
                     "dest_risk": dest_r, "count_1h": count}
            anomaly, ml, heur = self.anomaly.score(feats)

            signals = {"sensitivity": sens_idx / 3, "user": user_r, "device": dev_r,
                       "destination": dest_r, "context": ctx_r, "anomaly": round(anomaly, 4)}
            score = round(100 * sum(config.WEIGHTS[k] * v for k, v in signals.items()), 1)
            level = risk_level(score)
            decision, policy_notes = self._decide(level, sens_idx, u, trust_status)

            reasons = list(cls.reasons) or ["no sensitive patterns found"]
            if not cls.inspected:
                reasons.append(f"content not inspected ({cls.note}): judged by file name and size")
            reasons += user_reasons + ctx_reasons
            reasons.append(f"device '{dev['name']}' is {trust_status}")
            reasons.append(f"destination: {dest_type}")
            if count:
                reasons.append(f"{count} transfer(s) by this user in the last hour")
            if anomaly > 0:
                src = "frequency heuristic" if ml is None or heur >= ml else self.anomaly.source
                reasons.append(f"anomaly score {anomaly:.2f} ({src})")
            reasons += policy_notes

            file_id = db.insert(
                "INSERT INTO files (name, path, sha256, size_bytes, sensitivity, sensitivity_level, matches, inspected) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (payload.name, payload.path, payload.sha256, payload.size, LEVELS[sens_idx], sens_idx,
                 json.dumps(cls.matches), int(cls.inspected)))
            event_id = db.insert(
                "INSERT INTO transfer_events (ts, user_id, device_id, file_id, channel, dest_type, decision, "
                "action_taken, dry_run) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (ts_str(ts), u["id"], dev["id"], file_id, channel, dest_type, decision, None, int(self.dry_run)))
            db.insert("INSERT INTO risk_assessments (event_id, score, level, reasons, features, signals) "
                      "VALUES (?, ?, ?, ?, ?, ?)",
                      (event_id, score, level, json.dumps(reasons), json.dumps(feats), json.dumps(signals)))

            alert_msg = None
            if decision == "BLOCK":
                alert_msg = (f"[{level}] blocked {dest_type} transfer by '{user}': {payload.name} (score {score})"
                             + (" [dry-run: not enforced]" if self.dry_run else ""))
                alert_id = db.insert("INSERT INTO alerts (event_id, severity, status, created_at, message) "
                                     "VALUES (?, ?, ?, ?, ?)", (event_id, level, "OPEN", ts_str(utcnow()), alert_msg))

            audit.append(db, {
                "type": "decision", "event_id": event_id, "ts": ts_str(ts), "user": user, "role": u["role"],
                "device": dev["name"], "trust": trust_status, "channel": channel, "dest_type": dest_type,
                "file": payload.name, "size": payload.size, "sha256": payload.sha256,
                "sensitivity": LEVELS[sens_idx], "matches": cls.matches, "score": score, "level": level,
                "decision": decision, "reasons": reasons, "dry_run": self.dry_run}, ts_str(ts), event_id)

        if alert_msg:
            alerts.dispatch({"id": alert_id, "event_id": event_id, "severity": level, "message": alert_msg})

        return Decision(event_id=event_id, user=user, role=u["role"], device=dev["name"], trust=trust_status,
                        channel=channel, dest_type=dest_type, file_name=payload.name, size=payload.size,
                        sha256=payload.sha256, level_idx=sens_idx, score=score, level=level, decision=decision,
                        reasons=reasons, matches=dict(cls.matches), signals=signals, features=feats,
                        alert=alert_msg, dry_run=self.dry_run, inspected=cls.inspected)

    def record_response(self, event_id, action):
        """Store what the channel actually did (quarantined, dropped, 550, unshared...)."""
        with self.db.transaction():
            self.db.execute("UPDATE transfer_events SET action_taken = ? WHERE id = ?", (action, event_id))
            audit.append(self.db, {"type": "response", "event_id": event_id, "action": action},
                         ts_str(utcnow()), event_id)
