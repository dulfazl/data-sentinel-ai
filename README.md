# Data Sentinel AI

**An AI-powered, multi-channel Data Loss Prevention (DLP) system** — MSc team project
(Muhammed Dulfazal, Rohen Paul J, Adithya Ram) · Guide: Dr. Gayathri A. · Python Programming (PAAML503).

Every transfer of data out of the computer — USB drives, cloud sync folders, network shares, website
uploads / drag-and-drop / pastes, desktop e-mail and over-shared Google Drive files — goes through
one pipeline:

```
detect -> metadata -> classify -> context -> anomaly (Isolation Forest) -> risk score -> policy -> respond -> audit
```

The result is **ALLOW**, **WARN** or **BLOCK**, with plain-English reasons, an alert for every block,
and a tamper-evident (hash-chained) audit log shown on a Streamlit dashboard.
The algorithms, weights, thresholds and scenarios are the ones in the project review document.

---

## Contents

1. [Quick start (macOS)](#1-quick-start-macos)
2. [Setup by hand](#2-setup-by-hand)
3. [Every command](#3-every-command)
4. [Channels and how to connect them](#4-channels-and-how-to-connect-them)
5. [Configuration](#5-configuration)
6. [Tests](#6-tests)
7. [Machine learning results](#7-machine-learning-results)
8. [How it works](#8-how-it-works)
9. [Project layout](#9-project-layout)
10. [Known limits](#10-known-limits)

For the live review, follow **[DEMO.md](DEMO.md)**. The IEEE-format project report is in
[report/](report/Data_Sentinel_AI_IEEE_Report.pdf).

### Online demo dashboard

**Live demo: <https://data-sentinel-ai.streamlit.app>**

The dashboard runs on **Streamlit Community Cloud** from this repository (main file
`dashboard/app.py`, Python 3.13). The app has the secret `SENTINEL_DEMO_SEED = "1"`, so on a fresh
start it fills itself with the ten simulated scenarios. The endpoint agent (USB drives, sync
folders, browser API, mail gateway) protects the computer it runs on, so it always runs locally
with `start_demo.command`.

A Render blueprint ([`render.yaml`](render.yaml), free plan) is also included: Render → **New →
Blueprint** → pick this repository → **Apply**. It runs `simulate` and then the dashboard.

---

## 1. Quick start (macOS)

Double-click **`start_demo.command`** in Finder (or run `./start_demo.command` in Terminal).

It will:
1. create `.venv` and install the packages the first time (needs Python 3.10+),
2. reset the demo database and run the ten test scenarios,
3. open the dashboard at <http://localhost:8501>,
4. start the agent: browser API on `127.0.0.1:8765`, mail gateway on `127.0.0.1:1025`, and the
   `demo_usb/` folder watched as an untrusted USB drive.
   **Real USB drives, cloud sync folders and network shares are not watched by this script.**

The browser-API token is printed and copied to the clipboard — paste it in the extension options.
Press **Ctrl+C** in that window to stop everything. Add `--dry-run` to decide and log without blocking:
`./start_demo.command --dry-run`.

If Python 3.10+ is missing: install it from <https://www.python.org/downloads/macos/> or with
Homebrew (`brew install python@3.13`).

## 2. Setup by hand

```bash
python3 -m venv .venv
```
```bash
.venv/bin/pip install -r requirements.txt
```
```bash
.venv/bin/python ml/train_eval.py
```
```bash
.venv/bin/python -m data_sentinel simulate
```

On Windows use `.venv\Scripts\python` instead of `.venv/bin/python`. Optional extras
(Playwright for the extension test, Google API libraries for `scan-drive`, PostgreSQL driver) are in
`requirements-optional.txt`.

## 3. Every command

All commands are `python -m data_sentinel <command>` (inside the venv). `--db FILE` before the command
uses another SQLite file.

| Command | What it does |
|---|---|
| `init-db [--reset]` | Create tables; seed users alice (employee), bob (admin), carol (contractor), devices and the policy table. |
| `simulate [--no-reset]` | Reset the database (old events are backed up first) and run scenarios A–J and D. Prints each decision and a summary table, then verifies the audit chain. |
| `report [--limit N]` | Recent events, totals per decision, open alerts and audit status. |
| `verify-audit` | Recompute the hash chain. Exit code 1 and the row number if anything was edited or deleted. |
| `tamper-demo` | Copies the database, secretly changes one BLOCK to ALLOW **in the copy**, and shows `verify-audit` catching it. The real database is not touched. |
| `agent [--mail] [--watch FOLDER ...] [--no-usb] [--no-cloud] [--no-shares] [--no-browser] [--dry-run]` | Run all channels. Also: `--user NAME` (default: your login), `--watch-device Demo-USB`, `--watch-trust untrusted`, `--api-port`, `--smtp-port`. |
| `check FILE --dest cloud --device drive.google.com` | Run one file through the pipeline (also `--user`, `--trust`, `--channel`). |
| `watch FOLDER --device Demo-USB --trust untrusted` | Watch one folder as a USB drive (also `--user`, `--dest`, `--dry-run`). |
| `monitor` | Live view of new events and alerts in the terminal. |
| `device add NAME --trust trusted --type usb` / `device list` | Register a device or destination and its trust level. |
| `user add NAME --role contractor` / `user list` | Register a user and role. |
| `scan-drive [--fix] [--demo] [--dry-run]` | Find Drive files shared publicly or outside the company; `--fix` removes only the risky sharing of BLOCKed files; `--demo` uses a built-in fake Drive. |
| `try-paste [--host chatgpt.com] [--text ...] [--file F]` | Demo helper: send a paste to the running browser API exactly like the extension does. |
| `try-mail [--to friend@gmail.com] [--attach FILE ...]` | Demo helper: send a test e-mail through the running mail gateway and print the SMTP reply. |

Dashboard: `.venv/bin/streamlit run dashboard/app.py --server.address 127.0.0.1`

ML: `.venv/bin/python ml/train_eval.py` and `.venv/bin/python ml/compare_algorithms.py`

## 4. Channels and how to connect them

| Channel | How it is detected | What BLOCK does |
|---|---|---|
| USB drives | psutil every 2 s. macOS: `/Volumes/*` checked with `diskutil` (external/removable, not disk images). Windows: partitions flagged removable, named label + serial. Linux: `/sys/block/*/removable`, USB bus, `/media`, `/run/media`. | file moved to `quarantine/` |
| Cloud sync folders | Google Drive for desktop, OneDrive, Dropbox, iCloud Drive, Box found automatically | file moved out of the folder into `quarantine/` |
| Network shares | SMB / NFS / WebDAV / AFP mounts from psutil | file moved to `quarantine/` |
| Websites | browser extension: file inputs (also detached ones, as Google Drive uses), drag-and-drop, pastes of 20+ characters | event dropped, red banner |
| Desktop e-mail | SMTP gateway on `127.0.0.1:1025` | `550 5.7.1 Blocked by Data Sentinel: sensitive content in <file>` |
| Google Drive (files already shared) | Drive API v3 scan | with `--fix`: public/external permission removed |

All file watchers share one engine. Files already on a drive when watching starts are a baseline;
new or changed files are scanned once their size stops changing. Temp/lock files (`~$*`, `*.tmp`,
`*.part`, `*.crdownload`, `.DS_Store`, `desktop.ini`, `._*`) and OS folders (`System Volume Information`,
`$RECYCLE.BIN`, `.Trashes`, `.Spotlight-V100`, `.fseventsd`) are ignored. Each quarantined file gets a
`.sentinel.json` note (decision and reasons — no content).

### Browser extension (Chrome, Edge, Brave)

1. Start the agent (or `start_demo.command`) and copy the token it prints (also in `.sentinel_token`).
2. Open `chrome://extensions` (Edge: `edge://extensions`, Brave: `brave://extensions`), switch on
   **Developer mode**, click **Load unpacked** and pick the `extension/` folder.
3. The options page opens: paste the token, keep the URL `http://127.0.0.1:8765`, click **Save and test**
   — it should say *Connected to the agent - token accepted*.
4. Optional: tick **Block uploads and pastes when the agent is offline**.

How it works: a content script holds the upload / drop / paste event, the background worker asks the
local API, then the event is replayed unchanged (ALLOW, WARN + amber banner) or dropped (BLOCK + red
banner). Files up to 20 MB are sent with content; larger files as name + size only. The agent sends no
CORS headers, so web pages cannot call it; only the extension's background worker can.
Destination by host: cloud (drive.google.com, docs.google.com, dropbox.com, onedrive, wetransfer.com,
mega.nz …), email (mail.google.com, outlook …), messaging (web.whatsapp.com, web.telegram.org,
slack.com, teams, discord.com …), genai (chatgpt.com, gemini.google.com, claude.ai,
copilot.microsoft.com …), paste_site (pastebin.com, gist.github.com …), internal (company domains,
trusted); anything else is `web`. The dashboard (`localhost:8501`) is skipped so its "check a file"
upload works.

### Desktop e-mail (SMTP gateway)

Start with `agent --mail`. In the mail app (Apple Mail, Outlook, Thunderbird) set the **outgoing
(SMTP) server** to `127.0.0.1`, port `1025`, no SSL/TLS, no authentication. Subject, body and every
attachment are scanned. All recipients in `SENTINEL_COMPANY_DOMAINS` → `email_internal` (trusted);
any outside recipient → `email` (unknown trust), named after the riskiest outside domain
(personal webmail such as gmail.com first). Allowed mail gets an `X-Data-Sentinel` header and is relayed to
`SENTINEL_SMTP_UPSTREAM` (`host:port`; optional `SENTINEL_SMTP_STARTTLS=1`, `SENTINEL_SMTP_USER`,
`SENTINEL_SMTP_PASSWORD`) or saved as `.eml` in `outbox/` when no upstream is set.
If the sender is on a company domain, the event is recorded for that user (alice@company.com → alice).

### Google Drive scanner

Try it without an account: `python -m data_sentinel scan-drive --demo`.

For a real account:
1. In <https://console.cloud.google.com/> create a project and enable the **Google Drive API**.
2. *APIs & Services → OAuth consent screen*: choose *External*, add yourself as a test user.
3. *Credentials → Create credentials → OAuth client ID → Desktop app*; download the JSON and save it
   as `credentials.json` in the project folder (it is git-ignored).
4. `pip install google-api-python-client google-auth-oauthlib`
5. `python -m data_sentinel scan-drive` — a browser window asks you to sign in (read-only scope).
   The token is stored in `.drive_token.json`.
6. `python -m data_sentinel scan-drive --fix` asks again for the full Drive scope and removes only the
   risky permissions (anyone-with-link, public, outside people/domains) of BLOCKed files; owners and
   internal shares are kept. Run it without `--fix` first to see the report.

Files shared with "anyone" are scanned as `gdrive:public-link` (untrusted), files shared outside the
company as `gdrive:external` (unknown trust). Google Docs/Slides are exported as text, Sheets as CSV.

## 5. Configuration

| Variable | Default | Meaning |
|---|---|---|
| `SENTINEL_COMPANY_DOMAINS` | `company.com` | comma-separated company domains (trusted / internal) |
| `DATABASE_URL` | – | `postgresql://…` to use PostgreSQL (needs `psycopg`); otherwise SQLite |
| `SENTINEL_DB` | `data_sentinel.db` | SQLite file |
| `SENTINEL_USER` | your login name | user reported by the agent |
| `SENTINEL_SMTP_UPSTREAM` | – | `host:port` to relay allowed mail to |
| `SENTINEL_QUARANTINE`, `SENTINEL_OUTBOX` | `quarantine/`, `outbox/` | where blocked files / saved mails go |
| `SENTINEL_API_PORT`, `SENTINEL_SMTP_PORT` | `8765`, `1025` | ports (always bound to 127.0.0.1) |
| `SENTINEL_SLACK_WEBHOOK` | – | optional: also post alerts to a Slack incoming webhook |
| `SENTINEL_MODEL` | `models/anomaly_iforest.joblib` | saved Isolation Forest |

Users, roles and device trust live in the database: `user add`, `device add`.
The policy table (LOW→ALLOW, MEDIUM→WARN, HIGH/CRITICAL→BLOCK) is the `policies` table.

## 6. Tests

```bash
.venv/bin/python -m pytest -q
```

125 tests, in-memory SQLite, local ports only, no internet:
classifier (Luhn, levels, card not counted as Aadhaar), engine (scenarios, alerts, audit tampering,
matched values never stored, thread safety), watchers (baseline, quarantine, dry-run, temp files,
plug/unplug, sync-folder detection for macOS/Windows/Linux), browser API (categories, 401, BLOCK for a
secret sent to WhatsApp, no CORS, harmless paste, oversized upload, 413), SMTP gateway (internal mail
delivered with header, 550 for a test card to gmail.com, relay), Drive scanner (fake client, `--fix`
removes only the "anyone" permission), dashboard (Streamlit AppTest) and the **extension end-to-end
in Chromium** with Playwright (file input, detached input, drag-and-drop, paste, large file, offline
toggle).

The extension test needs `pip install playwright==1.52.0` and `python -m playwright install chromium`;
it is skipped otherwise.

## 7. Machine learning results

Synthetic data only. `ml/train_eval.py` (seed 42, 5,000 events, 5 % exfiltration, 70/30 split
stratified by attack pattern; Isolation Forest with 200 trees, contamination 0.05, trained without labels;
threshold 0.5):

| Approach | Precision | Recall | F1 | ROC-AUC | Leaks caught | Review doc (F1 / AUC / recall) |
|---|---|---|---|---|---|---|
| Rule-based heuristic | 66.7 % | 66.7 % | 66.7 % | 79.45 % | 50 of 75 | 62.9 / 74.7 / 60.0 |
| Isolation Forest | 98.6 % | 90.7 % | 94.4 % | 99.96 % | 68 of 75 | 93.2 / 99.9 / 90.7 |
| Proposed hybrid | 73.7 % | 97.3 % | 83.9 % | 99.68 % | 73 of 75 | 83.7 / 99.7 / 96.0 |

`ml/compare_algorithms.py` (mean of seeds 1–5):

| Algorithm | Precision | Recall | F1 | ROC-AUC | Review doc F1 / AUC |
|---|---|---|---|---|---|
| Isolation Forest | 93.5 % | 91.7 % | 92.6 % | 99.8 % | 92.8 / 99.9 |
| Elliptic Envelope | 82.6 % | 85.1 % | 83.6 % | 99.6 % | 83.5 / 99.6 |
| One-Class SVM | 67.8 % | 74.9 % | 71.0 % | 93.8 % | 71.3 / 94.6 |
| Frequency heuristic | 65.7 % | 66.9 % | 66.3 % | 78.7 % | 64.0 / 78.5 |
| Local Outlier Factor | 14.1 % | 14.7 % | 14.3 % | 52.4 % | 20.7 / 68.4 |

Luhn test: 10,000 random 16-digit numbers → **10,000** false alarms with the regex alone, **980** with
regex + Luhn (90.2 % fewer); all 6 standard test card numbers still detected (review doc: 991).

Outputs: `models/anomaly_iforest.joblib`, `results/metrics.json`, `results/ml_evaluation.md`,
`results/roc_curve.png`, `results/algorithm_comparison.{json,md,png}`, `results/luhn_test.{json,png}`.

Why the heuristic differs a little from the document: the heuristic cannot see the "one large file"
attack, so its score depends on how many of those land in the 30 % test set. Splitting by attack
pattern keeps exactly a third of each pattern in the test set, which gives stable numbers.

## 8. How it works

* **Metadata:** user, destination, channel, file name, size, time, SHA-256. File contents and matched
  values are never stored — only the type and count of each match (e.g. `credit card number x1`).
* **Classifier** (highest wins): 3 Restricted — Luhn-valid card numbers (13–19 digits), Aadhaar-style
  `dddd dddd dddd` (never on the digits of a card), PAN, US SSN, private-key headers, AWS keys,
  `password/secret/api_key = value of 6+ chars`, "restricted / top secret / strictly confidential";
  2 Confidential — "confidential", payroll, salary, salaries, customer list, balance sheet, 10+ e-mail
  addresses; 1 Internal — "internal use only". File-name rules: `.pem .key .pfx .p12 .env id_rsa` → 3;
  payroll, salary, passport, aadhaar, customer_data, confidential, restricted, secret, `.sql .bak .dump` → 2.
  Text formats are read, plus `.docx` / `.pdf`; anything else is judged by name.
* **Context signals (0–1):** user = role risk (admin 0.1, employee 0.4, intern 0.6, contractor 0.7)
  + 0.1 × min(blocks in 30 days, 3); trust: trusted 0, unknown 0.7, untrusted 1.0; destination:
  internal 0 … paste_site 1.0; context: +0.6 weekend or outside 07:00–20:00 IST, +0.3 over 50 MB.
* **Anomaly:** features [hour, sensitivity, size_mb, dest_risk, transfers in the last hour].
  heuristic = min(1, count/10); Isolation Forest unit score = clip((−score_samples − 0.5)/0.2, 0, 1);
  anomaly = max of the two. Uses `models/anomaly_iforest.joblib`, else trains on the database after
  50 events, else the heuristic only.
* **Risk** = 100 × (0.35·sensitivity/3 + 0.10·user + 0.20·trust + 0.15·destination + 0.10·context +
  0.10·anomaly). LOW < 25 ≤ MEDIUM < 50 ≤ HIGH < 70 ≤ CRITICAL.
* **Policy:** LOW ALLOW, MEDIUM WARN, HIGH/CRITICAL BLOCK, then: Restricted to any non-trusted
  destination → BLOCK; Public that would be WARN → ALLOW; admin + trusted device → BLOCK becomes WARN.
* **Audit:** append-only (database triggers refuse UPDATE/DELETE); each row stores
  SHA-256(previous hash + JSON record). `verify-audit` catches edited rows, deleted rows (also the last
  one) and changed decisions in the events table.
* **Thread safety:** one connection behind a lock; every event is one `BEGIN IMMEDIATE` transaction,
  so watcher threads, the API, the mail gateway and the dashboard can write at the same time.

## 9. Project layout

```
data_sentinel/      the package (engine, classifier, anomaly, audit, db, channels, CLI)
  watchers/         folder watcher, USB/share discovery, sync-folder detection
extension/          Chrome/Edge/Brave extension (Manifest V3, plain JavaScript)
dashboard/app.py    Streamlit dashboard
ml/                 train_eval.py, compare_algorithms.py, synthetic.py
models/, results/   trained model and ML results
tests/              pytest suite (incl. Playwright extension test)
demo_files/         synthetic demo files
start_demo.command  one-click demo start (macOS)
DEMO.md             live demo script; SPEC.md the brief; PLAN.md, PROGRESS.md
```

## 10. Known limits

* USB, sync-folder and share files are handled **just after** the copy, not before it (no kernel
  file-system filter driver). A synced file may already be uploading when it is moved out.
* A sync folder cannot tell a file you added from a file that arrived from the cloud; both are scanned.
* Browser coverage needs the extension; a user with developer tools can still get around it.
  Only Chromium browsers (Chrome, Edge, Brave) are supported.
* Desktop e-mail is only covered when the mail app sends through the gateway.
* The ML numbers come from synthetic data; real accuracy needs labelled real transfer logs.
* macOS asks Terminal for permission the first time the agent reads a USB stick
  ("Terminal would like to access files on a removable volume") — click **Allow**.
* `.key` is treated as a private-key file (per the rules), so Apple Keynote `.key` files are flagged.
* PostgreSQL support is written but was not tested here (no PostgreSQL server on this machine);
  SQLite is fully tested. Linux and Windows USB/sync-folder code follows the spec but was only tested
  with simulated inputs on macOS.
