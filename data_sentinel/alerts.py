"""Alert delivery hooks.

Every BLOCK stores an alert row and calls each hook in ALERT_HOOKS. The console line
("ALERT -> security team: ...") is printed together with the decision by format_decision().
Hooks for e-mail / Slack can be added with register_hook(); a Slack incoming-webhook hook is
included and switches on only when SENTINEL_SLACK_WEBHOOK is set.
"""
import json
import os
import threading
import urllib.request

ALERT_HOOKS = []


def register_hook(fn):
    """fn(alert: dict) -> None. alert has: id, event_id, severity, message."""
    ALERT_HOOKS.append(fn)
    return fn


def slack_hook(alert):
    url = os.environ.get("SENTINEL_SLACK_WEBHOOK")
    if not url:
        return

    def send():
        try:
            req = urllib.request.Request(url, data=json.dumps({"text": f"Data Sentinel: {alert['message']}"}).encode(),
                                         headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=5).close()
        except Exception as exc:                  # never let alert delivery break enforcement
            print(f"  [alerts] Slack delivery failed: {exc}")
    threading.Thread(target=send, daemon=True).start()


# E-mail hook placeholder: implement with smtplib using SENTINEL_SMTP_UPSTREAM when needed.

register_hook(slack_hook)


def dispatch(alert):
    for hook in list(ALERT_HOOKS):
        try:
            hook(alert)
        except Exception as exc:
            print(f"  [alerts] hook {getattr(hook, '__name__', hook)} failed: {exc}")
