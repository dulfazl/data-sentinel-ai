"""Map a website host or a set of e-mail recipients to a destination type and trust level."""
from . import config

HOST_CATEGORIES = {
    "cloud": ["drive.google.com", "docs.google.com", "sheets.google.com", "slides.google.com",
              "dropbox.com", "dropboxusercontent.com", "onedrive.live.com", "onedrive.com", "1drv.ms",
              "sharepoint.com", "box.com", "wetransfer.com", "we.tl", "mega.nz", "mega.io", "icloud.com",
              "mediafire.com", "sendspace.com", "pcloud.com", "sync.com", "filemail.com", "terabox.com"],
    "email": ["mail.google.com", "outlook.live.com", "outlook.office.com", "outlook.office365.com",
              "mail.yahoo.com", "mail.proton.me", "mail.protonmail.com", "mail.zoho.com", "mail.aol.com",
              "gmx.com", "mail.com", "mail.yandex.com"],
    "messaging": ["web.whatsapp.com", "whatsapp.com", "web.telegram.org", "slack.com", "teams.microsoft.com",
                  "teams.live.com", "discord.com", "discordapp.com", "messenger.com", "web.skype.com",
                  "chat.google.com", "signal.org"],
    "genai": ["chatgpt.com", "chat.openai.com", "gemini.google.com", "bard.google.com", "claude.ai",
              "copilot.microsoft.com", "perplexity.ai", "poe.com", "chat.deepseek.com", "deepseek.com",
              "chat.mistral.ai", "grok.com", "meta.ai", "huggingface.co", "you.com", "character.ai"],
    "paste_site": ["pastebin.com", "gist.github.com", "paste.ee", "hastebin.com", "privatebin.net",
                   "dpaste.org", "dpaste.com", "controlc.com", "justpaste.it", "rentry.co", "ghostbin.com",
                   "paste.mozilla.org", "pastes.io"],
}

PERSONAL_WEBMAIL = ["gmail.com", "googlemail.com", "yahoo.com", "outlook.com", "hotmail.com", "live.com",
                    "msn.com", "icloud.com", "me.com", "aol.com", "proton.me", "protonmail.com", "gmx.com",
                    "gmx.net", "yandex.com", "mail.com", "zoho.com", "rediffmail.com"]


def _matches(host, domain):
    return host == domain or host.endswith("." + domain)


def normalize_host(host):
    host = (host or "").strip().lower().rstrip(".")
    if "://" in host:
        host = host.split("://", 1)[1]
    host = host.split("/", 1)[0].split("@")[-1]
    if host.startswith("[") and "]" in host:           # IPv6 literal
        return host[1:host.index("]")]
    host = host.split(":", 1)[0]
    return host[4:] if host.startswith("www.") else host


def is_company_domain(domain, domains=None):
    domain = normalize_host(domain)
    return any(_matches(domain, d) for d in (domains if domains is not None else config.company_domains()))


def categorize_host(host, domains=None):
    """Return (dest_type, trust) for a website host."""
    host = normalize_host(host)
    if is_company_domain(host, domains):
        return "internal", "trusted"
    for category, hosts in HOST_CATEGORIES.items():
        if any(_matches(host, h) for h in hosts):
            return category, "unknown"
    return "web", "unknown"


def classify_recipients(recipients, domains=None):
    """Return (device_name, dest_type, trust) for an e-mail recipient list."""
    rcpt_domains = sorted({r.rsplit("@", 1)[-1].strip(" >").lower() for r in recipients if "@" in r})
    outside = [d for d in rcpt_domains if not is_company_domain(d, domains)]
    if not outside:
        return "mail:internal", "email_internal", "trusted"
    webmail = [d for d in outside if d in PERSONAL_WEBMAIL]
    riskiest = sorted(webmail, key=PERSONAL_WEBMAIL.index)[0] if webmail else outside[0]
    return f"mail:{riskiest}", "email", "unknown"
