# SPEC — Data Sentinel AI (original brief, saved verbatim)

I'm building our MSc team project "Data Sentinel AI", an AI-powered multi-channel Data Loss Prevention (DLP) system. I need it to actually run on this computer so I can demo it live at our project review. Detect my OS and make every command, script and path work on it. If Python 3.10+ isn't installed, stop and tell me how to install it.

STARTING POINT
- If this folder has data_sentinel_ai.zip or a data_sentinel_ai/ folder, that is our existing code. Unzip it, read all of it, run its tests, and build on it: fix what's broken and fill any gaps against the spec below. Don't rewrite parts that already work.
- If Data_Sentinel_AI_Project_Review.docx is here, read it (python-docx or pandoc). The code must stay consistent with it: same algorithms, numbers, scenarios and outputs.
- If neither exists, build everything from scratch to this spec.
- Before coding: save this prompt as SPEC.md, write a short plan, and keep a PROGRESS.md checklist that you update as you go. Run git init and commit after each milestone. Never push anywhere.
- Work through to the end without asking about routine steps. Ask me only when you're blocked, or before touching my real drives or accounts.

STACK
Python 3.10+ in a .venv. SQLite by default (PostgreSQL if DATABASE_URL is set). scikit-learn, numpy, joblib, psutil, aiosmtpd, streamlit, pandas, matplotlib, pytest. Chrome/Edge extension in Manifest V3, plain JavaScript. Package data_sentinel/, run as: python -m data_sentinel <command>

PIPELINE (the same for every channel)
detect -> metadata -> classify -> context -> anomaly -> risk score -> policy -> respond -> audit
1. Metadata: user, destination, channel, file name, size, time, SHA-256. Never store file contents or the matched sensitive values, only the type and count of what matched.
2. Classifier -> 0 Public, 1 Internal, 2 Confidential, 3 Restricted (highest match wins)
   - 3: card numbers (13-19 digits) that pass the Luhn check; Aadhaar-style "dddd dddd dddd" (must not also fire on the digits of a card number); PAN (ABCDE1234F); US SSN; private-key headers; AWS keys (AKIA + 16 chars); password/secret/api_key = a value of 6+ chars; the words restricted, top secret, strictly confidential
   - 2: confidential; payroll, salary, salaries, customer list, balance sheet; 10+ e-mail addresses
   - 1: internal use only
   - File names: .pem .key .pfx .p12 .env id_rsa -> 3; payroll, salary, passport, aadhaar, customer_data -> 2; confidential, restricted, secret -> 2; .sql .bak .dump -> 2
   - Reads text formats (.txt .csv .json .md .log .py .env .sql .xml .yaml .yml .ini .cfg .html), plus .docx/.pdf when python-docx/pdfplumber are installed. Anything else is judged by name only.
3. Context signals, each 0-1:
   - user: role risk (admin 0.1, employee 0.4, intern 0.6, contractor 0.7) + 0.1 x min(that user's blocked transfers in the last 30 days, 3), max 1
   - trust of device/destination: trusted 0, unknown 0.7, untrusted 1.0
   - destination type: internal 0, email_internal 0.2, network_share 0.3, email 0.6, usb 0.7, web 0.7, cloud 0.8, cloud_sync 0.8, messaging 0.8, genai 0.8, cloud_share 0.9, paste_site 1.0, other 0.8
   - context: +0.6 on weekends or outside 07:00-20:00 IST, +0.3 if the file is over 50 MB, max 1
4. Anomaly (the AI part): features [hour, sensitivity, size_mb, dest_risk, transfers by this user in the last hour]. Heuristic = min(1, count/10). Isolation Forest unit score = clip((-score_samples - 0.5) / 0.2, 0, 1). Anomaly = max(ML, heuristic). Load models/anomaly_iforest.joblib if present; otherwise train on the database once it has 50+ events; otherwise use the heuristic only.
5. Risk = 100 x (0.35*sensitivity/3 + 0.10*user + 0.20*trust + 0.15*destination + 0.10*context + 0.10*anomaly). Below 25 LOW, below 50 MEDIUM, below 70 HIGH, else CRITICAL.
6. Policy (stored in a policies table): LOW ALLOW, MEDIUM WARN, HIGH and CRITICAL BLOCK. Then apply, in this order: Restricted data to any non-trusted destination is always BLOCK; Public data that would get WARN gets ALLOW; admin + trusted device turns BLOCK into WARN. Every decision carries a list of plain-English reasons.
7. BLOCK raises an alert (stored and printed, with a hook for e-mail/Slack later).
8. Audit log: append-only. Each row stores SHA-256(previous hash + JSON record), and verify-audit must catch any edited or deleted row.
Database tables: users, devices, files, transfer_events, risk_assessments (score, level, reasons and features as JSON), alerts, policies, audit_log. Parameterized SQL only. One engine is shared by several watcher threads, so make it thread-safe.

CHANNELS (all must work; "->" is what BLOCK does)
- USB drives: poll psutil every 2 s for removable volumes. Windows: partitions flagged removable, named by volume label + serial. Linux: /sys/block/*/removable or USB bus, /media, /run/media. macOS: /Volumes checked with diskutil. Files already on the drive are a baseline; new files are scanned once their size stops changing. Ignore temp/lock files (~$*, *.tmp, *.part, *.crdownload, .DS_Store, desktop.ini) and OS folders (System Volume Information, $RECYCLE.BIN, .Trashes, .Spotlight-V100, .fseventsd). -> move the file to quarantine/
- Cloud sync folders: auto-detect Google Drive for desktop, OneDrive, Dropbox, iCloud Drive and Box; same watcher. -> move the file out of the folder
- Network shares (SMB/NFS/WebDAV mounts): same watcher. -> quarantine
- Any website, through the browser extension:
  - Intercept file-input uploads (including detached inputs, which Google Drive uses), drag-and-drop, and pastes of 20+ characters. Hold them and ask the local API.
  - ALLOW or WARN: replay the original event unchanged; WARN also shows an amber banner. BLOCK: drop it and show a red banner.
  - Files up to 20 MB are sent with their content; bigger ones as name + size only, and the engine judges them without writing a huge temp file.
  - Destination by host: cloud (drive.google.com, docs.google.com, dropbox.com, onedrive, wetransfer.com, mega.nz...), email (mail.google.com, outlook...), messaging (web.whatsapp.com, web.telegram.org, slack.com, teams, discord.com...), genai (chatgpt.com, gemini.google.com, claude.ai, copilot.microsoft.com...), paste_site (pastebin.com, gist.github.com...), internal (company domains), else web. Company domains are trusted; everything else is unknown.
  - Options page: agent URL, token, a "block when the agent is offline" toggle, and a "Save and test" button.
- Local scan API for the extension: 127.0.0.1:8765 only. POST /scan with an X-Sentinel-Token header (a random token created on first run and saved to .sentinel_token), plus GET /health. No CORS headers; return 413 when a request is too large.
- Desktop e-mail: SMTP gateway on 127.0.0.1:1025 (aiosmtpd). Scan subject + body and every attachment. All recipients in SENTINEL_COMPANY_DOMAINS -> email_internal, trusted. Any outside recipient -> email, unknown trust, named after the riskiest outside domain (personal webmail such as gmail.com first). -> reply 550 naming the blocked file. Otherwise add an X-Data-Sentinel header and relay to SENTINEL_SMTP_UPSTREAM, or save the .eml to outbox/ when no upstream is set.
- Files already in Google Drive (scan-drive): Drive API v3 with OAuth (credentials.json). Find files shared "anyone with the link", public, or with outside people/domains. Export Google Docs/Sheets as text and scan them as cloud_share (public -> untrusted, external -> unknown). --fix removes only the risky permissions on BLOCK. I may not have credentials, so test with a fake Drive client and document the setup steps.

COMMANDS
  python -m data_sentinel init-db | simulate | report | verify-audit
  python -m data_sentinel agent [--mail] [--watch FOLDER ...] [--no-usb] [--no-cloud] [--no-shares] [--no-browser] [--dry-run]
  python -m data_sentinel check FILE --dest cloud --device drive.google.com
  python -m data_sentinel watch FOLDER --device Demo-USB --trust untrusted
  python -m data_sentinel monitor
  python -m data_sentinel device add|list NAME --trust trusted|unknown|untrusted --type usb|cloud|...
  python -m data_sentinel user add|list NAME --role admin|employee|intern|contractor
  python -m data_sentinel scan-drive [--fix]
--watch treats a folder as a USB drive (for the demo). --dry-run decides, logs and alerts but never moves, drops or deletes anything.

DASHBOARD (streamlit run dashboard/app.py)
- KPI row: events, blocked, warnings, open alerts, audit chain intact/tampered
- Filters: channel, user, risk level, decision
- Charts: stacked bar of channel x decision; events by risk level; risk score over time
- Events table, plus "why was this scored this way" showing the reasons
- Alerts with "mark resolved"; a "check a file" upload; devices and policy tables

ML SCRIPTS (model -> models/, results -> results/)
- ml/train_eval.py: 5,000 synthetic events, 5% exfiltration, 70/30 stratified split, seed 42.
  - Normal events: hour ~ N(13, 2.5); sensitivity 0/1/2/3 with p .45/.40/.12/.03; size lognormal(-0.5, 1.0) MB; dest_risk from 0/.3/.6/.7/.8 with p .40/.25/.20/.10/.05; count ~ Poisson(1.5).
  - Exfiltration, in equal thirds: night bulk copy (hours 0-5 or 21-23, sensitivity 1-3, size lognormal(0.5, 1.0), dest .7/.8, count 8-39); one large sensitive file in office hours (hour ~ N(14, 3), sensitivity 2-3, size 60-900 MB, dest .6-.8, count ~ Poisson(1)); burst of small files (hour ~ N(15, 3), sensitivity 1-3, size lognormal(-1, 0.8), dest .6-.8, count 12-59).
  - Isolation Forest with 200 trees and contamination 0.05, trained without labels. Report precision, recall, F1 and ROC-AUC for the heuristic, Isolation Forest and hybrid at threshold 0.5. Save metrics.json, ml_evaluation.md and roc_curve.png.
- ml/compare_algorithms.py: Isolation Forest vs One-Class SVM vs Local Outlier Factor vs Elliptic Envelope vs the heuristic, mean over seeds 1-5. Plus a Luhn test: false alarms on 10,000 random 16-digit numbers with and without Luhn, and all standard test card numbers still detected.
- Our review document reports about: heuristic F1 63% / AUC 75%; Isolation Forest F1 93% / AUC 99.9%; hybrid recall 96%; Luhn cuts 10,000 false alarms to about 990. Yours should land close. Tell me the exact numbers you get.

SCENARIOS (simulate must produce exactly these decisions; scores within a few points; "/" = new line in file content)
Seed users: alice (employee), bob (admin), carol (contractor). Seed devices: corp-laptop (internal, trusted), Corp-EncryptedUSB (usb, trusted), SanDisk-USB-01 (usb, unknown), Unknown-USB-77 (usb, untrusted).
Run them in this order on Mon 5 Oct 2026: A-C and E-J at 11:30 IST, then D at 22:30 IST.
  A alice -> corp-laptop: "Join us for the annual picnic on Friday!" -> ALLOW ~4
  B alice -> SanDisk-USB-01: "Internal use only. Sprint planning notes for next week." -> WARN ~41
  C carol -> Unknown-USB-77: customer_payroll_confidential.csv = "RESTRICTED / name,card,salary / Test User,4111 1111 1111 1111,90000" -> BLOCK, CRITICAL ~74.5
  E bob -> drive.google.com (cloud): customer_list.csv with 25 e-mail addresses -> BLOCK ~50
  F alice -> chatgpt.com (genai): deploy_notes.txt containing "api_key = sk_live_51HxTestKeyOnly" -> BLOCK ~68
  G carol -> mail:gmail.com (email): q3_salaries.xlsx.csv = "Confidential / employee,salary / A,120000" -> BLOCK ~55
  H alice -> mail:internal (email_internal, trusted): "Paneer butter masala and rice on Wednesday." -> ALLOW ~11
  I bob -> OneDrive (cloud_sync): the file from C -> BLOCK ~66
  J bob -> gdrive:public-link (cloud_share, untrusted): the file from C -> BLOCK, CRITICAL ~74
  D alice -> SanDisk-USB-01: "Internal use only. Weekly status report." copied 12 times, one per minute -> 12th copy BLOCK ~59

TESTS (pytest, in-memory SQLite, no network)
- Classifier: Luhn; classifier levels; a card number not also counted as Aadhaar.
- Engine: scenarios A, B and C; alert on block; audit tamper detection; matched values never stored.
- Watchers: folder baseline + quarantine, and nothing moved in --dry-run; sync-folder detection.
- Browser API: destination categories; 401 without a token; BLOCK for a secret sent to WhatsApp; no CORS header; harmless paste not blocked; oversized upload judged by name and size.
- SMTP gateway: internal mail delivered with the header; external mail with a test card refused with 550.
- Drive scanner (fake client): flags the public payroll file; --fix removes only the "anyone" permission; report-only changes nothing.
- Extension: serve a local page with a file input, a drop zone and a textarea, and drive it with Playwright + the unpacked extension if you can. If not, test content.js with jsdom against the real API.

RULES
- Synthetic test data only. No real personal data, cards or keys.
- While testing, never touch my real USB drives, cloud sync folders, mailbox or Google Drive. Use temp folders, --watch, outbox mode and fakes. Ask me before running anything against real ones.
- Don't change the weights, thresholds, rules or scenarios above without asking me. They're quoted in our review document.
- Install packages only inside .venv.
- If something can't work on my OS, say so plainly and suggest the closest alternative.

DONE MEANS
1. pytest passes, simulate gives the decisions above, and verify-audit reports the chain intact.
2. With the agent running:
   - a restricted test file dropped into a watched demo folder is quarantined (only logged with --dry-run);
   - the SMTP gateway refuses a test mail to a gmail.com address carrying a test card;
   - the API blocks pasting an API key into chatgpt.com.
3. The dashboard opens and shows the simulated events without errors.
4. The extension loads in Chrome/Edge. Give me a 5-minute checklist to verify it myself on Google Drive, Gmail and ChatGPT using the demo files.
5. Deliverables:
   - README.md (setup + every command) and requirements.txt
   - demo_files/ with synthetic files: public notice, internal memo, payroll with a test card, notes with a fake API key, customer list
   - a one-click start script for my OS: resets the demo database, runs simulate, then starts the agent (browser API + mail gateway + a demo_usb/ folder watched as a USB drive, no real drives or sync folders) and the dashboard
   - DEMO.md: a 5-7 minute step-by-step demo script for the review with the expected output at each step, including an optional step with a real USB stick
6. End with a short summary in simple words:
   - what works
   - what to show in the demo
   - known limits: USB/sync/share files are handled just after the copy, not before it; browser coverage needs the extension; desktop e-mail is only covered through the gateway; ML numbers come from synthetic data
