# Live demo script — Data Sentinel AI (5–7 minutes)

All files are synthetic (`demo_files/`). Nothing real is blocked, moved or sent.
Scores below are from a run on this Mac during office hours (IST). They move a little:
**after 20:00 IST every score is 6 points higher** (off-hours context), and each transfer you make in the
same hour adds about 1 point (that is the anomaly signal working). Decisions stay the same if you follow
the order below.

---

## Before the review (10 minutes, once)

1. **Start fresh** right before the review: double-click `start_demo.command`.
   It resets the database, runs the scenarios, opens the dashboard and starts the agent.
   Leave this Terminal window visible — it prints every decision live.
2. **Extension**: in your browser open `brave://extensions` (Chrome: `chrome://extensions`,
   Edge: `edge://extensions`) → Developer mode on → **Load unpacked** → choose the `extension/` folder.
   Paste the token (the start script copied it to the clipboard) → **Save and test** →
   *"Connected to the agent - token accepted"*. (You only need to load it once; after each restart the
   token stays the same.)
3. Sign in to **Google Drive**, **Gmail** and **ChatGPT** in that browser, each in its own tab.
4. Open a second Terminal tab in the project folder for the commands below
   (`cd` to the project, then use `.venv/bin/python -m data_sentinel ...`).
5. Open two Finder windows side by side: `demo_files/` and `demo_usb/`.
6. Do the [5-minute extension checklist](#5-minute-extension-checklist) once, then **restart
   `start_demo.command`** so the live demo starts from a clean history.

---

## Step 1 — The idea (30 s)

> "Data leaves a company through many doors: USB sticks, cloud folders, websites, AI chat, e-mail,
> shared Drive links. Data Sentinel puts one AI pipeline behind all of them: classify the content, look
> at who/where/when, ask an Isolation Forest whether the behaviour is unusual, compute a 0–100 risk
> score, and ALLOW, WARN or BLOCK — with reasons, an alert and a tamper-evident audit log."

## Step 2 — The ten test scenarios (45 s)

Show the start-script window (scroll up) or run `report`. Expected summary:

```
ID  Sensitivity    Score  Level     Decision Expected
A   Public           4.0  LOW       ALLOW    ALLOW ok
B   Internal        41.2  MEDIUM    WARN     WARN ok
C   Restricted      74.0  CRITICAL  BLOCK    BLOCK ok
D   Internal        59.2  HIGH      BLOCK    BLOCK ok
E   Confidential    50.3  HIGH      BLOCK    BLOCK ok
F   Restricted      67.2  HIGH      BLOCK    BLOCK ok
G   Confidential    55.3  HIGH      BLOCK    BLOCK ok
H   Public          11.0  LOW       ALLOW    ALLOW ok
I   Restricted      65.2  HIGH      BLOCK    BLOCK ok
J   Restricted      73.7  CRITICAL  BLOCK    BLOCK ok
Audit chain intact (21 records verified).
```

> "Same decisions as in our review document; scores within one point (C 74.0 vs 74.5)."
> Point at **D**: an *Internal* file, but the 12th copy at 22:30 is blocked — behaviour, not content.

## Step 3 — USB drive (60 s)

Drag these from `demo_files/` into `demo_usb/` **one at a time** (wait ~3 s each):

| File | Expected in the agent window |
|---|---|
| `public_notice.txt` | `[usb] ALLOW  public_notice.txt -> Demo-USB  (Public, risk 34.5 MEDIUM)` |
| `internal_memo.txt` | `DECISION : WARN`, risk ≈ 47 (MEDIUM) |
| `customer_payroll_confidential.csv` | `DECISION : BLOCK`, risk ≈ 71.5 (CRITICAL), reasons incl. `content: credit card number x1 -> Restricted`, then `ALERT -> security team: [CRITICAL] blocked usb transfer ...` and `RESPONSE : quarantined to quarantine/...` |

Show that the payroll file **vanished from `demo_usb/`** and is in `quarantine/` with a
`.sentinel.json` note (reasons only, no content).

> "The card number was validated with the Luhn checksum. We only store *'credit card number x1'*,
> never the number."

## Step 4 — Websites, through the extension (90 s)

**Google Drive** (`drive.google.com` → *New → File upload*):

| Upload | Expected |
|---|---|
| `public_notice.txt` | uploads normally, no banner |
| `internal_memo.txt` | uploads, **amber banner** "Data Sentinel warning: internal_memo.txt (Internal) is going to drive.google.com…" |
| `customer_payroll_confidential.csv` | **red banner** "Blocked by Data Sentinel: customer_payroll_confidential.csv (Restricted) cannot be sent to drive.google.com." — nothing appears in Drive |

> "Drive uses a hidden file input that is never attached to the page — we catch that too.
> Drag-and-drop is caught the same way."

**ChatGPT** (`chatgpt.com`), click in the message box:
1. Open `demo_files/harmless_paste.txt`, copy its line, paste → the text appears normally.
2. Copy the line from `demo_files/paste_api_key.txt` (`api_key = sk_live_51HxTestKeyOnly`), paste →
   **red banner** "Blocked by Data Sentinel: pasted text (Restricted) cannot be sent to chatgpt.com.";
   nothing is pasted. Agent window: `[browser] pasted text -> chatgpt.com`, `DECISION : BLOCK`, risk ≈ 69.

*No internet?* Same check from the terminal:
`.venv/bin/python -m data_sentinel try-paste` → `DECISION : BLOCK (risk ~69 HIGH, Restricted)`.

## Step 5 — Desktop e-mail through the gateway (45 s)

```bash
.venv/bin/python -m data_sentinel try-mail --to friend@gmail.com --attach demo_files/customer_payroll_confidential.csv
```
Expected: `Gateway reply: 550 5.7.1 Blocked by Data Sentinel: sensitive content in customer_payroll_confidential.csv`

```bash
.venv/bin/python -m data_sentinel try-mail --to bob@company.com --subject Lunch --body "Paneer butter masala and rice on Wednesday."
```
Expected: `Gateway reply: 250 accepted` and a new `.eml` in `outbox/` whose first line is
`X-Data-Sentinel: ALLOW; score=...`

> "A real mail app (Apple Mail, Outlook, Thunderbird) works the same way with its SMTP server set to
> 127.0.0.1 port 1025."

## Step 6 — Dashboard (60 s)

Switch to <http://localhost:8501> (refreshes every 5 s):
* KPI row: events, blocked, warnings, open alerts, **Audit chain ✅ Intact**.
* *Decisions by channel* — usb, browser, email, cloud_sync, drive, internal.
* *Risk score over time* — hover a dot for details.
* **Why was this scored this way?** pick the payroll USB event: reasons + score breakdown
  (sensitivity 35 pts, device 20, destination 10.5, user 4 …).
* Alerts → select one → **Mark resolved**.

## Step 7 — Tamper-evident audit log (30 s)

```bash
.venv/bin/python -m data_sentinel tamper-demo
```
Expected:
```
Changed audit row 3: decision BLOCK -> ALLOW, hash left as it was.
Real database : Audit chain intact (... records verified).
Tampered copy : TAMPERING detected at audit row 3: record content does not match its hash (row edited)
```
> "Every record holds the SHA-256 of the previous one. Change or delete any row and the chain breaks."

## Step 8 — Close with the limits (20 s)

USB/sync/share copies are handled just after the copy (not before); browser coverage needs the
extension; desktop e-mail is covered through the gateway; the ML numbers come from synthetic data.

---

## Optional extras

**Google Drive sharing scan (no account needed):**
```bash
.venv/bin/python -m data_sentinel scan-drive --demo --fix
```
Expected: `[BLOCK] customer_payroll_confidential - shared with anyone with the link … FIXED: removed
sharing: anyone with the link`, while the public picnic notice and the partner note are ALLOWed and
left alone. (With a real account: see README → *Google Drive scanner*.)

**Dry-run mode:** stop the demo (Ctrl+C) and start `./start_demo.command --dry-run`. Copying the payroll
file to `demo_usb/` now prints `DECISION : BLOCK [dry-run]`, `RESPONSE : dry-run: file left in place`
— the file stays, but the event and alert are recorded.

### Optional: a real USB stick (2 minutes)

Use a spare stick with nothing important on it, and only the demo files.

1. Stop the demo agent (Ctrl+C in the start-script window; the dashboard stops too).
2. Start the agent with real USB watching (cloud folders and shares still off). Start with `--dry-run`
   the first time if you like:
   ```bash
   .venv/bin/python -m data_sentinel agent --mail --watch demo_usb --no-cloud --no-shares
   ```
   and the dashboard in another tab: `.venv/bin/streamlit run dashboard/app.py`
3. Plug in the stick. Expected within 2 s:
   `[usb] USB:<LABEL>-<id> connected at /Volumes/<LABEL> - N existing file(s) baselined`
   (files already on the stick are never touched). macOS may ask *"Terminal would like to access files
   on a removable volume"* → **Allow**.
4. In Finder, copy `demo_files/customer_payroll_confidential.csv` onto the stick → BLOCK, the copy is
   moved off the stick into `quarantine/`. Copy `public_notice.txt` → ALLOW, it stays.
5. Optional: `.venv/bin/python -m data_sentinel device add "USB:<LABEL>-<id>" --trust trusted --type usb`
   to register it as a company stick, and copy `internal_memo.txt` again to compare scores.

---

## 5-minute extension checklist

Do this once before the review, with the agent running (`start_demo.command`). Tick each line.

**Setup (1 min)**
- [ ] Extension loaded from `extension/` (Developer mode → Load unpacked). No errors on the
      extensions page.
- [ ] Extension icon → popup says **"Protected - agent connected"**.
- [ ] Options → **Save and test** → *"Connected to the agent - token accepted"*.

**Google Drive (1.5 min)** — `drive.google.com`
- [ ] *New → File upload* → `public_notice.txt` → uploads, no banner.
- [ ] *New → File upload* → `internal_memo.txt` → uploads with an **amber** banner.
- [ ] *New → File upload* → `customer_payroll_confidential.csv` → **red** banner, file not in Drive.
- [ ] Drag `customer_list.csv` from Finder onto the Drive window → **red** banner, not uploaded.
- [ ] Delete the two test uploads from Drive afterwards.

**Gmail (1.5 min)** — `mail.google.com` → Compose (you do not need to send anything)
- [ ] Paperclip → attach `customer_payroll_confidential.csv` → **red** banner, no attachment chip.
- [ ] Drag `deploy_notes.txt` into the compose window → **red** banner.
- [ ] Paste the line from `paste_api_key.txt` into the body → **red** banner, text not inserted.
- [ ] Paste the line from `harmless_paste.txt` → text appears. Discard the draft.

**ChatGPT (1 min)** — `chatgpt.com`
- [ ] Paste the line from `harmless_paste.txt` → text appears in the box.
- [ ] Paste the line from `paste_api_key.txt` → **red** banner, nothing pasted.
- [ ] Paperclip / drag `deploy_notes.txt` → **red** banner, no file attached.
- [ ] Type fewer than 20 characters and paste a short word → not checked (pastes under 20 characters
      pass straight through, by design).

**Agent window**: each check above printed a `[browser] ...` decision. If a check did not behave as
listed, note the site and the step — website code changes often, and the extension was tested
end-to-end on a local test page in Chromium, not on these live sites.

Then restart `start_demo.command` so the review starts with a clean history.
