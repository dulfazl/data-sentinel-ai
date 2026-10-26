#!/bin/bash
# Data Sentinel AI - one-click demo start for macOS.
# Double-click this file in Finder (or run ./start_demo.command in Terminal).
#
#  1. sets up .venv the first time (needs Python 3.10+)
#  2. resets the demo database and runs the scenarios (simulate)
#  3. starts the dashboard  -> http://localhost:8501
#  4. starts the agent: browser API (127.0.0.1:8765) + mail gateway (127.0.0.1:1025)
#     + demo_usb/ watched as an untrusted USB drive.  Real USB drives, cloud sync folders
#     and network shares are NOT watched.
# Extra arguments go to the agent, e.g.  ./start_demo.command --dry-run
# Press Ctrl+C in this window to stop everything.

cd "$(dirname "$0")" || exit 1
ROOT="$(pwd)"
set -o pipefail

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }

# ------------------------------------------------------------------ Python + venv
if [ ! -x .venv/bin/python ]; then
  PY=""
  for c in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
      PY="$c"; break
    fi
  done
  if [ -z "$PY" ]; then
    echo "Python 3.10 or newer is needed. Install it from https://www.python.org/downloads/macos/"
    echo "or with Homebrew:  brew install python@3.13   - then run this script again."
    read -r -p "Press Return to close." _; exit 1
  fi
  say "First run: creating .venv with $PY and installing packages (a few minutes)..."
  "$PY" -m venv .venv && .venv/bin/pip install -q --upgrade pip && .venv/bin/pip install -q -r requirements.txt \
    || { echo "Package installation failed."; read -r -p "Press Return to close." _; exit 1; }
fi
PYV=.venv/bin/python

if [ ! -f models/anomaly_iforest.joblib ]; then
  say "Training the Isolation Forest model (ml/train_eval.py)..."
  $PYV ml/train_eval.py || exit 1
fi

# ------------------------------------------------------------------ ports free?
busy=""
for port in 8765 1025 8501; do
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then busy="$busy $port"; fi
done
if [ -n "$busy" ]; then
  echo "These ports are already in use:$busy"
  echo "Another Data Sentinel agent or dashboard is probably still running - stop it (Ctrl+C in its window) and try again."
  lsof -nP -iTCP -sTCP:LISTEN | grep -E ":(8765|1025|8501) " || true
  read -r -p "Press Return to close." _; exit 1
fi

# ------------------------------------------------------------------ reset + simulate
say "Resetting the demo database and running the test scenarios..."
rm -f data_sentinel.db data_sentinel.db-wal data_sentinel.db-shm
mkdir -p demo_usb logs
$PYV -m data_sentinel simulate | tail -16 || exit 1

TOKEN="$($PYV -c 'from data_sentinel.browser_api import load_or_create_token; print(load_or_create_token())')"
if [ -z "$DEMO_NO_BROWSER" ]; then
  printf '%s' "$TOKEN" | pbcopy 2>/dev/null && COPIED=" (copied to the clipboard)"
fi

# ------------------------------------------------------------------ dashboard
say "Starting the dashboard (log: logs/dashboard.log)..."
.venv/bin/streamlit run dashboard/app.py --server.address 127.0.0.1 --server.port 8501 > logs/dashboard.log 2>&1 &
DASH_PID=$!
cleanup() {
  kill "$DASH_PID" 2>/dev/null
  wait "$DASH_PID" 2>/dev/null
  echo "Stopped."
}
trap cleanup EXIT
trap 'exit 130' INT TERM
for _ in $(seq 1 40); do
  curl -s -o /dev/null http://127.0.0.1:8501/_stcore/health && break
  sleep 0.5
done
[ -z "$DEMO_NO_BROWSER" ] && open "http://localhost:8501" 2>/dev/null

cat <<EOF

==========================================================================
 Dashboard        : http://localhost:8501
 Browser API      : http://127.0.0.1:8765   token: $TOKEN$COPIED
                    -> paste the token in the extension's Options page
 Mail gateway     : 127.0.0.1:1025 (no upstream: mails are saved in outbox/)
 Demo USB folder  : $ROOT/demo_usb
 Demo files       : $ROOT/demo_files
 Try it           : cp demo_files/customer_payroll_confidential.csv demo_usb/
                    .venv/bin/python -m data_sentinel try-paste
                    .venv/bin/python -m data_sentinel try-mail --attach demo_files/customer_payroll_confidential.csv
==========================================================================
EOF

# ------------------------------------------------------------------ agent (foreground)
$PYV -m data_sentinel agent --mail --watch demo_usb --no-usb --no-cloud --no-shares "$@"
