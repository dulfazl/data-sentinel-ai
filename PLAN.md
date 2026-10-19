# Plan

**Target machine:** macOS 27 (Apple Silicon), Python 3.13 (Homebrew) in `.venv`, zsh.
**Starting point:** no existing code in this folder. Found in `~/Downloads`:
- `Data_Sentinel_AI_Project_Review.docx` — the review document (numbers, scenarios, sample outputs). Code must match it.
- `data_sentinel_ai.pdf` — a printed listing of an earlier single-file prototype (`data_sentinel_ai.py`, scenarios A–D).
  Its rule tables, reason wording and output format are reused so the CLI output matches the review document.

## Architecture

```
data_sentinel/            python -m data_sentinel <command>
  config.py               weights, thresholds, risk tables, paths, env vars
  db.py                   SQLite (default) / PostgreSQL, thread-safe, parameterized SQL, schema + seed
  classifier.py           regex + Luhn rules, filename rules, text extraction (txt/csv/…/docx/pdf)
  anomaly.py              Isolation Forest (saved model / trained on DB) + frequency heuristic
  engine.py               the pipeline: metadata → classify → context → anomaly → risk → policy → alert → audit
  audit.py                hash-chained audit log + verify
  destinations.py         host → destination category (browser), e-mail recipient → destination
  scenarios.py            simulate (A–J, D)
  watchers/               folder watcher (baseline, stable size, ignore list, quarantine),
                          USB volume discovery (macOS/Windows/Linux), sync folders, network shares
  browser_api.py          127.0.0.1:8765  POST /scan, GET /health (token, no CORS, 413)
  smtp_gateway.py         127.0.0.1:1025  aiosmtpd, 550 on BLOCK, header + relay/outbox
  drive_scanner.py        Drive API v3 scanner (real + fake client), --fix
  agent.py                runs all channels as threads on one shared engine
  cli.py                  every command
extension/                Manifest V3: content.js (isolated), page_hook.js (MAIN world, detached inputs),
                          background.js (talks to the agent), options page
dashboard/app.py          Streamlit dashboard
ml/                       train_eval.py, compare_algorithms.py (synthetic data, results/ + models/)
tests/                    pytest (in-memory SQLite, no network) + Playwright extension test
demo_files/, DEMO.md, README.md, start_demo.command
```

## Milestones (one commit each)

1. Spec, plan, progress, git, venv
2. Core engine + DB + classifier + audit, with unit tests
3. CLI + `simulate` matching scenarios A–J and D
4. ML scripts (model saved to `models/`, numbers compared with the review document)
5. Channels: folder/USB/sync/share watchers, browser API, SMTP gateway, Drive scanner, agent
6. Browser extension + Playwright test
7. Dashboard
8. Demo files, start script, README, DEMO.md, final end-to-end check

## Testing safety

Tests and checks only use temp folders, `--watch`, outbox mode, fake Drive client and local ports.
No real USB drive, sync folder, mailbox or Google account is touched.
